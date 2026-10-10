# YouTube reference learning: API limits & legal notes

Short reference for the "Canais" style-learning feature (`docs/PROMPT_CANAIS.md`).

## Official API (`providers/impl/search_youtube.py`)

- Metadata (channel uploads, view/like/comment counts, titles, durations)
  comes only from the official **YouTube Data API v3** with a user-supplied
  API key. No scraping, no HTML parsing, for metadata — ever.
- Default project quota: **10,000 units/day**, resetting at **midnight
  Pacific Time**. `channels.list`, `playlistItems.list`, and `videos.list`
  each cost **1 unit**; `search.list` costs **100 units** (its own 100
  calls/day sub-bucket). We list a channel's uploads via its uploads
  playlist instead of `search.list` for exactly this reason — `search.list`
  is only used as a last resort to resolve a legacy `/c/<name>` custom URL,
  which has no direct lookup endpoint.
- **The official API does not return another creator's captions/transcript.**
  Caption download requires the video owner's own authorization.
- A private/deleted/nonexistent video or channel id does not 404 — the
  official endpoints return HTTP 200 with an empty `items` array.

## Media download / deep-dive (`services/media_download.py`, `services/reference_deepdive.py`)

**Updated 2026-10-09** — superseded the original "no media download, ever"
stance above, by the user's own explicit decision (same posture as
`MP_ENABLE_UNOFFICIAL_TRANSCRIPTS`: the ToS-risk tradeoff is the project
owner's call, not a default).

- `MP_ENABLE_REFERENCE_MEDIA_DOWNLOAD` (off by default). When on, a
  channel's top `reference_deepdive_top_n` videos (by `outlier_score`), or a
  single-video reference's one video, each get a background "deep-dive":
  `yt-dlp` downloads the video (<=480p, capped at
  `reference_deepdive_max_duration_s`), it's transcribed locally with
  faster-whisper (`engine/video_lab/speech.py` — the same adapter the
  Laboratório de vídeo already uses; free, no API key, nothing uploaded to a
  third party), then run through the same scene-detection/beat/vision
  pipeline as the Lab to derive a structural "where attention likely
  concentrates" estimate.
- This is **not** real audience retention. No official API exposes
  retention/"most replayed" data for a video the user doesn't own — YouTube
  Analytics retention curves require the channel owner's own OAuth, and the
  "most replayed" graph in the player is itself scraped by third-party tools
  from the watch page, not an API. `attention_notes` is a deterministic
  estimate from cut pacing, speech rhythm, and beat-role structure —
  labeled as such everywhere it's surfaced.
- Still never stored: the downloaded video, extracted audio, and extracted
  frame images are always deleted at the end of the run (success or
  failure) — only derived numbers/text survive (`scene_breakdown`,
  `attention_notes`, the transcript subject to `MP_KEEP_TRANSCRIPTS`, and
  the abstract vision descriptor per scene, never the frame itself — same
  policy as thumbnail vision below).
- Manual transcript paste/upload (the original Phase 4 fallback) was
  **removed** from the product on the same date — the deep-dive is now the
  only transcript source. A video whose deep-dive fails (private, age/
  region-locked, download error, too long) simply has no transcript; there
  is intentionally no manual override.
- An unofficial-captions adapter is still named in the product spec but
  intentionally not wired to anything — scraping YouTube's caption
  endpoints outside the official API is a separate decision the user has
  not made.

## Data retention

- Thumbnails are stored as hotlink URLs only — never downloaded.
- Transcripts, when obtained, are deleted after analysis by default
  (`MP_KEEP_TRANSCRIPTS=false`) and are never shown in the UI or reproduced
  in generated scripts (style is learned abstractly; content is not copied).

## Other platforms

TikTok and other platforms are out of scope for now (explicit 2026-10-09
decision: focus on YouTube first). Any future adapter should follow the
same rule: official API for metadata first; media download/scraping is its
own explicit, separate decision from the user, same as above.
