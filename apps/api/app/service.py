import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .categories import category_registry
from .category import CategoryDefinition, CategoryRegistry
from .models import DatasetVersion, Entity, Guess, Puzzle, Round, now
from .scheduler import apply_month_plan, build_month_plan, choose_daily


def active_dataset(db: Session, category_id: str = "countries", day: date | None = None) -> DatasetVersion:
    day = day or datetime.now(timezone.utc).date()
    dataset = db.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.category == category_id,
            DatasetVersion.is_active.is_(True),
            (DatasetVersion.effective_month <= day.strftime("%Y-%m")) | DatasetVersion.effective_month.is_(None),
        )
        .order_by(DatasetVersion.effective_month.desc(), DatasetVersion.published_at.desc())
    )
    if dataset is None:
        raise HTTPException(503, f"No published dataset for category {category_id}")
    return dataset


def definition_for(puzzle: Puzzle, registry: CategoryRegistry = category_registry) -> CategoryDefinition:
    try:
        return registry.resolve(puzzle.category, puzzle.question_id)
    except KeyError as exc:
        raise HTTPException(503, f"Game definition is not registered: {puzzle.category}/{puzzle.question_id}") from exc




def daily_puzzle(
    db: Session,
    day: date | None = None,
    registry: CategoryRegistry = category_registry,
    require_exact_month: bool = False,
) -> Puzzle:
    day = day or datetime.now(timezone.utc).date()
    puzzle = db.scalar(select(Puzzle).where(Puzzle.day == day))
    if puzzle:
        return puzzle

    try:
        choice = choose_daily(db, day, registry, require_exact_month)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    puzzle = Puzzle(
        category=choice["category"],
        question_id=choice["question"],
        day=day,
        dataset_id=choice["dataset_id"],
        target_id=choice["target_id"],
    )
    db.add(puzzle)
    try:
        db.commit()
        return puzzle
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Puzzle).where(Puzzle.day == day))
        if existing is None:
            raise
        return existing


def schedule_month(db: Session, month: str, registry: CategoryRegistry = category_registry) -> int:
    plan = build_month_plan(db, month, registry)
    return apply_month_plan(db, month, plan["fingerprint"], registry)["created"]


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
        existing = db.scalar(select(Round).where(Round.player_id == player_id, Round.puzzle_id == puzzle.id))
        if existing is None:
            raise
        return existing


def create_practice_round(
    db: Session,
    player_id: str,
    category_id: str = "countries",
    question_id: str | None = None,
    registry: CategoryRegistry = category_registry,
) -> tuple[Round, Puzzle]:
    try:
        definition = registry.resolve(category_id, question_id)
    except KeyError as exc:
        raise HTTPException(404, "Category or question not found") from exc
    dataset = active_dataset(db, definition.category_id)
    entity_ids = definition.eligible_entity_ids(db, dataset.id)
    if not entity_ids:
        raise HTTPException(503, f"No eligible {definition.entity_label.lower()} entities")
    puzzle = Puzzle(
        category=definition.category_id,
        question_id=definition.question_id,
        day=None,
        dataset_id=dataset.id,
        target_id=secrets.choice(entity_ids),
    )
    db.add(puzzle)
    db.flush()
    round_ = Round(player_id=player_id, puzzle_id=puzzle.id)
    db.add(round_)
    db.commit()
    return round_, puzzle


def serialize_round(
    db: Session,
    round_: Round,
    puzzle: Puzzle,
    registry: CategoryRegistry = category_registry,
) -> dict:
    definition = definition_for(puzzle, registry)
    guesses = list(db.scalars(select(Guess).where(Guess.round_id == round_.id).order_by(Guess.turn)))
    rows = []
    for guess in guesses:
        entity = db.get(Entity, guess.entity_id)
        rows.append({"turn": guess.turn, "entity_id": entity.id, "name": entity.name, "feedback": guess.feedback})
    result = {
        "round_id": round_.id,
        "category": definition.category_id,
        "question": definition.question_id,
        "game": definition.metadata(),
        "date": puzzle.day.isoformat() if puzzle.day else None,
        "status": round_.status,
        "max_guesses": definition.guess_limit,
        "remaining": max(0, definition.guess_limit - len(guesses)),
        "guesses": rows,
        "rules": definition.rules,
    }
    if round_.status != "playing":
        result["answer"] = definition.serialize_answer(db, puzzle.dataset_id, puzzle.target_id)
    return result


def submit_guess(
    db: Session,
    round_id: str,
    player_id: str,
    entity_id: str,
    idempotency_key: str | None,
    registry: CategoryRegistry = category_registry,
) -> dict:
    # PostgreSQL locks the row so concurrent tabs cannot spend the same turn.
    round_ = db.scalar(select(Round).where(Round.id == round_id, Round.player_id == player_id).with_for_update())
    if round_ is None:
        raise HTTPException(404, "Round not found")
    puzzle = db.get(Puzzle, round_.puzzle_id)
    definition = definition_for(puzzle, registry)
    if idempotency_key:
        prior = db.scalar(select(Guess).where(Guess.round_id == round_id, Guess.idempotency_key == idempotency_key))
        if prior:
            if prior.entity_id != entity_id:
                raise HTTPException(409, "Idempotency key reused for a different guess")
            return serialize_round(db, round_, puzzle, registry)
    if round_.status != "playing":
        raise HTTPException(409, "Round has ended")
    prior_entity = db.scalar(select(Guess).where(Guess.round_id == round_id, Guess.entity_id == entity_id))
    if prior_entity:
        raise HTTPException(409, f"{definition.entity_label} already guessed")

    feedback = definition.compare(db, puzzle.dataset_id, puzzle.target_id, entity_id)
    turn = db.scalar(select(func.count(Guess.id)).where(Guess.round_id == round_id)) + 1
    if turn > definition.guess_limit:
        raise HTTPException(409, "No guesses remaining")
    db.add(
        Guess(
            round_id=round_id,
            turn=turn,
            entity_id=entity_id,
            feedback=feedback,
            idempotency_key=idempotency_key,
        )
    )
    if entity_id == puzzle.target_id:
        round_.status = "won"
        round_.completed_at = now()
    elif turn == definition.guess_limit:
        round_.status = "lost"
        round_.completed_at = now()
    db.commit()
    return serialize_round(db, round_, puzzle, registry)


def stats(
    db: Session,
    player_id: str,
    category_id: str | None = "countries",
    question_id: str | None = None,
) -> dict:
    query = (
        select(Puzzle.day, Round.status)
        .join(Round, Round.puzzle_id == Puzzle.id)
        .where(Round.player_id == player_id, Puzzle.day.is_not(None), Round.status != "playing")
    )
    if category_id is not None:
        query = query.where(Puzzle.category == category_id)
    if question_id is not None:
        query = query.where(Puzzle.question_id == question_id)
    completed = db.execute(query.order_by(Puzzle.day.desc())).all()
    wins = sum(status == "won" for _, status in completed)
    streak = 0
    expected = datetime.now(timezone.utc).date()
    if completed and completed[0][0] < expected:
        expected -= timedelta(days=1)
    for completed_day, status in completed:
        if completed_day != expected or status != "won":
            break
        streak += 1
        expected -= timedelta(days=1)
    return {"played": len(completed), "won": wins, "current_streak": streak}
