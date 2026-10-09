"""Provider abstraction layer.

Each AI capability (LLM, image, video, TTS, STT, music, search, publish) is
defined as an abstract base. Concrete providers register themselves and are
selected at runtime by the :class:`~app.providers.router.ProviderRouter`, which
handles priority ordering, fallback chains, and cost accounting.
"""

from app.providers import registry  # noqa: F401  (ensure registry is importable)
