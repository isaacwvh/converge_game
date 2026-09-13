"""One-time schema migration and optional demo seed."""
from alembic import command
from alembic.config import Config

from .config import settings
from .import_countries import seed_demo_if_empty


def main():
    command.upgrade(Config("alembic.ini"), "head")
    if settings.seed_demo:
        seed_demo_if_empty()


if __name__ == "__main__":
    main()
