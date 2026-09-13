import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .categories import category_registry
from .category import CategoryDefinition, CategoryRegistry
from .config import settings
from .models import DatasetVersion, Puzzle

POLICY_VERSION = "balanced-least-used-v1"


@dataclass(frozen=True)
class AvailableGame:
    definition: CategoryDefinition
    dataset: DatasetVersion
    entity_ids: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.definition.key


def parse_month(month: str) -> date:
    try:
        first = date.fromisoformat(f"{month}-01")
        if first.strftime("%Y-%m") != month:
            raise ValueError()
        return first
    except ValueError as exc:
        raise ValueError("Month must be YYYY-MM") from exc


def available_games(
    db: Session,
    day: date,
    registry: CategoryRegistry = category_registry,
    require_exact_month: bool = True,
) -> tuple[AvailableGame, ...]:
    month = day.strftime("%Y-%m")
    available = []
    for definition in registry.definitions():
        dataset = db.scalar(
            select(DatasetVersion)
            .where(
                DatasetVersion.category == definition.category_id,
                DatasetVersion.is_active.is_(True),
                (DatasetVersion.effective_month <= month) | DatasetVersion.effective_month.is_(None),
            )
            .order_by(DatasetVersion.effective_month.desc().nulls_last(), DatasetVersion.published_at.desc())
        )
        if dataset is None:
            continue
        if dataset.effective_month != month and (require_exact_month or dataset.label != "demo-v1"):
            continue
        entity_ids = tuple(sorted(definition.eligible_entity_ids(db, dataset.id)))
        if entity_ids:
            available.append(AvailableGame(definition, dataset, entity_ids))
    return tuple(available)


def _history(db: Session) -> tuple[dict[tuple[str, str], Counter], dict[tuple[str, str], list[tuple[date, str]]]]:
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    dated: dict[tuple[str, str], list[tuple[date, str]]] = defaultdict(list)
    rows = db.execute(
        select(Puzzle.category, Puzzle.question_id, Puzzle.day, Puzzle.target_id)
        .where(Puzzle.day.is_not(None))
        .order_by(Puzzle.day)
    ).all()
    for category_id, question_id, puzzle_day, target_id in rows:
        key = (category_id, question_id)
        counts[key][target_id] += 1
        dated[key].append((puzzle_day, target_id))
    return counts, dated


def _game_for_day(day: date, available: tuple[AvailableGame, ...]) -> AvailableGame:
    digest = hashlib.sha256(f"{settings.daily_salt}:{day.isoformat()}:global".encode()).digest()
    return available[int.from_bytes(digest[:8], "big") % len(available)]


def _target_for_day(
    day: date,
    game: AvailableGame,
    dated_history: list[tuple[date, str]],
) -> str:
    eligible = set(game.entity_ids)
    prior = [(puzzle_day, target_id) for puzzle_day, target_id in dated_history if puzzle_day < day and target_id in eligible]
    recent_limit = min(settings.recent_target_window, max(0, len(game.entity_ids) - 1))
    recent = {target_id for _, target_id in prior[-recent_limit:]} if recent_limit else set()
    candidates = [entity_id for entity_id in game.entity_ids if entity_id not in recent]
    if not candidates:
        candidates = list(game.entity_ids)

    last_used = {}
    for puzzle_day, target_id in prior:
        last_used[target_id] = puzzle_day
    never_used = [entity_id for entity_id in candidates if entity_id not in last_used]
    if never_used:
        candidates = never_used
    else:
        oldest = min(last_used[entity_id] for entity_id in candidates)
        candidates = [entity_id for entity_id in candidates if last_used[entity_id] == oldest]

    digest = hashlib.sha256(
        f"{settings.daily_salt}:{day.isoformat()}:{game.definition.category_id}:{game.definition.question_id}:{POLICY_VERSION}".encode()
    ).digest()
    return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]


def choose_daily(
    db: Session,
    day: date,
    registry: CategoryRegistry = category_registry,
    require_exact_month: bool = False,
) -> dict:
    available = available_games(db, day, registry, require_exact_month)
    if not available:
        raise ValueError(f"No playable category has a published snapshot for {day.strftime('%Y-%m')}")
    counts, dated = _history(db)
    game = _game_for_day(day, available)
    target_id = _target_for_day(day, game, dated[game.key])
    return {
        "date": day.isoformat(),
        "category": game.definition.category_id,
        "question": game.definition.question_id,
        "dataset_id": game.dataset.id,
        "dataset_label": game.dataset.label,
        "eligible_count": len(game.entity_ids),
        "target_id": target_id,
        "prior_uses": counts[game.key][target_id],
        "status": "planned",
    }


def build_month_plan(
    db: Session,
    month: str,
    registry: CategoryRegistry = category_registry,
) -> dict:
    first = parse_month(month)
    available = available_games(db, first, registry, require_exact_month=True)
    if not available:
        raise ValueError(f"Publish at least one playable {month} category snapshot before scheduling")

    existing = {
        puzzle.day: puzzle
        for puzzle in db.scalars(
            select(Puzzle).where(Puzzle.day >= first, Puzzle.day < first + timedelta(days=32), Puzzle.day.is_not(None))
        )
        if puzzle.day.strftime("%Y-%m") == month
    }
    counts, dated = _history(db)
    days = []
    current = first
    while current.strftime("%Y-%m") == month:
        puzzle = existing.get(current)
        if puzzle is not None:
            dataset = db.get(DatasetVersion, puzzle.dataset_id)
            days.append(
                {
                    "date": current.isoformat(),
                    "category": puzzle.category,
                    "question": puzzle.question_id,
                    "dataset_id": puzzle.dataset_id,
                    "dataset_label": dataset.label if dataset else "missing",
                    "target_id": puzzle.target_id,
                    "status": "scheduled",
                    "puzzle_id": puzzle.id,
                }
            )
        else:
            game = _game_for_day(current, available)
            target_id = _target_for_day(current, game, dated[game.key])
            days.append(
                {
                    "date": current.isoformat(),
                    "category": game.definition.category_id,
                    "question": game.definition.question_id,
                    "dataset_id": game.dataset.id,
                    "dataset_label": game.dataset.label,
                    "eligible_count": len(game.entity_ids),
                    "target_id": target_id,
                    "prior_uses": counts[game.key][target_id],
                    "status": "planned",
                }
            )
            counts[game.key][target_id] += 1
            dated[game.key].append((current, target_id))
        current += timedelta(days=1)

    availability = [
        {
            "category": game.definition.category_id,
            "question": game.definition.question_id,
            "dataset_id": game.dataset.id,
            "dataset_label": game.dataset.label,
            "eligible_count": len(game.entity_ids),
            "eligible_hash": hashlib.sha256("\n".join(game.entity_ids).encode()).hexdigest(),
        }
        for game in available
    ]
    fingerprint_payload = {
        "policy": POLICY_VERSION,
        "month": month,
        "availability": availability,
        "days": days,
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode()).hexdigest()
    distribution = Counter((item["category"], item["question"]) for item in days if item["status"] == "planned")
    return {
        **fingerprint_payload,
        "fingerprint": fingerprint,
        "planned_count": sum(item["status"] == "planned" for item in days),
        "scheduled_count": sum(item["status"] == "scheduled" for item in days),
        "distribution": [
            {"category": key[0], "question": key[1], "days": value}
            for key, value in sorted(distribution.items())
        ],
        "repeat_count": sum(item.get("prior_uses", 0) > 0 for item in days if item["status"] == "planned"),
    }


def public_plan(plan: dict, reveal_targets: bool = False) -> dict:
    result = {key: value for key, value in plan.items() if key != "days"}
    result["days"] = []
    for item in plan["days"]:
        public_item = {key: value for key, value in item.items() if key != "target_id"}
        if reveal_targets:
            public_item["target_id"] = item["target_id"]
        result["days"].append(public_item)
    return result


def apply_month_plan(
    db: Session,
    month: str,
    fingerprint: str,
    registry: CategoryRegistry = category_registry,
) -> dict:
    plan = build_month_plan(db, month, registry)
    if plan["fingerprint"] != fingerprint:
        raise ValueError("Schedule state changed after preview; create a new preview")
    for item in plan["days"]:
        if item["status"] != "planned":
            continue
        db.add(
            Puzzle(
                category=item["category"],
                question_id=item["question"],
                day=date.fromisoformat(item["date"]),
                dataset_id=item["dataset_id"],
                target_id=item["target_id"],
            )
        )
    db.commit()
    return {
        "month": month,
        "created": plan["planned_count"],
        "preserved": plan["scheduled_count"],
        "fingerprint": fingerprint,
    }
