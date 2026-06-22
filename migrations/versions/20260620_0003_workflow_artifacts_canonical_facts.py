"""Add workflow audits, artifacts, and canonical facts.

Revision ID: 20260620_0003
Revises: 20260619_0002
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260620_0003"
down_revision: str | None = "20260619_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create workflow, artifact, and canonical fact tables."""

    op.create_table(
        "workflow_runs",
        sa.Column("workflow_run_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), nullable=True),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("intent_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "idx_workflow_runs_scope",
        "workflow_runs",
        ["system_name", "kb_name", "version"],
    )
    op.create_table(
        "workflow_steps",
        sa.Column("workflow_step_id", sa.String(), primary_key=True),
        sa.Column(
            "workflow_run_id",
            sa.String(),
            sa.ForeignKey("workflow_runs.workflow_run_id"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_paths", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "idx_workflow_steps_run",
        "workflow_steps",
        ["workflow_run_id", "step_index"],
    )
    op.create_table(
        "artifact_records",
        sa.Column("artifact_id", sa.String(), primary_key=True),
        sa.Column("workflow_run_id", sa.String(), nullable=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("debug_json_path", sa.Text(), nullable=True),
        sa.Column("source_chunk_ids", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("validation_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "idx_artifact_records_scope",
        "artifact_records",
        ["system_name", "kb_name", "version"],
    )
    op.create_table(
        "canonical_facts",
        sa.Column("canonical_fact_id", sa.String(), primary_key=True),
        sa.Column("system_name", sa.String(), nullable=False),
        sa.Column("kb_name", sa.String(), nullable=False),
        sa.Column("semantic_key", sa.String(), nullable=False),
        sa.Column("current_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("originating_fact_id", sa.String(), nullable=False),
        sa.Column("active_fact_id", sa.String(), nullable=False),
        sa.Column("originating_version_id", sa.String(), nullable=False),
        sa.Column("last_confirmed_version_id", sa.String(), nullable=False),
        sa.Column("superseded_by_fact_id", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "system_name",
            "kb_name",
            "semantic_key",
            name="uq_canonical_fact_semantic_key",
        ),
    )
    op.create_index(
        "idx_canonical_facts_active",
        "canonical_facts",
        ["system_name", "kb_name", "status"],
    )


def downgrade() -> None:
    """Drop workflow, artifact, and canonical fact tables."""

    op.drop_index("idx_canonical_facts_active", table_name="canonical_facts")
    op.drop_table("canonical_facts")
    op.drop_index("idx_artifact_records_scope", table_name="artifact_records")
    op.drop_table("artifact_records")
    op.drop_index("idx_workflow_steps_run", table_name="workflow_steps")
    op.drop_table("workflow_steps")
    op.drop_index("idx_workflow_runs_scope", table_name="workflow_runs")
    op.drop_table("workflow_runs")
