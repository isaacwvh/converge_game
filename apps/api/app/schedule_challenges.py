"""Operator job: python -m app.schedule_challenges YYYY-MM."""
import sys

from .db import SessionLocal
from .service import schedule_month

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.schedule_challenges YYYY-MM")
    with SessionLocal() as db:
        print(f"Created {schedule_month(db, sys.argv[1])} daily challenges")
