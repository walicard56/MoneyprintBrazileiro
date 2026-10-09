"""Upload validation for the Laboratório de vídeo (Etapa 3) — validated by
CONTENT (there is a real, readable video track; duration/size are within
limits), not by filename extension. No ``ffprobe`` dependency (often
missing on Windows dev machines, see services/binaries.py): OpenCV's
``VideoCapture`` reads the real fps/frame-count/duration directly."""

from __future__ import annotations

from app.core.config import settings


def probe_video(path: str) -> tuple[bool, float]:
    """Returns ``(has_video, duration_s)``. ``has_video=False`` if the file
    can't be opened as a video at all (wrong format, corrupt, audio-only)."""
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return False, 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        ok, _frame = cap.read()
        if not ok:
            return False, 0.0
        duration_s = (frame_count / fps) if fps > 0 else 0.0
        return True, duration_s
    finally:
        cap.release()


def validate_upload(path: str, size_bytes: int) -> str | None:
    """Returns a user-facing error message in pt-BR, or ``None`` if valid."""
    max_bytes = settings.lab_max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        return f"Arquivo muito grande (máx. {settings.lab_max_upload_mb} MB)."

    has_video, duration_s = probe_video(path)
    if not has_video:
        return "O arquivo enviado não parece ser um vídeo válido."
    if duration_s <= 0:
        return "Não foi possível determinar a duração do vídeo."
    if duration_s > settings.lab_max_duration_s:
        return f"Vídeo muito longo (máx. {settings.lab_max_duration_s // 60} min)."
    return None
