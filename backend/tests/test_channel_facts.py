"""Tests for ``services.channel_facts.compute_channel_facts`` — pure,
deterministic statistics computed before any LLM call (Etapa 1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import ReferenceVideoRole
from app.db.models import ReferenceVideo
from app.services.channel_facts import compute_channel_facts


def _video(**kw) -> ReferenceVideo:
    now = datetime.now(timezone.utc)
    return ReferenceVideo(
        source_id="src1",
        external_id=kw.pop("external_id"),
        title=kw.pop("title", "Video"),
        duration_s=kw.pop("duration_s", 600),
        views=kw.pop("views", 1000),
        likes=kw.pop("likes", 10),
        comments=kw.pop("comments", 1),
        outlier_score=kw.pop("outlier_score", None),
        role=kw.pop("role", ReferenceVideoRole.NONE),
        published_at=kw.pop("published_at", now),
        analysis=kw.pop("analysis", {}),
    )


def test_detects_series_by_shared_title_prefix_mulho_like() -> None:
    """Inspired by the real "Mulho" channel: 5 installments of "Os Piores
    Encontros ..." (one tagged Vol.2/Vol.3) plus an unrelated video."""
    videos = [
        _video(external_id="v1", title="Os Piores Encontros na Amazônia", views=200000, outlier_score=5.9),
        _video(external_id="v2", title="Os Piores Encontros de Caçadores", views=190000, outlier_score=5.5),
        _video(
            external_id="v3",
            title="Os Piores Encontros em Florestas [Vol.2]",
            views=180000,
            outlier_score=5.2,
        ),
        _video(
            external_id="v4",
            title="Os Piores Encontros em Florestas [Vol.3]",
            views=170000,
            outlier_score=5.0,
        ),
        _video(
            external_id="v5", title="Os Piores Encontros com Animais da África", views=160000, outlier_score=4.8
        ),
        _video(external_id="v6", title="Um vlog qualquer sem relação", views=5000, outlier_score=0.2),
    ]

    facts = compute_channel_facts(videos)

    assert len(facts.series) == 1
    series = facts.series[0]
    assert series.label == "Os Piores Encontros"
    assert series.video_count == 5
    assert series.best_video_external_id == "v1"
    assert series.best_multiplier == pytest.approx(5.9)
    # The marker-based (Vol.2/Vol.3) group is fully covered by the
    # prefix-based series — must not show up as a second, duplicate series.
    assert {v.external_id for v in videos if v.external_id != "v6"} == set(series.video_external_ids)


def test_clusters_group_shared_topic_terms() -> None:
    videos = [
        _video(external_id="v1", title="Caçador encontra onça na Amazônia", views=50000, outlier_score=4.0),
        _video(external_id="v2", title="Caçador perdido na Amazônia profunda", views=40000, outlier_score=3.0),
        _video(external_id="v3", title="Receita de bolo de chocolate", views=1000, outlier_score=0.1),
    ]
    facts = compute_channel_facts(videos)

    assert len(facts.clusters) >= 1
    grouped_ids = {eid for c in facts.clusters for eid in c.top_video_external_ids}
    assert {"v1", "v2"} <= grouped_ids
    assert "v3" not in grouped_ids


def test_title_patterns_counts_emoji_caps_question_brackets() -> None:
    videos = [
        _video(external_id="v1", title="VOCÊ NÃO VAI CRER NISSO 😱 [Vol.1]"),
        _video(external_id="v2", title="Por que isso acontece?"),
    ]
    patterns = compute_channel_facts(videos).title_patterns

    assert patterns.pct_emoji == pytest.approx(0.5)
    assert patterns.pct_caps == pytest.approx(0.5)
    assert patterns.pct_question == pytest.approx(0.5)
    assert patterns.pct_brackets_or_volume == pytest.approx(0.5)


def test_cadence_computes_median_days_between_uploads_and_long_pct() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    videos = [
        _video(external_id="v1", published_at=base, duration_s=600),
        _video(external_id="v2", published_at=base + timedelta(days=7), duration_s=30),
        _video(external_id="v3", published_at=base + timedelta(days=14), duration_s=600),
    ]
    cadence = compute_channel_facts(videos).cadence

    assert cadence.median_days_between_uploads == pytest.approx(7.0)
    assert cadence.pct_long_videos == pytest.approx(2 / 3)
    assert cadence.most_common_weekday is not None


def test_top_vs_bottom_diff_only_when_both_roles_present() -> None:
    top = _video(
        external_id="t1",
        title="TITULO BEM GRANDE E CHEIO DE DETALHE",
        views=100000,
        outlier_score=5.0,
        role=ReferenceVideoRole.TOP,
    )
    bottom = _video(
        external_id="b1", title="curto", views=100, outlier_score=0.1, role=ReferenceVideoRole.BOTTOM
    )

    facts = compute_channel_facts([top, bottom])
    assert facts.top_vs_bottom  # non-empty
    assert facts.top_vs_bottom["avg_length_chars"] > 0

    facts_no_bottom = compute_channel_facts([top])
    assert facts_no_bottom.top_vs_bottom == {}


def test_compute_channel_facts_handles_empty_list() -> None:
    facts = compute_channel_facts([])
    assert facts.n_videos == 0
    assert facts.median_views == 0.0
    assert facts.series == []
    assert facts.clusters == []
