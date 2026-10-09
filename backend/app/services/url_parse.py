"""Pure YouTube URL parsing — no network calls.

Deliberately dependency-free: this only recognizes which YouTube resource a
URL points at and extracts its identifier, so it can be unit-tested without
mocking HTTP and reused by both the API layer (to validate input before
accepting it) and the ``search_youtube`` provider (to decide what to look up).

Anti-SSRF by construction: only a fixed allowlist of YouTube hosts is
accepted, and nothing here (or in the provider that uses it) ever issues a
request to the *user-supplied* URL — only to fixed Google API endpoints,
using the identifier extracted here as a query parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

_ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)

# YouTube video/channel ids and handles/usernames/custom names are all
# short, URL-safe tokens in practice. Validating the shape rejects obvious
# garbage early instead of forwarding it into an API call.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class InvalidYouTubeUrl(ValueError):
    """The given URL isn't a recognized/allowed YouTube video or channel link."""


@dataclass
class ParsedYouTubeUrl:
    """What a YouTube URL points at, before any network call is made."""

    kind: str  # "video" | "channel"
    video_id: str = ""
    channel_id: str = ""
    handle: str = ""
    username: str = ""
    custom_name: str = ""


def _clean_id(value: str) -> str:
    value = value.strip()
    if not value or not _ID_RE.match(value):
        raise InvalidYouTubeUrl(f"Not a valid YouTube identifier: {value!r}")
    return value


def parse_youtube_url(url: str) -> ParsedYouTubeUrl:
    """Parse a YouTube video or channel URL into its kind + identifier.

    Raises :class:`InvalidYouTubeUrl` for anything not on the host allowlist
    or not matching a recognized video/channel URL shape.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise InvalidYouTubeUrl(f"Could not parse URL: {url!r}") from exc

    host = parts.hostname or ""
    if host not in _ALLOWED_HOSTS:
        raise InvalidYouTubeUrl(f"Host not allowed: {host!r}")

    path = parts.path.rstrip("/")
    segments = [seg for seg in path.split("/") if seg]

    if host in {"youtu.be", "www.youtu.be"}:
        if not segments:
            raise InvalidYouTubeUrl("youtu.be URL has no video id.")
        return ParsedYouTubeUrl(kind="video", video_id=_clean_id(segments[0]))

    if not segments:
        raise InvalidYouTubeUrl("YouTube URL has no recognizable path.")

    first = segments[0]

    if first == "watch":
        query = parse_qs(parts.query)
        video_ids = query.get("v") or []
        if not video_ids:
            raise InvalidYouTubeUrl("watch URL has no 'v' query parameter.")
        return ParsedYouTubeUrl(kind="video", video_id=_clean_id(video_ids[0]))

    if first == "shorts":
        if len(segments) < 2:
            raise InvalidYouTubeUrl("shorts URL has no video id.")
        return ParsedYouTubeUrl(kind="video", video_id=_clean_id(segments[1]))

    if first == "channel":
        if len(segments) < 2:
            raise InvalidYouTubeUrl("channel URL has no channel id.")
        return ParsedYouTubeUrl(kind="channel", channel_id=_clean_id(segments[1]))

    if first == "user":
        if len(segments) < 2:
            raise InvalidYouTubeUrl("user URL has no username.")
        return ParsedYouTubeUrl(kind="channel", username=_clean_id(segments[1]))

    if first == "c":
        if len(segments) < 2:
            raise InvalidYouTubeUrl("custom /c/ URL has no name.")
        return ParsedYouTubeUrl(kind="channel", custom_name=_clean_id(segments[1]))

    if first.startswith("@"):
        return ParsedYouTubeUrl(kind="channel", handle=_clean_id(first[1:]))

    raise InvalidYouTubeUrl(f"Unrecognized YouTube URL shape: {url!r}")
