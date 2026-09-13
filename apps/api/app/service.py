import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .domain import MAX_GUESSES, compare
from .models import AnonymousPlayer, CountryValue, DatasetVersion, Entity, Guess, Puzzle, Round, now


def active_dataset(db: Session) -> DatasetVersion:
    dataset = db.scalar(select(DatasetVersion).where(DatasetVersion.category == "countries", DatasetVersion.is_active.is_(True)))
    if dataset is None:
        raise HTTPException(503, "No published country dataset")
    return dataset


def value_for(db: Session, dataset_id: str, entity_id: str) -> CountryValue:
    value = db.get(CountryValue, (dataset_id, entity_id))
    if value is None:
        raise HTTPException(422, "Country is not eligible in this puzzle")
    return value


def daily_puzzle(db: Session, day=None) -> Puzzle:
    day = day or datetime.now(timezone.utc).date()
    puzzle = db.scalar(select(Puzzle).where(Puzzle.category == "countries", Puzzle.day == day))
    if puzzle:
        return puzzle
    dataset = active_dataset(db)
    ids = list(db.scalars(select(CountryValue.entity_id).where(CountryValue.dataset_id == dataset.id).order_by(CountryValue.entity_id)))
    if not ids:
        raise HTTPException(503, "No eligible countries")
    digest = hashlib.sha256(f"{settings.daily_salt}:{day.isoformat()}:countries".encode()).digest()
    target_id = ids[int.from_bytes(digest[:8], "big") % len(ids)]
    puzzle = Puzzle(category="countries", day=day, dataset_id=dataset.id, target_id=target_id)
    db.add(puzzle)
    try:
        db.commit()
        return puzzle
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Puzzle).where(Puzzle.category == "countries", Puzzle.day == day))


def get_or_create_round(db: Session, player_id: str, puzzle: Puzzle) -> Round:
    round_ = db.scalar(select(Round).where(Round.player_id == player_id, Round.puzzle_id == puzzle.id))
    if round_:
        return round_
    round_ = Round(player_id=player_id, puzzle_id=puzzle.id)
    db.add(round_)
    try:
        db.commit()
        return round_
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Round).where(Round.player_id == player_id, Round.puzzle_id == puzzle.id))


def serialize_round(db: Session, round_: Round, puzzle: Puzzle) -> dict:
    guesses = list(db.scalars(select(Guess).where(Guess.round_id == round_.id).order_by(Guess.turn)))
    rows = []
    for guess in guesses:
        entity = db.get(Entity, guess.entity_id)
        rows.append({"turn": guess.turn, "entity_id": entity.id, "name": entity.name, "feedback": guess.feedback})
    result = {
        "round_id": round_.id,
        "category": "countries",
        "date": puzzle.day.isoformat() if puzzle.day else None,
        "status": round_.status,
        "max_guesses": MAX_GUESSES,
        "remaining": MAX_GUESSES - len(guesses),
        "guesses": rows,
        "rules": {"arrows": "Relative to your guess: up means the answer is larger; down means smaller", "distance": "Great-circle distance between the selected capitals, rounded to 100 km", "timezone": "UTC"},
    }
    if round_.status != "playing":
        target = db.get(Entity, puzzle.target_id)
        value = value_for(db, puzzle.dataset_id, puzzle.target_id)
        result["answer"] = {"entity_id": target.id, "name": target.name, "capital": value.capital, "population": value.population, "area_km2": float(value.area_km2), "gdp_per_capita_usd": float(value.gdp_per_capita_usd), "temp_c": float(value.temp_c), "provenance": value.provenance}
    return result


def submit_guess(db: Session, round_id: str, player_id: str, entity_id: str, idempotency_key: str | None) -> dict:
    # PostgreSQL locks the row so concurrent tabs cannot spend the same turn.
    round_ = db.scalar(select(Round).where(Round.id == round_id, Round.player_id == player_id).with_for_update())
    if round_ is None:
        raise HTTPException(404, "Round not found")
    puzzle = db.get(Puzzle, round_.puzzle_id)
    if idempotency_key:
        prior = db.scalar(select(Guess).where(Guess.round_id == round_id, Guess.idempotency_key == idempotency_key))
        if prior:
            if prior.entity_id != entity_id:
                raise HTTPException(409, "Idempotency key reused for a different guess")
            return serialize_round(db, round_, puzzle)
    if round_.status != "playing":
        raise HTTPException(409, "Round has ended")
    prior_entity = db.scalar(select(Guess).where(Guess.round_id == round_id, Guess.entity_id == entity_id))
    if prior_entity:
        raise HTTPException(409, "Country already guessed")
    guessed = value_for(db, puzzle.dataset_id, entity_id)
    target = value_for(db, puzzle.dataset_id, puzzle.target_id)
    turn = db.scalar(select(func.count(Guess.id)).where(Guess.round_id == round_id)) + 1
    if turn > MAX_GUESSES:
        raise HTTPException(409, "No guesses remaining")
    feedback = compare(target, guessed)
    db.add(Guess(round_id=round_id, turn=turn, entity_id=entity_id, feedback=feedback, idempotency_key=idempotency_key))
    if entity_id == puzzle.target_id:
        round_.status = "won"
        round_.completed_at = now()
    elif turn == MAX_GUESSES:
        round_.status = "lost"
        round_.completed_at = now()
    db.commit()
    return serialize_round(db, round_, puzzle)


def stats(db: Session, player_id: str) -> dict:
    completed = db.execute(select(Puzzle.day, Round.status).join(Round, Round.puzzle_id == Puzzle.id).where(Round.player_id == player_id, Puzzle.category == "countries", Puzzle.day.is_not(None), Round.status != "playing").order_by(Puzzle.day.desc())).all()
    wins = sum(status == "won" for _, status in completed)
    streak = 0
    expected = datetime.now(timezone.utc).date()
    if completed and completed[0][0] < expected:
        from datetime import timedelta
        expected -= timedelta(days=1)
    for day, status in completed:
        if day != expected or status != "won":
            break
        streak += 1
        from datetime import timedelta
        expected -= timedelta(days=1)
    return {"played": len(completed), "won": wins, "current_streak": streak}
