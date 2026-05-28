# sendDocument artifacts hardening

Daniel request: "dont bother sending the SHA256. harden this so artifacts always get sent like this as sendDocument"

Interpretation: when Telegram gateway final responses include `MEDIA:/absolute/path` artifacts, send them as Telegram documents (sendDocument), not photos/audio/video previews, so Markdown docs and arbitrary artifacts arrive as native files. Do not require the assistant to paste SHA256 in chat.

Need: inspect Telegram platform adapter/media handling, patch behavior, add regression tests, keep artifact captions concise.

## 2026-05-28 implementation notes

Worktree: `/usr/local/lib/hermes-agent/wt/senddocument-artifacts`.

Commands run:

- `git status --short`
- `rg -n "MEDIA:|sendDocument|send_document|send_photo|send_audio|send_video|telegram" gateway tests -S`
- `git log --all -G 'MEDIA:' --oneline -- gateway tests | head -40`
- `sed -n '2320,2485p' gateway/platforms/base.py`
- `sed -n '3540,3808p' gateway/platforms/base.py`
- `sed -n '11570,11705p' gateway/run.py`
- `sed -n '3850,4060p' gateway/platforms/telegram.py`
- `uv run --with pytest --with pytest-timeout --with pytest-asyncio pytest tests/gateway/test_tts_media_routing.py tests/gateway/test_telegram_documents.py::TestSendDocument -q` -> blocked by read-only `/root/.cache/uv`.
- `UV_CACHE_DIR=/tmp/uv-cache uv run --with pytest --with pytest-timeout --with pytest-asyncio pytest tests/gateway/test_tts_media_routing.py tests/gateway/test_telegram_documents.py::TestSendDocument -q` -> blocked by restricted network while downloading `markupsafe==3.0.3`.
- `/usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/gateway/test_tts_media_routing.py tests/gateway/test_telegram_documents.py::TestSendDocument -q` -> `24 passed in 0.85s`.
- `/usr/local/lib/hermes-agent/venv/bin/python -m py_compile gateway/platforms/base.py gateway/run.py gateway/platforms/telegram.py tests/gateway/test_tts_media_routing.py tests/gateway/test_telegram_documents.py` -> passed.
- `git diff --check` -> passed.
- `git add docs/context/context-2026-05-28-senddocument-artifacts.md gateway/platforms/base.py gateway/run.py tests/gateway/test_telegram_documents.py tests/gateway/test_tts_media_routing.py` -> blocked: worktree Git metadata path `/usr/local/lib/hermes-agent/.git/worktrees/senddocument-artifacts/index.lock` is read-only in this sandbox.

Decisions:

- Kept `MEDIA:` path parsing unchanged.
- Changed only Telegram final-response `MEDIA:` artifact dispatch. Both non-streamed `BasePlatformAdapter._process_message_background()` and streamed `GatewayRunner._deliver_media_from_response()` now route explicit Telegram `MEDIA:` attachments through `send_document`, regardless of image/audio/video/text extension.
- Left auto-detected bare local file routing unchanged; Daniel's request was specifically for `MEDIA:/absolute/path` artifacts.
- Left inbound stored artifact hashes as internal metadata only. No SHA256 is added to user-visible chat output.
- Added regression coverage proving Telegram `MEDIA:` image, audio, video, and text artifacts call `send_document` instead of image/audio/video senders, and proving `TelegramAdapter.send_document()` calls the bot `send_document` method for the same extension classes.
