# STT Silence Hallucination Context - 2026-06-07

## Incident

Telegram voice messages with near-silent or otherwise bad OGG audio were being
passed to speech-to-text and then injected into the gateway user context as if
the words were spoken.

Evidence from the Garden concierge audio cache:

- `audio_fe249f26a0e2.ogg`: 30.54 seconds, 48,178 bytes, `ffmpeg volumedetect`
  mean/max around `-91 dB`. Manual OpenAI `gpt-4o-transcribe` returned empty,
  but the gateway delivered context claiming `or.`.
- `audio_fb6f3ae35941.ogg`: 1.78 seconds, 3,600 bytes, same `-91 dB` signal.
  Repeated manual STT returned unstable hallucinations including `Hello!`,
  `influence.`, and `Hello.`.

No API keys or Telegram identifiers are needed to reproduce the source-level
failure mode: a near-silent OGG can produce non-empty STT model text, and the
gateway used any successful result as transcript context.

## Root Cause

The gateway trusted provider text for `MessageType.VOICE` without first checking
whether the cached audio had speech-like signal. Modern STT models can emit
plausible tokens on silence or corrupt/low-signal audio. The gateway also only
checked `result["success"]`, so a provider that reported success with a blank
transcript could still enter the "successful transcript" branch.

## Fix

`tools/transcription_tools.py` now probes audio with `ffmpeg volumedetect` before
calling any STT provider. If max volume is at or below `-55 dB`, or mean volume
is at or below `-75 dB`, transcription returns a failure envelope with:

- `success: false`
- empty `transcript`
- cached absolute `path`
- measured mean/max dB when available

The probe fails open when `ffmpeg` is unavailable or cannot produce volume data,
so hosts without ffmpeg keep the previous provider path.

Provider results are also normalized through a finalizer:

- successful but empty transcripts become transcription-unavailable failures;
- local faster-whisper `no_speech_prob` is surfaced, and high no-speech
  probability is rejected as probable non-speech audio.

`gateway/run.py` now defensively requires a non-empty transcript before adding
`Here's what they said` context or echoing a Telegram transcript. On failure it
preserves the cached audio path and tells the model that transcription is
unavailable for that audio instead of injecting guessed speech.

## Verification

Regression coverage:

- near-silent signal is rejected before provider dispatch;
- real generated silent OGG is rejected when ffmpeg is present;
- empty "successful" provider responses are converted to unavailable;
- Telegram voice context does not echo or inject blank successful transcripts
  and retains the cached path.
