from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .admin_auth import AdminIdentity, require_admin, require_confirmation, require_csrf, require_sensitive_admin
from .admin_service import (
    audit,
    dataset_detail,
    enqueue_country_fetch,
    list_audit,
    list_datasets,
    list_jobs,
    publish_dataset,
    review_dataset,
    schedule_preview,
    state,
)
from .db import get_db
from .models import DatasetVersion, Entity, Puzzle
from .scheduler import apply_month_plan

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class FetchCountriesIn(BaseModel):
    effective_month: str
    confirmation: str | None = None


class ConfirmationIn(BaseModel):
    confirmation: str | None = None


class ApplyScheduleIn(BaseModel):
    month: str
    fingerprint: str
    confirmation: str | None = None


@router.get("/state")
def admin_state(admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    return state(db)


@router.get("/datasets")
def datasets(admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    return list_datasets(db)


@router.get("/datasets/{dataset_id}")
def dataset(dataset_id: str, admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    result = dataset_detail(db, dataset_id)
    if result is None:
        raise HTTPException(404, "Dataset not found")
    return result


@router.post("/datasets/{dataset_id}/review")
def review(
    dataset_id: str,
    admin: AdminIdentity = Depends(require_sensitive_admin),
    db: Session = Depends(get_db),
):
    try:
        return review_dataset(db, dataset_id, admin.subject)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/datasets/{dataset_id}/publish")
def publish(
    dataset_id: str,
    body: ConfirmationIn,
    admin: AdminIdentity = Depends(require_sensitive_admin),
    db: Session = Depends(get_db),
):
    dataset = db.get(DatasetVersion, dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset not found")
    require_confirmation(body.confirmation, f"PRODUCTION PUBLISH {dataset.label}")
    try:
        return publish_dataset(db, dataset_id, admin.subject)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/jobs/countries/fetch")
def fetch_countries(
    body: FetchCountriesIn,
    admin: AdminIdentity = Depends(require_sensitive_admin),
    db: Session = Depends(get_db),
):
    require_confirmation(body.confirmation, f"PRODUCTION FETCH {body.effective_month}")
    try:
        return enqueue_country_fetch(db, body.effective_month, admin.subject)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs")
def jobs(admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    return list_jobs(db)


@router.get("/audit")
def audit_log(admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    return list_audit(db)

@router.get("/schedule/preview")
def preview(month: str, admin: AdminIdentity = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return schedule_preview(db, month)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/schedule/apply")
def apply_schedule(
    body: ApplyScheduleIn,
    admin: AdminIdentity = Depends(require_sensitive_admin),
    db: Session = Depends(get_db),
):
    require_confirmation(body.confirmation, f"PRODUCTION SCHEDULE {body.month}")
    try:
        result = apply_month_plan(db, body.month, body.fingerprint)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Another scheduler changed this month; create a new preview") from exc
    audit(db, admin.subject, "schedule.apply", result)
    db.commit()
    return result


@router.post("/schedule/{day}/reveal")
def reveal_target(
    day: date,
    admin: AdminIdentity = Depends(require_sensitive_admin),
    db: Session = Depends(get_db),
):
    puzzle = db.scalar(select(Puzzle).where(Puzzle.day == day))
    if puzzle is None:
        raise HTTPException(404, "Challenge not scheduled")
    target = db.get(Entity, puzzle.target_id)
    dataset = db.get(DatasetVersion, puzzle.dataset_id)
    audit(db, admin.subject, "schedule.reveal", {"day": day.isoformat(), "puzzle_id": puzzle.id})
    db.commit()
    return {
        "date": day.isoformat(),
        "category": puzzle.category,
        "question": puzzle.question_id,
        "dataset": dataset.label,
        "target": {"id": target.id, "code": target.code, "name": target.name},
    }
