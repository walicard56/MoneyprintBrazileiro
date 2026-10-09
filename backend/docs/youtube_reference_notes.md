# YouTube reference learning: API limits & legal notes

Short reference for the "Canais" style-learning feature (`docs/PROMPT_CANAIS.md`).

## Official API (`providers/impl/search_youtube.py`)

- Uses only the official **YouTube Data API v3** with a user-supplied API
  key. No scraping, no `yt-dlp`, no media download — ever.
- Default project quota: **10,000 units/day**, resetting at **midnight
  Pacific Time**. `channels.list`, `playlistItems.list`, and `videos.list`
  each cost **1 unit**; `search.list` costs **100 units** (its own 100
  calls/day sub-bucket). We list a channel's uploads via its uploads
  playlist instead of `search.list` for exactly this reason — `search.list`
  is only used as a last resort to resolve a legacy `/c/<name>` custom URL,
  which has no direct lookup endpoint.
- **The official API does not return another creator's captions/transcript.**
  Caption download requires the video owner's own authorization. This is
  why transcript sourcing (Phase 4) is pluggable: the user pastes/uploads a
  transcript themselves, or uploads audio for our own `STTProvider` to
  transcribe. An unofficial captions adapter exists but is **off by default**
  behind `MP_ENABLE_UNOFFICIAL_TRANSCRIPTS` — it isn't part of the official
  API, can break at any time, and may violate YouTube's Terms of Service.
  Enabling it is the user's own, explicit decision.
- A private/deleted/nonexistent video or channel id does not 404 — the
  official endpoints return HTTP 200 with an empty `items` array.

## Data retention

- Thumbnails are stored as hotlink URLs only — never downloaded.
- Transcripts, when obtained, are deleted after analysis by default
  (`MP_KEEP_TRANSCRIPTS=false`) and are never shown in the UI or reproduced
  in generated scripts (style is learned abstractly; content is not copied).

## Other platforms

TikTok and other platforms are out of scope for now. Any future adapter
should follow the same rule: official API first, no scraping/download
without an explicit, separate decision from the user.
