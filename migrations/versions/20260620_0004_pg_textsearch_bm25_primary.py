"""Preserve optional pg_textsearch BM25 compatibility.

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
    """Create the optional BM25 index only when pg_textsearch already exists.

    Native PostgreSQL FTS is the default lexical backend.

    This migration deliberately does not install pg_textsearch because:

    - the extension may not exist on a local PostgreSQL installation;
    - installing extensions is an operator-level responsibility;
    - a native-FTS installation must be able to complete all migrations;
    - pg_textsearch is activated only through explicit configuration.
    """

    op.execute(
        """
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_extension
                WHERE extname = 'pg_textsearch'
            ) THEN
                BEGIN
                    EXECUTE
                        'CREATE INDEX IF NOT EXISTS idx_chunks_text_bm25 '
                        'ON chunks USING bm25 (text) '
                        'WITH (text_config=''english'')';

                    RAISE NOTICE
                        'pg_textsearch is installed; optional BM25 index verified.';
                EXCEPTION
                    WHEN undefined_object
                        OR invalid_parameter_value
                        OR feature_not_supported
                    THEN
                        RAISE NOTICE
                            'pg_textsearch exists, but its BM25 index could not '
                            'be created. Native PostgreSQL FTS remains available.';
                END;
            ELSE
                RAISE NOTICE
                    'pg_textsearch is not installed; skipping the optional '
                    'BM25 index. Native PostgreSQL FTS remains active.';
            END IF;
        END
        $migration$;
        """
    )


def downgrade() -> None:
    """Remove only the optional index created by this migration."""

    op.execute("DROP INDEX IF EXISTS idx_chunks_text_bm25")