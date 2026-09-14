from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .category import CategoryDefinition
from .country_catalog import CATALOG_VERSION, SOURCE_URL, STANDARD_TARGET_CODES, difficulty_counts, profile_for
from .domain import compare
from .models import CountryValue, Entity


class CountriesCategory(CategoryDefinition):
    category_id = "countries"
    category_name = "Countries"
    question_id = "identify-country"
    question_name = "Mystery country"
    entity_label = "Country"
    prompt = "Find the mystery country."
    guess_limit = 8
    dimensions = (
        {
            "id": "continent",
            "label": "Continent",
            "feedback": "match",
        },
        {
            "id": "population",
            "label": "Population",
            "feedback": "direction",
            "display": {"style": "compact", "maximum_fraction_digits": 1},
        },
        {
            "id": "area_km2",
            "label": "Area",
            "feedback": "direction",
            "display": {"style": "number", "maximum_fraction_digits": 0, "suffix": " km²"},
        },
        {
            "id": "gdp_per_capita_usd",
            "label": "GDP/person",
            "feedback": "direction",
            "display": {"style": "currency", "currency": "USD", "maximum_fraction_digits": 0},
        },
        {
            "id": "temp_c",
            "label": "Temp.",
            "feedback": "direction",
            "display": {"style": "number", "minimum_fraction_digits": 1, "maximum_fraction_digits": 1, "suffix": "°C"},
        },
        {
            "id": "distance_km",
            "label": "Distance",
            "feedback": "distance",
            "display": {"style": "number", "maximum_fraction_digits": 0, "suffix": " km"},
            "companion_feedback": "capital_direction",
        },
    )
    rules = {
        "arrows": "Arrows compare the answer with your guess; labels show how close the values are",
        "continent": "Continent shows whether your guess and the answer share a continent",
        "distance": "Capital distance is rounded to 100 km; the compass points from your guess toward the answer",
        "hints": "The answer's subregion unlocks after five incorrect guesses",
        "timezone": "UTC",
    }

    def target_entity_ids(self, db: Session, dataset_id: str) -> list[str]:
        return list(
            db.scalars(
                select(CountryValue.entity_id)
                .join(Entity, Entity.id == CountryValue.entity_id)
                .where(
                    CountryValue.dataset_id == dataset_id,
                    Entity.category == self.category_id,
                    Entity.code.in_(STANDARD_TARGET_CODES),
                )
                .order_by(CountryValue.entity_id)
            )
        )

    def search_entities(self, db: Session, dataset_id: str, query: str, limit: int = 25) -> list[Entity]:
        entities = db.scalars(
            select(Entity)
            .join(CountryValue, CountryValue.entity_id == Entity.id)
            .where(CountryValue.dataset_id == dataset_id, Entity.category == self.category_id)
            .order_by(Entity.name)
        ).all()
        needle = query.strip().casefold()
        return [
            entity
            for entity in entities
            if needle in entity.name.casefold() or any(needle in alias.casefold() for alias in entity.aliases)
        ][:limit]

    def admin_dataset_diagnostics(self, db: Session, dataset_id: str) -> dict:
        codes = list(
            db.scalars(
                select(Entity.code)
                .join(CountryValue, CountryValue.entity_id == Entity.id)
                .where(CountryValue.dataset_id == dataset_id, Entity.category == self.category_id)
                .order_by(Entity.code)
            )
        )
        counts = difficulty_counts(codes)
        target_count = sum(counts[tier] for tier in ("easy", "medium"))
        return {
            "eligible_count": target_count,
            "target_count": target_count,
            "searchable_count": len(codes),
            "difficulty_counts": counts,
            "difficulty_catalog_version": CATALOG_VERSION,
            "geography_source": SOURCE_URL,
            "unclassified_codes": sorted(code for code in codes if profile_for(code) is None),
        }


    def admin_dataset_rows(self, db: Session, dataset_id: str) -> list[dict]:
        values = db.scalars(
            select(CountryValue)
            .join(Entity, Entity.id == CountryValue.entity_id)
            .where(CountryValue.dataset_id == dataset_id, Entity.category == self.category_id)
            .order_by(Entity.name)
        ).all()
        return [
            {
                "entity_id": value.entity.id,
                "code": value.entity.code,
                "name": value.entity.name,
                "continent": profile.continent if (profile := profile_for(value.entity.code)) else "Unclassified",
                "subregion": profile.subregion if profile else "Unclassified",
                "difficulty": profile.difficulty if profile else "unclassified",
                "standard_target": profile.standard_target if profile else False,
                "population": value.population,
                "area_km2": float(value.area_km2),
                "gdp_per_capita_usd": float(value.gdp_per_capita_usd),
                "temp_c": float(value.temp_c),
                "capital": value.capital,
                "capital_lat": float(value.capital_lat),
                "capital_lon": float(value.capital_lon),
                "provenance": value.provenance,
            }
            for value in values
        ]

    def _value_for(self, db: Session, dataset_id: str, entity_id: str) -> CountryValue:
        value = db.get(CountryValue, (dataset_id, entity_id))
        entity = db.get(Entity, entity_id)
        if value is None or entity is None or entity.category != self.category_id:
            raise HTTPException(422, "Country is not eligible in this puzzle")
        return value

    def compare(self, db: Session, dataset_id: str, target_id: str, guess_id: str) -> dict:
        target = self._value_for(db, dataset_id, target_id)
        guess = self._value_for(db, dataset_id, guess_id)
        return compare(
            target,
            guess,
            profile_for(target.entity.code),
            profile_for(guess.entity.code),
        )

    def build_hints(
        self, db: Session, dataset_id: str, target_id: str, guess_count: int, round_status: str
    ) -> list[dict]:
        if round_status != "playing" or guess_count < 5:
            return []
        value = self._value_for(db, dataset_id, target_id)
        profile = profile_for(value.entity.code)
        if profile is None or not profile.subregion:
            return []
        return [
            {
                "id": "target-subregion",
                "label": "Region hint",
                "value": profile.subregion,
                "unlocked_at_guess": 5,
            }
        ]


    def serialize_answer(self, db: Session, dataset_id: str, target_id: str) -> dict:
        value = self._value_for(db, dataset_id, target_id)
        entity = value.entity
        profile = profile_for(entity.code)
        return {
            "code": entity.code,
            "difficulty": profile.difficulty if profile else "unclassified",
            "entity_id": entity.id,
            "name": entity.name,
            "capital": value.capital,
            "population": value.population,
            "area_km2": float(value.area_km2),
            "gdp_per_capita_usd": float(value.gdp_per_capita_usd),
            "temp_c": float(value.temp_c),
            "provenance": value.provenance,
        }
