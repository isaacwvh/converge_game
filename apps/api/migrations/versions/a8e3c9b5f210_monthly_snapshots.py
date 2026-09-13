"""Monthly snapshot effective date.

Revision ID: a8e3c9b5f210
Revises: fd359cf82c62
"""
from alembic import op
import sqlalchemy as sa

revision = "a8e3c9b5f210"
down_revision = "fd359cf82c62"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dataset_versions", sa.Column("effective_month", sa.String(length=7), nullable=True))
    op.create_index("ix_dataset_versions_effective_month", "dataset_versions", ["effective_month"])


def downgrade():
    op.drop_index("ix_dataset_versions_effective_month", table_name="dataset_versions")
    op.drop_column("dataset_versions", "effective_month")
