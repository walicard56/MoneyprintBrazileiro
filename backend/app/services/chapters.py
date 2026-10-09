"""Chapter extraction from a video's description (Etapa 2, item 1).

YouTube has no chapters API — creators mark them by convention, as
timestamped lines in the description (``0:00 Intro``, ``00:01:30 - The
twist``, ...). This is a pure function: the raw description is only ever
held in memory long enough to call this, then discarded (see
``services/reference_ingest.py``) — only the extracted ``Chapter`` list is
persisted, the same public-metadata footprint as a video's title.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# "0:00", "00:00", "0:00:00", "00:00:00" — mm:ss or hh:mm:ss, 1-2 digits
# per field.
_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}(?::\d{2}){1,2})\b")
# Separator between the timestamp and the chapter title: a dash/hyphen
# (optionally surrounded by spaces) or just whitespace.
_SEPARATOR_RE = re.compile(r"^[\s\-–—:]+")


class Chapter(BaseModel):
    title: str
    start_s: int


def _parse_timestamp(text: str) -> int | None:
    parts = text.split(":")
    try:
        values = [int(p) for p in parts]
    except ValueError:
        return None
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    if len(values) == 3:
        hours, minutes, seconds = values
        return hours * 3600 + minutes * 60 + seconds
    return None


def extract_chapters(description: str, *, min_chapters: int = 3) -> list[Chapter]:
    """Returns the chapter list, or ``[]`` if fewer than ``min_chapters``
    timestamped lines are found — a couple of stray timestamps mentioned in
    passing isn't a chapter list, so this avoids a false positive."""
    if not description:
        return []

    chapters: list[Chapter] = []
    for line in description.splitlines():
        match = _TIMESTAMP_RE.search(line)
        if not match:
            continue
        start_s = _parse_timestamp(match.group(1))
        if start_s is None:
            continue
        title = line[match.end() :]
        title = _SEPARATOR_RE.sub("", title).strip()
        if not title:
            # The timestamp might come after the title instead of before it.
            title = _SEPARATOR_RE.sub("", line[: match.start()]).strip()
        if not title:
            continue
        chapters.append(Chapter(title=title, start_s=start_s))

    if len(chapters) < min_chapters:
        return []

    # YouTube requires the first chapter to start at 0:00 and timestamps to
    # be strictly increasing — lines that don't fit that shape are almost
    # certainly not a real chapter list (e.g. a list of unrelated links each
    # followed by an unrelated number).
    chapters.sort(key=lambda c: c.start_s)
    if chapters[0].start_s != 0:
        return []
    for prev, cur in zip(chapters, chapters[1:]):
        if cur.start_s <= prev.start_s:
            return []
    return chapters
