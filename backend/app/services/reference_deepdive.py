"""Deep-dive analysis for a reference channel's best-performing videos.

``run_deep_dive`` drives one ``ReferenceVideo`` from ``pending`` through to
``ready``/``failed`` (mirrors ``services/reference_ingest.py``'s shape) and
never raises. Off by default (``MP_ENABLE_REFERENCE_MEDIA_DOWNLOAD=false``);
``services/reference_ingest.py`` only ever dispatches this when the flag is
on, for a channel's top ``reference_deepdive_top_n`` videos by
``outlier_score`` (or a single-video reference's one video).

Pipeline, reusing the exact engine modules the Laboratório de vídeo (Etapa
3) already uses on the user's own uploads — applied here to media
downloaded via ``services/media_download``:

1. Download the video (<=480p, duration-capped) to a scratch temp dir.
2. Transcribe it locally with faster-whisper (``engine/video_lab/speech``)
   — free, no API key, no third-party upload — and store the transcript
   like any other (``transcript_status=fetched``), subject to the existing
   ``MP_KEEP_TRANSCRIPTS`` retention policy.
3. Detect scenes/cuts, and for each one: words/min, caption presence, and
   an abstract vision descriptor (shot type, mood, ...) via the same
   LLM-vision call the Lab uses — never the frame image itself, only its
   derived JSON descriptor (same policy as ``thumbnail_vision.py``).
4. Assign beat roles (hook/contexto/escalada/virada/fecho/cliffhanger/cta)
   and derive a handful of deterministic, human-readable notes about where
   attention likely concentrates — an estimate from structure/pacing, never
   real audience-retention data (no official API exposes that for a video
   the user doesn't own).

The scratch temp dir (downloaded media, extracted audio, extracted frames)
is always removed at the end, success or failure — only derived numbers and
text are ever persisted (D3: never retain third-party media).
"""

from __future__ import annotations

import os
import shutil
import tempfile

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import DeepDiveStatus, LogLevel, TranscriptStatus
from app.db.models import Project, ReferenceVideo
from app.services.logs import log
from app.services.media_download import MediaDownloadError, download_video
from app.services.originality import minhash_signature
from app.services.transcripts import delete_transcript, write_transcript


def run_deep_dive(db: Session, reference_video_id: str) -> None:
    video = db.get(ReferenceVideo, reference_video_id)
    if video is None:
        return
    try:
        _run(db, video)
    except Exception as exc:  # noqa: BLE001 - never crash the calling thread/task
        db.rollback()
        _fail(db, reference_video_id, f"Deep-dive failed: {exc}")


def _run(db: Session, video: ReferenceVideo) -> None:
    project_id = video.source.project_id if video.source else None

    video.deepdive_status = DeepDiveStatus.RUNNING
    video.deepdive_stage = "downloading"
    video.deepdive_error = ""
    db.commit()

    tmp_dir = tempfile.mkdtemp(prefix="mp_refdd_")
    try:
        url = f"https://www.youtube.com/watch?v={video.external_id}"
        try:
            media_path = download_video(
                url, tmp_dir, max_duration_s=settings.reference_deepdive_max_duration_s
            )
        except MediaDownloadError as exc:
            _fail(db, video.id, str(exc))
            return

        from app.engine.video_lab import audio_metrics, beats, frames as lab_frames, speech
        from app.engine.video_lab.autotune import autotune_scenes
        from app.engine.video_lab.scenes import refine_scenes
        from app.engine.video_lab.vision import analyze_scene

        video.deepdive_stage = "detecting_scenes"
        db.commit()
        autotune_result = autotune_scenes(media_path)
        refined = refine_scenes(autotune_result.scenes, media_path)

        video.deepdive_stage = "transcribing"
        db.commit()
        audio_path = os.path.join(tmp_dir, "audio.wav")
        has_audio = audio_metrics.extract_audio(media_path, audio_path)
        words = speech.transcribe_words(audio_path) if has_audio else []
        transcript_text = " ".join(w.text for w in words).strip()
        if transcript_text:
            write_transcript(video, transcript_text, status=TranscriptStatus.FETCHED)
            db.commit()
            _refresh_fiche_with_transcript(db, video, transcript_text, project_id)

        video.deepdive_stage = "analyzing_scenes"
        db.commit()
        narration_by_scene: dict[int, str] = {}
        scene_breakdown: list[dict] = []
        for scene in refined:
            scene_words = speech.words_in(scene, words)
            narration_by_scene[scene.index] = " ".join(w.text for w in scene_words)
            wpm = (
                audio_metrics.words_per_minute(len(scene_words), scene.duration_s)
                if scene_words
                else None
            )

            anchor_path = os.path.join(tmp_dir, f"scene_{scene.index:04d}_anchor.jpg")
            last_path = os.path.join(tmp_dir, f"scene_{scene.index:04d}_last.jpg")
            lab_frames.extract_scene_thumbnails(
                media_path, scene.start_s, scene.end_s, anchor_path, last_path
            )
            vision = None
            if os.path.exists(anchor_path) and os.path.exists(last_path):
                vision = analyze_scene(db, anchor_path, last_path)
            for frame_path in (anchor_path, last_path):
                if os.path.exists(frame_path):
                    os.remove(frame_path)

            scene_breakdown.append(
                {
                    "index": scene.index,
                    "start_s": round(scene.start_s, 2),
                    "end_s": round(scene.end_s, 2),
                    "wpm": round(wpm, 1) if wpm else None,
                    "has_caption": bool(vision and vision.has_caption),
                    "vision": vision.model_dump() if vision else {},
                }
            )

        beat_infos = beats.assign_beats(refined, narration_by_scene)
        for row, beat_info in zip(scene_breakdown, beat_infos, strict=True):
            row["beat_role"] = beat_info.role

        video.scene_breakdown = scene_breakdown
        video.attention_notes = _summarize_attention(scene_breakdown)
        video.deepdive_status = DeepDiveStatus.READY
        video.deepdive_stage = "ready"
        db.commit()
        log(
            db,
            f"Deep-dive ready for reference video {video.external_id} "
            f"({len(scene_breakdown)} scenes).",
            stage="deepdive_ready",
            project_id=project_id,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _summarize_attention(scene_breakdown: list[dict]) -> list[str]:
    """Deterministic, human-readable estimate of where attention likely
    concentrates, from structure/pacing alone — never claimed as real
    retention data."""
    if not scene_breakdown:
        return []

    notes: list[str] = []
    hook_scenes = [s for s in scene_breakdown if s.get("beat_role") == "hook"]
    if hook_scenes:
        notes.append(f"Gancho nos primeiros {hook_scenes[-1]['end_s']:.0f}s do vídeo.")

    fastest = min(scene_breakdown, key=lambda s: s["end_s"] - s["start_s"])
    notes.append(
        f"Corte mais rápido em {fastest['start_s']:.0f}s "
        f"({fastest['end_s'] - fastest['start_s']:.1f}s de duração)."
    )

    wpm_scenes = [s for s in scene_breakdown if s.get("wpm")]
    if wpm_scenes:
        peak = max(wpm_scenes, key=lambda s: s["wpm"])
        notes.append(f"Pico de ritmo de fala em {peak['start_s']:.0f}s (~{peak['wpm']:.0f} palavras/min).")

    captioned_ratio = sum(1 for s in scene_breakdown if s.get("has_caption")) / len(scene_breakdown)
    if captioned_ratio > 0.5:
        notes.append("Legenda na tela presente na maior parte do vídeo.")

    cliffhangers = [s for s in scene_breakdown if s.get("beat_role") == "cliffhanger"]
    if cliffhangers:
        notes.append(f"Possível cliffhanger em {cliffhangers[0]['start_s']:.0f}s.")

    return notes


def _refresh_fiche_with_transcript(
    db: Session, video: ReferenceVideo, transcript: str, project_id: str | None
) -> None:
    """Rebuilds the video's abstract fiche now that a transcript exists —
    ``_run_style_analysis`` (``reference_ingest.py``) already ran this per
    video at ingestion time, but always without a transcript: it runs
    synchronously, well before this background deep-dive finishes
    downloading/transcribing. Best-effort, like every analysis step (D7);
    the transcript is deleted right after, same retention policy as the
    ingestion-time path (``MP_KEEP_TRANSCRIPTS``)."""
    try:
        from app.agents.reference import ReferenceAgentContext, ReferenceAnalystAgent

        project = db.get(Project, project_id) if project_id else None
        ctx = ReferenceAgentContext(db, project, video.source)
        analysis = ReferenceAnalystAgent(ctx).analyze(video, transcript)
        video.analysis = analysis.model_dump(mode="json")
        video.originality_signature = minhash_signature(transcript)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - one video's fiche refresh is always best-effort
        log(
            db,
            f"Deep-dive fiche refresh failed for video {video.external_id}: {exc}",
            level=LogLevel.WARNING,
            stage="deepdive_analyzing",
            project_id=project_id,
        )
    finally:
        delete_transcript(video)
        db.commit()


def _fail(db: Session, reference_video_id: str, message: str) -> None:
    db.rollback()
    video = db.get(ReferenceVideo, reference_video_id)
    if video is None:
        return
    video.deepdive_status = DeepDiveStatus.FAILED
    video.deepdive_stage = "failed"
    video.deepdive_error = message[:2000]
    db.commit()
    project_id = video.source.project_id if video.source else None
    log(db, message, level=LogLevel.ERROR, stage="deepdive_failed", project_id=project_id)
