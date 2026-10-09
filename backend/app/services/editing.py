"""In-app video editor: scene split/merge and an undo/redo log (Etapa 7).

``before``/``after`` on each ``EditOperation`` are full snapshots of the
video's scene list, so undo/redo never special-cases what kind of edit it
was — it just replaces the current scenes with a snapshot.

Every function here re-queries scenes with ``_scenes_for`` instead of
reading ``video.scenes``: that relationship is only populated/reordered
when the ORM (re)loads it from the DB, not live as ``.index`` changes or
as siblings are added with a bare ``video_id=`` (no ``back_populates``
append) — trusting the cached collection mid-edit silently drops or
misorders scenes.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import EditOperation, Scene, Video

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# created_at/updated_at are datetimes (not JSON-serializable as stored on
# EditOperation) and shouldn't be reconstructed from a stale snapshot
# anyway — a restored scene gets its own fresh timestamps.
_SCENE_COLUMNS = [c.name for c in Scene.__table__.columns if c.name not in ("created_at", "updated_at")]


def _scenes_for(db: Session, video_id: str) -> list[Scene]:
    return list(
        db.execute(select(Scene).where(Scene.video_id == video_id).order_by(Scene.index)).scalars()
    )


def snapshot_scenes(db: Session, video: Video) -> list[dict[str, Any]]:
    return [{name: getattr(scene, name) for name in _SCENE_COLUMNS} for scene in _scenes_for(db, video.id)]


def restore_scenes(db: Session, video: Video, snapshot: list[dict[str, Any]]) -> None:
    for existing in _scenes_for(db, video.id):
        db.delete(existing)
    db.flush()
    for item in snapshot:
        db.add(Scene(**item))
    db.flush()


def record_edit(
    db: Session, video: Video, kind: str, before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> None:
    """Appends ``kind`` as the next op and discards any redo tail — the
    same semantics as a text editor: editing after an undo throws away
    the undone-then-abandoned future."""
    cfg = dict(video.config)
    cursor = int(cfg.get("edit_cursor", 0))
    db.execute(delete(EditOperation).where(EditOperation.video_id == video.id, EditOperation.seq >= cursor))
    db.add(EditOperation(video_id=video.id, seq=cursor, kind=kind, before=before, after=after))
    cfg["edit_cursor"] = cursor + 1
    video.config = cfg


def undo(db: Session, video: Video) -> bool:
    """Returns False with no change if there's nothing to undo."""
    cfg = dict(video.config)
    cursor = int(cfg.get("edit_cursor", 0))
    if cursor <= 0:
        return False
    op = db.execute(
        select(EditOperation).where(EditOperation.video_id == video.id, EditOperation.seq == cursor - 1)
    ).scalar_one_or_none()
    if op is None:
        return False
    restore_scenes(db, video, op.before)
    cfg["edit_cursor"] = cursor - 1
    video.config = cfg
    return True


def redo(db: Session, video: Video) -> bool:
    """Returns False with no change if there's nothing to redo."""
    cfg = dict(video.config)
    cursor = int(cfg.get("edit_cursor", 0))
    op = db.execute(
        select(EditOperation).where(EditOperation.video_id == video.id, EditOperation.seq == cursor)
    ).scalar_one_or_none()
    if op is None:
        return False
    restore_scenes(db, video, op.after)
    cfg["edit_cursor"] = cursor + 1
    video.config = cfg
    return True


def split_scene(db: Session, video: Video, scene: Scene, *, at_ratio: float) -> tuple[Scene, Scene]:
    """Splits ``scene`` into two, at roughly ``at_ratio`` of the way through
    its narration (by word count, the nearest sentence boundary if there is
    one, else just the word index) — both halves start as a copy of the
    original scene's visuals/camera, since there's no new image yet for the
    half that didn't exist before."""
    words = scene.narration.split()
    if len(words) < 2:
        raise ValueError("Scene narration is too short to split.")
    at_ratio = min(max(at_ratio, 0.0), 1.0)
    target_idx = max(1, min(len(words) - 1, round(len(words) * at_ratio)))

    sentences = [s for s in _SENTENCE_SPLIT_RE.split(scene.narration.strip()) if s.strip()]
    split_idx = target_idx
    if len(sentences) > 1:
        cursor = 0
        best_idx, best_dist = target_idx, None
        for sentence in sentences[:-1]:
            cursor += len(sentence.split())
            dist = abs(cursor - target_idx)
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = cursor, dist
        split_idx = max(1, min(len(words) - 1, best_idx))

    first_words, second_words = words[:split_idx], words[split_idx:]
    ratio = len(first_words) / len(words)
    original_duration = scene.duration  # `first` below is `scene` itself, not a copy

    first = scene
    first.narration = " ".join(first_words)
    first.duration = max(0.5, round(original_duration * ratio, 2))

    # Make room right after `first` before inserting, so `second` never
    # shares an index with another scene even transiently (index ties would
    # make the eventual re-sort order undefined).
    for other in _scenes_for(db, video.id):
        if other.id != first.id and other.index > first.index:
            other.index += 1
    db.flush()

    second = Scene(
        video_id=video.id,
        index=first.index + 1,
        duration=max(0.5, round(original_duration * (1 - ratio), 2)),
        narration=" ".join(second_words),
        dialogue=scene.dialogue,
        character_slugs=list(scene.character_slugs or []),
        location=scene.location,
        visual_description=scene.visual_description,
        visual_prompt=scene.visual_prompt,
        video_prompt=scene.video_prompt,
        camera=dict(scene.camera or {}),
        action=scene.action,
        lighting=scene.lighting,
        transition=scene.transition,
        sfx=scene.sfx,
        music=scene.music,
        subtitle=scene.subtitle,
        subtitle_position=scene.subtitle_position,
        image_path=scene.image_path,
        clip_path=scene.clip_path,
        status=scene.status,
    )
    db.add(second)
    db.flush()
    _renumber(db, video)
    return first, second


def merge_scenes(db: Session, video: Video, first: Scene, second: Scene) -> Scene:
    """Merges ``second`` into ``first`` (``first`` must come immediately
    before ``second``) — keeps ``first``'s visuals, concatenates narration,
    sums duration."""
    if second.index != first.index + 1:
        raise ValueError("Scenes to merge must be adjacent.")
    first.narration = f"{first.narration} {second.narration}".strip()
    first.dialogue = f"{first.dialogue} {second.dialogue}".strip() if second.dialogue else first.dialogue
    first.duration = round(first.duration + second.duration, 2)
    db.delete(second)
    db.flush()
    _renumber(db, video)
    return first


def _renumber(db: Session, video: Video) -> None:
    for i, scene in enumerate(_scenes_for(db, video.id), start=1):
        scene.index = i
    db.flush()
