"""Enable pg_textsearch BM25 index for chunk text.

Revision ID: 20260620_0004
Revises: 20260620_0003
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260620_0004"
down_revision: str | None = "20260620_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the primary pg_textsearch BM25 index for lexical retrieval."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_text_bm25 "
        "ON chunks USING bm25 (text) WITH (text_config='english')"
    )


def downgrade() -> None:
    """Drop the pg_textsearch BM25 index."""

    op.execute("DROP INDEX IF EXISTS idx_chunks_text_bm25")
    op.execute("DROP EXTENSION IF EXISTS pg_textsearch")
