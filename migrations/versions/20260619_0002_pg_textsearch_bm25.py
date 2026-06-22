"""Use native PostgreSQL full-text search index for chunk text.

Revision ID: 20260619_0002
Revises: 20260618_0001
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260619_0002"
down_revision: str | None = "20260618_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create native PostgreSQL FTS index for chunk text."""

    op.execute("DROP INDEX IF EXISTS idx_chunks_text_bm25")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_text_fts "
        "ON chunks USING GIN (to_tsvector('english', coalesce(text, '')))"
    )


def downgrade() -> None:
    """Drop native PostgreSQL FTS index."""

    op.execute("DROP INDEX IF EXISTS idx_chunks_text_fts")
