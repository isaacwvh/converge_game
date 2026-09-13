from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.import_countries import import_file, publish
from app.models import DatasetVersion, Puzzle
from app.service import schedule_month


def test_monthly_snapshot_pins_challenges(client):
    today = datetime.now(timezone.utc).date()
    month = today.strftime("%Y-%m")
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "demo_countries.csv"
    label = f"test-{month}"
    import_file(path, label, activate=False, effective_month=month)
    with SessionLocal() as db:
        staged = db.scalar(select(DatasetVersion).where(DatasetVersion.label == label))
        assert not staged.is_active
    publish(label)
    with SessionLocal() as db:
        count = schedule_month(db, month)
        assert count == (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - date(today.year, today.month, 1)).days
        assert schedule_month(db, month) == 0
        puzzle = db.scalar(select(Puzzle).where(Puzzle.day == today))
        assert puzzle.dataset_id == staged.id
    listing = client.get(f"/api/v1/challenges/countries?month={month}")
    assert listing.status_code == 200
    assert all("answer" not in item for item in listing.json()["days"])
    round_ = client.get(f"/api/v1/challenges/countries/{today.isoformat()}")
    assert round_.status_code == 200
    assert round_.json()["date"] == today.isoformat()
    search = client.get(f"/api/v1/entities/countries/search?q=Japan&round_id={round_.json()['round_id']}")
    assert len(search.json()) == 1
    assert client.get(f"/api/v1/challenges/countries/{today.year + 1}-01-01").status_code == 404


def test_old_challenge_is_not_backfilled_with_current_snapshot(client):
    yesterday = date.fromordinal(datetime.now(timezone.utc).date().toordinal() - 1)
    assert client.get(f"/api/v1/challenges/countries/{yesterday}").status_code == 404
