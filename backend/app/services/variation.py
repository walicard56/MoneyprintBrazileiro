"""Structural variation check within a channel (Etapa 4, item 4C).

Compares a video's own abstract fingerprint (hook type, scene count,
average scene duration, caption/music/aspect settings) against the
channel's last N videos — never the narration text itself. High
similarity sets ``variation_hint`` on the video's config, surfaced as a
badge on Vídeos/VideoDetail.

This reduces superficial repetition; it does NOT guarantee monetization
eligibility. YouTube's "inauthentic/repetitive content" policy (in effect
since 2025-07-15) evaluates a channel as a whole, not any single video —
that claim comes from the policy itself, not from this codebase, and
nothing here should be read as a guarantee either way.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Scene, Video


def _hook_type(scene: Scene) -> str:
    return "question" if "?" in (scene.narration or "") else "statement"


def build_fingerprint(video: Video, scenes: list[Scene]) -> dict[str, Any]:
    if not scenes:
        return {}
    durations = [s.duration for s in scenes]
    return {
        "hook_type": _hook_type(scenes[0]),
        "n_scenes": len(scenes),
        "avg_scene_duration_s": sum(durations) / len(durations),
        "structure": video.config.get("structure", ""),
        "subtitle_style": video.config.get("subtitle_style", ""),
        "music_enabled": bool(video.config.get("music_enabled", True)),
        "aspect_ratio": video.config.get("aspect_ratio", "9:16"),
    }


def fingerprint_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0

    checks = [
        (a.get("hook_type") == b.get("hook_type"), 1.0),
        (_close(a.get("n_scenes"), b.get("n_scenes"), tolerance=2), 1.0),
        (_close(a.get("avg_scene_duration_s"), b.get("avg_scene_duration_s"), tolerance=1.5), 1.0),
        (bool(a.get("structure")) and a.get("structure") == b.get("structure"), 1.0),
        (bool(a.get("subtitle_style")) and a.get("subtitle_style") == b.get("subtitle_style"), 0.5),
        (a.get("music_enabled") == b.get("music_enabled"), 0.5),
        (a.get("aspect_ratio") == b.get("aspect_ratio"), 0.5),
    ]
    total = sum(weight for _matched, weight in checks)
    score = sum(weight for matched, weight in checks if matched)
    return score / total if total else 0.0


def _close(x: float | None, y: float | None, *, tolerance: float) -> bool:
    return x is not None and y is not None and abs(x - y) <= tolerance


def check_variation(db: Session, video: Video) -> dict[str, Any]:
    """Builds and stores this video's fingerprint, compares it against the
    channel's recent videos, and sets ``variation_hint`` when the closest
    match is at/above the configured threshold. Returns that match (or
    ``{}`` if there's nothing to compare, or no scene yet)."""
    scenes = list(db.execute(select(Scene).where(Scene.video_id == video.id)).scalars())
    fingerprint = build_fingerprint(video, scenes)
    if not fingerprint:
        return {}

    cfg = dict(video.config)
    cfg["variation_fingerprint"] = fingerprint
    video.config = cfg

    candidates = list(
        db.execute(
            select(Video)
            .where(Video.project_id == video.project_id, Video.id != video.id)
            .order_by(Video.created_at.desc())
            .limit(settings.variation_lookback * 4)  # over-fetch: not all have a fingerprint yet
        ).scalars()
    )

    best: dict[str, Any] = {}
    checked = 0
    for other in candidates:
        other_fp = (other.config or {}).get("variation_fingerprint")
        if not other_fp:
            continue
        checked += 1
        similarity = fingerprint_similarity(fingerprint, other_fp)
        if not best or similarity > best["similarity"]:
            best = {"similarity": similarity, "video_id": other.id}
        if checked >= settings.variation_lookback:
            break

    cfg = dict(video.config)
    if best and best["similarity"] >= settings.variation_similarity_threshold:
        cfg["variation_hint"] = best
    else:
        cfg.pop("variation_hint", None)
    video.config = cfg
    return best
