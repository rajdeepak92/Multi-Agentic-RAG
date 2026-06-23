"""Add canonical requirement ledger evidence and coverage structures.

Revision ID: 20260623_0005
Revises: 20260620_0004
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260623_0005"
down_revision: str | None = "20260620_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend requirements into a canonical ledger with evidence and coverage."""

    op.add_column("requirements", sa.Column("canonical_id", sa.String(), nullable=True))
    op.add_column(
        "requirements",
        sa.Column(
            "requirement_type",
            sa.String(),
            nullable=False,
            server_default="functional",
        ),
    )
    op.add_column("requirements", sa.Column("category", sa.String(), nullable=True))
    op.add_column("requirements", sa.Column("title", sa.String(), nullable=True))
    op.add_column("requirements", sa.Column("normalized_text", sa.Text(), nullable=True))
    op.add_column("requirements", sa.Column("source_name", sa.String(), nullable=True))
    op.add_column("requirements", sa.Column("page", sa.Integer(), nullable=True))
    op.add_column("requirements", sa.Column("section_title", sa.String(), nullable=True))
    op.add_column(
        "requirements",
        sa.Column(
            "story_driving",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "coverage_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "extraction_method",
            sa.String(),
            nullable=False,
            server_default="deterministic",
        ),
    )
    op.add_column(
        "requirements",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column("requirements", sa.Column("semantic_key", sa.String(), nullable=True))
    op.add_column(
        "requirements",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "requirements",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        """
        UPDATE requirements
        SET canonical_id = COALESCE(canonical_id, requirement_id),
            normalized_text = COALESCE(
                normalized_text,
                lower(regexp_replace(text, '\\s+', ' ', 'g'))
            ),
            semantic_key = COALESCE(semantic_key, lower(requirement_id))
        """
    )
    op.create_index(
        "idx_requirements_scope_type",
        "requirements",
        ["system_name", "kb_name", "version", "requirement_type"],
    )
    op.create_index(
        "idx_requirements_canonical",
        "requirements",
        ["system_name", "kb_name", "version", "canonical_id"],
    )

    op.create_table(
        "requirement_evidence",
        sa.Column("requirement_evidence_id", sa.String(), nullable=False),
        sa.Column("requirement_pk", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.String(), nullable=False),
        sa.Column("document_version_id", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column(
            "extraction_method",
            sa.String(),
            nullable=False,
            server_default="deterministic",
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.chunk_id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.document_version_id"]),
        sa.ForeignKeyConstraint(["requirement_pk"], ["requirements.requirement_pk"]),
        sa.PrimaryKeyConstraint("requirement_evidence_id"),
        sa.UniqueConstraint(
            "requirement_pk",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_requirement_evidence_span",
        ),
    )
    op.create_index(
        "idx_requirement_evidence_requirement",
        "requirement_evidence",
        ["requirement_pk"],
    )
    op.create_index(
        "idx_requirement_evidence_version",
        "requirement_evidence",
        ["document_version_id"],
    )
    op.execute(
        """
        INSERT INTO requirement_evidence (
            requirement_evidence_id,
            requirement_pk,
            chunk_id,
            document_version_id,
            source_name,
            page,
            section_title,
            start_offset,
            end_offset,
            evidence_text,
            extraction_method,
            confidence,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            'requirement_evidence:' || requirement_pk || ':' || requirement_pk_data.chunk_id,
            requirement_pk,
            requirement_pk_data.chunk_id,
            requirement_pk_data.document_version_id,
            COALESCE(chunks.source_name, requirement_pk_data.source_name, ''),
            COALESCE(chunks.page, requirement_pk_data.page, 1),
            COALESCE(chunks.section_title, requirement_pk_data.section_title),
            NULL,
            NULL,
            requirement_pk_data.text,
            requirement_pk_data.extraction_method,
            requirement_pk_data.confidence,
            jsonb_build_object('backfilled_from', 'requirements'),
            now(),
            now()
        FROM requirements AS requirement_pk_data
        LEFT JOIN chunks ON chunks.chunk_id = requirement_pk_data.chunk_id
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "requirement_coverage",
        sa.Column("coverage_id", sa.String(), nullable=False),
        sa.Column("requirement_pk", sa.String(), nullable=False),
        sa.Column("canonical_id", sa.String(), nullable=False),
        sa.Column("story_id", sa.String(), nullable=True),
        sa.Column("coverage_status", sa.String(), nullable=False),
        sa.Column("deferred_reason", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_pages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["requirement_pk"], ["requirements.requirement_pk"]),
        sa.PrimaryKeyConstraint("coverage_id"),
        sa.UniqueConstraint("requirement_pk", "story_id", name="uq_requirement_coverage_story"),
    )
    op.create_index(
        "idx_requirement_coverage_status",
        "requirement_coverage",
        ["coverage_status"],
    )


def downgrade() -> None:
    """Remove the requirement ledger extension objects."""

    op.drop_index("idx_requirement_coverage_status", table_name="requirement_coverage")
    op.drop_table("requirement_coverage")
    op.drop_index("idx_requirement_evidence_version", table_name="requirement_evidence")
    op.drop_index("idx_requirement_evidence_requirement", table_name="requirement_evidence")
    op.drop_table("requirement_evidence")
    op.drop_index("idx_requirements_canonical", table_name="requirements")
    op.drop_index("idx_requirements_scope_type", table_name="requirements")
    for column_name in (
        "updated_at",
        "created_at",
        "semantic_key",
        "confidence",
        "extraction_method",
        "coverage_required",
        "story_driving",
        "section_title",
        "page",
        "source_name",
        "normalized_text",
        "title",
        "category",
        "requirement_type",
        "canonical_id",
    ):
        op.drop_column("requirements", column_name)
