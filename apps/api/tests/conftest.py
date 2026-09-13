import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_converge.db"
os.environ["DAILY_SALT"] = "test-secret"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import Base, engine
from app.main import app
from app.import_countries import seed_demo_if_empty


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_demo_if_empty()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)
    engine.dispose()
    Path("test_converge.db").unlink(missing_ok=True)
