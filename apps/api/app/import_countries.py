"""Operator-only country CSV import: python -m app.import_countries FILE LABEL."""
import csv
import json
import sys
import hashlib
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from sqlalchemy import select

from .environment import assert_dataset_allowed
from .db import SessionLocal
from .models import CountryValue, DatasetVersion, Entity, now

REQUIRED = {"code", "name", "aliases", "population", "area_km2", "gdp_per_capita_usd", "temp_c", "capital", "capital_lat", "capital_lon", "provenance"}


def validate_rows(rows: list[dict]) -> list[dict]:
    if len(rows) < 5:
        raise ValueError("Dataset must have at least five countries")
    codes = set()
    for row in rows:
        missing = REQUIRED - set(row)
        if missing:
            raise ValueError(f"Missing fields: {sorted(missing)}")
        code = row["code"].strip().upper()
        if len(code) != 3 or not code.isalpha() or code in codes:
            raise ValueError(f"Duplicate or invalid country code: {code}")
        codes.add(code)
        for key in ("name", "capital"):
            if not row[key].strip():
                raise ValueError(f"Missing {key} for {code}")
        try:
            population = int(row["population"])
            area = float(row["area_km2"])
            gdp = float(row["gdp_per_capita_usd"])
            temperature = float(row["temp_c"])
            latitude = float(row["capital_lat"])
            longitude = float(row["capital_lon"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric field for {code}") from exc
        if population <= 0 or not all(isfinite(value) and value > 0 for value in (area, gdp)):
            raise ValueError(f"Invalid positive metric for {code}")
        if not isfinite(latitude) or not isfinite(longitude) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError(f"Invalid coordinates for {code}")
        if not isfinite(temperature) or not -80 <= temperature <= 60:
            raise ValueError(f"Implausible temperature for {code}")
        try:
            provenance = json.loads(row["provenance"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid provenance for {code}") from exc
        if not isinstance(provenance, dict):
            raise ValueError(f"Invalid provenance for {code}")
    return rows


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing columns: {sorted(REQUIRED - set(reader.fieldnames or []))}")
        rows = list(reader)
    return validate_rows(rows)


def import_rows(rows: list[dict], label: str, manifest: dict, activate: bool = False, effective_month: str | None = None):
    rows = validate_rows(rows)
    effective_month = effective_month or datetime.now(timezone.utc).strftime("%Y-%m")
    if datetime.strptime(effective_month, "%Y-%m").strftime("%Y-%m") != effective_month:
        raise ValueError("Month must be YYYY-MM")
    with SessionLocal() as db:
        if db.scalar(select(DatasetVersion).where(DatasetVersion.label == label)):
            raise ValueError(f"Dataset label already exists: {label}")
        if db.scalar(select(DatasetVersion).where(DatasetVersion.category == "countries", DatasetVersion.effective_month == effective_month, DatasetVersion.is_active.is_(True))):
            raise ValueError(f"Month {effective_month} already has a published snapshot")
        dataset = DatasetVersion(category="countries", label=label, source_manifest=manifest, is_active=False, effective_month=effective_month)
        db.add(dataset)
        db.flush()
        for row in rows:
            code = row["code"].strip().upper()
            entity = db.scalar(select(Entity).where(Entity.category == "countries", Entity.code == code))
            if entity is None:
                entity = Entity(category="countries", code=code, name=row["name"].strip(), aliases=[a.strip() for a in row["aliases"].split("|") if a.strip()])
                db.add(entity)
                db.flush()
            db.add(CountryValue(
                dataset_id=dataset.id, entity_id=entity.id, population=int(row["population"]),
                area_km2=float(row["area_km2"]), gdp_per_capita_usd=float(row["gdp_per_capita_usd"]),
                temp_c=float(row["temp_c"]), capital=row["capital"].strip(),
                capital_lat=float(row["capital_lat"]), capital_lon=float(row["capital_lon"]),
                provenance=json.loads(row["provenance"]),
            ))
        db.flush()
        if activate:
            dataset.is_active = True
        db.commit()
        return dataset.id


def import_file(path: Path, label: str, activate: bool = False, effective_month: str | None = None):
    rows = load_rows(path)
    return import_rows(rows, label, {"file": path.name, "count": len(rows)}, activate, effective_month)


def fetch_and_stage(effective_month: str):
    from .country_sources import fetch_country_rows
    rows, manifest = fetch_country_rows()
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]
    label = f"worldbank-{effective_month}-{digest}"
    manifest["fingerprint"] = digest
    with SessionLocal() as db:
        if db.scalar(select(DatasetVersion.id).where(DatasetVersion.label == label)):
            return label
    import_rows(rows, label, manifest, effective_month=effective_month)
    return label


def publish(label: str):
    with SessionLocal() as db:
        dataset = db.scalar(select(DatasetVersion).where(DatasetVersion.label == label))
        if dataset is None:
            raise ValueError(f"Unknown dataset: {label}")
        if db.scalar(select(DatasetVersion).where(DatasetVersion.category == dataset.category, DatasetVersion.effective_month == dataset.effective_month, DatasetVersion.is_active.is_(True), DatasetVersion.id != dataset.id)):
            raise ValueError(f"Month {dataset.effective_month} already has a published snapshot")
        assert_dataset_allowed(dataset, "publish")
        dataset.reviewed_at = now()
        dataset.reviewed_by = "operator-cli"
        dataset.is_active = True
        db.commit()
        return dataset.id


def seed_demo_if_empty():
    with SessionLocal() as db:
        if db.scalar(select(DatasetVersion.id).limit(1)):
            return
    path = Path(__file__).resolve().parent.parent / "data" / "demo_countries.csv"
    rows = load_rows(path)
    import_rows(rows, "demo-v1", {"file": path.name, "count": len(rows), "demo": True}, activate=True, effective_month="1970-01")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "fetch":
        print(fetch_and_stage(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "publish":
        print(publish(sys.argv[2]))
    elif len(sys.argv) == 3:
        print(import_file(Path(sys.argv[1]), sys.argv[2]))
    else:
        raise SystemExit("Usage: python -m app.import_countries fetch YYYY-MM | publish LABEL | CSV_PATH LABEL")
