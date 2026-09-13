from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.category import CategoryDefinition, CategoryRegistry
from app.db import SessionLocal
from app.models import AnonymousPlayer, DatasetVersion, Entity, Puzzle
from app.service import daily_puzzle, get_or_create_round, serialize_round, submit_guess


class TestThingsCategory(CategoryDefinition):
    category_id = "test-things"
    category_name = "Test things"
    question_id = "identify-thing"
    question_name = "Mystery thing"
    entity_label = "Thing"
    prompt = "Find the mystery thing."
    guess_limit = 2
    dimensions = (
        {
            "id": "name_length",
            "label": "Name length",
            "feedback": "direction",
            "display": {"style": "number", "maximum_fraction_digits": 0},
        },
    )
    rules = {"arrows": "Arrows compare name length", "timezone": "UTC"}

    def eligible_entity_ids(self, db, dataset_id):
        dataset = db.get(DatasetVersion, dataset_id)
        if dataset is None or dataset.category != self.category_id:
            return []
        return list(
            db.scalars(
                select(Entity.id).where(Entity.category == self.category_id).order_by(Entity.id)
            )
        )

    def search_entities(self, db, dataset_id, query, limit=25):
        eligible = set(self.eligible_entity_ids(db, dataset_id))
        needle = query.casefold()
        return [
            entity
            for entity in db.scalars(
                select(Entity).where(Entity.category == self.category_id).order_by(Entity.name)
            )
            if entity.id in eligible and needle in entity.name.casefold()
        ][:limit]

    def compare(self, db, dataset_id, target_id, guess_id):
        eligible = self.eligible_entity_ids(db, dataset_id)
        if target_id not in eligible or guess_id not in eligible:
            raise ValueError("Thing is not eligible")
        target = db.get(Entity, target_id)
        guess = db.get(Entity, guess_id)
        difference = len(target.name) - len(guess.name)
        direction = "equal" if difference == 0 else "up" if difference > 0 else "down"
        return {"name_length": {"direction": direction, "guess_value": len(guess.name)}}

    def serialize_answer(self, db, dataset_id, target_id):
        if target_id not in self.eligible_entity_ids(db, dataset_id):
            raise ValueError("Thing is not eligible")
        entity = db.get(Entity, target_id)
        return {"entity_id": entity.id, "name": entity.name}


def test_country_compatibility_route_is_the_global_daily_round(client):
    global_round = client.get("/api/v1/daily")
    compatibility_round = client.get("/api/v1/daily/countries")
    assert global_round.status_code == 200
    assert compatibility_round.status_code == 200
    assert global_round.json()["round_id"] == compatibility_round.json()["round_id"]
    assert global_round.json()["question"] == "identify-country"
    assert global_round.json()["game"]["dimensions"][0]["id"] == "population"
    catalog = client.get("/api/v1/categories").json()
    assert catalog[0]["id"] == "countries"
    assert catalog[0]["questions"][0]["question_id"] == "identify-country"
    assert catalog[0]["questions"][0]["guess_limit"] == 8
    dated_round = client.get(f"/api/v1/challenges/{global_round.json()['date']}")
    assert dated_round.status_code == 200
    assert dated_round.json()["round_id"] == global_round.json()["round_id"]
    with SessionLocal() as db:
        today = datetime.now(timezone.utc).date()
        assert len(list(db.scalars(select(Puzzle).where(Puzzle.day == today)))) == 1


def test_database_enforces_one_global_puzzle_per_day(client):
    state = client.get("/api/v1/daily").json()
    with SessionLocal() as db:
        existing = db.scalar(select(Puzzle))
        db.add(
            Puzzle(
                category="another-category",
                question_id="another-question",
                day=existing.day,
                dataset_id=existing.dataset_id,
                target_id=existing.target_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert state["date"] is not None


def test_registered_second_category_reuses_round_lifecycle(client):
    registry = CategoryRegistry([TestThingsCategory()])
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with SessionLocal() as db:
        dataset = DatasetVersion(
            category="test-things",
            label="test-things-current",
            source_manifest={"test": True},
            is_active=True,
            effective_month=month,
        )
        player = AnonymousPlayer()
        entities = [
            Entity(category="test-things", code="ONE", name="One", aliases=[]),
            Entity(category="test-things", code="THREE", name="Three", aliases=[]),
        ]
        db.add_all([dataset, player, *entities])
        db.commit()

        puzzle = daily_puzzle(db, datetime.now(timezone.utc).date(), registry, require_exact_month=True)
        round_ = get_or_create_round(db, player.id, puzzle)
        initial = serialize_round(db, round_, puzzle, registry)
        assert initial["category"] == "test-things"
        assert initial["question"] == "identify-thing"
        assert initial["max_guesses"] == 2
        assert "answer" not in initial

        finished = submit_guess(db, round_.id, player.id, puzzle.target_id, "win", registry)
        assert finished["status"] == "won"
        assert finished["answer"]["entity_id"] == puzzle.target_id
