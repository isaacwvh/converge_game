"""Global daily challenges and explicit question identity.

Revision ID: c31f8d7a42e6
Revises: a8e3c9b5f210
"""
from alembic import op
import sqlalchemy as sa

revision = "c31f8d7a42e6"
down_revision = "a8e3c9b5f210"
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_N_name)s"}


def _unique_name(columns: set[str]) -> str | None:
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints("puzzles"):
        if set(constraint["column_names"]) == columns:
            return constraint["name"]
    return None


def upgrade():
    bind = op.get_bind()
    duplicate_day = bind.execute(
        sa.text("SELECT day FROM puzzles WHERE day IS NOT NULL GROUP BY day HAVING COUNT(*) > 1 LIMIT 1")
    ).scalar()
    if duplicate_day is not None:
        raise RuntimeError(
            f"Cannot enforce one global challenge for {duplicate_day}: multiple puzzles already exist; "
            "resolve them without deleting referenced rounds before retrying"
        )

    old_name = _unique_name({"category", "day"})
    op.add_column("puzzles", sa.Column("question", sa.String(length=80), nullable=True))
    bind.execute(sa.text("UPDATE puzzles SET question = 'identify-country' WHERE question IS NULL"))

    options = {"recreate": "always"} if bind.dialect.name == "sqlite" else {}
    if old_name is None:
        options["naming_convention"] = _NAMING_CONVENTION
        old_name = "uq_puzzles_category_day"
    with op.batch_alter_table("puzzles", **options) as batch_op:
        batch_op.alter_column("question", existing_type=sa.String(length=80), nullable=False)
        batch_op.drop_constraint(old_name, type_="unique")
        batch_op.create_unique_constraint("uq_puzzles_day", ["day"])


def downgrade():
    bind = op.get_bind()
    day_name = _unique_name({"day"}) or "uq_puzzles_day"
    options = {"recreate": "always"} if bind.dialect.name == "sqlite" else {}
    if _unique_name({"day"}) is None:
        options["naming_convention"] = _NAMING_CONVENTION
    with op.batch_alter_table("puzzles", **options) as batch_op:
        batch_op.drop_constraint(day_name, type_="unique")
        batch_op.create_unique_constraint("uq_puzzles_category_day", ["category", "day"])
        batch_op.drop_column("question")
