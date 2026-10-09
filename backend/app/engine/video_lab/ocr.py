"""On-screen caption/text detection (Etapa 3) — tesseract optional; only
words at confidence >= MIN_CONFIDENCE are kept. Used only to flag caption
presence/position for the private (ephemeral) analysis layer, D6 — the read
text itself is never stored permanently and never feeds generation."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.binaries import tesseract_path

MIN_CONFIDENCE = 80.0


@dataclass
class OcrWord:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int


def is_available() -> bool:
    return tesseract_path() is not None


def detect_text(image_path: str) -> list[OcrWord]:
    """High-confidence OCR words found in the image. Returns ``[]`` with no
    tesseract installed (common on Windows dev machines, per the product
    spec) — never raises, never invents a result."""
    if not is_available():
        return []
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return []

    pytesseract.pytesseract.tesseract_cmd = tesseract_path()
    try:
        with Image.open(image_path) as image:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception:  # noqa: BLE001 - OCR is always best-effort
        return []

    words: list[OcrWord] = []
    for i, text in enumerate(data.get("text", [])):
        text = text.strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][i])
        except (ValueError, IndexError, KeyError):
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        words.append(
            OcrWord(
                text=text,
                confidence=confidence,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
            )
        )
    return words


def caption_position(words: list[OcrWord], image_height: int) -> str:
    """``"top"``/``"center"``/``"bottom"``/``""`` from the vertical position
    of the detected words — a simple heuristic for tagging a scene's
    caption position without needing to know anything about the text."""
    if not words or image_height <= 0:
        return ""
    avg_center = sum(w.top + w.height / 2 for w in words) / len(words)
    ratio = avg_center / image_height
    if ratio < 0.33:
        return "top"
    if ratio > 0.66:
        return "bottom"
    return "center"
