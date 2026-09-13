from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.category import CategoryDefinition, CategoryRegistry
from app.db import SessionLocal
from app.models import DatasetVersion, Entity
from app.scheduler import apply_month_plan, build_month_plan


class ManifestCategory(CategoryDefinition):
    category_name = "Manifest category"
    question_id = "identify"
    question_name = "Identify"
    entity_label = "Item"
    prompt = "Identify the item."
    guess_limit = 3
    dimensions = ({"id": "match", "label": "Match", "feedback": "direction", "display": {"style": "number"}},)
    rules = {"timezone": "UTC"}

    def __init__(self, category_id):
        self.category_id = category_id

    def eligible_entity_ids(self, db, dataset_id):
        dataset = db.get(DatasetVersion, dataset_id)
        codes = set(dataset.source_manifest["eligible_codes"])
        return list(
            db.scalars(
                select(Entity.id)
                .where(Entity.category == self.category_id, Entity.code.in_(codes))
                .order_by(Entity.id)
            )
        )

    def search_entities(self, db, dataset_id, query, limit=25):
        ids = set(self.eligible_entity_ids(db, dataset_id))
        return [entity for entity in db.scalars(select(Entity).where(Entity.id.in_(ids))) if query.casefold() in entity.name.casefold()][:limit]

    def compare(self, db, dataset_id, target_id, guess_id):
        return {"match": {"direction": "equal" if target_id == guess_id else "up", "guess_value": 1}}

    def serialize_answer(self, db, dataset_id, target_id):
        entity = db.get(Entity, target_id)
        return {"entity_id": entity.id, "name": entity.name}


def next_month(month: str) -> str:
    first = date.fromisoformat(f"{month}-01")
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1).strftime("%Y-%m")


def add_category_data(db, category_id: str, month: str, codes: list[str]):
    existing = {entity.code for entity in db.scalars(select(Entity).where(Entity.category == category_id))}
    for code in codes:
        if code not in existing:
            db.add(Entity(category=category_id, code=code, name=f"{category_id} {code}", aliases=[]))
    dataset = DatasetVersion(
        category=category_id,
        label=f"{category_id}-{month}",
        source_manifest={"eligible_codes": codes},
        is_active=True,
        effective_month=month,
    )
    db.add(dataset)
    db.commit()
    return dataset


def test_rotation_is_balanced_independently_for_registered_categories(client):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    registry = CategoryRegistry([ManifestCategory("alpha"), ManifestCategory("beta")])
    with SessionLocal() as db:
        add_category_data(db, "alpha", month, ["A", "B", "C"])
        add_category_data(db, "beta", month, ["X", "Y", "Z"])
        plan = build_month_plan(db, month, registry)
        by_category = defaultdict(list)
        for day in plan["days"]:
            by_category[day["category"]].append(day["target_id"])
        assert set(by_category) == {"alpha", "beta"}
        for targets in by_category.values():
            assert len(set(targets[:3])) == 3
            counts = [targets.count(target) for target in set(targets)]
            assert max(counts) - min(counts) <= 1


def test_rotation_handles_added_and_removed_entities_without_flooding_new_data(client):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    following = next_month(month)
    category = ManifestCategory("evolving")
    registry = CategoryRegistry([category])
    with SessionLocal() as db:
        add_category_data(db, "evolving", month, ["A", "B", "C", "D", "E"])
        first_plan = build_month_plan(db, month, registry)
        apply_month_plan(db, month, first_plan["fingerprint"], registry)

        add_category_data(db, "evolving", following, ["B", "C", "D", "E", "F"])
        second_plan = build_month_plan(db, following, registry)
        first_five = second_plan["days"][:5]
        codes_by_id = {
            entity.id: entity.code
            for entity in db.scalars(select(Entity).where(Entity.category == "evolving"))
        }
        first_codes = [codes_by_id[day["target_id"]] for day in first_five]
        assert first_codes[0] == "F"
        assert set(first_codes) == {"B", "C", "D", "E", "F"}
