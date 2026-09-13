"""Operator-only country CSV import: python -m app.import_countries FILE LABEL."""
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import select, update

from .db import SessionLocal
from .models import CountryValue, DatasetVersion, Entity

REQUIRED = {"code", "name", "aliases", "population", "area_km2", "gdp_per_capita_usd", "temp_c", "capital", "capital_lat", "capital_lon", "provenance"}


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing columns: {sorted(REQUIRED - set(reader.fieldnames or []))}")
        rows = list(reader)
    if len(rows) < 5:
        raise ValueError("Dataset must have at least five countries")
    codes = set()
    for row in rows:
        code = row["code"].strip().upper()
        if not code or code in codes:
            raise ValueError(f"Duplicate or missing code: {code}")
        codes.add(code)
        for key in ("name", "capital"):
            if not row[key].strip():
                raise ValueError(f"Missing {key} for {code}")
        if int(row["population"]) <= 0 or float(row["area_km2"]) <= 0 or float(row["gdp_per_capita_usd"]) <= 0:
            raise ValueError(f"Invalid positive metric for {code}")
        if not -90 <= float(row["capital_lat"]) <= 90 or not -180 <= float(row["capital_lon"]) <= 180:
            raise ValueError(f"Invalid coordinates for {code}")
        if not -80 <= float(row["temp_c"]) <= 60:
            raise ValueError(f"Implausible temperature for {code}")
        json.loads(row["provenance"])
    return rows


def import_file(path: Path, label: str, activate: bool = True):
    rows = load_rows(path)
    with SessionLocal() as db:
        if db.scalar(select(DatasetVersion).where(DatasetVersion.label == label)):
            raise ValueError(f"Dataset label already exists: {label}")
        dataset = DatasetVersion(category="countries", label=label, source_manifest={"file": path.name, "count": len(rows)}, is_active=False)
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
            db.execute(update(DatasetVersion).where(DatasetVersion.category == "countries").values(is_active=False))
            dataset.is_active = True
        db.commit()
        return dataset.id


def seed_demo_if_empty():
    with SessionLocal() as db:
        if db.scalar(select(DatasetVersion.id).limit(1)):
            return
    import_file(Path(__file__).resolve().parent.parent / "data" / "demo_countries.csv", "demo-v1")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m app.import_countries CSV_PATH VERSION_LABEL")
    print(import_file(Path(sys.argv[1]), sys.argv[2]))
