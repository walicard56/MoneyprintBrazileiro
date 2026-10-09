"""media capability

Revision ID: 9a2ed300025b
Revises: 929a716210e1
Create Date: 2026-10-09 18:41:27.494212

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = '9a2ed300025b'
down_revision: str | None = '929a716210e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite's "enum" is just a CHECK constraint re-derived from the Python
    # enum on every migration, so no DDL is needed there. PostgreSQL's
    # ``capability`` is a native enum type: ALTER TYPE ... ADD VALUE cannot
    # run inside the transaction Alembic normally opens, so it needs its
    # own autocommit block (same pattern as e14cf69b8262's AgentType values).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE capability ADD VALUE IF NOT EXISTS 'MEDIA'")


def downgrade() -> None:
    # No-op: PostgreSQL has no ALTER TYPE ... DROP VALUE, so 'MEDIA' is
    # intentionally left in place once added.
    pass
