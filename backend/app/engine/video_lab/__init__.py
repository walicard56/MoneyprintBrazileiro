"""Laboratório de vídeo (Etapa 3): pure, no-network analysis of a user-
uploaded video — scene detection, speech, OCR, audio metrics, palette,
vision, beats, and the aggregated "grammar" built from them.

Every module here takes file paths and plain data in, returns plain data
out — no DB session, no HTTP call except the optional vision step (D8,
itself just an LLM call through the existing provider router). Heavy
dependencies (``scenedetect``, ``opencv-python-headless``, ``faster-whisper``,
``numpy``) live in the ``lab`` extra (``pyproject.toml``) and are imported
lazily inside each function, never at module import time, so the API can
boot without them installed.
"""

from __future__ import annotations
