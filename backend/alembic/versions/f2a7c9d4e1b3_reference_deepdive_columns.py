"""reference video deep-dive columns

Revision ID: f2a7c9d4e1b3
Revises: 0102b44834b5
Create Date: 2026-10-09 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a7c9d4e1b3'
down_revision: str | None = '0102b44834b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('reference_videos', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'deepdive_status',
                sa.Enum('NONE', 'PENDING', 'RUNNING', 'READY', 'FAILED', name='deepdivestatus'),
                nullable=False,
                server_default='NONE',
            )
        )
        batch_op.add_column(sa.Column('deepdive_stage', sa.String(length=50), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('deepdive_error', sa.String(length=2000), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('scene_breakdown', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.add_column(sa.Column('attention_notes', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.create_index(
            batch_op.f('ix_reference_videos_deepdive_status'), ['deepdive_status'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('reference_videos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reference_videos_deepdive_status'))
        batch_op.drop_column('attention_notes')
        batch_op.drop_column('scene_breakdown')
        batch_op.drop_column('deepdive_error')
        batch_op.drop_column('deepdive_stage')
        batch_op.drop_column('deepdive_status')

    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('DROP TYPE IF EXISTS deepdivestatus')
