"""Originality check — MinHash similarity against analyzed reference
transcripts (Etapa 4, item 4C).

A reference's transcript is held in memory only long enough to compute its
MinHash signature (a list of integers) — only the signature is ever
persisted on ``ReferenceVideo.originality_signature``, never the text
itself (same posture as D5's transcript deletion, just computed a step
earlier, before that deletion happens).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

NUM_HASHES = 64
SHINGLE_SIZE = 6  # words per shingle (spec range: 5-8)


def normalize_text(text: str) -> list[str]:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", ascii_text.lower())


def shingles(words: list[str], size: int = SHINGLE_SIZE) -> set[str]:
    if not words:
        return set()
    if len(words) < size:
        return {" ".join(words)}
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def _hash_with_seed(value: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def minhash_signature(text: str, *, num_hashes: int = NUM_HASHES) -> list[int]:
    """Returns ``[]`` for text too short to shingle at all (e.g. empty)."""
    shingle_set = shingles(normalize_text(text))
    if not shingle_set:
        return []
    return [min(_hash_with_seed(s, seed) for s in shingle_set) for seed in range(num_hashes)]


def estimate_similarity(sig_a: list[int], sig_b: list[int]) -> float:
    """Fraction of matching slots — an unbiased estimator of the Jaccard
    similarity between the two shingle sets."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


@dataclass
class SimilarityMatch:
    reference_video_id: str
    similarity: float


def check_script(db: Session, project_id: str, text: str) -> list[SimilarityMatch]:
    """Similarity of ``text`` against every analyzed reference video that
    belongs to this project's own learned references, sorted descending.
    ``[]`` when there's nothing to compare against or ``text`` is too
    short to shingle."""
    from app.db.models import ReferenceSource, ReferenceVideo

    candidate_sig = minhash_signature(text)
    if not candidate_sig:
        return []

    rows = db.execute(
        select(ReferenceVideo)
        .join(ReferenceSource, ReferenceVideo.source_id == ReferenceSource.id)
        .where(ReferenceSource.project_id == project_id)
    ).scalars()

    matches = [
        SimilarityMatch(
            reference_video_id=row.id,
            similarity=estimate_similarity(candidate_sig, row.originality_signature),
        )
        for row in rows
        if row.originality_signature
    ]
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches
