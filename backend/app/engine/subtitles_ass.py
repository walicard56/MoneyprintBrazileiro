"""Minimal SRT -> ASS conversion (Etapa 6) — ``render_long.py`` burns
captions via ffmpeg's ``ass`` filter, which needs an ``.ass`` file; the STT
pipeline (``stt_whisper.py``/``stt_assemblyai.py``) only ever produces
``.srt``. This is a basic, single-style converter — no per-word karaoke
timing, just the same captions ffmpeg's ``subtitles`` filter would burn,
in a format that also supports styling (size/color/position) consistently
across ffmpeg builds that lack libass's SRT auto-styling.
"""

from __future__ import annotations

import re

_SRT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
_SRT_BLOCK_RE = re.compile(
    r"\d+\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)

_ALIGNMENT_BY_POSITION = {"top": 8, "center": 5, "bottom": 2}


def _srt_time_to_ass(value: str) -> str:
    match = _SRT_TIME_RE.match(value)
    if not match:
        return "0:00:00.00"
    h, m, s, ms = match.groups()
    centiseconds = int(ms) // 10
    return f"{int(h)}:{m}:{s}.{centiseconds:02d}"


def srt_to_ass(
    srt_text: str,
    *,
    width: int = 1920,
    height: int = 1080,
    fontsize: int = 48,
    color: str = "#FFFFFF",
    position: str = "bottom",
    uppercase: bool = False,
) -> str:
    """Returns the ``.ass`` file contents for ``srt_text``."""
    # ASS colors are &HAABBGGRR; drop the leading '#' and reverse RGB order.
    hexcolor = color.lstrip("#")
    if len(hexcolor) == 6:
        r, g, b = hexcolor[0:2], hexcolor[2:4], hexcolor[4:6]
    else:
        r, g, b = "FF", "FF", "FF"
    ass_color = f"&H00{b}{g}{r}".upper()
    alignment = _ALIGNMENT_BY_POSITION.get(position, 2)
    margin_v = 60 if position != "center" else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},{ass_color},{ass_color},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []
    for match in _SRT_BLOCK_RE.finditer(srt_text.strip() + "\n\n"):
        start, end, text = match.groups()
        text = " ".join(line.strip() for line in text.strip().splitlines())
        if uppercase:
            text = text.upper()
        text = text.replace("{", "(").replace("}", ")")  # ASS override-tag delimiters
        lines.append(f"Dialogue: 0,{_srt_time_to_ass(start)},{_srt_time_to_ass(end)},Default,,0,0,0,,{text}")

    return header + "\n".join(lines) + "\n"


def write_ass_from_srt(srt_path: str, ass_path: str, **kwargs) -> str:
    with open(srt_path, encoding="utf-8") as f:
        srt_text = f.read()
    ass_text = srt_to_ass(srt_text, **kwargs)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)
    return ass_path
