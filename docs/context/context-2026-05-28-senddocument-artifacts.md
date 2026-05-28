# sendDocument artifacts hardening

Daniel request: "dont bother sending the SHA256. harden this so artifacts always get sent like this as sendDocument"

Interpretation: when Telegram gateway final responses include `MEDIA:/absolute/path` artifacts, send them as Telegram documents (sendDocument), not photos/audio/video previews, so Markdown docs and arbitrary artifacts arrive as native files. Do not require the assistant to paste SHA256 in chat.

Need: inspect Telegram platform adapter/media handling, patch behavior, add regression tests, keep artifact captions concise.
