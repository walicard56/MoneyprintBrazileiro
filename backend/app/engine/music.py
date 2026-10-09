"""Background-music selection, ported from MoneyPrinterV2's utils."""

from __future__ import annotations

import os
import random

_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")


def choose_random_song(songs_dir: str) -> str | None:
    """Return a random audio file from ``songs_dir``, or None if there are none."""
    if not os.path.isdir(songs_dir):
        return None
    songs = [
        os.path.join(songs_dir, name)
        for name in os.listdir(songs_dir)
        if os.path.isfile(os.path.join(songs_dir, name))
        and name.lower().endswith(_AUDIO_EXTS)
    ]
    if not songs:
        return None
    return random.choice(songs)
