import time
from datetime import timedelta

from sqlalchemy import select

from .admin_service import audit
from .config import settings
from .db import SessionLocal
from .environment import ensure_installation
from .import_countries import fetch_and_stage
from .models import DatasetVersion, OperatorJob, now


def process_next_job() -> bool:
    with SessionLocal() as db:
        stale_before = now() - timedelta(minutes=30)
        job = db.scalar(
            select(OperatorJob)
            .where(
                (OperatorJob.status == "queued")
                | ((OperatorJob.status == "running") & (OperatorJob.started_at < stale_before))
            )
            .order_by(OperatorJob.created_at)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        job.status = "running"
        job.started_at = now()
        job.completed_at = None
        job.error = None
        db.commit()
        job_id = job.id
        kind = job.kind
        payload = job.payload
        requested_by = job.requested_by

    try:
        if kind != "countries.fetch":
            raise ValueError(f"Unsupported operator job: {kind}")
        label = fetch_and_stage(payload["effective_month"])
        with SessionLocal() as db:
            dataset = db.scalar(select(DatasetVersion).where(DatasetVersion.label == label))
            job = db.get(OperatorJob, job_id)
            job.status = "succeeded"
            job.result = {"dataset_id": dataset.id, "label": label, "effective_month": dataset.effective_month}
            job.completed_at = now()
            audit(db, "system:operator-worker", "job.succeeded", {"job_id": job_id, "kind": kind, "requested_by": requested_by})
            db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(OperatorJob, job_id)
            job.status = "failed"
            job.error = str(exc)[:4000]
            job.completed_at = now()
            audit(db, "system:operator-worker", "job.failed", {"job_id": job_id, "kind": kind, "error": job.error, "requested_by": requested_by})
            db.commit()
    return True


def main() -> None:
    with SessionLocal() as db:
        ensure_installation(db)
    while True:
        if not process_next_job():
            time.sleep(settings.operator_job_poll_seconds)


if __name__ == "__main__":
    main()
