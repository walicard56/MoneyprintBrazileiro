"""Tests for services.originality (Etapa 4, item 4C): MinHash similarity
estimation and the check_script lookup against learned references."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ReferenceKind
from app.db.models import Project, ReferenceSource, ReferenceVideo
from app.db.session import SessionLocal
from app.services.originality import check_script, estimate_similarity, minhash_signature, shingles


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


_TRANSCRIPT = " ".join(f"palavra numero {i} do texto de referencia completo" for i in range(40))


def test_identical_text_has_similarity_one() -> None:
    sig_a = minhash_signature(_TRANSCRIPT)
    sig_b = minhash_signature(_TRANSCRIPT)
    assert estimate_similarity(sig_a, sig_b) == pytest.approx(1.0)


def test_unrelated_text_has_low_similarity() -> None:
    other = " ".join(f"assunto totalmente diferente item {i} nada a ver" for i in range(40))
    sig_a = minhash_signature(_TRANSCRIPT)
    sig_b = minhash_signature(other)
    assert estimate_similarity(sig_a, sig_b) < 0.2


def test_paraphrased_but_structurally_similar_text_scores_between() -> None:
    # Same shingle structure, one word changed throughout — should land
    # meaningfully above "unrelated" and below "identical".
    paraphrased = _TRANSCRIPT.replace("palavra", "termo")
    sig_a = minhash_signature(_TRANSCRIPT)
    sig_b = minhash_signature(paraphrased)
    sim = estimate_similarity(sig_a, sig_b)
    assert 0.0 < sim < 1.0


def test_empty_text_has_no_signature() -> None:
    assert minhash_signature("") == []
    assert minhash_signature("   ") == []


def test_shingles_short_text_falls_back_to_whole_text() -> None:
    assert shingles(["a", "b"], size=6) == {"a b"}
    assert shingles([], size=6) == set()


def _project(db: Session) -> Project:
    project = Project(name="P", niche="x", language="English")
    db.add(project)
    db.commit()
    return project


def _reference_with_signature(db: Session, project_id: str, text: str) -> ReferenceVideo:
    source = ReferenceSource(project_id=project_id, kind=ReferenceKind.VIDEO, url="https://x")
    db.add(source)
    db.flush()
    video = ReferenceVideo(
        source_id=source.id, external_id="v1", title="T", originality_signature=minhash_signature(text)
    )
    db.add(video)
    db.commit()
    return video


def test_check_script_finds_the_closest_reference(db: Session) -> None:
    project = _project(db)
    ref = _reference_with_signature(db, project.id, _TRANSCRIPT)

    matches = check_script(db, project.id, _TRANSCRIPT)

    assert matches
    assert matches[0].reference_video_id == ref.id
    assert matches[0].similarity == pytest.approx(1.0)


def test_check_script_empty_without_any_analyzed_reference(db: Session) -> None:
    project = _project(db)
    assert check_script(db, project.id, _TRANSCRIPT) == []


def test_check_script_only_considers_this_projects_own_references(db: Session) -> None:
    project_a = _project(db)
    project_b = _project(db)
    _reference_with_signature(db, project_b.id, _TRANSCRIPT)

    assert check_script(db, project_a.id, _TRANSCRIPT) == []
