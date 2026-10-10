"""Downloads a YouTube video's media for the reference deep-dive pipeline.

Off by default (``MP_ENABLE_REFERENCE_MEDIA_DOWNLOAD=false``) — gated the
same way as unofficial transcripts and the Lab's link-fetch: downloading
third-party media carries ToS risk that's the project owner's own explicit
decision (2026-10-09), not a default. Callers must check the flag
themselves; this module performs no flag check of its own, matching
``services/media_download``'s siblings (``thumbnail_vision``,
``transcripts``).

Uses ``yt-dlp`` (the ``lab`` extra) — the only dependency added for this.
Every import is lazy so importing this module never requires the extra to
be installed, only calling into it does (same convention as
``engine/video_lab/*``).
"""

from __future__ import annotations

import os

from app.services.binaries import ffmpeg_path


class MediaDownloadError(Exception):
    """Download failed, was rejected (too long), or yt-dlp isn't installed."""


def download_video(url: str, dest_dir: str, *, max_duration_s: int) -> str:
    """Downloads ``url`` into ``dest_dir`` at <=480p and returns the local
    file path. Rejects (without downloading) a video longer than
    ``max_duration_s``. Raises :class:`MediaDownloadError` on any failure —
    network error, private/region-locked video, missing dependency, etc.
    Caller owns ``dest_dir`` and is responsible for deleting it afterward.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise MediaDownloadError(
            "yt-dlp is not installed. Install the backend's 'lab' extra to enable "
            "reference media download."
        ) from exc

    def _reject_if_too_long(info_dict: dict, *, incomplete: bool = False) -> str | None:
        duration = info_dict.get("duration")
        if duration and duration > max_duration_s:
            return f"Video too long for deep-dive analysis ({int(duration)}s > {max_duration_s}s)."
        return None

    # Merging separately-downloaded video+audio streams needs ffmpeg. Reuse
    # the same resolution services/binaries.py already uses elsewhere
    # (system ffmpeg, else the one bundled with imageio-ffmpeg) rather than
    # relying on yt-dlp's own PATH search, which doesn't know about that
    # bundled fallback. Without ffmpeg at all, fall back to a single
    # pre-muxed progressive stream that needs no merge.
    exe = ffmpeg_path()
    format_selector = (
        "bv*[height<=480]+ba/b[height<=480]/best" if exe else "best[height<=480]/best"
    )

    out_template = os.path.join(dest_dir, "media.%(ext)s")
    ydl_opts = {
        "format": format_selector,
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "match_filter": _reject_if_too_long,
        "retries": 2,
        "socket_timeout": 30,
    }
    if exe:
        ydl_opts["ffmpeg_location"] = exe

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise MediaDownloadError(str(exc)) from exc

    for name in os.listdir(dest_dir):
        if name.startswith("media."):
            return os.path.join(dest_dir, name)
    raise MediaDownloadError("Download reported success but no output file was found.")
