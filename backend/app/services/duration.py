"""Free-text duration parsing (Etapa 6) — "20 min", "1h30", "uma hora e
meia", "90s", "1:30:00" → seconds. Supports pt-BR and English; a bare
number is interpreted as seconds, matching how ``video.config["duration"]``
is already used everywhere else in this codebase.
"""

from __future__ import annotations

import re

_HMS_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_NUMBER_WORD_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hora|horas|m|min|mins|minuto|minutos|s|sec|segundo|segundos)\b", re.IGNORECASE)
_BARE_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")

# "uma hora", "meia hora", "uma hora e meia" — word numbers only need to
# cover the small set actually likely to be typed; this is not a general
# number-words parser.
_WORD_NUMBERS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "meia": 0.5, "meio": 0.5,
}

_UNIT_SECONDS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hora": 3600, "horas": 3600,
    "m": 60, "min": 60, "mins": 60, "minuto": 60, "minutos": 60,
    "s": 1, "sec": 1, "segundo": 1, "segundos": 1,
}


def _parse_number(text: str) -> float:
    return float(text.replace(",", "."))


def _parse_word_numbers(text: str) -> int | None:
    """"uma hora e meia" -> 5400, "meia hora" -> 1800 — a short, explicit
    set of spoken-number phrases, not general number-word parsing."""
    lowered = text.lower()
    if "hora" not in lowered:
        return None

    total_hours = 0.0
    found = False
    # "meia hora" (half an hour) said on its own, with no leading number word.
    if re.search(r"\bmeia\s+hora\b", lowered) and not re.search(r"\bhora[s]?\s+e\s+meia\b", lowered):
        total_hours += 0.5
        found = True

    for word, value in _WORD_NUMBERS.items():
        if word == "meia":
            continue
        if re.search(rf"\b{word}\s+hora", lowered):
            total_hours += value
            found = True
    if re.search(r"\bhora[s]?\s+e\s+meia\b", lowered):
        total_hours += 0.5
        found = True

    return round(total_hours * 3600) if found else None


def parse_duration(text: str, language: str = "pt") -> int | None:
    """Returns the duration in seconds, or ``None`` if ``text`` couldn't be
    parsed at all — callers should fall back to a sane default and warn,
    never silently guess."""
    text = (text or "").strip()
    if not text:
        return None

    if _BARE_NUMBER_RE.match(text):
        return round(_parse_number(text))

    match = _HMS_RE.match(text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    word_result = _parse_word_numbers(text)
    if word_result is not None:
        return word_result

    total_seconds = 0.0
    found_any = False
    for match in _NUMBER_WORD_RE.finditer(text):
        value = _parse_number(match.group(1))
        unit = match.group(2).lower()
        total_seconds += value * _UNIT_SECONDS[unit]
        found_any = True

    return round(total_seconds) if found_any else None
