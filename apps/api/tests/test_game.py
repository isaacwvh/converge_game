import pytest

from app.domain import capital_distance_km, direction
from app.import_countries import validate_rows


def test_direction():
    assert direction(20, 10) == "up"
    assert direction(10, 20) == "down"
    assert direction(10.04, 10, 0.1) == "equal"


def test_anonymous_daily_round_and_duplicate(client):
    first = client.get("/api/v1/daily/countries")
    assert first.status_code == 200
    state = first.json()
    assert state["status"] == "playing"
    assert "answer" not in state
    assert client.get("/api/v1/daily/countries").json()["round_id"] == state["round_id"]
    choices = client.get("/api/v1/entities/countries/search?q=Japan").json()
    assert len(choices) == 1
    path = f"/api/v1/rounds/{state['round_id']}/guesses"
    body = {"entity_id": choices[0]["id"]}
    result = client.post(path, json=body, headers={"Idempotency-Key": "first"})
    assert result.status_code == 200
    assert len(result.json()["guesses"]) == 1
    feedback = result.json()["guesses"][0]["feedback"]
    assert feedback["population"]["proximity"] in {"exact", "very-close", "close", "far", "very-far"}
    assert feedback["continent"]["guess_value"] == "Asia"
    assert feedback["capital_direction"]["direction"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "same"}
    retry = client.post(path, json=body, headers={"Idempotency-Key": "first"})
    assert retry.status_code == 200
    assert len(retry.json()["guesses"]) == 1
    if result.json()["status"] == "playing":
        assert client.post(path, json=body).status_code == 409


def test_other_browser_has_separate_round(client):
    first = client.get("/api/v1/daily/countries").json()
    client.cookies.clear()
    second = client.get("/api/v1/daily/countries").json()
    assert first["round_id"] != second["round_id"]
    assert first["date"] == second["date"]


def test_ineligible_country_is_rejected(client):
    state = client.get("/api/v1/daily/countries").json()
    response = client.post(f"/api/v1/rounds/{state['round_id']}/guesses", json={"entity_id": "missing"})
    assert response.status_code == 422


def test_distance_is_zero_for_same_country(client):
    from app.db import SessionLocal
    from app.models import CountryValue
    from sqlalchemy import select
    with SessionLocal() as db:
        country = db.scalar(select(CountryValue))
        assert capital_distance_km(country, country) == 0


def test_practice_round_is_independent(client):
    daily = client.get("/api/v1/daily/countries").json()
    practice = client.post("/api/v1/rounds/practice").json()
    assert practice["round_id"] != daily["round_id"]
    assert practice["date"] is None
    assert "answer" not in practice


def test_country_import_rejects_non_finite_required_metric():
    rows = [
        {
            "code": code,
            "name": f"Country {code}",
            "aliases": "",
            "population": "100",
            "area_km2": "10",
            "gdp_per_capita_usd": "1000",
            "temp_c": "20",
            "capital": f"Capital {code}",
            "capital_lat": "1",
            "capital_lon": "2",
            "provenance": "{}",
        }
        for code in ("AAA", "BBB", "CCC", "DDD", "EEE")
    ]
    rows[0]["gdp_per_capita_usd"] = "nan"
    with pytest.raises(ValueError, match="Invalid positive metric"):
        validate_rows(rows)
