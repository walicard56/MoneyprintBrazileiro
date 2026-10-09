"""Drives one Laboratório de vídeo analysis (Etapa 3) from ``pending``
through to ``ready``/``failed`` — mirrors the shape of
``services/reference_ingest.py``: updates status/stage/progress as it
goes, and never raises (every failure is recorded on the row instead of
crashing the calling thread/task, D7).

Two layers, per D6: ``LabScene.private`` is ephemeral (OCR'd text, the
scene's own narration snippet) and wiped by ``lab.purge_expired`` — it
never feeds generation. Everything else (numbers and labels: wpm, palette,
vision descriptors, beat role) is the permanent "grammar" layer.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import LabRunStatus
from app.db.models import ChannelGrammar, LabScene, VideoGrammar, VideoLabRun
from app.engine.video_lab import audio_metrics, beats, frames, ocr, palette as palette_mod, speech
from app.engine.video_lab.autotune import autotune_scenes
from app.engine.video_lab.grammar import SceneGrammarInput, aggregate_channel_grammar, build_video_grammar
from app.engine.video_lab.scenes import refine_scenes
from app.engine.video_lab.vision import analyze_scene
from app.services.logs import log

MAX_AUTOTUNE_ATTEMPTS_LOGGED = "autotune_attempts"


def run_lab_analysis(db: Session, run_id: str) -> None:
    run = db.get(VideoLabRun, run_id)
    if run is None:
        return

    try:
        _run(db, run)
    except Exception as exc:  # noqa: BLE001 - never crash the calling thread/task
        db.rollback()
        run = db.get(VideoLabRun, run_id)
        if run is not None:
            run.status = LabRunStatus.FAILED
            run.error = str(exc)[:2000]
            db.commit()
        log(db, f"Lab run {run_id} failed: {exc}", stage="failed", project_id=None)


def _run(db: Session, run: VideoLabRun) -> None:
    run.status = LabRunStatus.RUNNING
    run.stage = "detecting_scenes"
    run.progress = 10
    db.commit()

    autotune_result = autotune_scenes(run.media_path)
    run.params = {
        **run.params,
        "threshold_used": autotune_result.threshold_used,
        "autotune_attempts": autotune_result.attempts,
        "fps": autotune_result.fps,
    }
    run.stage = "refining_scenes"
    run.progress = 25
    db.commit()

    refined = refine_scenes(autotune_result.scenes, run.media_path)

    run.stage = "extracting_audio"
    run.progress = 40
    db.commit()

    run_dir = os.path.join(settings.media_root, "lab", run.id)
    os.makedirs(run_dir, exist_ok=True)
    audio_path = os.path.join(run_dir, "audio.wav")
    has_audio = audio_metrics.extract_audio(run.media_path, audio_path)
    silence = audio_metrics.silence_ratio(audio_path) if has_audio else None
    loudness = audio_metrics.integrated_loudness(audio_path) if has_audio else None
    words = speech.transcribe_words(audio_path) if has_audio else []

    run.stage = "analyzing_scenes"
    run.progress = 60
    db.commit()

    narration_by_scene: dict[int, str] = {}
    scene_rows: list[LabScene] = []
    grammar_inputs: list[SceneGrammarInput] = []

    for scene in refined:
        anchor_path = os.path.join(run_dir, f"scene_{scene.index:04d}_anchor.jpg")
        last_path = os.path.join(run_dir, f"scene_{scene.index:04d}_last.jpg")
        frames.extract_scene_thumbnails(run.media_path, scene.start_s, scene.end_s, anchor_path, last_path)

        scene_words = speech.words_in(scene, words)
        text = " ".join(w.text for w in scene_words)
        narration_by_scene[scene.index] = text
        wpm = audio_metrics.words_per_minute(len(scene_words), scene.duration_s) if scene_words else None

        colors = palette_mod.dominant_colors(anchor_path) if os.path.exists(anchor_path) else []

        ocr_words = ocr.detect_text(anchor_path) if os.path.exists(anchor_path) else []
        has_caption = len(ocr_words) > 0

        vision_descriptors = None
        if os.path.exists(anchor_path) and os.path.exists(last_path):
            vision_descriptors = analyze_scene(db, anchor_path, last_path)
            if vision_descriptors is not None:
                has_caption = has_caption or vision_descriptors.has_caption

        grammar_inputs.append(
            SceneGrammarInput(
                index=scene.index,
                start_s=scene.start_s,
                end_s=scene.end_s,
                fade_in=scene.fade_in,
                fade_out=scene.fade_out,
                wpm=wpm,
                has_caption=has_caption,
                palette=colors,
                beat_role="",  # filled in below, after assign_beats
            )
        )
        scene_rows.append(
            LabScene(
                run_id=run.id,
                index=scene.index,
                start_s=scene.start_s,
                end_s=scene.end_s,
                duration_s=scene.duration_s,
                anchor_thumb=anchor_path if os.path.exists(anchor_path) else "",
                last_thumb=last_path if os.path.exists(last_path) else "",
                fade_in=scene.fade_in,
                fade_out=scene.fade_out,
                wpm=wpm,
                has_caption=has_caption,
                palette=colors,
                vision=vision_descriptors.model_dump() if vision_descriptors else {},
                private={
                    "narration": text,
                    "ocr_words": [w.text for w in ocr_words],
                },
            )
        )

    run.stage = "assigning_beats"
    run.progress = 85
    db.commit()

    beat_infos = beats.assign_beats(refined, narration_by_scene)
    for row, beat_info, grammar_input in zip(scene_rows, beat_infos, grammar_inputs):
        row.beat_role = beat_info.role
        grammar_input.beat_role = beat_info.role

    db.add_all(scene_rows)

    video_grammar = build_video_grammar(grammar_inputs, silence_ratio=silence, loudness_lufs=loudness)
    db.add(VideoGrammar(run_id=run.id, grammar=video_grammar))

    if not settings.lab_keep_media and run.media_path and os.path.exists(run.media_path):
        try:
            os.remove(run.media_path)
        except OSError:
            pass
    if has_audio and os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass

    run.status = LabRunStatus.READY
    run.stage = "ready"
    run.progress = 100
    run.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.lab_retention_days)
    db.commit()

    # Rebuilt AFTER the status flip above: the rebuild query only counts
    # READY runs, so a project's grammar must see this run as done first.
    if run.project_id:
        rebuild_channel_grammar_for_project(db, run.project_id)

    log(db, f"Lab run {run.id} ready ({len(scene_rows)} scenes).", stage="ready", project_id=run.project_id)


def rebuild_channel_grammar_for_project(db: Session, project_id: str) -> None:
    rows = list(
        db.execute(
            select(VideoGrammar)
            .join(VideoLabRun, VideoGrammar.run_id == VideoLabRun.id)
            .where(VideoLabRun.project_id == project_id, VideoLabRun.status == LabRunStatus.READY)
        ).scalars()
    )
    grammars = [r.grammar for r in rows]
    aggregated = aggregate_channel_grammar(grammars)

    existing = db.execute(
        select(ChannelGrammar).where(ChannelGrammar.project_id == project_id)
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            ChannelGrammar(project_id=project_id, grammar=aggregated, videos_analyzed=len(grammars))
        )
    else:
        existing.grammar = aggregated
        existing.videos_analyzed = len(grammars)
    db.commit()


def purge_expired(db: Session) -> int:
    """Deletes media/thumbnails/``private`` for every run past its
    ``expires_at`` — the Celery Beat task ``lab.purge_expired``."""
    now = datetime.now(timezone.utc)
    runs = list(
        db.execute(
            select(VideoLabRun).where(
                VideoLabRun.expires_at.is_not(None), VideoLabRun.expires_at <= now
            )
        ).scalars()
    )
    purged = 0
    for run in runs:
        for scene in run.scenes:
            for path in (scene.anchor_thumb, scene.last_thumb):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            scene.anchor_thumb = ""
            scene.last_thumb = ""
            scene.private = {}
        if run.media_path and os.path.exists(run.media_path):
            try:
                os.remove(run.media_path)
            except OSError:
                pass
        run.expires_at = None
        purged += 1
    if purged:
        db.commit()
    return purged
