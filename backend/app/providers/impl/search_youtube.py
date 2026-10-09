"""YouTube Data API v3 search provider (reqs D4/D5 — reference learning).

Field paths and quota costs below are confirmed against
developers.google.com/youtube/v3/docs (channels, playlistItems, videos
resources) and the quota calculator, 2026-10-09:

- ``channels.list``, ``playlistItems.list``, ``videos.list``: 1 quota unit
  each, with no documented cap on ids for ``videos.list`` (50 is the
  conventional safe batch size, matching ``playlistItems.list``'s
  ``maxResults`` ceiling).
- ``search.list``: 100 quota units per call, in its own 100-calls/day
  bucket. Default project quota is 10,000 units/day, resetting at midnight
  Pacific Time.
- A private/deleted/nonexistent video or channel id does *not* 404 — the
  list call succeeds with an empty ``items`` array.
- A quota-exceeded failure is HTTP 403 with
  ``error.errors[0].reason == "quotaExceeded"``.

Low-quota strategy (D4): list a channel's uploads via its "uploads" playlist
(``channels.list`` -> ``contentDetails.relatedPlaylists.uploads`` ->
``playlistItems.list``), never ``search.list`` — except as a last resort to
resolve a legacy ``/c/<name>`` custom URL, which has no direct lookup
endpoint. Never downloads video/audio; only reads public metadata via the
official API. See ``backend/docs/youtube_reference_notes.md``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.providers.base import (
    ChannelInfo,
    ProviderError,
    ResolvedRef,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    Usage,
    VideoInfo,
)
from app.providers.errors import ErrorCategory, classify
from app.providers.registry import register
from app.services.url_parse import InvalidYouTubeUrl, parse_youtube_url

DEFAULT_ENDPOINT = "https://www.googleapis.com/youtube/v3"
# videos.list has no documented hard cap on `id` count; playlistItems.list's
# maxResults tops out at 50, so 50 is used everywhere as the one safe batch size.
_BATCH_SIZE = 50
_PACIFIC = ZoneInfo("America/Los_Angeles")
# A well-known, always-public channel, used only to probe connectivity/auth.
_HEALTH_CHECK_CHANNEL_ID = "UC_x5XG1OV2P6uZZ5FSM9Ttw"  # Google for Developers

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


@register(
    display_name="YouTube Data API v3",
    default_endpoint=DEFAULT_ENDPOINT,
    notes=(
        "Official YouTube Data API v3. Used to learn a channel/video's public "
        "stats for style analysis — never downloads media or scrapes HTML. "
        "Get a key from console.cloud.google.com (enable 'YouTube Data API v3')."
    ),
)
class YouTubeDataApiSearch(SearchProvider):
    provider_key = "youtube_data_api"

    def fetch(self, request: SearchRequest) -> SearchResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing YouTube Data API key.", retryable=False)

        if request.op == "resolve":
            return self._resolve(request.url)
        if request.op == "video":
            return self._video(request.external_id)
        if request.op == "channel":
            return self._channel(request.external_id)
        if request.op == "channel_videos":
            return self._channel_videos(request.external_id, request.limit, request.page_token)
        raise ProviderError(f"Unknown search op: {request.op!r}", retryable=False)

    def health_check(self) -> bool:
        if not self.spec.api_key:
            return False
        try:
            self._get_json("channels", {"part": "id", "id": _HEALTH_CHECK_CHANNEL_ID})
            return True
        except Exception:  # noqa: BLE001
            return False

    # --- ops ---

    def _resolve(self, url: str) -> SearchResponse:
        try:
            parsed = parse_youtube_url(url)
        except InvalidYouTubeUrl as exc:
            raise ProviderError(
                str(exc), category=ErrorCategory.INVALID_REQUEST, retryable=False
            ) from exc

        if parsed.kind == "video":
            return SearchResponse(data=ResolvedRef(kind="video", external_id=parsed.video_id))

        if parsed.channel_id:
            return SearchResponse(data=ResolvedRef(kind="channel", external_id=parsed.channel_id))

        if parsed.handle:
            channel_id = self._lookup_channel_id(for_handle=parsed.handle)
            if not channel_id:
                raise ProviderError(
                    f"No YouTube channel found for handle '@{parsed.handle}'.",
                    category=ErrorCategory.INVALID_REQUEST,
                    retryable=False,
                )
            return SearchResponse(data=ResolvedRef(kind="channel", external_id=channel_id))

        if parsed.username:
            channel_id = self._lookup_channel_id(for_username=parsed.username)
            if not channel_id:
                raise ProviderError(
                    f"No YouTube channel found for username '{parsed.username}'.",
                    category=ErrorCategory.INVALID_REQUEST,
                    retryable=False,
                )
            return SearchResponse(data=ResolvedRef(kind="channel", external_id=channel_id))

        if parsed.custom_name:
            # Cheap path first (1 unit): some /c/ names are also the legacy
            # username. Only fall back to search.list (100 units) if that misses.
            channel_id = self._lookup_channel_id(for_username=parsed.custom_name)
            if not channel_id:
                channel_id = self._search_channel_by_name(parsed.custom_name)
            if not channel_id:
                raise ProviderError(
                    f"No YouTube channel found for custom URL '/c/{parsed.custom_name}'.",
                    category=ErrorCategory.INVALID_REQUEST,
                    retryable=False,
                )
            return SearchResponse(data=ResolvedRef(kind="channel", external_id=channel_id))

        raise ProviderError("Could not resolve URL to a video or channel.", retryable=False)

    def _video(self, video_id: str) -> SearchResponse:
        if not video_id:
            raise ProviderError("Missing video id.", retryable=False)
        body = self._get_json(
            "videos", {"part": "snippet,contentDetails,statistics", "id": video_id}
        )
        items = body.get("items") or []
        if not items:
            # videos.list returns HTTP 200 with empty items for a
            # private/deleted/nonexistent id — there is no 404 to catch.
            raise ProviderError(
                f"Video not found or private: {video_id}",
                category=ErrorCategory.INVALID_REQUEST,
                retryable=False,
            )
        return SearchResponse(data=_video_info_from_item(items[0]))

    def _channel(self, channel_id: str) -> SearchResponse:
        if not channel_id:
            raise ProviderError("Missing channel id.", retryable=False)
        body = self._get_json(
            "channels", {"part": "snippet,contentDetails,statistics", "id": channel_id}
        )
        items = body.get("items") or []
        if not items:
            raise ProviderError(
                f"Channel not found: {channel_id}",
                category=ErrorCategory.INVALID_REQUEST,
                retryable=False,
            )
        item = items[0]
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        content = item.get("contentDetails") or {}
        uploads = (content.get("relatedPlaylists") or {}).get("uploads", "")
        info = ChannelInfo(
            external_id=str(item.get("id", channel_id)),
            title=snippet.get("title", ""),
            uploads_playlist_id=uploads,
            subscriber_count=int(stats.get("subscriberCount", 0) or 0),
            video_count=int(stats.get("videoCount", 0) or 0),
            view_count=int(stats.get("viewCount", 0) or 0),
        )
        return SearchResponse(data=info)

    def _channel_videos(self, channel_id: str, limit: int, page_token: str) -> SearchResponse:
        if not channel_id:
            raise ProviderError("Missing channel id.", retryable=False)

        channel_info: ChannelInfo = self._channel(channel_id).data
        uploads_playlist_id = channel_info.uploads_playlist_id
        if not uploads_playlist_id:
            raise ProviderError(
                f"Channel {channel_id} has no uploads playlist.",
                category=ErrorCategory.INVALID_REQUEST,
                retryable=False,
            )

        limit = max(0, limit)
        video_ids: list[str] = []
        next_token = page_token
        while len(video_ids) < limit:
            page_size = min(_BATCH_SIZE, limit - len(video_ids))
            params: dict = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": page_size,
            }
            if next_token:
                params["pageToken"] = next_token
            body = self._get_json("playlistItems", params)
            items = body.get("items") or []
            for item in items:
                vid = (item.get("contentDetails") or {}).get("videoId", "")
                if vid:
                    video_ids.append(vid)
            next_token = body.get("nextPageToken", "")
            if not next_token or not items:
                break

        videos: list[VideoInfo] = []
        for i in range(0, len(video_ids), _BATCH_SIZE):
            batch = video_ids[i : i + _BATCH_SIZE]
            body = self._get_json(
                "videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(batch)}
            )
            for item in body.get("items") or []:
                videos.append(_video_info_from_item(item))

        return SearchResponse(data=videos, usage=Usage(), next_page_token=next_token)

    # --- helpers ---

    def _lookup_channel_id(self, *, for_handle: str = "", for_username: str = "") -> str:
        params: dict = {"part": "id"}
        if for_handle:
            params["forHandle"] = for_handle
        elif for_username:
            params["forUsername"] = for_username
        else:
            return ""
        body = self._get_json("channels", params)
        items = body.get("items") or []
        return str(items[0].get("id", "")) if items else ""

    def _search_channel_by_name(self, name: str) -> str:
        """Last resort for legacy ``/c/`` custom URLs (no direct lookup
        endpoint exists): costs 100 quota units vs. 1 for channels.list, so
        this only runs once the cheap ``forUsername`` lookup has failed."""
        body = self._get_json(
            "search", {"part": "snippet", "type": "channel", "q": name, "maxResults": 1}
        )
        items = body.get("items") or []
        if not items:
            return ""
        return str((items[0].get("id") or {}).get("channelId", ""))

    def _get_json(self, path: str, params: dict) -> dict:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        query = dict(params)
        query["key"] = self.spec.api_key
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/{path}", params=query)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Request failed: {exc}", category=classify(exception=exc)
            ) from exc

        if resp.status_code >= 400:
            raise self._error_for(resp)
        return resp.json()

    @staticmethod
    def _error_for(resp: httpx.Response) -> ProviderError:
        # Never include the request URL here — it carries ?key=<api_key>.
        reason = _error_reason(resp)
        if resp.status_code == 403 and reason == "quotaExceeded":
            return ProviderError(
                "YouTube Data API daily quota exceeded.",
                category=ErrorCategory.RATE_LIMIT,
                retry_after=_seconds_until_pacific_midnight(),
            )
        return ProviderError(
            f"YouTube Data API HTTP {resp.status_code}: {resp.text[:300]}",
            category=classify(status_code=resp.status_code, body=resp.text),
        )


def _error_reason(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    errors = (body.get("error") or {}).get("errors") or []
    return str(errors[0].get("reason", "")) if errors else ""


def _seconds_until_pacific_midnight() -> float:
    now = datetime.now(_PACIFIC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def _video_info_from_item(item: dict) -> VideoInfo:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    content = item.get("contentDetails") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
    return VideoInfo(
        external_id=str(item.get("id", "")),
        title=snippet.get("title", ""),
        published_at=snippet.get("publishedAt", ""),
        duration_s=_parse_iso8601_duration(content.get("duration", "")),
        views=int(stats.get("viewCount", 0) or 0),
        likes=int(stats.get("likeCount", 0) or 0),
        comments=int(stats.get("commentCount", 0) or 0),
        thumbnail_url=thumb.get("url", ""),
        channel_id=snippet.get("channelId", ""),
    )


def _parse_iso8601_duration(value: str) -> int:
    if not value:
        return 0
    match = _DURATION_RE.match(value)
    if not match:
        return 0
    parts = match.groupdict()
    days = int(parts["days"] or 0)
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds
