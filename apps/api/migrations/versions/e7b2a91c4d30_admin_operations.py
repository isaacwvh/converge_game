"""Administrator operations and environment identity.

Revision ID: e7b2a91c4d30
Revises: c31f8d7a42e6
"""
from alembic import op
import sqlalchemy as sa

revision = "e7b2a91c4d30"
down_revision = "c31f8d7a42e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dataset_versions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dataset_versions", sa.Column("reviewed_by", sa.String(length=255), nullable=True))
    op.create_table(
        "installation",
        sa.Column("id", sa.String(length=20), nullable=False),
        sa.Column("deployment_id", sa.String(length=100), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deployment_id"),
    )
    op.create_table(
        "operator_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operator_jobs_kind", "operator_jobs", ["kind"])
    op.create_index("ix_operator_jobs_status", "operator_jobs", ["status"])
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("admin_subject", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_log_admin_subject", "admin_audit_log", ["admin_subject"])
    op.create_index("ix_admin_audit_log_action", "admin_audit_log", ["action"])
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])


def downgrade():
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_action", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_subject", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_index("ix_operator_jobs_status", table_name="operator_jobs")
    op.drop_index("ix_operator_jobs_kind", table_name="operator_jobs")
    op.drop_table("operator_jobs")
    op.drop_table("installation")
    op.drop_column("dataset_versions", "reviewed_by")
    op.drop_column("dataset_versions", "reviewed_at")
