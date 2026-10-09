"""Pure parsing tests for every YouTube URL shape the "Canais" feature accepts.

No network involved — see ``app/services/url_parse.py``.
"""

from __future__ import annotations

import pytest

from app.services.url_parse import InvalidYouTubeUrl, parse_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s&list=PLxyz",
    ],
)
def test_watch_url_variants(url: str) -> None:
    parsed = parse_youtube_url(url)
    assert parsed.kind == "video"
    assert parsed.video_id == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc123",
    ],
)
def test_youtu_be_variants(url: str) -> None:
    parsed = parse_youtube_url(url)
    assert parsed.kind == "video"
    assert parsed.video_id == "dQw4w9WgXcQ"


def test_shorts_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/shorts/abcDEF12345")
    assert parsed.kind == "video"
    assert parsed.video_id == "abcDEF12345"


def test_channel_id_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/channel/UCtest1234567890")
    assert parsed.kind == "channel"
    assert parsed.channel_id == "UCtest1234567890"


def test_handle_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/@SomeCreator")
    assert parsed.kind == "channel"
    assert parsed.handle == "SomeCreator"


def test_handle_url_with_trailing_tab() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/@SomeCreator/videos")
    assert parsed.kind == "channel"
    assert parsed.handle == "SomeCreator"


def test_user_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/user/LegacyUser")
    assert parsed.kind == "channel"
    assert parsed.username == "LegacyUser"


def test_custom_c_url() -> None:
    parsed = parse_youtube_url("https://www.youtube.com/c/CustomName")
    assert parsed.kind == "channel"
    assert parsed.custom_name == "CustomName"


def test_m_dot_host_is_allowed() -> None:
    parsed = parse_youtube_url("https://m.youtube.com/channel/UCtest1234567890")
    assert parsed.kind == "channel"
    assert parsed.channel_id == "UCtest1234567890"


def test_disallowed_host_rejected() -> None:
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url("https://evil.example.com/watch?v=dQw4w9WgXcQ")


def test_ssrf_style_host_rejected() -> None:
    """The allowlist, not a blocklist, is what keeps this safe against SSRF —
    confirm a host merely containing "youtube.com" as a substring is still
    rejected, since hostname matching (not substring matching) is used."""
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ")


def test_watch_without_v_param_rejected() -> None:
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url("https://www.youtube.com/watch?list=PLxyz")


def test_unrecognized_path_rejected() -> None:
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url("https://www.youtube.com/results?search_query=cats")


def test_malformed_id_rejected() -> None:
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url("https://www.youtube.com/watch?v=<script>alert(1)</script>")
