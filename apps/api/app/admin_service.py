from datetime import date, datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .categories import category_registry
from .config import settings
from .environment import assert_dataset_allowed, is_demo_dataset
from .models import (
    AdminAuditLog,
    AnonymousPlayer,
    DatasetVersion,
    Guess,
    OperatorJob,
    Puzzle,
    Round,
    now,
)
from .scheduler import build_month_plan, parse_month, public_plan


def iso(value):
    return value.isoformat() if value is not None else None


def audit(db: Session, subject: str, action: str, details: dict) -> None:
    db.add(AdminAuditLog(admin_subject=subject, action=action, details=details))


def _definitions(category_id: str):
    return [definition for definition in category_registry.definitions() if definition.category_id == category_id]


def dataset_summary(db: Session, dataset: DatasetVersion) -> dict:
    definitions = _definitions(dataset.category)
    questions = [
        {
            "question": definition.question_id,
            "eligible_count": len(definition.eligible_entity_ids(db, dataset.id)),
        }
        for definition in definitions
    ]
    puzzle_count = db.scalar(select(func.count(Puzzle.id)).where(Puzzle.dataset_id == dataset.id)) or 0
    conflicting_active = db.scalar(
        select(DatasetVersion.id).where(
            DatasetVersion.category == dataset.category,
            DatasetVersion.effective_month == dataset.effective_month,
            DatasetVersion.is_active.is_(True),
            DatasetVersion.id != dataset.id,
        )
    )
    return {
        "id": dataset.id,
        "category": dataset.category,
        "label": dataset.label,
        "effective_month": dataset.effective_month,
        "is_active": dataset.is_active,
        "is_demo": is_demo_dataset(dataset),
        "imported_at": iso(dataset.published_at),
        "reviewed_at": iso(dataset.reviewed_at),
        "reviewed_by": dataset.reviewed_by,
        "source_manifest": dataset.source_manifest,
        "questions": questions,
        "puzzle_count": puzzle_count,
        "can_review": not dataset.is_active,
        "can_publish": bool(dataset.reviewed_at and dataset.effective_month and not dataset.is_active and not conflicting_active),
        "publish_blocker": (
            "Dataset is already active"
            if dataset.is_active
            else "Review this snapshot first"
            if dataset.reviewed_at is None
            else "Effective month is required"
            if not dataset.effective_month
            else "Another snapshot is already active for this category and month"
            if conflicting_active
            else None
        ),
    }


def list_datasets(db: Session) -> list[dict]:
    datasets = db.scalars(
        select(DatasetVersion).order_by(DatasetVersion.effective_month.desc().nulls_last(), DatasetVersion.published_at.desc())
    ).all()
    return [dataset_summary(db, dataset) for dataset in datasets]


def dataset_detail(db: Session, dataset_id: str) -> dict | None:
    dataset = db.get(DatasetVersion, dataset_id)
    if dataset is None:
        return None
    summary = dataset_summary(db, dataset)
    definitions = _definitions(dataset.category)
    rows = definitions[0].admin_dataset_rows(db, dataset.id) if definitions else []
    previous_query = select(DatasetVersion).where(
        DatasetVersion.category == dataset.category,
        DatasetVersion.id != dataset.id,
    )
    if dataset.effective_month:
        previous_query = previous_query.where(
            (DatasetVersion.effective_month <= dataset.effective_month)
            | DatasetVersion.effective_month.is_(None)
        )
    previous = db.scalar(
        previous_query.order_by(
            DatasetVersion.effective_month.desc().nulls_last(),
            DatasetVersion.published_at.desc(),
        )
    )
    comparison = None
    if previous is not None and definitions:
        previous_rows = definitions[0].admin_dataset_rows(db, previous.id)
        current_codes = {row["code"]: row for row in rows}
        previous_codes = {row["code"]: row for row in previous_rows}
        comparison = {
            "previous_dataset_id": previous.id,
            "previous_label": previous.label,
            "added": sorted(set(current_codes) - set(previous_codes)),
            "removed": sorted(set(previous_codes) - set(current_codes)),
            "renamed": [
                {"code": code, "from": previous_codes[code]["name"], "to": current_codes[code]["name"]}
                for code in sorted(set(current_codes) & set(previous_codes))
                if current_codes[code]["name"] != previous_codes[code]["name"]
            ],
        }
    return {**summary, "rows": rows, "comparison": comparison}


def review_dataset(db: Session, dataset_id: str, subject: str) -> dict:
    dataset = db.get(DatasetVersion, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")
    if dataset.is_active:
        raise ValueError("Active datasets cannot be newly reviewed")
    dataset.reviewed_at = now()
    dataset.reviewed_by = subject
    audit(db, subject, "dataset.review", {"dataset_id": dataset.id, "label": dataset.label})
    db.commit()
    return dataset_summary(db, dataset)


def publish_dataset(db: Session, dataset_id: str, subject: str) -> dict:
    dataset = db.get(DatasetVersion, dataset_id)
    if dataset is None:
        raise ValueError("Dataset not found")
    if dataset.reviewed_at is None:
        raise ValueError("Dataset must be reviewed before publication")
    if not dataset.effective_month:
        raise ValueError("Dataset effective month is required")
    if dataset.is_active:
        return dataset_summary(db, dataset)
    assert_dataset_allowed(dataset, "publish")
    conflict = db.scalar(
        select(DatasetVersion.id).where(
            DatasetVersion.category == dataset.category,
            DatasetVersion.effective_month == dataset.effective_month,
            DatasetVersion.is_active.is_(True),
            DatasetVersion.id != dataset.id,
        )
    )
    if conflict:
        raise ValueError("Another snapshot is already active for this category and month")
    dataset.is_active = True
    audit(db, subject, "dataset.publish", {"dataset_id": dataset.id, "label": dataset.label})
    db.commit()
    return dataset_summary(db, dataset)


def enqueue_country_fetch(db: Session, effective_month: str, subject: str) -> dict:
    parse_month(effective_month)
    existing = db.scalar(
        select(OperatorJob).where(
            OperatorJob.kind == "countries.fetch",
            OperatorJob.status.in_(["queued", "running"]),
            OperatorJob.payload["effective_month"].as_string() == effective_month,
        )
    )
    if existing:
        raise ValueError(f"A country fetch is already {existing.status} for {effective_month}")
    job = OperatorJob(
        kind="countries.fetch",
        status="queued",
        payload={"effective_month": effective_month},
        requested_by=subject,
    )
    db.add(job)
    audit(db, subject, "job.enqueue", {"job_id": job.id, "kind": job.kind, "effective_month": effective_month})
    db.commit()
    return serialize_job(job)


def serialize_job(job: OperatorJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "requested_by": job.requested_by,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "completed_at": iso(job.completed_at),
    }


def list_jobs(db: Session, limit: int = 50) -> list[dict]:
    jobs = db.scalars(select(OperatorJob).order_by(OperatorJob.created_at.desc()).limit(limit)).all()
    return [serialize_job(job) for job in jobs]


def list_audit(db: Session, limit: int = 100) -> list[dict]:
    entries = db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": entry.id,
            "admin_subject": entry.admin_subject,
            "action": entry.action,
            "details": entry.details,
            "created_at": iso(entry.created_at),
        }
        for entry in entries
    ]


def schedule_preview(db: Session, month: str) -> dict:
    return public_plan(build_month_plan(db, month))


def state(db: Session) -> dict:
    today = datetime.now(timezone.utc).date()
    today_puzzle = db.scalar(select(Puzzle).where(Puzzle.day == today))
    migration = None
    try:
        migration = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        db.rollback()
    url = make_url(settings.database_url)
    datasets = list_datasets(db)
    warnings = []
    if settings.seed_demo:
        warnings.append("SEED_DEMO is enabled; empty databases will receive demo data")
    if any(dataset["is_active"] and dataset["is_demo"] for dataset in datasets):
        warnings.append("A demo dataset is active")
    if settings.daily_salt in {"development-only-salt", "replace-with-a-long-random-secret-before-production"}:
        warnings.append("The development daily salt is configured")
    if not settings.oidc_configured:
        warnings.append("Administrator OIDC is not fully configured")
    if settings.admin_local_login_enabled:
        warnings.append("Local administrator login is enabled; disable it when OIDC is ready")
    month = today.strftime("%Y-%m")
    scheduled_this_month = db.scalar(
        select(func.count(Puzzle.id)).where(
            Puzzle.day >= date(today.year, today.month, 1),
            Puzzle.day < date(today.year + (today.month == 12), today.month % 12 + 1, 1),
        )
    ) or 0
    return {
        "environment": settings.app_env,
        "deployment_id": settings.deployment_id,
        "app_version": settings.app_version,
        "database": {"driver": url.drivername, "host": url.host or "local-file", "name": url.database},
        "migration": migration,
        "utc_today": today.isoformat(),
        "oidc_configured": settings.oidc_configured,
        "warnings": warnings,
        "categories": category_registry.catalog(),
        "datasets": datasets,
        "today": {
            "scheduled": today_puzzle is not None,
            "category": today_puzzle.category if today_puzzle else None,
            "question": today_puzzle.question_id if today_puzzle else None,
            "dataset_id": today_puzzle.dataset_id if today_puzzle else None,
        },
        "current_month": {"month": month, "scheduled_days": scheduled_this_month},
        "counts": {
            "players": db.scalar(select(func.count(AnonymousPlayer.id))) or 0,
            "rounds": db.scalar(select(func.count(Round.id))) or 0,
            "guesses": db.scalar(select(func.count(Guess.id))) or 0,
            "daily_puzzles": db.scalar(select(func.count(Puzzle.id)).where(Puzzle.day.is_not(None))) or 0,
        },
    }
