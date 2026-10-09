"""Wikimedia Commons media search (Etapa 5, item 3) — no API key needed.

Uses the MediaWiki Action API's ``generator=search`` over namespace 6
(File:) with ``prop=imageinfo`` for the URL/dimensions/license. License and
attribution live inside ``imageinfo[0].extmetadata`` (free-text metadata,
not a fixed schema) — ``LicenseShortName``/``Artist`` are read defensively,
since not every file has them filled in.
"""

from __future__ import annotations

import re

import httpx

from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
_THUMB_WIDTH = 480
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(value: str) -> str:
    return _HTML_TAG_RE.sub("", value).strip()


@register(
    display_name="Wikimedia Commons (media search)",
    requires_api_key=False,
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Free, no API key. Public-domain/CC-licensed images from Wikimedia Commons.",
)
class WikimediaMedia(MediaSearchProvider):
    provider_key = "media_wikimedia"

    def search(self, request: MediaRequest) -> MediaResponse:
        base = self.spec.endpoint or DEFAULT_ENDPOINT
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": request.query,
            "gsrnamespace": 6,
            "gsrlimit": max(1, min(request.per_page, 50)),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": _THUMB_WIDTH,
            "format": "json",
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(base, params=params)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc

        pages = ((body.get("query") or {}).get("pages") or {}).values()
        items: list[MediaItem] = []
        for page in pages:
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = str(info.get("mime", ""))
            kind = "video" if mime.startswith("video/") else "photo"
            extmeta = info.get("extmetadata") or {}
            license_name = (extmeta.get("LicenseShortName") or {}).get("value", "")
            artist = _strip_html((extmeta.get("Artist") or {}).get("value", ""))
            items.append(
                MediaItem(
                    id=str(page.get("pageid", "")),
                    kind=kind,
                    thumbnail_url=str(info.get("thumburl") or info.get("url", "")),
                    download_url=str(info.get("url", "")),
                    width=int(info.get("width", 0) or 0),
                    height=int(info.get("height", 0) or 0),
                    license=str(license_name or "see source"),
                    author=artist,
                    source_url=f"https://commons.wikimedia.org/?curid={page.get('pageid', '')}",
                )
            )
        return MediaResponse(items=items, usage=Usage())
