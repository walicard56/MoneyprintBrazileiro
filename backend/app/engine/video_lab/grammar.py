"""Per-video and per-channel "grammar" aggregation (Etapa 3) — the numbers
that fill a style profile's previously-null ritmo/música/legenda/imagens
fields, each with a confidence that scales with how many videos went into
it (1 video = low, 3-4 = medium, 5+ = high)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any

HOOK_WINDOW_S = 15.0


@dataclass
class SceneGrammarInput:
    index: int
    start_s: float
    end_s: float
    fade_in: bool = False
    fade_out: bool = False
    wpm: float | None = None
    has_caption: bool = False
    palette: list[str] = field(default_factory=list)
    beat_role: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    low, high = int(k), min(int(k) + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def _cuts_per_minute(scenes: list[SceneGrammarInput]) -> float | None:
    if not scenes:
        return None
    total_s = sum(s.duration_s for s in scenes)
    if total_s <= 0:
        return None
    return len(scenes) / (total_s / 60.0)


def build_video_grammar(
    scenes: list[SceneGrammarInput],
    *,
    silence_ratio: float | None = None,
    loudness_lufs: float | None = None,
) -> dict[str, Any]:
    """One video's grammar: scene-length stats, fade %, cuts/min for the
    hook (first 15s) vs. the body, average wpm, caption presence, palette,
    and beat-role counts. Returns ``{}`` for an empty scene list."""
    if not scenes:
        return {}

    durations = [s.duration_s for s in scenes]
    hook_scenes = [s for s in scenes if s.start_s < HOOK_WINDOW_S]
    body_scenes = [s for s in scenes if s.start_s >= HOOK_WINDOW_S]
    wpm_values = [s.wpm for s in scenes if s.wpm is not None]
    palette_counter: Counter[str] = Counter(c for s in scenes for c in s.palette)
    beat_counter: Counter[str] = Counter(s.beat_role for s in scenes if s.beat_role)

    return {
        "n_scenes": len(scenes),
        "total_duration_s": scenes[-1].end_s - scenes[0].start_s,
        "scene_duration_median_s": median(durations),
        "scene_duration_p25_s": _percentile(durations, 25),
        "scene_duration_p75_s": _percentile(durations, 75),
        "pct_scenes_with_fade": sum(1 for s in scenes if s.fade_in or s.fade_out) / len(scenes),
        "cuts_per_min_hook": _cuts_per_minute(hook_scenes),
        "cuts_per_min_body": _cuts_per_minute(body_scenes),
        "avg_wpm": (sum(wpm_values) / len(wpm_values)) if wpm_values else None,
        "pct_scenes_with_caption": sum(1 for s in scenes if s.has_caption) / len(scenes),
        "palette": [c for c, _ in palette_counter.most_common(5)],
        "beat_counts": dict(beat_counter),
        "silence_ratio": silence_ratio,
        "loudness_lufs": loudness_lufs,
    }


def _confidence_for(n: int) -> str:
    if n >= 5:
        return "high"
    if n >= 3:
        return "medium"
    return "low"


def _field(video_grammars: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [g[key] for g in video_grammars if g.get(key) is not None]
    if not values:
        return {"value": None, "confidence": "low", "n": 0}
    return {"value": median(values), "confidence": _confidence_for(len(values)), "n": len(values)}


def aggregate_channel_grammar(video_grammars: list[dict[str, Any]]) -> dict[str, Any]:
    """Combines several videos' ``build_video_grammar`` results into one
    channel-level grammar. Returns ``{}`` for an empty list."""
    if not video_grammars:
        return {}

    palette_counter: Counter[str] = Counter()
    for g in video_grammars:
        palette_counter.update(g.get("palette") or [])

    return {
        "videos_analyzed": len(video_grammars),
        "scene_duration_median_s": _field(video_grammars, "scene_duration_median_s"),
        "scene_duration_p25_s": _field(video_grammars, "scene_duration_p25_s"),
        "scene_duration_p75_s": _field(video_grammars, "scene_duration_p75_s"),
        "cuts_per_min_hook": _field(video_grammars, "cuts_per_min_hook"),
        "cuts_per_min_body": _field(video_grammars, "cuts_per_min_body"),
        "avg_wpm": _field(video_grammars, "avg_wpm"),
        "pct_scenes_with_fade": _field(video_grammars, "pct_scenes_with_fade"),
        "pct_scenes_with_caption": _field(video_grammars, "pct_scenes_with_caption"),
        "loudness_lufs": _field(video_grammars, "loudness_lufs"),
        "silence_ratio": _field(video_grammars, "silence_ratio"),
        "palette": [c for c, _ in palette_counter.most_common(5)],
    }
