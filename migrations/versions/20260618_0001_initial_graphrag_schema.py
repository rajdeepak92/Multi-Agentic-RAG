"""Initial GraphRAG schema.

Revision ID: 20260618_0001
Revises:
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260618_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create GraphRAG schema."""

    op.create_table(
        "systems",
        sa.Column("system_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), sa.ForeignKey("systems.system_name"), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("system_name", "kb_name", "source_name", name="uq_document_lineage"),
    )
    op.create_table(
        "document_versions",
        sa.Column("document_version_id", sa.String(), primary_key=True),
        sa.Column(
            "document_id", sa.String(), sa.ForeignKey("documents.document_id"), nullable=False
        ),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_version_id", sa.String(), nullable=True),
        sa.Column("superseded_by_version_id", sa.String(), nullable=True),
        sa.Column("optimistic_lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "document_id", "version", "content_hash", name="uq_document_version_hash"
        ),
    )
    op.create_index(
        "idx_document_versions_active",
        "document_versions",
        ["system_name", "kb_name", "status"],
    )
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(),
            sa.ForeignKey("document_versions.document_version_id"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("idx_chunks_document_version", "chunks", ["document_version_id"])
    op.create_index("idx_chunks_system_status", "chunks", ["system_name", "kb_name", "status"])
    op.execute(
        "CREATE INDEX idx_chunks_text_fts ON chunks USING GIN (to_tsvector('english', text))"
    )
    op.create_table(
        "facts",
        sa.Column("fact_id", sa.String(), primary_key=True),
        sa.Column("fact_key", sa.String(), nullable=False),
        sa.Column("fact_type", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), sa.ForeignKey("chunks.chunk_id"), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("requirement_id", sa.String(), nullable=True),
        sa.Column("semantic_key", sa.String(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("idx_facts_system_status", "facts", ["system_name", "kb_name", "status"])
    op.create_index("idx_facts_key", "facts", ["fact_key"])
    op.create_index("idx_facts_version", "facts", ["document_version_id"])
    op.create_table(
        "requirements",
        sa.Column("requirement_pk", sa.String(), primary_key=True),
        sa.Column("requirement_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "system_name",
            "kb_name",
            "requirement_id",
            "document_version_id",
            name="uq_requirement_version",
        ),
    )
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.String(), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "deltas",
        sa.Column("delta_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("from_document_version_id", sa.String(), nullable=False),
        sa.Column("to_document_version_id", sa.String(), nullable=False),
        sa.Column("from_version", sa.String(), nullable=False),
        sa.Column("to_version", sa.String(), nullable=False),
        sa.Column("fact_key", sa.String(), nullable=True),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("change_magnitude", sa.String(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("affected_requirement_id", sa.String(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "idx_deltas_versions", "deltas", ["system_name", "kb_name", "from_version", "to_version"]
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("ingestion_run_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("document_version_id", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "retrieval_metadata",
        sa.Column("retrieval_metadata_id", sa.String(), primary_key=True),
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    """Drop GraphRAG schema."""

    op.drop_table("retrieval_metadata")
    op.drop_table("ingestion_runs")
    op.drop_index("idx_deltas_versions", table_name="deltas")
    op.drop_table("deltas")
    op.drop_table("entities")
    op.drop_table("requirements")
    op.drop_index("idx_facts_version", table_name="facts")
    op.drop_index("idx_facts_key", table_name="facts")
    op.drop_index("idx_facts_system_status", table_name="facts")
    op.drop_table("facts")
    op.execute("DROP INDEX IF EXISTS idx_chunks_text_fts")
    op.drop_index("idx_chunks_system_status", table_name="chunks")
    op.drop_index("idx_chunks_document_version", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("idx_document_versions_active", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("systems")
