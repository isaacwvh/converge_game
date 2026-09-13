from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import DatasetVersion, Installation


def ensure_installation(db: Session) -> Installation:
    settings.validate_runtime()
    installation = db.get(Installation, "installation")
    if installation is None:
        installation = Installation(
            id="installation",
            deployment_id=settings.deployment_id,
            environment=settings.app_env,
        )
        db.add(installation)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            installation = db.get(Installation, "installation")
    if installation is None:
        raise RuntimeError("Installation identity could not be initialized")
    if installation.deployment_id != settings.deployment_id or installation.environment != settings.app_env:
        raise RuntimeError(
            "Database deployment identity mismatch: "
            f"database={installation.environment}/{installation.deployment_id}, "
            f"application={settings.app_env}/{settings.deployment_id}"
        )
    return installation


def is_demo_dataset(dataset: DatasetVersion) -> bool:
    return dataset.label == "demo-v1" or bool((dataset.source_manifest or {}).get("demo"))


def assert_dataset_allowed(dataset: DatasetVersion, operation: str) -> None:
    if settings.app_env == "production" and is_demo_dataset(dataset):
        raise ValueError(f"Production cannot {operation} demo dataset {dataset.label}")
