"""Background ingestion for a learned reference (one video, or a whole channel).

``ingest_reference`` is the single entry point, mirroring the shape of the
video pipeline's ``run_pipeline_sync``: it drives a ``ReferenceSource`` from
``pending`` through to ``ready``/``failed``, updating ``status``/``stage``/
``progress`` as it goes, and never raises — every failure (missing provider,
bad URL, quota exceeded, ...) is recorded on the row instead of crashing the
calling thread/task (D7).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.reference import (
    ReferenceAgentContext,
    ReferenceAnalystAgent,
    StyleProfilerAgent,
    TrendAgent,
    style_profile_data_to_dict,
)
from app.core.config import settings
from app.core.enums import (
    Capability,
    LogLevel,
    ProfileStatus,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
)
from app.db.models import EditorialDirection, Project, ReferenceSource, ReferenceVideo, StyleProfile
from app.providers.base import ChannelInfo, SearchRequest, VideoInfo
from app.providers.router import ProviderRouter
from app.services.logs import log
from app.services.transcripts import delete_transcript, read_transcript

# Videos younger than this are excluded from the median-views calculation so a
# just-published video (which hasn't had time to accumulate views) doesn't
# drag the channel's typical performance down.
_MIN_AGE_HOURS_FOR_MEDIAN = 72

NO_SEARCH_PROVIDER_MESSAGE = (
    "No SEARCH provider configured. Add a YouTube Data API v3 provider in "
    "Providers before learning a reference."
)


def ingest_reference(db: Session, source_id: str) -> None:
    source = db.get(ReferenceSource, source_id)
    if source is None:
        return

    router = ProviderRouter(db)
    if not router.specs(Capability.SEARCH):
        # Checked upfront (distinct from a configured provider that later
        # fails mid-ingestion, e.g. quota exceeded) so the row gets the
        # precise, actionable message rather than a generic failure.
        _fail(db, source_id, NO_SEARCH_PROVIDER_MESSAGE)
        return

    def fetch(op: str, **kw):
        request = SearchRequest(op=op, **kw)

        def _fn(provider):
            resp = provider.fetch(request)
            return resp, resp.usage

        result = router.run(Capability.SEARCH, _fn, project_id=source.project_id)
        return result.value

    try:
        source.status = ReferenceStatus.FETCHING
        source.stage = "resolving_url"
        source.progress = 5
        db.commit()
        log(db, f"Resolving {source.url}", stage="resolving_url", project_id=source.project_id)

        resolved = fetch("resolve", url=source.url).data
        source.kind = ReferenceKind.VIDEO if resolved.kind == "video" else ReferenceKind.CHANNEL
        source.external_id = resolved.external_id
        db.commit()

        if source.kind == ReferenceKind.VIDEO:
            _ingest_single_video(db, source, fetch)
        else:
            _ingest_channel(db, source, fetch)

        _run_style_analysis(db, source, router)

        source.status = ReferenceStatus.READY
        source.stage = "ready"
        source.progress = 100
        db.commit()
        log(db, "Reference ready.", stage="ready", project_id=source.project_id)
    except Exception as exc:  # noqa: BLE001 - never crash the calling thread/task
        _fail(db, source_id, f"Reference ingestion failed: {exc}")


def _ingest_single_video(db: Session, source: ReferenceSource, fetch) -> None:
    source.stage = "fetching_video"
    source.progress = 40
    db.commit()

    info: VideoInfo = fetch("video", external_id=source.external_id).data
    source.title = info.title
    source.stats = {"n_videos": 1}
    db.add(
        ReferenceVideo(
            source_id=source.id,
            external_id=info.external_id,
            title=info.title,
            published_at=_parse_dt(info.published_at),
            duration_s=info.duration_s,
            views=info.views,
            likes=info.likes,
            comments=info.comments,
            thumbnail_url=info.thumbnail_url,
            role=ReferenceVideoRole.REPRESENTATIVE,
        )
    )
    db.commit()


def _ingest_channel(db: Session, source: ReferenceSource, fetch) -> None:
    source.stage = "fetching_channel"
    source.progress = 15
    db.commit()

    channel: ChannelInfo = fetch("channel", external_id=source.external_id).data
    source.title = channel.title
    source.owner_title = channel.title
    db.commit()

    source.stage = "fetching_uploads"
    source.progress = 35
    db.commit()
    log(
        db,
        f"Fetching up to {settings.reference_max_videos} uploads.",
        stage="fetching_uploads",
        project_id=source.project_id,
    )

    videos_info: list[VideoInfo] = fetch(
        "channel_videos", external_id=source.external_id, limit=settings.reference_max_videos
    ).data

    source.stage = "scoring_outliers"
    source.progress = 75
    db.commit()

    now = datetime.now(timezone.utc)
    parsed: list[tuple[VideoInfo, datetime | None, float | None]] = []
    eligible_views: list[int] = []
    for info in videos_info:
        published_at = _parse_dt(info.published_at)
        age_hours = (now - published_at).total_seconds() / 3600 if published_at else None
        parsed.append((info, published_at, age_hours))
        if age_hours is None or age_hours >= _MIN_AGE_HOURS_FOR_MEDIAN:
            eligible_views.append(info.views)

    median_views = float(statistics.median(eligible_views)) if eligible_views else 0.0

    rows: list[ReferenceVideo] = []
    for info, published_at, age_hours in parsed:
        outlier_score = (info.views / median_views) if median_views > 0 else None
        views_per_day = (info.views / (age_hours / 24)) if age_hours and age_hours > 0 else None
        rows.append(
            ReferenceVideo(
                source_id=source.id,
                external_id=info.external_id,
                title=info.title,
                published_at=published_at,
                duration_s=info.duration_s,
                views=info.views,
                likes=info.likes,
                comments=info.comments,
                thumbnail_url=info.thumbnail_url,
                outlier_score=outlier_score,
                views_per_day=views_per_day,
            )
        )
    db.add_all(rows)
    db.flush()  # assign ids before role assignment, which keys off them

    _assign_roles(rows, median_views)

    published_dates = [r.published_at for r in rows if r.published_at is not None]
    source.stats = {
        "n_videos": len(rows),
        "median_views": median_views,
        "subscriber_count": channel.subscriber_count,
        "window_start": min(published_dates).isoformat() if published_dates else None,
        "window_end": max(published_dates).isoformat() if published_dates else None,
    }
    db.commit()
    log(
        db,
        f"Scored {len(rows)} videos (median views: {median_views:.0f}).",
        stage="scoring_outliers",
        project_id=source.project_id,
    )


def _run_style_analysis(db: Session, source: ReferenceSource, router: ProviderRouter) -> None:
    """Fiches -> draft style profile -> editorial directions (Phase 4).

    Every step here is independently best-effort: a failure in profiling or
    direction discovery must not flip an otherwise-successful reference back
    to ``failed`` — the metadata and role scoring already gathered are still
    useful on their own. Without any LLM provider configured, this stops
    cleanly at "ready" with no profile, exactly as the product spec asks.
    """
    if not router.specs(Capability.LLM):
        log(
            db,
            "No LLM provider configured; reference is ready, but no style "
            "profile or directions were generated.",
            level=LogLevel.WARNING,
            stage="analyzing",
            project_id=source.project_id,
        )
        return

    videos = list(
        db.execute(
            select(ReferenceVideo).where(
                ReferenceVideo.source_id == source.id,
                ReferenceVideo.role != ReferenceVideoRole.NONE,
            )
        ).scalars()
    )
    if not videos:
        return

    source.status = ReferenceStatus.ANALYZING
    source.stage = "analyzing_videos"
    source.progress = 85
    db.commit()

    project = db.get(Project, source.project_id) if source.project_id else None
    ctx = ReferenceAgentContext(db, project, source)
    analyst = ReferenceAnalystAgent(ctx)

    had_transcript = False
    for video in videos:
        transcript = read_transcript(video)
        had_transcript = had_transcript or bool(transcript)
        try:
            analysis = analyst.analyze(video, transcript)
        except Exception as exc:  # noqa: BLE001 - one bad video shouldn't sink the batch
            log(
                db,
                f"Reference analyst failed for video {video.external_id}: {exc}",
                level=LogLevel.WARNING,
                stage="analyzing_videos",
                project_id=source.project_id,
            )
            continue
        video.analysis = analysis.model_dump(mode="json")
        delete_transcript(video)
    db.commit()

    if source.project_id is None:
        log(
            db,
            "Reference has no channel yet; skipping style profile and "
            "directions, which both require one.",
            stage="analyzing",
            project_id=None,
        )
        return

    source.stage = "building_profile"
    source.progress = 92
    db.commit()

    profiler = StyleProfilerAgent(ctx)
    try:
        profile_data = profiler.build_profile(videos, had_transcript=had_transcript)
    except Exception as exc:  # noqa: BLE001 - keep the reference "ready" regardless
        log(
            db,
            f"Style profiling failed: {exc}",
            level=LogLevel.WARNING,
            stage="building_profile",
            project_id=source.project_id,
        )
    else:
        db.add(
            StyleProfile(
                project_id=source.project_id,
                version=_next_style_profile_version(db, source.project_id),
                status=ProfileStatus.DRAFT,
                profile=style_profile_data_to_dict(profile_data),
                source_ids=[source.id],
            )
        )
        db.commit()

    source.stage = "discovering_directions"
    source.progress = 97
    db.commit()

    top_videos = [v for v in videos if v.role == ReferenceVideoRole.TOP]
    if not top_videos:
        return

    trend = TrendAgent(ctx)
    try:
        directions = trend.discover(project.niche if project else "", top_videos)
    except Exception as exc:  # noqa: BLE001 - keep the reference "ready" regardless
        log(
            db,
            f"Direction discovery failed: {exc}",
            level=LogLevel.WARNING,
            stage="discovering_directions",
            project_id=source.project_id,
        )
        return

    for item in directions:
        db.add(
            EditorialDirection(
                project_id=source.project_id,
                source_id=source.id,
                title=item.title,
                why=item.why,
                approach=item.approach,
                evidence=item.evidence.model_dump(mode="json"),
            )
        )
    db.commit()


def _next_style_profile_version(db: Session, project_id: str) -> int:
    existing = [
        p.version
        for p in db.execute(
            select(StyleProfile).where(StyleProfile.project_id == project_id)
        ).scalars()
    ]
    return max(existing, default=0) + 1


def _assign_roles(rows: list[ReferenceVideo], median_views: float) -> None:
    """Classify each scored video as top/bottom/representative/none.

    - ``top``: the biggest outliers (top ~10%, and at least 3x the median) —
      "what blew up".
    - ``bottom``: the worst ~10% — contrast for "what didn't land".
    - ``representative``: the ``reference_deep_count`` videos closest to the
      channel's typical performance (outlier_score near 1), which feed the
      deep per-video analysis in Phase 4.
    """
    # Paired explicitly with its non-null score (rather than re-reading the
    # nullable `r.outlier_score` attribute later) so the type checker can see
    # every sort/comparison below is on a plain float.
    scored: list[tuple[ReferenceVideo, float]] = [
        (r, r.outlier_score) for r in rows if r.outlier_score is not None
    ]
    if not scored or median_views <= 0:
        return

    n = len(scored)
    top_n = max(1, n // 10)
    bottom_n = max(1, n // 10)

    by_desc = sorted(scored, key=lambda pair: pair[1], reverse=True)
    top = [r for r, score in by_desc[:top_n] if score >= 3.0]
    for r in top:
        r.role = ReferenceVideoRole.TOP
    top_ids = {r.id for r in top}

    by_asc = sorted(scored, key=lambda pair: pair[1])
    bottom = [r for r, _score in by_asc[:bottom_n] if r.id not in top_ids]
    for r in bottom:
        r.role = ReferenceVideoRole.BOTTOM
    bottom_ids = {r.id for r in bottom}

    remaining = [
        (r, score) for r, score in scored if r.id not in top_ids and r.id not in bottom_ids
    ]
    remaining.sort(key=lambda pair: abs(pair[1] - 1.0))
    for r, _score in remaining[: settings.reference_deep_count]:
        r.role = ReferenceVideoRole.REPRESENTATIVE


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fail(db: Session, source_id: str, message: str) -> None:
    db.rollback()
    source = db.get(ReferenceSource, source_id)
    if source is None:
        return
    source.status = ReferenceStatus.FAILED
    source.error = message[:2000]
    db.commit()
    log(db, message, level=LogLevel.ERROR, stage="failed", project_id=source.project_id)
