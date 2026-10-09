"""Structural skeleton — "modelar a estrutura de um vídeo" (Etapa 4, item
4B). Builds an abstract beat structure (role, target duration, shot/camera
style, caption/wpm targets) from a channel's measured grammar, or from one
specific Laboratório de vídeo run's own scenes when available (richer:
real per-beat durations and vision descriptors, not just channel-wide
averages).

D7: never a word of text from the reference — only numbers and labels. The
skeleton is filled in by the user's OWN topic and characters downstream
(ScriptAgent/StoryboardAgent, via {skeleton_guidance}).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_HOOK_MAX_S = 15.0
_GENERIC_ROLES = ["hook", "contexto", "escalada", "virada", "fecho"]


@dataclass
class SkeletonBeat:
    role: str
    duration_target_s: float
    shot_type: str = "other"
    camera_motion: str = "other"
    transition: str = "cut"  # "cut" | "fade"
    caption_style: str = ""  # "on" | "off" | ""
    wpm_target: float | None = None
    cliffhanger: bool = False
    hook_max_s: float | None = None


@dataclass
class Skeleton:
    beats: list[SkeletonBeat] = field(default_factory=list)
    serial: bool = False

    @property
    def n_beats(self) -> int:
        return len(self.beats)

    def to_config(self) -> list[dict[str, Any]]:
        return [asdict(b) for b in self.beats]


def skeleton_from_config(raw: list[dict[str, Any]] | None) -> Skeleton | None:
    if not raw:
        return None
    return Skeleton(beats=[SkeletonBeat(**b) for b in raw])


def build_skeleton_from_scenes(scenes: list[dict[str, Any]], *, serial: bool = False) -> Skeleton:
    """``scenes``: dicts shaped like ``LabScene`` rows (duration_s,
    beat_role, fade_in/fade_out, has_caption, wpm, vision)."""
    beats: list[SkeletonBeat] = []
    for s in scenes:
        vision = s.get("vision") or {}
        role = s.get("beat_role") or "contexto"
        beats.append(
            SkeletonBeat(
                role=role,
                duration_target_s=float(s.get("duration_s") or 4.0),
                shot_type=vision.get("shot_type", "other"),
                camera_motion=vision.get("camera_motion", "other"),
                transition="fade" if (s.get("fade_in") or s.get("fade_out")) else "cut",
                caption_style="on" if s.get("has_caption") else "off",
                wpm_target=s.get("wpm"),
                cliffhanger=role in ("cliffhanger", "cta"),
                hook_max_s=DEFAULT_HOOK_MAX_S if role == "hook" else None,
            )
        )
    return Skeleton(beats=beats, serial=serial)


def build_skeleton_from_grammar(grammar: dict[str, Any], *, n_beats: int = 5) -> Skeleton:
    """Fallback with no specific run analyzed — a generic
    hook/contexto/escalada/virada/fecho shape, sized from the channel's own
    overall medians (never a per-beat breakdown, since the grammar doesn't
    have one)."""
    roles = _GENERIC_ROLES[: max(2, min(n_beats, len(_GENERIC_ROLES)))]
    scene_s = (grammar.get("scene_duration_median_s") or {}).get("value") or 4.0
    wpm = (grammar.get("avg_wpm") or {}).get("value")
    pct_caption = (grammar.get("pct_scenes_with_caption") or {}).get("value") or 0.0
    pct_fade = (grammar.get("pct_scenes_with_fade") or {}).get("value") or 0.0

    beats = [
        SkeletonBeat(
            role=role,
            duration_target_s=DEFAULT_HOOK_MAX_S if role == "hook" else float(scene_s),
            transition="fade" if pct_fade >= 0.5 else "cut",
            caption_style="on" if pct_caption >= 0.5 else "off",
            wpm_target=wpm,
            cliffhanger=role == "fecho",
            hook_max_s=DEFAULT_HOOK_MAX_S if role == "hook" else None,
        )
        for role in roles
    ]
    return Skeleton(beats=beats)


def compile_skeleton_guidance(skeleton: Skeleton | None) -> str:
    """Renders a skeleton as prompt text for {skeleton_guidance} — numbers
    and labels only, exactly D7's rule."""
    if not skeleton or not skeleton.beats:
        return ""
    lines = [
        "Follow this structural skeleton (from a measured reference) for your OWN "
        "original topic — match the number of beats, their target durations, and "
        "pacing; never reuse any text, character, or plot from the reference:"
    ]
    for i, beat in enumerate(skeleton.beats, start=1):
        parts = [f"{i}. {beat.role} (~{beat.duration_target_s:.1f}s)"]
        if beat.hook_max_s:
            parts.append(f"hook must land within {beat.hook_max_s:.0f}s")
        if beat.wpm_target:
            parts.append(f"~{beat.wpm_target:.0f} words/min")
        if beat.transition == "fade":
            parts.append("fades in/out")
        if beat.caption_style == "on":
            parts.append("has an on-screen caption")
        if beat.cliffhanger:
            parts.append("ends on a cliffhanger/open loop or a call to action")
        lines.append(" — ".join(parts))
    lines.append(f"Total beats: {skeleton.n_beats}.")
    return "\n".join(lines)
