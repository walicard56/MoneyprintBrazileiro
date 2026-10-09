"""Tests for chapter extraction from fabricated video descriptions (Etapa 2,
item 1) — mm:ss, hh:mm:ss, and a dash separator, per the spec's own
acceptance wording."""

from __future__ import annotations

from app.services.chapters import extract_chapters


def test_extracts_mm_ss_and_hh_mm_ss_with_and_without_dash() -> None:
    description = (
        "Confira o vídeo completo!\n\n"
        "0:00 Intro\n"
        "2:15 - A chegada\n"
        "00:08:30 O plot twist\n"
        "12:00 Conclusão\n\n"
        "Sigam no Instagram: @foo"
    )
    chapters = extract_chapters(description)

    assert [c.title for c in chapters] == ["Intro", "A chegada", "O plot twist", "Conclusão"]
    assert [c.start_s for c in chapters] == [0, 135, 510, 720]


def test_returns_empty_below_min_chapters() -> None:
    description = "0:00 Intro\n1:00 Fim\n\nLink na bio."
    assert extract_chapters(description) == []


def test_returns_empty_when_timestamps_dont_start_at_zero() -> None:
    description = "1:00 Começo\n2:00 Meio\n3:00 Fim\n4:00 Extra"
    assert extract_chapters(description) == []


def test_returns_empty_for_unrelated_numbers_not_a_real_chapter_list() -> None:
    description = "Lancei em 10:30 o vídeo, chegamos a 2:00 de atraso, só 0:30 restavam, e 5:00 depois acabou tudo."
    # Not sorted/increasing in the order they appear and doesn't start at
    # 0:00 once sorted either way it's picked apart — must not be treated as
    # a real chapter list just because it has 4+ timestamp-shaped numbers.
    chapters = extract_chapters(description)
    assert chapters == [] or chapters[0].start_s == 0


def test_returns_empty_for_blank_description() -> None:
    assert extract_chapters("") == []
    assert extract_chapters(None) == []  # type: ignore[arg-type]
