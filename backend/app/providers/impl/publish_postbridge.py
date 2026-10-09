"""Post Bridge publishing adapter (ported from MoneyPrinterV2).

Post Bridge cross-posts a video to connected social accounts (TikTok, Instagram,
etc.). The target social-account IDs come from the Account's params; the API key
comes from the provider config.
"""

from __future__ import annotations

import mimetypes
import os

import httpx

from app.providers.base import (
    ProviderError,
    PublishProvider,
    PublishRequest,
    PublishResponse,
    Usage,
)
from app.providers.errors import classify
from app.providers.registry import register

API_BASE = "https://api.post-bridge.com/v1"


@register(
    display_name="Post Bridge",
    default_endpoint=API_BASE,
    notes="Cross-posts video to connected accounts. Set social account IDs on the Account.",
)
class PostBridgePublish(PublishProvider):
    provider_key = "post_bridge"

    def publish(self, request: PublishRequest) -> PublishResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing Post Bridge API key.", retryable=False)
        if not os.path.exists(request.video_path):
            raise ProviderError(
                f"Video file not found: {request.video_path}", retryable=False
            )

        social_account_ids = request.account.get("social_account_ids") or []
        if not social_account_ids:
            raise ProviderError(
                "No Post Bridge social_account_ids configured on the account.",
                retryable=False,
            )

        base = (self.spec.endpoint or API_BASE).rstrip("/")
        headers = {"Authorization": f"Bearer {self.spec.api_key}"}

        media_id = self._upload_media(base, headers, request.video_path)
        caption = request.caption or request.title or ""

        payload: dict = {
            "caption": caption,
            "social_accounts": list(social_account_ids),
            "media": [media_id],
            "processing_enabled": True,
        }
        if request.title:
            payload["platform_configurations"] = {"tiktok": {"title": request.title}}
        if request.scheduled_at:
            payload["scheduled_at"] = request.scheduled_at

        with httpx.Client(timeout=120) as client:
            resp = client.post(f"{base}/posts", json=payload, headers=headers)
        if resp.status_code >= 400:
            raise ProviderError(
                f"Post Bridge HTTP {resp.status_code}: {resp.text[:300]}",
                category=classify(status_code=resp.status_code, body=resp.text),
            )
        body = resp.json()
        return PublishResponse(
            external_id=str(body.get("id", "")),
            external_url=str(body.get("url", "")),
            raw=body,
            usage=Usage(),
        )

    def _upload_media(self, base: str, headers: dict, path: str) -> str:
        name = os.path.basename(path)
        mime = mimetypes.guess_type(path)[0] or "video/mp4"
        size = os.path.getsize(path)
        with httpx.Client(timeout=120) as client:
            create = client.post(
                f"{base}/media/create-upload-url",
                json={"name": name, "mime_type": mime, "size_bytes": size},
                headers=headers,
            )
            if create.status_code >= 400:
                raise ProviderError(
                    f"create-upload-url failed: HTTP {create.status_code}: {create.text[:200]}",
                    category=classify(status_code=create.status_code, body=create.text),
                )
            data = create.json()
            media_id, upload_url = data.get("media_id"), data.get("upload_url")
            if not media_id or not upload_url:
                raise ProviderError("Post Bridge did not return media_id/upload_url.")

            with open(path, "rb") as fh:
                put = client.put(upload_url, content=fh.read(), headers={"Content-Type": mime})
            if put.status_code not in (200, 201):
                raise ProviderError(
                    f"Media upload failed: HTTP {put.status_code}",
                    category=classify(status_code=put.status_code, body=put.text),
                )
        return str(media_id)
