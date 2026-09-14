from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.admin_auth import AdminIdentity, require_admin, require_csrf, require_sensitive_admin
from app.admin_jobs import process_next_job
from app.db import SessionLocal
from app.import_countries import import_file
from app.main import app
from app.models import DatasetVersion, OperatorJob, Puzzle


@pytest.fixture
def admin_client(client):
    identity = AdminIdentity("test-admin", "admin@example.test", "Test Admin")
    app.dependency_overrides[require_admin] = lambda: identity
    app.dependency_overrides[require_csrf] = lambda: identity
    app.dependency_overrides[require_sensitive_admin] = lambda: identity
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_review_publish_preview_and_apply_schedule(admin_client):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    path = Path(__file__).resolve().parent.parent / "data" / "demo_countries.csv"
    dataset_id = import_file(path, f"admin-stage-{month}", activate=False, effective_month=month)

    listing = admin_client.get("/api/v1/admin/datasets")
    assert listing.status_code == 200
    staged = next(dataset for dataset in listing.json() if dataset["id"] == dataset_id)
    assert staged["can_publish"] is False
    assert staged["questions"][0]["eligible_count"] == 10

    detail = admin_client.get(f"/api/v1/admin/datasets/{dataset_id}")
    assert detail.status_code == 200
    assert len(detail.json()["rows"]) == 10

    reviewed = admin_client.post(f"/api/v1/admin/datasets/{dataset_id}/review")
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed_by"] == "test-admin"
    assert reviewed.json()["can_publish"] is True

    published = admin_client.post(f"/api/v1/admin/datasets/{dataset_id}/publish", json={})
    assert published.status_code == 200
    assert published.json()["is_active"] is True

    preview = admin_client.get(f"/api/v1/admin/schedule/preview?month={month}")
    assert preview.status_code == 200
    plan = preview.json()
    assert plan["planned_count"] == len(plan["days"])
    assert all("target_id" not in day for day in plan["days"])

    applied = admin_client.post(
        "/api/v1/admin/schedule/apply",
        json={"month": month, "fingerprint": plan["fingerprint"]},
    )
    assert applied.status_code == 200
    assert applied.json()["created"] == len(plan["days"])

    with SessionLocal() as db:
        puzzles = list(db.scalars(select(Puzzle).where(Puzzle.day.is_not(None)).order_by(Puzzle.day)))
        first_cycle = [puzzle.target_id for puzzle in puzzles[:10]]
        assert len(set(first_cycle)) == 10
        counts = db.execute(
            select(Puzzle.target_id, func.count(Puzzle.id)).where(Puzzle.day.is_not(None)).group_by(Puzzle.target_id)
        ).all()
        appearances = [count for _, count in counts]
        assert max(appearances) - min(appearances) <= 1

    stale = admin_client.post(
        "/api/v1/admin/schedule/apply",
        json={"month": month, "fingerprint": plan["fingerprint"]},
    )
    assert stale.status_code == 409

    revealed = admin_client.post(f"/api/v1/admin/schedule/{plan['days'][0]['date']}/reveal")
    assert revealed.status_code == 200
    assert revealed.json()["target"]["name"]
    assert revealed.json()["target"]["difficulty"] in {"easy", "medium"}
    actions = [entry["action"] for entry in admin_client.get("/api/v1/admin/audit").json()]
    assert "dataset.review" in actions
    assert "dataset.publish" in actions
    assert "schedule.apply" in actions
    assert "schedule.reveal" in actions


def test_country_fetch_runs_as_durable_worker_job(admin_client, monkeypatch):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with SessionLocal() as db:
        dataset = DatasetVersion(
            category="countries",
            label="worker-result",
            source_manifest={"test": True},
            is_active=False,
            effective_month=month,
        )
        db.add(dataset)
        db.commit()

    monkeypatch.setattr("app.admin_jobs.fetch_and_stage", lambda effective_month: "worker-result")
    queued = admin_client.post("/api/v1/admin/jobs/countries/fetch", json={"effective_month": month})
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert process_next_job() is True

    with SessionLocal() as db:
        job = db.scalar(select(OperatorJob))
        assert job.status == "succeeded"
        assert job.result["label"] == "worker-result"
