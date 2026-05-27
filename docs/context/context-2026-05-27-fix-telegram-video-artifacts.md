# fix-telegram-video-artifacts

- task: Diagnose and fix Telegram video attachment ingestion for Garden concierge/Hermesage.
- worktree: /usr/local/lib/hermes-agent-wt-fix-telegram-video-artifacts-20260527233308
- base: 25f43d38de86582f5bc2d5be6843f824eac21634
- note: source work done in isolated worktree; live profile has existing unrelated dirty files and must be patched carefully after verification.
- observed live artifact: /var/lib/garden-concierge-hermes/hermes-agents/garden-concierge/cache/videos/video_c8314e1e0f31.mp4 exists, while Telegram prompt surfaced it as image/screenshot in prior founder message.

## Execution Notes

- Inspected `gateway/platforms/telegram.py`, `gateway/platforms/base.py`, and `gateway/run.py`.
- Root distinction: Telegram video download/storage was already partially working for native `message.video` and `.mp4` document uploads: bytes are downloaded and saved under `cache/videos/`. The break was downstream classification: normalized events had only generic `media_urls` / `media_types`, no structured stored-artifact kind, and `GatewayRunner._prepare_inbound_message_text()` had explicit prompt branches for images, audio/voice, and documents but no video branch.
- Additional ingress gap: Telegram handler registration and message-type detection did not explicitly include `animation` or `video_note`, so those payload classes could miss the media path or be treated generically.
- Patch direction: add structured `MessageEvent.stored_artifacts` entries with `kind`, `media_type`, `path`, `bytes`, and SHA-256 `content_hash`; classify Telegram `video`, document-video, `animation`, and `video_note` as video artifacts; make prompt construction use stored artifact kind before MIME-prefix heuristics so `image/gif` animations do not route through image/screenshot vision handling.

## Verification

- `uv run --with pytest --with pytest-timeout --with pytest-asyncio pytest tests/gateway/test_telegram_documents.py::TestVideoDownloadBlock tests/gateway/test_telegram_audio_vs_voice.py -q` -> 13 passed.
- `uv run --with pytest --with pytest-timeout --with pytest-asyncio pytest tests/gateway/test_telegram_documents.py -q` -> 44 passed.
- `/usr/bin/python3 -m py_compile gateway/platforms/base.py gateway/platforms/telegram.py gateway/run.py tests/gateway/test_telegram_documents.py tests/gateway/test_telegram_audio_vs_voice.py` -> passed.
- `git diff --check` -> passed.
