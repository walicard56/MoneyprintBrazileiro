"""Beat-role assignment from scene statistics (Etapa 3).

Narration text is only ever held in memory here, to count questions and
"open loop" markers — the output carries roles, timestamps, and counts,
never a word of the narration itself (D6: style is learned abstractly)."""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.video_lab.scenes import RefinedScene

HOOK_MAX_S = 15.0
_CONTEXT_END_RATIO = 0.35
_ESCALATION_END_RATIO = 0.75

_OPEN_LOOP_MARKERS = (
    "mas antes", "só que", "até que", "no final", "mas o que você não sabe",
    "but first", "until", "wait for it", "what you don't know",
)
_CTA_MARKERS = (
    "se inscreva", "clique", "comente", "compartilhe", "siga", "deixe um like",
    "subscribe", "comment", "share", "click", "follow", "leave a like",
)


@dataclass
class BeatInfo:
    scene_index: int
    role: str  # hook | contexto | escalada | virada | fecho | cliffhanger | cta
    start_s: float
    end_s: float
    question_count: int = 0
    open_loop_count: int = 0


def _count_questions(text: str) -> int:
    return text.count("?")


def _count_open_loops(text: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(marker) for marker in _OPEN_LOOP_MARKERS)


def _closing_role(text: str, question_count: int, open_loop_count: int) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _CTA_MARKERS):
        return "cta"
    if question_count > 0 or open_loop_count > 0:
        return "cliffhanger"
    return "fecho"


def assign_beats(scenes: list[RefinedScene], narration_by_scene: dict[int, str]) -> list[BeatInfo]:
    """One ``BeatInfo`` per scene, in order. ``narration_by_scene`` maps a
    scene's ``index`` to its narration text (e.g. from ``speech.words_in``,
    joined) — pass ``{}`` to skip the question/open-loop counts (cliffhanger
    detection then falls back to "fecho" for the closing scene)."""
    if not scenes:
        return []

    video_start = scenes[0].start_s
    total_s = max(scenes[-1].end_s - video_start, 1e-6)
    n = len(scenes)

    beats: list[BeatInfo] = []
    for i, scene in enumerate(scenes):
        text = narration_by_scene.get(scene.index, "")
        question_count = _count_questions(text)
        open_loop_count = _count_open_loops(text)
        elapsed = scene.start_s - video_start
        progress = elapsed / total_s

        if i == 0 and elapsed < HOOK_MAX_S:
            role = "hook"
        elif i == n - 1:
            role = _closing_role(text, question_count, open_loop_count)
        elif progress < _CONTEXT_END_RATIO:
            role = "contexto"
        elif progress < _ESCALATION_END_RATIO:
            role = "escalada"
        else:
            role = "virada"

        beats.append(
            BeatInfo(
                scene_index=scene.index,
                role=role,
                start_s=scene.start_s,
                end_s=scene.end_s,
                question_count=question_count,
                open_loop_count=open_loop_count,
            )
        )
    return beats
