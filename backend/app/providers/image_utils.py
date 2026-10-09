"""Shared helpers for LLM adapters that forward ``LLMRequest.images`` (D8)."""

from __future__ import annotations

import base64
import mimetypes

_DEFAULT_MIME = "image/jpeg"


def image_to_base64(path: str) -> tuple[str, str]:
    """Returns ``(mime_type, base64_data)`` for a local image file."""
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return mime or _DEFAULT_MIME, data


def image_to_data_url(path: str) -> str:
    """Returns a ``data:<mime>;base64,<data>`` URL for a local image file."""
    mime, data = image_to_base64(path)
    return f"data:{mime};base64,{data}"
