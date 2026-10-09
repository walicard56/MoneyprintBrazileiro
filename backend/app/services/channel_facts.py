"""Deterministic, code-computed statistics over a channel's reference videos.

Etapa 1 of the "análise robusta" spec calls this "fatos calculados em código
antes do LLM": series detection, topic clusters, title patterns, upload
cadence, and a top-vs-bottom trait diff — all computed with the standard
library only (no heavy NLP dependency). These numbers are the ONLY source of
truth for anything numeric that reaches ``StyleProfilerAgent``/``TrendAgent``;
the prompts explicitly forbid estimating a number that isn't in here.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from statistics import median
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.db.models import ReferenceVideo

# A video counts as "long" (vs. a short) from this duration up.
_LONG_VIDEO_THRESHOLD_S = 60

_WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

_SERIES_MARKERS = [
    re.compile(r"\bvol\.?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bparte\s*\d+\b", re.IGNORECASE),
    re.compile(r"#\d+\b"),
    re.compile(r"\bep(?:is[oó]dio)?\.?\s*\d+\b", re.IGNORECASE),
]

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF✀-➿]"
)

_STOPWORDS = {
    # pt-BR
    "a", "o", "os", "as", "de", "da", "do", "das", "dos", "em", "no", "na",
    "nos", "nas", "um", "uma", "uns", "umas", "para", "por", "com", "que",
    "e", "ou", "se", "ao", "aos", "à", "às", "é", "foi", "são", "mais",
    "como", "este", "esta", "isso", "seu", "sua", "quando", "mas",
    # en
    "the", "an", "of", "in", "on", "to", "and", "or", "is", "are", "for",
    "this", "that", "with", "from", "by", "at", "as", "it", "its", "be",
}


class SeriesFact(BaseModel):
    """A set of 2+ videos recognized as installments of the same series,
    either by a shared ``vol./parte/#N/ep.`` marker or by a shared 3+ word
    title prefix."""

    label: str
    video_count: int
    mean_views: float
    median_views: float
    best_multiplier: float | None
    best_video_external_id: str | None
    best_video_views: int | None
    video_external_ids: list[str] = Field(default_factory=list)


class ClusterFact(BaseModel):
    """A loose topical group of videos sharing a strong unigram/bigram term
    in their titles — a lightweight stand-in for real clustering."""

    label: str
    video_count: int
    mean_views: float
    mean_outlier_score: float | None
    best_multiplier: float | None
    best_video_external_id: str | None
    best_video_views: int | None
    top_video_external_ids: list[str] = Field(default_factory=list)


class TitlePatternFacts(BaseModel):
    avg_length_chars: float
    pct_emoji: float
    pct_caps: float
    pct_brackets_or_volume: float
    pct_question: float
    avg_numbers_count: float
    avg_punctuation_count: float


class CadenceFacts(BaseModel):
    median_days_between_uploads: float | None
    most_common_weekday: str | None
    pct_long_videos: float


class ChannelFacts(BaseModel):
    n_videos: int
    median_views: float
    series: list[SeriesFact] = Field(default_factory=list)
    clusters: list[ClusterFact] = Field(default_factory=list)
    title_patterns: TitlePatternFacts
    cadence: CadenceFacts
    # Positive values mean "top" videos score higher on this trait than
    # "bottom" ones; empty when either role is missing.
    top_vs_bottom: dict[str, float] = Field(default_factory=dict)


# --- Series detection -------------------------------------------------------


def _strip_series_marker(title: str) -> str:
    cleaned = title
    for pattern in _SERIES_MARKERS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\[\s*\]|\(\s*\)", "", cleaned)
    return " ".join(cleaned.split()).strip(" -:|,")


def _series_facts_from_groups(
    groups: dict[str, list["ReferenceVideo"]], labels: dict[str, str]
) -> list[SeriesFact]:
    facts: list[SeriesFact] = []
    for key, members in groups.items():
        views = [m.views for m in members]
        scored = [m for m in members if m.outlier_score is not None]
        best = max(scored, key=lambda m: m.outlier_score, default=None)
        facts.append(
            SeriesFact(
                label=labels.get(key, key),
                video_count=len(members),
                mean_views=sum(views) / len(views),
                median_views=float(median(views)),
                best_multiplier=best.outlier_score if best else None,
                best_video_external_id=best.external_id if best else None,
                best_video_views=best.views if best else None,
                video_external_ids=[m.external_id for m in members],
            )
        )
    facts.sort(key=lambda f: f.mean_views, reverse=True)
    return facts


def _detect_series_by_marker(videos: list["ReferenceVideo"]) -> list[SeriesFact]:
    groups: dict[str, list["ReferenceVideo"]] = {}
    labels: dict[str, str] = {}
    for v in videos:
        if any(p.search(v.title) for p in _SERIES_MARKERS):
            stripped = _strip_series_marker(v.title)
            key = stripped.lower()
            groups.setdefault(key, []).append(v)
            labels.setdefault(key, stripped)
    groups = {k: members for k, members in groups.items() if len(members) >= 2}
    return _series_facts_from_groups(groups, labels)


def _detect_series_by_prefix(
    videos: list["ReferenceVideo"], min_words: int = 3, min_members: int = 3
) -> list[SeriesFact]:
    groups: dict[str, list["ReferenceVideo"]] = {}
    labels: dict[str, str] = {}
    used: set[str] = set()
    for v in videos:
        words = v.title.split()
        if len(words) < min_words or v.external_id in used:
            continue
        key = " ".join(w.lower() for w in words[:min_words])
        if key in groups:
            continue
        matches = [
            other
            for other in videos
            if other.external_id not in used
            and " ".join(w.lower() for w in other.title.split()[:min_words]) == key
        ]
        if len(matches) >= min_members:
            for m in matches:
                used.add(m.external_id)
            groups[key] = matches
            labels[key] = " ".join(words[:min_words])
    return _series_facts_from_groups(groups, labels)


def _detect_series(videos: list["ReferenceVideo"]) -> list[SeriesFact]:
    series = _detect_series_by_prefix(videos)
    covered: set[str] = set()
    for s in series:
        covered.update(s.video_external_ids)
    for s in _detect_series_by_marker(videos):
        if not (set(s.video_external_ids) & covered):
            series.append(s)
            covered.update(s.video_external_ids)
    series.sort(key=lambda f: f.mean_views, reverse=True)
    return series


# --- Topic clusters (lightweight TF-IDF over unigrams/bigrams) -------------


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _tokens(title: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(title))
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def _ngrams(tokens: list[str]) -> set[str]:
    grams = set(tokens)
    grams.update(f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1))
    return grams


def _cluster_by_shared_terms(
    videos: list["ReferenceVideo"], min_cluster_size: int = 2, max_clusters: int = 8
) -> list[ClusterFact]:
    per_video_terms: dict[str, set[str]] = {}
    doc_freq: Counter[str] = Counter()
    for v in videos:
        terms = _ngrams(_tokens(v.title))
        per_video_terms[v.external_id] = terms
        doc_freq.update(terms)

    n_docs = max(len(videos), 1)
    idf = {term: math.log(n_docs / df) + 1 for term, df in doc_freq.items()}

    by_id = {v.external_id: v for v in videos}
    best_term_per_video: dict[str, str] = {}
    for ext_id, terms in per_video_terms.items():
        shareable = [t for t in terms if doc_freq[t] >= 2]
        if not shareable:
            continue
        best_term_per_video[ext_id] = max(shareable, key=lambda t: idf[t])

    groups: dict[str, list[str]] = {}
    for ext_id, term in best_term_per_video.items():
        groups.setdefault(term, []).append(ext_id)

    clusters: list[ClusterFact] = []
    for term, ids in groups.items():
        if len(ids) < min_cluster_size:
            continue
        members = [by_id[i] for i in ids]
        views = [m.views for m in members]
        scores = [m.outlier_score for m in members if m.outlier_score is not None]
        best = max(
            (m for m in members if m.outlier_score is not None),
            key=lambda m: m.outlier_score,
            default=None,
        )
        top3 = sorted(members, key=lambda m: m.views, reverse=True)[:3]
        clusters.append(
            ClusterFact(
                label=term,
                video_count=len(members),
                mean_views=sum(views) / len(views),
                mean_outlier_score=(sum(scores) / len(scores)) if scores else None,
                best_multiplier=best.outlier_score if best else None,
                best_video_external_id=best.external_id if best else None,
                best_video_views=best.views if best else None,
                top_video_external_ids=[m.external_id for m in top3],
            )
        )
    clusters.sort(key=lambda c: c.mean_views, reverse=True)
    return clusters[:max_clusters]


# --- Title patterns ----------------------------------------------------------


def _compute_title_patterns(videos: list["ReferenceVideo"]) -> TitlePatternFacts:
    n = len(videos) or 1
    lengths = [len(v.title) for v in videos]
    has_emoji = sum(1 for v in videos if _EMOJI_RE.search(v.title))
    has_caps_word = sum(1 for v in videos if re.search(r"\b[A-ZÀ-Ý]{4,}\b", v.title))
    has_brackets_or_vol = sum(
        1
        for v in videos
        if re.search(r"[\[\(]|\bvol\.?\s*\d+\b", v.title, re.IGNORECASE)
    )
    has_question = sum(1 for v in videos if "?" in v.title)
    numbers_counts = [len(re.findall(r"\d+", v.title)) for v in videos]
    punctuation_counts = [len(re.findall(r"[!?.,:;]", v.title)) for v in videos]

    return TitlePatternFacts(
        avg_length_chars=sum(lengths) / n,
        pct_emoji=has_emoji / n,
        pct_caps=has_caps_word / n,
        pct_brackets_or_volume=has_brackets_or_vol / n,
        pct_question=has_question / n,
        avg_numbers_count=sum(numbers_counts) / n,
        avg_punctuation_count=sum(punctuation_counts) / n,
    )


# --- Cadence ------------------------------------------------------------------


def _compute_cadence(videos: list["ReferenceVideo"]) -> CadenceFacts:
    dated = sorted(
        (v for v in videos if v.published_at is not None), key=lambda v: v.published_at
    )
    median_days: float | None = None
    if len(dated) >= 2:
        deltas = [
            (dated[i].published_at - dated[i - 1].published_at).total_seconds() / 86400
            for i in range(1, len(dated))
        ]
        median_days = float(median(deltas))

    most_common: str | None = None
    if dated:
        weekday_counts = Counter(v.published_at.weekday() for v in dated)
        most_common = _WEEKDAYS_PT[weekday_counts.most_common(1)[0][0]]

    n = len(videos) or 1
    long_count = sum(1 for v in videos if v.duration_s >= _LONG_VIDEO_THRESHOLD_S)
    return CadenceFacts(
        median_days_between_uploads=median_days,
        most_common_weekday=most_common,
        pct_long_videos=long_count / n,
    )


# --- Top vs. bottom trait diff ----------------------------------------------


def _top_vs_bottom_diff(videos: list["ReferenceVideo"]) -> dict[str, float]:
    from app.core.enums import ReferenceVideoRole

    top = [v for v in videos if v.role == ReferenceVideoRole.TOP]
    bottom = [v for v in videos if v.role == ReferenceVideoRole.BOTTOM]
    if not top or not bottom:
        return {}

    top_patterns = _compute_title_patterns(top)
    bottom_patterns = _compute_title_patterns(bottom)
    top_duration = sum(v.duration_s for v in top) / len(top)
    bottom_duration = sum(v.duration_s for v in bottom) / len(bottom)

    return {
        "avg_length_chars": top_patterns.avg_length_chars - bottom_patterns.avg_length_chars,
        "pct_emoji": top_patterns.pct_emoji - bottom_patterns.pct_emoji,
        "pct_caps": top_patterns.pct_caps - bottom_patterns.pct_caps,
        "pct_brackets_or_volume": (
            top_patterns.pct_brackets_or_volume - bottom_patterns.pct_brackets_or_volume
        ),
        "pct_question": top_patterns.pct_question - bottom_patterns.pct_question,
        "avg_duration_s": top_duration - bottom_duration,
    }


def compute_channel_facts(videos: list["ReferenceVideo"]) -> ChannelFacts:
    """Pure function: every number it returns is directly computed from
    ``videos`` — nothing here is inferred, estimated, or guessed."""
    views = [v.views for v in videos]
    median_views = float(median(views)) if views else 0.0

    return ChannelFacts(
        n_videos=len(videos),
        median_views=median_views,
        series=_detect_series(videos),
        clusters=_cluster_by_shared_terms(videos),
        title_patterns=_compute_title_patterns(videos),
        cadence=_compute_cadence(videos),
        top_vs_bottom=_top_vs_bottom_diff(videos),
    )
