from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_auth import router as admin_auth_router
from .admin_routes import router as admin_router
from .categories import category_registry
from .config import settings
from .db import SessionLocal, get_db
from .environment import ensure_installation
from .models import AnonymousPlayer, Puzzle, Round
from .service import (
    active_dataset,
    create_practice_round,
    daily_puzzle,
    definition_for,
    get_or_create_round,
    serialize_round,
    stats,
    submit_guess,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        ensure_installation(db)
    yield


app = FastAPI(title="Converge API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.admin_session_secret,
    session_cookie="converge_admin_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=settings.cookie_secure,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)
app.include_router(admin_auth_router)
app.include_router(admin_router)


def player(request: Request, response: Response, db: Session = Depends(get_db)) -> AnonymousPlayer:
    cookie = request.cookies.get("__Host-converge_id" if settings.cookie_secure else "converge_id")
    current = db.get(AnonymousPlayer, cookie) if cookie else None
    if current is None:
        current = AnonymousPlayer()
        db.add(current)
        db.commit()
        name = "__Host-converge_id" if settings.cookie_secure else "converge_id"
        response.set_cookie(
            name,
            current.id,
            max_age=365 * 86400,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
    return current


class GuessIn(BaseModel):
    entity_id: str


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/v1/categories")
def categories():
    return category_registry.catalog()


@app.get("/api/v1/entities/{category_id}/search")
def search(
    category_id: str,
    q: str = "",
    round_id: str | None = None,
    question: str | None = None,
    p: AnonymousPlayer = Depends(player),
    db: Session = Depends(get_db),
):
    if round_id:
        round_ = db.scalar(select(Round).where(Round.id == round_id, Round.player_id == p.id))
        if round_ is None:
            raise HTTPException(404, "Round not found")
        puzzle = db.get(Puzzle, round_.puzzle_id)
        if puzzle.category != category_id:
            raise HTTPException(422, "Search category does not match the round")
        definition = definition_for(puzzle)
        dataset_id = puzzle.dataset_id
    else:
        try:
            definition = category_registry.resolve(category_id, question)
        except KeyError as exc:
            raise HTTPException(404, "Category or question not found") from exc
        dataset_id = active_dataset(db, definition.category_id).id
    return [
        definition.serialize_entity(entity)
        for entity in definition.search_entities(db, dataset_id, q)
    ]


@app.get("/api/v1/daily/countries")
@app.get("/api/v1/daily")
def daily(p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    puzzle = daily_puzzle(db)
    round_ = get_or_create_round(db, p.id, puzzle)
    return serialize_round(db, round_, puzzle)


def archive_start(today: date) -> date:
    index = today.year * 12 + today.month - 12
    return date(index // 12, index % 12 + 1, 1)


def check_challenge_access(day: date):
    """Central place for a future archive entitlement check."""
    today = datetime.now(timezone.utc).date()
    if day > today or day < archive_start(today):
        raise HTTPException(404, "Challenge outside available archive")


@app.get("/api/v1/challenges/countries")
@app.get("/api/v1/challenges")
def challenges(month: str | None = None, p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    month = month or today.strftime("%Y-%m")
    try:
        first = date.fromisoformat(f"{month}-01")
        if first.strftime("%Y-%m") != month:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422, "Month must be YYYY-MM") from exc
    if first < archive_start(today) or first > today:
        raise HTTPException(404, "Month outside available archive")
    puzzles = db.scalars(
        select(Puzzle).where(Puzzle.day >= first, Puzzle.day <= today).order_by(Puzzle.day)
    ).all()
    puzzle_ids = [puzzle.id for puzzle in puzzles]
    rounds = {
        round_.puzzle_id: round_.status
        for round_ in db.scalars(
            select(Round).where(Round.player_id == p.id, Round.puzzle_id.in_(puzzle_ids))
        )
    } if puzzle_ids else {}
    return {
        "month": month,
        "days": [
            {
                "date": puzzle.day.isoformat(),
                "category": puzzle.category,
                "question": puzzle.question_id,
                "status": rounds.get(puzzle.id, "available"),
            }
            for puzzle in puzzles
            if puzzle.day.strftime("%Y-%m") == month
        ],
    }


@app.get("/api/v1/challenges/countries/{day}")
@app.get("/api/v1/challenges/{day}")
def challenge(day: date, p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    check_challenge_access(day)
    puzzle = db.scalar(select(Puzzle).where(Puzzle.day == day))
    if puzzle is None:
        if day != datetime.now(timezone.utc).date():
            raise HTTPException(404, "Challenge not scheduled")
        puzzle = daily_puzzle(db, day)
    return serialize_round(db, get_or_create_round(db, p.id, puzzle), puzzle)


@app.post("/api/v1/rounds/practice")
def practice(p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    # This compatibility endpoint remains countries-only. Future themed category
    # access needs an explicit entitlement design rather than an open query flag.
    round_, puzzle = create_practice_round(db, p.id)
    return serialize_round(db, round_, puzzle)


@app.get("/api/v1/rounds/{round_id}")
def get_round(round_id: str, p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    round_ = db.scalar(select(Round).where(Round.id == round_id, Round.player_id == p.id))
    if round_ is None:
        raise HTTPException(404, "Round not found")
    return serialize_round(db, round_, db.get(Puzzle, round_.puzzle_id))


@app.post("/api/v1/rounds/{round_id}/guesses")
def guess(
    round_id: str,
    body: GuessIn,
    idempotency_key: str | None = Header(default=None),
    p: AnonymousPlayer = Depends(player),
    db: Session = Depends(get_db),
):
    if idempotency_key is not None and len(idempotency_key) > 80:
        raise HTTPException(422, "Idempotency key too long")
    return submit_guess(db, round_id, p.id, body.entity_id, idempotency_key)


@app.get("/api/v1/stats")
def overall_stats(p: AnonymousPlayer = Depends(player), db: Session = Depends(get_db)):
    return stats(db, p.id, category_id=None)


@app.get("/api/v1/stats/{category_id}")
def category_stats(
    category_id: str,
    question: str | None = None,
    p: AnonymousPlayer = Depends(player),
    db: Session = Depends(get_db),
):
    if not any(definition.category_id == category_id for definition in category_registry.definitions()):
        raise HTTPException(404, "Category not found")
    if question is not None:
        try:
            category_registry.resolve(category_id, question)
        except KeyError as exc:
            raise HTTPException(404, "Question not found") from exc
    return stats(db, p.id, category_id=category_id, question_id=question)
