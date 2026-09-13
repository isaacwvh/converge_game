from contextlib import asynccontextmanager
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AnonymousPlayer, CountryValue, DatasetVersion, Entity, Puzzle, Round
from .service import active_dataset, daily_puzzle, get_or_create_round, serialize_round, stats, submit_guess

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Converge API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key"])


def player(request: Request, response: Response, db: Session = Depends(get_db)) -> AnonymousPlayer:
    cookie = request.cookies.get("__Host-converge_id" if settings.cookie_secure else "converge_id")
    current = db.get(AnonymousPlayer, cookie) if cookie else None
    if current is None:
        current = AnonymousPlayer()
        db.add(current)
        db.commit()
        name = "__Host-converge_id" if settings.cookie_secure else "converge_id"
        response.set_cookie(name, current.id, max_age=365 * 86400, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return current


class GuessIn(BaseModel):
    entity_id: str


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/v1/categories")
def categories():
    return [{"id": "countries", "name": "Countries", "dimensions": ["population", "area_km2", "gdp_per_capita_usd", "temp_c", "distance_km"]}]


@app.get("/api/v1/entities/countries/search")
def search(q: str = "", db: Session = Depends(get_db)):
    dataset_id = daily_puzzle(db).dataset_id
    entities = db.scalars(select(Entity).join(CountryValue, CountryValue.entity_id == Entity.id).where(CountryValue.dataset_id == dataset_id).order_by(Entity.name)).all()
    needle = q.strip().casefold()
    matches = [e for e in entities if needle in e.name.casefold() or any(needle in alias.casefold() for alias in e.aliases)]
    return [{"id": e.id, "name": e.name, "code": e.code} for e in matches[:25]]


@app.get("/api/v1/daily/countries")
def daily(response: Response, p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    puzzle = daily_puzzle(db)
    round_ = get_or_create_round(db, p.id, puzzle)
    return serialize_round(db, round_, puzzle)


@app.post("/api/v1/rounds/practice")
def practice(p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    dataset = active_dataset(db)
    ids = list(db.scalars(select(CountryValue.entity_id).where(CountryValue.dataset_id == dataset.id)))
    if not ids:
        raise HTTPException(503, "No eligible countries")
    puzzle = Puzzle(category="countries", day=None, dataset_id=dataset.id, target_id=secrets.choice(ids))
    db.add(puzzle)
    db.flush()
    round_ = Round(player_id=p.id, puzzle_id=puzzle.id)
    db.add(round_)
    db.commit()
    return serialize_round(db, round_, puzzle)


@app.get("/api/v1/rounds/{round_id}")
def get_round(round_id: str, p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    round_ = db.scalar(select(Round).where(Round.id == round_id, Round.player_id == p.id))
    if round_ is None:
        raise HTTPException(404, "Round not found")
    return serialize_round(db, round_, db.get(Puzzle, round_.puzzle_id))


@app.post("/api/v1/rounds/{round_id}/guesses")
def guess(round_id: str, body: GuessIn, idempotency_key: str | None = Header(default=None), p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    if idempotency_key is not None and len(idempotency_key) > 80:
        raise HTTPException(422, "Idempotency key too long")
    return submit_guess(db, round_id, p.id, body.entity_id, idempotency_key)


@app.get("/api/v1/stats/countries")
def player_stats(p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    return stats(db, p.id)
