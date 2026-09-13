"""One-time schema migration and optional demo seed."""
from alembic import command
from alembic.config import Config

from .config import settings
from .db import SessionLocal
from .environment import ensure_installation
from .import_countries import seed_demo_if_empty


def main():
    settings.validate_runtime()
    command.upgrade(Config("alembic.ini"), "head")
    with SessionLocal() as db:
        ensure_installation(db)
    if settings.seed_demo:
        seed_demo_if_empty()


if __name__ == "__main__":
    main()
