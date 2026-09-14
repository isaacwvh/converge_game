from sqlalchemy import select

from app.country_catalog import COUNTRY_GAMEPLAY, STANDARD_TARGET_CODES, profile_for
from app.country_category import CountriesCategory
from app.db import SessionLocal
from app.domain import capital_direction, compare, ratio_proximity, temperature_proximity
from app.models import AnonymousPlayer, CountryValue, DatasetVersion, Entity, Guess, Puzzle, Round
from app.service import serialize_round


def country_value(code: str, latitude: float = 0, longitude: float = 0) -> CountryValue:
    entity = Entity(id=f"entity-{code}", category="countries", code=code, name=code, aliases=[])
    return CountryValue(
        dataset_id="dataset",
        entity_id=entity.id,
        entity=entity,
        population=1_000_000,
        area_km2=100_000,
        gdp_per_capita_usd=10_000,
        temp_c=20,
        capital=code,
        capital_lat=latitude,
        capital_lon=longitude,
        provenance={},
    )


def add_country(db, dataset_id: str, code: str, name: str) -> Entity:
    entity = Entity(category="countries", code=code, name=name, aliases=[])
    db.add(entity)
    db.flush()
    db.add(
        CountryValue(
            dataset_id=dataset_id,
            entity_id=entity.id,
            population=100_000,
            area_km2=1_000,
            gdp_per_capita_usd=5_000,
            temp_c=22,
            capital=f"{name} City",
            capital_lat=1,
            capital_lon=2,
            provenance={},
        )
    )
    return entity


def test_catalog_has_explicit_standard_and_expert_policy():
    assert len(COUNTRY_GAMEPLAY) >= 249
    assert profile_for("USA").difficulty == "easy"
    assert profile_for("CIV").difficulty == "medium"
    assert profile_for("ABW").difficulty == "expert"
    assert "USA" in STANDARD_TARGET_CODES
    assert "ABW" not in STANDARD_TARGET_CODES


def test_expert_and_unknown_countries_remain_searchable_but_not_targets(client):
    category = CountriesCategory()
    with SessionLocal() as db:
        dataset = db.scalar(select(DatasetVersion).where(DatasetVersion.label == "demo-v1"))
        aruba = add_country(db, dataset.id, "ABW", "Aruba")
        unknown = add_country(db, dataset.id, "ZZZ", "Zedland")
        db.commit()

        targets = set(category.target_entity_ids(db, dataset.id))
        assert aruba.id not in targets
        assert unknown.id not in targets
        assert category.search_entities(db, dataset.id, "Aruba")[0].id == aruba.id
        assert category.search_entities(db, dataset.id, "Zedland")[0].id == unknown.id

        diagnostics = category.admin_dataset_diagnostics(db, dataset.id)
        assert diagnostics["target_count"] == 10
        assert diagnostics["searchable_count"] == 12
        assert diagnostics["difficulty_counts"]["expert"] == 1
        answer = category.serialize_answer(db, dataset.id, aruba.id)
        assert answer["name"] == "Aruba"
        assert answer["difficulty"] == "expert"


def test_successful_guess_reveals_the_target_difficulty(client):
    state = client.get("/api/v1/daily").json()
    with SessionLocal() as db:
        round_ = db.get(Round, state["round_id"])
        puzzle = db.get(Puzzle, round_.puzzle_id)
        target_id = puzzle.target_id
    result = client.post(
        f"/api/v1/rounds/{state['round_id']}/guesses",
        json={"entity_id": target_id},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "won"
    assert result.json()["answer"]["difficulty"] in {"easy", "medium"}



def test_direction_proximity_and_continent_feedback():
    origin = country_value("USA")
    east = country_value("JPN", longitude=10)
    west = country_value("BRA", longitude=-10)
    across_date_line = country_value("FJI", longitude=-170)
    near_date_line = country_value("NZL", longitude=170)

    assert capital_direction(east, origin) == {"direction": "E", "arrow": "→"}
    assert capital_direction(west, origin) == {"direction": "W", "arrow": "←"}
    assert capital_direction(across_date_line, near_date_line) == {"direction": "E", "arrow": "→"}
    assert ratio_proximity(100, 101) == "exact"
    assert ratio_proximity(100, 120) == "close"
    assert ratio_proximity(100, 200) == "very-far"
    assert temperature_proximity(-2, -1.5) == "very-close"
    assert temperature_proximity(10, 18) == "very-far"

    feedback = compare(east, origin, profile_for("JPN"), profile_for("USA"))
    assert feedback["continent"] == {"guess_value": "North America", "match": False}
    assert feedback["capital_direction"] == {"direction": "E", "arrow": "→"}
    assert feedback["population"]["proximity"] == "exact"


def test_subregion_hint_unlocks_after_five_incorrect_guesses(client):
    category = CountriesCategory()
    with SessionLocal() as db:
        dataset = db.scalar(select(DatasetVersion).where(DatasetVersion.label == "demo-v1"))
        target = db.scalar(select(Entity).where(Entity.code == "JPN"))
        guesses = list(db.scalars(select(Entity).where(Entity.code.in_(["USA", "BRA", "DEU", "AUS", "IND"])).order_by(Entity.code)))
        player = AnonymousPlayer()
        db.add(player)
        db.flush()
        puzzle = Puzzle(
            category="countries",
            question_id="identify-country",
            day=None,
            dataset_id=dataset.id,
            target_id=target.id,
        )
        db.add(puzzle)
        db.flush()
        round_ = Round(player_id=player.id, puzzle_id=puzzle.id)
        db.add(round_)
        db.flush()
        for turn, entity in enumerate(guesses[:4], start=1):
            db.add(
                Guess(
                    round_id=round_.id,
                    turn=turn,
                    entity_id=entity.id,
                    feedback={"population": {"direction": "up", "guess_value": 1}},
                )
            )
        db.commit()
        assert serialize_round(db, round_, puzzle)["hints"] == []

        db.add(
            Guess(
                round_id=round_.id,
                turn=5,
                entity_id=guesses[4].id,
                feedback={"population": {"direction": "up", "guess_value": 1}},
            )
        )
        db.commit()
        state = serialize_round(db, round_, puzzle)
        assert state["hints"] == [
            {
                "id": "target-subregion",
                "label": "Region hint",
                "value": "Eastern Asia",
                "unlocked_at_guess": 5,
            }
        ]
        assert "proximity" not in state["guesses"][0]["feedback"]["population"]
