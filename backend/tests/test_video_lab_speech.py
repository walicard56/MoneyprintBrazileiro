"""Tests for engine.video_lab.speech: words_in (pure, fabricated word list
per the spec's own acceptance wording) plus one live smoke test of the
real faster-whisper wiring against a non-speech tone (just confirms it
runs end-to-end without crashing and degrades to an empty list — there's
no real recorded speech available to transcribe in this environment)."""

from __future__ import annotations

from app.engine.video_lab.scenes import RefinedScene
from app.engine.video_lab.speech import transcribe_words, words_in
from app.providers.base import Word


def _word(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end)


def test_words_in_keeps_only_words_inside_the_scene_window() -> None:
    scene = RefinedScene(index=0, start_s=2.0, end_s=4.0)
    words = [
        _word("antes", 0.0, 1.0),
        _word("entrando", 1.8, 2.2),  # midpoint 2.0 -> inside [2.0, 4.0)
        _word("dentro", 2.5, 3.0),
        _word("saindo", 3.8, 4.5),  # midpoint 4.15 -> outside
        _word("depois", 5.0, 6.0),
    ]

    selected = [w.text for w in words_in(scene, words)]

    assert selected == ["entrando", "dentro"]


def test_words_in_empty_scene_or_words_returns_empty() -> None:
    scene = RefinedScene(index=0, start_s=0.0, end_s=1.0)
    assert words_in(scene, []) == []


def test_transcribe_words_runs_end_to_end_on_a_non_speech_tone(tmp_path) -> None:
    """Real faster-whisper call (tiny model) against a pure tone — there's
    no actual speech, so this mainly proves the wiring (ffmpeg audio in,
    WhisperSTT call, word extraction) doesn't crash; an empty/near-empty
    result is expected and fine."""
    from tests.video_lab_helpers import make_tone_and_silence_audio

    audio_path = str(tmp_path / "tone.wav")
    make_tone_and_silence_audio(audio_path, tone_s=1.0, silence_s=1.0)

    words = transcribe_words(audio_path, model="tiny")

    assert isinstance(words, list)
    for w in words:
        assert isinstance(w, Word)
