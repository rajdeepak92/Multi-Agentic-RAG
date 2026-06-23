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
    """Create the optional pg_textsearch BM25 index when the server supports it."""

    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_textsearch;
        EXCEPTION
            WHEN undefined_file OR insufficient_privilege THEN
                RAISE NOTICE 'pg_textsearch is unavailable; keeping native FTS only.';
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_textsearch') THEN
                CREATE INDEX IF NOT EXISTS idx_chunks_text_bm25
                ON chunks USING bm25 (text) WITH (text_config='english');
            END IF;
        EXCEPTION
            WHEN undefined_object OR invalid_parameter_value THEN
                RAISE NOTICE 'pg_textsearch BM25 index could not be created.';
        END
        $$;
        """
    )


def downgrade() -> None:
    """Drop the pg_textsearch BM25 index."""

    op.execute("DROP INDEX IF EXISTS idx_chunks_text_bm25")
    op.execute("DROP EXTENSION IF EXISTS pg_textsearch")
