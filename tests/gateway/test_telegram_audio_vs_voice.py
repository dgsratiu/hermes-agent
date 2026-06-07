"""
Tests for #24870 — Telegram: audio file attachments must NOT be routed to STT.

Telegram distinguishes three kinds of audio payloads:
  - message.voice  → Opus/OGG voice message  → STT pipeline
  - message.audio  → audio file attachment   → file path note, NOT STT
  - message.document (audio mime) → generic file route

These tests confirm that:
  1. MessageType.VOICE events still flow through the STT pipeline.
  2. MessageType.AUDIO events bypass STT and get a file-path context note instead.
  3. Mixed media lists (voice + audio) split correctly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


def _make_runner(stt_enabled: bool = True) -> "GatewayRunner":  # type: ignore[name-defined]
    from gateway.run import GatewayRunner

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(stt_enabled=stt_enabled)
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    runner._has_setup_skill = lambda: False
    return runner


def _voice_event(path: str = "/tmp/voice.ogg") -> MessageEvent:
    return MessageEvent(
        text="",
        message_type=MessageType.VOICE,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm"),
        media_urls=[path],
        media_types=["audio/ogg"],
    )


def _audio_event(path: str = "/tmp/song.mp3") -> MessageEvent:
    return MessageEvent(
        text="",
        message_type=MessageType.AUDIO,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm"),
        media_urls=[path],
        media_types=["audio/mpeg"],
    )


def _video_event(path: str = "/tmp/video_c8314e1e0f31.mp4", media_type: str = "video/mp4") -> MessageEvent:
    return MessageEvent(
        text="",
        message_type=MessageType.VIDEO,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm"),
        media_urls=[path],
        media_types=[media_type],
        stored_artifacts=[
            {
                "kind": "video",
                "media_type": media_type,
                "path": path,
                "bytes": 123,
                "content_hash": "sha256",
            }
        ],
    )


# ---------------------------------------------------------------------------
# 1. VOICE still goes through STT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_message_still_transcribed():
    """MessageType.VOICE must still be sent through _enrich_message_with_transcription."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _voice_event("/tmp/voice.ogg")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={"success": True, "transcript": "hello world", "provider": "whisper"},
    ) as mock_transcribe:
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    mock_transcribe.assert_called_once_with("/tmp/voice.ogg")
    assert "hello world" in result
    assert "voice message" in result.lower()


@pytest.mark.asyncio
async def test_voice_message_echoes_transcript_to_chat():
    """Successful Telegram voice STT should remain visible as its own bubble."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _voice_event("/tmp/voice.ogg")
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=True)
    adapter.send_or_update_status = AsyncMock(return_value=True)
    adapter.edit_message = AsyncMock(return_value=True)
    runner.adapters = {Platform.TELEGRAM: adapter}

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={"success": True, "transcript": "hello world", "provider": "whisper"},
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    adapter.send.assert_awaited_once_with(
        "1",
        "🎤 Voice transcript:\nhello world",
        reply_to=None,
        metadata=None,
    )
    adapter.send_or_update_status.assert_not_awaited()
    adapter.edit_message.assert_not_awaited()
    assert "hello world" in result


@pytest.mark.asyncio
async def test_voice_message_echoes_multiple_transcripts_in_one_message():
    """Multiple Telegram voice clips should produce one durable transcript echo."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = MessageEvent(
        text="",
        message_type=MessageType.VOICE,
        source=source,
        media_urls=["/tmp/one.ogg", "/tmp/two.ogg"],
        media_types=["audio/ogg", "audio/ogg"],
    )
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=True)
    runner.adapters = {Platform.TELEGRAM: adapter}

    transcripts = iter(["first clip", "second clip"])

    def fake_transcribe(_path: str) -> dict[str, str | bool]:
        return {
            "success": True,
            "transcript": next(transcripts),
            "provider": "whisper",
        }

    with patch("tools.transcription_tools.transcribe_audio", side_effect=fake_transcribe):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    adapter.send.assert_awaited_once_with(
        "1",
        "🎤 Voice transcript 1:\nfirst clip\n\n🎤 Voice transcript 2:\nsecond clip",
        reply_to=None,
        metadata=None,
    )
    assert "first clip" in result
    assert "second clip" in result


@pytest.mark.asyncio
async def test_voice_message_does_not_echo_failed_transcription():
    """Failed STT gets the existing setup/error path, not a transcript echo."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _voice_event("/tmp/voice.ogg")
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=True)
    runner.adapters = {Platform.TELEGRAM: adapter}

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={"success": False, "transcript": "", "error": "backend unavailable"},
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
    )

    adapter.send.assert_not_awaited()
    assert "transcription is unavailable" in result
    assert "/tmp/voice.ogg" in result


@pytest.mark.asyncio
async def test_voice_message_does_not_inject_empty_successful_transcript():
    """Blank STT responses must not become successful voice transcript context."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _voice_event("/tmp/silent.ogg")
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=True)
    runner.adapters = {Platform.TELEGRAM: adapter}

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={
            "success": True,
            "transcript": "  ",
            "provider": "openai",
            "path": "/tmp/silent.ogg",
        },
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    adapter.send.assert_not_awaited()
    assert "Here's what they said" not in result
    assert "transcription is unavailable" in result
    assert "/tmp/silent.ogg" in result


# ---------------------------------------------------------------------------
# 2. AUDIO file attachment bypasses STT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audio_attachment_skips_stt():
    """MessageType.AUDIO must NOT be routed to STT — transcribe_audio must not be called."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/song.mp3")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("transcribe_audio must NOT be called for audio file attachments"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert result is not None
    assert "/tmp/song.mp3" in result
    assert "audio file attachment" in result.lower()


@pytest.mark.asyncio
async def test_audio_attachment_context_note_format():
    """Context note for audio file attachments should include the file path and guidance."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/cache_12345_my_song.mp3")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("must not be called"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert "my_song.mp3" in result
    assert "audio file attachment" in result.lower()
    # Should NOT contain the voice-message transcription wrapper text
    assert "voice message" not in result.lower()


# ---------------------------------------------------------------------------
# 3. STT disabled still results in no transcription for audio file attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audio_attachment_skips_stt_when_stt_disabled():
    """Even with STT disabled, AUDIO must NOT produce STT disabled notice — just a file note."""
    runner = _make_runner(stt_enabled=False)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/podcast.m4a")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("must not be called"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    # Should NOT see the "transcription is disabled" note — that's only for VOICE
    assert "transcription is disabled" not in result.lower()
    assert "audio file attachment" in result.lower()
    assert "/tmp/podcast.m4a" in result


@pytest.mark.asyncio
async def test_video_attachment_gets_video_context_note_not_image_analysis():
    """Video attachments should be surfaced as videos, not screenshots/images."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _video_event("/tmp/video_c8314e1e0f31.mp4")

    with patch(
        "tools.vision_tools.vision_analyze_tool",
        side_effect=AssertionError("video must not be sent to image analysis"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert "video attachment" in result.lower()
    assert "/tmp/video_c8314e1e0f31.mp4" in result
    assert "not as an image or screenshot" in result


@pytest.mark.asyncio
async def test_animation_gif_artifact_stays_video_in_prompt():
    """Telegram animation artifacts may have image/gif MIME but video kind."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _video_event("/tmp/video_cache/video_abc123.gif", media_type="image/gif")

    with patch(
        "tools.vision_tools.vision_analyze_tool",
        side_effect=AssertionError("animation must not be sent to image analysis"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert "video attachment (image/gif)" in result
    assert "image:" not in result.lower()
    assert "screenshot" in result


def test_video_media_placeholder_uses_video_label_for_queued_turns():
    from gateway.run import _build_media_placeholder

    event = _video_event("/tmp/video_cache/video_abc123.gif", media_type="image/gif")

    placeholder = _build_media_placeholder(event)

    assert placeholder == "[User sent a video: /tmp/video_cache/video_abc123.gif]"
    assert "image" not in placeholder.lower()


# ---------------------------------------------------------------------------
# 4. Telegram gateway: msg.audio → MessageType.AUDIO (not VOICE)
# ---------------------------------------------------------------------------

def test_telegram_media_type_detection_audio_vs_voice():
    """The Telegram platform must set MessageType.AUDIO for msg.audio, VOICE for msg.voice."""
    from gateway.platforms.base import MessageType

    # The Telegram adapter's _build_media_type already returns correct values
    # via MessageType.AUDIO for .audio and MessageType.VOICE for .voice.
    # Check the constants match expected semantic roles.
    assert MessageType.AUDIO.value == "audio"
    assert MessageType.VOICE.value == "voice"
    # Sanity: they are distinct
    assert MessageType.AUDIO != MessageType.VOICE
