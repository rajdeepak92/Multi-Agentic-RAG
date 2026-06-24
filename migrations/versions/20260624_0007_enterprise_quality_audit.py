"""Add enterprise quality, semantic-unit, and publication audit tables.

Revision ID: 20260624_0007
Revises: 20260624_0006
Create Date: 2026-06-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260624_0007"
down_revision: str | None = "20260624_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create additive enterprise audit tables."""

    op.create_table(
        "semantic_units",
        sa.Column("semantic_unit_id", sa.String(), nullable=False),
        sa.Column("record_type", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("exact_evidence", sa.Text(), nullable=False),
        sa.Column("requirement_ids", JSONB, nullable=False),
        sa.Column("fact_ids", JSONB, nullable=False),
        sa.Column("evidence_hash", sa.String(), nullable=False),
        sa.Column("lifecycle_status", sa.String(), nullable=False),
        sa.Column("embedding_fingerprint", sa.String(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("semantic_unit_id"),
    )
    op.create_index(
        "idx_semantic_units_scope",
        "semantic_units",
        ["system_name", "kb_name", "version"],
    )
    op.create_index("idx_semantic_units_record_type", "semantic_units", ["record_type"])
    op.create_index(
        "idx_semantic_units_embedding",
        "semantic_units",
        ["embedding_fingerprint"],
    )

    op.create_table(
        "story_groups",
        sa.Column("story_group_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("persona", sa.String(), nullable=True),
        sa.Column("business_outcome", sa.Text(), nullable=True),
        sa.Column("requirement_pks", JSONB, nullable=False),
        sa.Column("requirement_ids", JSONB, nullable=False),
        sa.Column("grouping_rationale", sa.Text(), nullable=False),
        sa.Column("cohesion_score", sa.Float(), nullable=True),
        sa.Column("grouping_method", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("story_group_id"),
    )
    op.create_index("idx_story_groups_scope", "story_groups", ["system_name", "kb_name", "version"])

    op.create_table(
        "story_quality_evaluations",
        sa.Column("story_quality_evaluation_id", sa.String(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=False),
        sa.Column("story_group_id", sa.String(), nullable=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("deployment", sa.String(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dimension_scores", JSONB, nullable=False),
        sa.Column("critical_failures", JSONB, nullable=False),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("story_quality_evaluation_id"),
    )
    op.create_index("idx_story_quality_story", "story_quality_evaluations", ["story_id"])

    op.create_table(
        "fact_quality_evaluations",
        sa.Column("fact_quality_evaluation_id", sa.String(), nullable=False),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("golden_dataset", sa.Text(), nullable=True),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1", sa.Float(), nullable=True),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("fact_quality_evaluation_id"),
    )
    op.create_index(
        "idx_fact_quality_scope",
        "fact_quality_evaluations",
        ["system_name", "kb_name", "version"],
    )

    op.create_table(
        "retrieval_metrics",
        sa.Column("retrieval_metric_id", sa.String(), nullable=False),
        sa.Column("retrieval_run_id", sa.String(), nullable=True),
        sa.Column("query_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("retrieval_metric_id"),
    )
    op.create_index("idx_retrieval_metrics_query", "retrieval_metrics", ["query_id", "source"])

    op.create_table(
        "generation_attempts",
        sa.Column("generation_attempt_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("story_group_id", sa.String(), nullable=True),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("deployment", sa.String(), nullable=False),
        sa.Column("prompt_hash", sa.String(), nullable=True),
        sa.Column("requested_max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("redacted_metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("generation_attempt_id"),
    )
    op.create_index("idx_generation_attempts_run", "generation_attempts", ["run_id", "task_name"])

    op.create_table(
        "provider_usage_records",
        sa.Column("provider_usage_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("deployment", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("finish_reason", sa.String(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_usage_id"),
    )

    op.create_table(
        "publication_decisions",
        sa.Column("publication_decision_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("publication_allowed", sa.Boolean(), nullable=False),
        sa.Column("artifact_status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("publication_decision_id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_publication_decision_idempotency",
        ),
    )
    op.create_index("idx_publication_decisions_run", "publication_decisions", ["run_id"])

    op.create_table(
        "story_payloads",
        sa.Column("story_payload_id", sa.String(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("story_group_id", sa.String(), nullable=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("yaml_path", sa.Text(), nullable=True),
        sa.Column("json_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("story_payload_id"),
        sa.UniqueConstraint("story_id", "run_id", name="uq_story_payload_story_run"),
    )
    op.create_index(
        "idx_story_payloads_scope",
        "story_payloads",
        ["system_name", "kb_name", "version"],
    )


def downgrade() -> None:
    """Drop only tables introduced by this revision."""

    op.drop_index("idx_story_payloads_scope", table_name="story_payloads")
    op.drop_table("story_payloads")
    op.drop_index("idx_publication_decisions_run", table_name="publication_decisions")
    op.drop_table("publication_decisions")
    op.drop_table("provider_usage_records")
    op.drop_index("idx_generation_attempts_run", table_name="generation_attempts")
    op.drop_table("generation_attempts")
    op.drop_index("idx_retrieval_metrics_query", table_name="retrieval_metrics")
    op.drop_table("retrieval_metrics")
    op.drop_index("idx_fact_quality_scope", table_name="fact_quality_evaluations")
    op.drop_table("fact_quality_evaluations")
    op.drop_index("idx_story_quality_story", table_name="story_quality_evaluations")
    op.drop_table("story_quality_evaluations")
    op.drop_index("idx_story_groups_scope", table_name="story_groups")
    op.drop_table("story_groups")
    op.drop_index("idx_semantic_units_embedding", table_name="semantic_units")
    op.drop_index("idx_semantic_units_record_type", table_name="semantic_units")
    op.drop_index("idx_semantic_units_scope", table_name="semantic_units")
    op.drop_table("semantic_units")
