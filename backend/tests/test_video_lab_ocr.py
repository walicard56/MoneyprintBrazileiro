"""Tests for engine.video_lab.ocr. This dev machine has no tesseract
binary installed (confirmed — see services/binaries.py), which is exactly
the degrade-gracefully scenario item 4 of the spec calls out: detect_text
must return [] cleanly, never raise, never invent a result. caption_position
is pure and tested with fabricated OcrWord data regardless."""

from __future__ import annotations

from app.engine.video_lab.ocr import OcrWord, caption_position, detect_text, is_available


def test_is_available_reflects_this_machine_with_no_tesseract() -> None:
    assert is_available() is False


def test_detect_text_returns_empty_without_tesseract(tmp_path) -> None:
    # Doesn't even need a real image: the binary check short-circuits first.
    assert detect_text(str(tmp_path / "nonexistent.png")) == []


def _word(text: str, top: int, height: int = 20) -> OcrWord:
    return OcrWord(text=text, confidence=90.0, left=0, top=top, width=50, height=height)


def test_caption_position_top() -> None:
    assert caption_position([_word("legenda", top=10)], image_height=300) == "top"


def test_caption_position_bottom() -> None:
    assert caption_position([_word("legenda", top=260)], image_height=300) == "bottom"


def test_caption_position_center() -> None:
    assert caption_position([_word("legenda", top=140)], image_height=300) == "center"


def test_caption_position_empty_without_words() -> None:
    assert caption_position([], image_height=300) == ""
