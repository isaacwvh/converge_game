from abc import ABC, abstractmethod
from collections.abc import Iterable

from sqlalchemy.orm import Session

from .models import Entity


class CategoryDefinition(ABC):
    """One playable question within a category.

    The engine identifies a game by both category_id and question_id. A category
    can therefore add more questions later without changing the round lifecycle.
    """

    category_id: str
    category_name: str
    question_id: str
    question_name: str
    entity_label: str
    prompt: str
    guess_limit: int
    dimensions: tuple[dict, ...]
    rules: dict

    @property
    def key(self) -> tuple[str, str]:
        return self.category_id, self.question_id

    def metadata(self) -> dict:
        return {
            "category_id": self.category_id,
            "category_name": self.category_name,
            "question_id": self.question_id,
            "question_name": self.question_name,
            "entity_label": self.entity_label,
            "prompt": self.prompt,
            "guess_limit": self.guess_limit,
            "dimensions": list(self.dimensions),
            "rules": self.rules,
        }

    @abstractmethod
    def target_entity_ids(self, db: Session, dataset_id: str) -> list[str]:
        """Return stable, sorted IDs allowed as targets for this question."""

    @abstractmethod
    def search_entities(self, db: Session, dataset_id: str, query: str, limit: int = 25) -> list[Entity]:
        """Search valid guesses in the pinned dataset; this may be broader than targets."""

    @abstractmethod
    def compare(self, db: Session, dataset_id: str, target_id: str, guess_id: str) -> dict:
        """Build persisted feedback for one guess."""

    @abstractmethod
    def serialize_answer(self, db: Session, dataset_id: str, target_id: str) -> dict:
        """Serialize the answer after a round has ended."""

    def build_hints(
        self, db: Session, dataset_id: str, target_id: str, guess_count: int, round_status: str
    ) -> list[dict]:
        """Return deterministic hints unlocked by the current round state."""
        return []

    def admin_dataset_diagnostics(self, db: Session, dataset_id: str) -> dict:
        target_count = len(self.target_entity_ids(db, dataset_id))
        return {"eligible_count": target_count, "target_count": target_count}

    def serialize_entity(self, entity: Entity) -> dict:
        return {"id": entity.id, "name": entity.name, "code": entity.code}

    def admin_dataset_rows(self, db: Session, dataset_id: str) -> list[dict]:
        return [
            self.serialize_entity(entity)
            for entity_id in self.target_entity_ids(db, dataset_id)
            if (entity := db.get(Entity, entity_id)) is not None
        ]


class CategoryRegistry:
    def __init__(self, definitions: Iterable[CategoryDefinition] = ()):
        self._definitions: dict[tuple[str, str], CategoryDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: CategoryDefinition) -> None:
        if not definition.category_id or not definition.question_id:
            raise ValueError("Category and question IDs are required")
        if definition.guess_limit <= 0:
            raise ValueError("Guess limit must be positive")
        if definition.key in self._definitions:
            raise ValueError(f"Duplicate game definition: {definition.key}")
        self._definitions[definition.key] = definition

    def resolve(self, category_id: str, question_id: str | None = None) -> CategoryDefinition:
        if question_id is not None:
            try:
                return self._definitions[(category_id, question_id)]
            except KeyError as exc:
                raise KeyError(f"Unknown game: {category_id}/{question_id}") from exc
        matches = [definition for definition in self.definitions() if definition.category_id == category_id]
        if len(matches) != 1:
            raise KeyError(f"Category {category_id!r} does not identify exactly one question")
        return matches[0]

    def definitions(self) -> tuple[CategoryDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def catalog(self) -> list[dict]:
        grouped: dict[str, dict] = {}
        for definition in self.definitions():
            question = definition.metadata()
            category = grouped.setdefault(
                definition.category_id,
                {
                    "id": definition.category_id,
                    "name": definition.category_name,
                    "entity_label": definition.entity_label,
                    "questions": [],
                },
            )
            category["questions"].append(question)
        for category in grouped.values():
            # Keep the original one-question category response useful to old clients.
            if len(category["questions"]) == 1:
                first = category["questions"][0]
                category["dimensions"] = first["dimensions"]
                category["guess_limit"] = first["guess_limit"]
        return list(grouped.values())
