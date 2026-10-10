"""Unit tests for services.media_download's yt-dlp wrapper — yt_dlp.YoutubeDL
itself is faked (no real network calls in tests), but the duration-rejection
and output-path logic are the module's own and run for real."""

from __future__ import annotations

import os

import pytest
import yt_dlp

from app.services.media_download import MediaDownloadError, download_video


_CAPTURED_OPTS: list[dict] = []


class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: records the options it was built
    with, and ``download()`` drives the real ``match_filter`` callback
    exactly like the real library would before fetching anything."""

    def __init__(self, opts: dict) -> None:
        self.opts = opts
        _CAPTURED_OPTS.append(opts)

    def __enter__(self) -> "_FakeYDL":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def download(self, urls: list[str]) -> int:
        reason = self.opts["match_filter"]({"duration": self._fake_duration})
        if reason:
            raise yt_dlp.utils.DownloadError(reason)
        out_path = self.opts["outtmpl"] % {"ext": "mp4"}
        with open(out_path, "wb") as fh:
            fh.write(b"fake video bytes")
        return 0


def test_rejects_video_longer_than_max_duration(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeYDL._fake_duration = 5000
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)

    with pytest.raises(MediaDownloadError, match="too long"):
        download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=10)


def test_downloads_and_returns_output_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeYDL._fake_duration = 30
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)

    result = download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=600)

    assert result == os.path.join(str(tmp_path), "media.mp4")
    assert os.path.exists(result)


def test_download_error_wrapped_as_media_download_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FailingYDL(_FakeYDL):
        def download(self, urls: list[str]) -> int:
            raise yt_dlp.utils.DownloadError("Private video")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FailingYDL)

    with pytest.raises(MediaDownloadError, match="Private video"):
        download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=600)


def test_passes_bundled_ffmpeg_location_to_yt_dlp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: on Windows dev machines without ffmpeg on PATH, yt-dlp
    must still be told where the imageio-ffmpeg-bundled binary is (via
    services/binaries.py), or merging separately-downloaded video+audio
    streams fails with 'ffmpeg is not installed' even though it's available."""
    _CAPTURED_OPTS.clear()
    _FakeYDL._fake_duration = 30
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr("app.services.media_download.ffmpeg_path", lambda: "C:/bundled/ffmpeg.exe")

    download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=600)

    assert _CAPTURED_OPTS[-1]["ffmpeg_location"] == "C:/bundled/ffmpeg.exe"
    assert "bv*" in _CAPTURED_OPTS[-1]["format"]


def test_falls_back_to_progressive_format_without_any_ffmpeg(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ffmpeg anywhere (system or bundled): must not request a merge it
    can't perform — falls back to a single pre-muxed stream instead."""
    _CAPTURED_OPTS.clear()
    _FakeYDL._fake_duration = 30
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr("app.services.media_download.ffmpeg_path", lambda: None)

    download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=600)

    assert "ffmpeg_location" not in _CAPTURED_OPTS[-1]
    assert "+" not in _CAPTURED_OPTS[-1]["format"]


def test_missing_yt_dlp_raises_media_download_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if name == "yt_dlp":
            raise ImportError("no module named yt_dlp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    with pytest.raises(MediaDownloadError, match="yt-dlp is not installed"):
        download_video("https://www.youtube.com/watch?v=x", str(tmp_path), max_duration_s=600)
