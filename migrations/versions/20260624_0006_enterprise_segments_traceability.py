"""Add enterprise segment, review, retrieval, and traceability tables.

Revision ID: 20260624_0006
Revises: 20260623_0005
Create Date: 2026-06-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260624_0006"
down_revision: str | None = "20260623_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Add traceability structures and deterministic compatibility backfills."""

    op.create_table(
        "source_segments",
        sa.Column("segment_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(), nullable=False, server_default="body"),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_ids", JSONB, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.document_version_id"]),
        sa.PrimaryKeyConstraint("segment_id"),
    )
    op.create_index(
        "idx_source_segments_version",
        "source_segments",
        ["document_version_id", "segment_index"],
    )
    op.create_index(
        "idx_source_segments_scope",
        "source_segments",
        ["system_name", "kb_name", "version"],
    )

    op.create_table(
        "requirement_candidates",
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("segment_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requirement_type", sa.String(), nullable=False),
        sa.Column("canonical_id", sa.String(), nullable=True),
        sa.Column("proposed_requirement_id", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("evidence_start_offset", sa.Integer(), nullable=True),
        sa.Column("evidence_end_offset", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("semantic_key", sa.String(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint(
            "document_version_id",
            "semantic_key",
            name="uq_requirement_candidate_semantic",
        ),
    )
    op.create_index(
        "idx_requirement_candidates_scope",
        "requirement_candidates",
        ["system_name", "kb_name", "version"],
    )
    op.create_index(
        "idx_requirement_candidates_segment",
        "requirement_candidates",
        ["segment_id"],
    )

    op.create_table(
        "document_coverage",
        sa.Column("coverage_inventory_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("segment_id", sa.String(), nullable=True),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("coverage_status", sa.String(), nullable=False),
        sa.Column("requirement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", JSONB, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("coverage_inventory_id"),
    )
    op.create_index(
        "idx_document_coverage_scope",
        "document_coverage",
        ["system_name", "kb_name", "version"],
    )
    op.create_index("idx_document_coverage_segment", "document_coverage", ["segment_id"])

    op.create_table(
        "requirement_conflicts",
        sa.Column("conflict_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("semantic_key", sa.String(), nullable=False),
        sa.Column("requirement_pks", JSONB, nullable=False),
        sa.Column("candidate_ids", JSONB, nullable=False),
        sa.Column("evidence_ids", JSONB, nullable=False),
        sa.Column("claims", JSONB, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index(
        "idx_requirement_conflicts_scope",
        "requirement_conflicts",
        ["system_name", "kb_name", "version"],
    )
    op.create_index(
        "idx_requirement_conflicts_status",
        "requirement_conflicts",
        ["status"],
    )

    op.create_table(
        "retrieval_runs",
        sa.Column("retrieval_run_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("retrieval_mode", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("retrieval_run_id"),
    )
    op.create_table(
        "retrieval_hits",
        sa.Column("retrieval_hit_id", sa.String(), nullable=False),
        sa.Column("retrieval_run_id", sa.String(), nullable=False),
        sa.Column("result_id", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=True),
        sa.Column("requirement_pk", sa.String(), nullable=True),
        sa.Column("evidence_id", sa.String(), nullable=True),
        sa.Column("lineage_key", sa.String(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("retrieval_hit_id"),
    )
    op.create_index("idx_retrieval_hits_run", "retrieval_hits", ["retrieval_run_id", "rank"])

    op.create_table(
        "evidence_packs",
        sa.Column("evidence_pack_id", sa.String(), nullable=False),
        sa.Column("retrieval_run_id", sa.String(), nullable=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("requirement_pks", JSONB, nullable=False),
        sa.Column("chunk_ids", JSONB, nullable=False),
        sa.Column("evidence_ids", JSONB, nullable=False),
        sa.Column("conflict_ids", JSONB, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("evidence_pack_id"),
    )

    op.create_table(
        "review_events",
        sa.Column("review_event_id", sa.String(), nullable=False),
        sa.Column("workflow_run_id", sa.String(), nullable=True),
        sa.Column("ingestion_run_id", sa.String(), nullable=True),
        sa.Column("retrieval_run_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=True),
        sa.Column("kb_name", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("redacted_payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("review_event_id"),
    )
    op.create_index("idx_review_events_ingestion", "review_events", ["ingestion_run_id"])
    op.create_index("idx_review_events_workflow", "review_events", ["workflow_run_id"])

    op.create_table(
        "trace_manifests",
        sa.Column("trace_manifest_id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("workflow_run_id", sa.String(), nullable=True),
        sa.Column("generation_id", sa.String(), nullable=True),
        sa.Column("source_document_version_id", sa.String(), nullable=True),
        sa.Column("requirement_pks", JSONB, nullable=False),
        sa.Column("evidence_pack_id", sa.String(), nullable=True),
        sa.Column("story_ids", JSONB, nullable=False),
        sa.Column("config_fingerprint", sa.String(), nullable=False),
        sa.Column("model_fingerprint", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("trace_manifest_id"),
    )

    op.execute(
        """
        INSERT INTO source_segments (
            segment_id,
            document_version_id,
            document_id,
            system_name,
            kb_name,
            version,
            status,
            source_name,
            page,
            segment_index,
            segment_type,
            section_title,
            start_offset,
            end_offset,
            text,
            chunk_ids,
            metadata
        )
        SELECT
            'segment_' || md5(chunk_id),
            document_version_id,
            document_id,
            system_name,
            kb_name,
            version,
            status,
            source_name,
            page,
            chunk_index,
            'chunk',
            section_title,
            0,
            length(text),
            text,
            jsonb_build_array(chunk_id),
            jsonb_build_object('backfilled_from', 'chunks')
        FROM chunks
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO requirement_candidates (
            candidate_id,
            document_version_id,
            document_id,
            segment_id,
            chunk_id,
            system_name,
            kb_name,
            version,
            status,
            requirement_type,
            canonical_id,
            proposed_requirement_id,
            text,
            normalized_text,
            evidence_text,
            evidence_start_offset,
            evidence_end_offset,
            scope,
            confidence,
            semantic_key,
            rejection_reason,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            'requirement_candidate_' || md5(requirement_pk),
            document_version_id,
            document_id,
            'segment_' || md5(chunk_id),
            chunk_id,
            system_name,
            kb_name,
            version,
            'promoted',
            requirement_type,
            canonical_id,
            requirement_id,
            text,
            COALESCE(normalized_text, lower(regexp_replace(text, '\\s+', ' ', 'g'))),
            text,
            NULL,
            NULL,
            category,
            confidence,
            COALESCE(semantic_key, lower(requirement_id)),
            NULL,
            jsonb_build_object('backfilled_from', 'requirements'),
            created_at,
            updated_at
        FROM requirements
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO document_coverage (
            coverage_inventory_id,
            document_version_id,
            document_id,
            system_name,
            kb_name,
            version,
            segment_id,
            section_title,
            coverage_status,
            requirement_count,
            candidate_count,
            conflict_count,
            notes,
            metadata,
            created_at
        )
        SELECT
            'coverage_inventory_' || md5(segment_id),
            document_version_id,
            document_id,
            system_name,
            kb_name,
            version,
            segment_id,
            section_title,
            'unknown',
            0,
            0,
            0,
            jsonb_build_array('backfilled from chunk; finer classification unknown'),
            jsonb_build_object('backfilled_from', 'source_segments'),
            now()
        FROM source_segments
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """Drop only newly added traceability structures."""

    op.drop_table("trace_manifests")
    op.drop_index("idx_review_events_workflow", table_name="review_events")
    op.drop_index("idx_review_events_ingestion", table_name="review_events")
    op.drop_table("review_events")
    op.drop_table("evidence_packs")
    op.drop_index("idx_retrieval_hits_run", table_name="retrieval_hits")
    op.drop_table("retrieval_hits")
    op.drop_table("retrieval_runs")
    op.drop_index("idx_requirement_conflicts_status", table_name="requirement_conflicts")
    op.drop_index("idx_requirement_conflicts_scope", table_name="requirement_conflicts")
    op.drop_table("requirement_conflicts")
    op.drop_index("idx_document_coverage_segment", table_name="document_coverage")
    op.drop_index("idx_document_coverage_scope", table_name="document_coverage")
    op.drop_table("document_coverage")
    op.drop_index("idx_requirement_candidates_segment", table_name="requirement_candidates")
    op.drop_index("idx_requirement_candidates_scope", table_name="requirement_candidates")
    op.drop_table("requirement_candidates")
    op.drop_index("idx_source_segments_scope", table_name="source_segments")
    op.drop_index("idx_source_segments_version", table_name="source_segments")
    op.drop_table("source_segments")
