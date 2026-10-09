"""Test fixtures.

Each test run uses an isolated temporary SQLite database and a fixed encryption
key, configured via environment variables BEFORE the app is imported so the
module-level engine binds to the test DB.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "moneyprint_test.db")
os.environ["MP_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["MP_SECRET_ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["MP_LOCAL_API_TOKEN"] = ""
os.environ["MP_ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
