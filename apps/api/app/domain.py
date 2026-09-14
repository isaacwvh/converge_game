from math import asin, atan2, cos, degrees, radians, sin, sqrt

from .country_catalog import CountryGameplay
from .models import CountryValue

PROXIMITY_ORDER = ("exact", "very-close", "close", "far", "very-far")
COMPASS_POINTS = (
    ("N", "↑"),
    ("NE", "↗"),
    ("E", "→"),
    ("SE", "↘"),
    ("S", "↓"),
    ("SW", "↙"),
    ("W", "←"),
    ("NW", "↖"),
)


def direction(target: float, guess: float, tolerance: float = 0) -> str:
    difference = float(target) - float(guess)
    if abs(difference) <= tolerance:
        return "equal"
    return "up" if difference > 0 else "down"


def ratio_proximity(target: float, guess: float) -> str:
    low, high = sorted((float(target), float(guess)))
    if low <= 0:
        raise ValueError("Ratio proximity requires positive values")
    ratio = high / low
    for label, maximum in zip(PROXIMITY_ORDER, (1.02, 1.10, 1.25, 1.60, float("inf"))):
        if ratio <= maximum:
            return label
    raise AssertionError("Unreachable proximity ratio")


def temperature_proximity(target: float, guess: float) -> str:
    difference = abs(float(target) - float(guess))
    for label, maximum in zip(PROXIMITY_ORDER, (0.1, 1.0, 3.0, 7.0, float("inf"))):
        if difference <= maximum:
            return label
    raise AssertionError("Unreachable temperature difference")


def capital_distance_km(a: CountryValue, b: CountryValue) -> int:
    lat1, lon1 = radians(float(a.capital_lat)), radians(float(a.capital_lon))
    lat2, lon2 = radians(float(b.capital_lat)), radians(float(b.capital_lon))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    km = 6371.0088 * 2 * asin(min(1.0, sqrt(h)))
    return int((km + 50) // 100 * 100)


def capital_direction(target: CountryValue, guess: CountryValue) -> dict[str, str]:
    target_lat = radians(float(target.capital_lat))
    guess_lat = radians(float(guess.capital_lat))
    longitude_delta = radians(float(target.capital_lon) - float(guess.capital_lon))
    x = sin(longitude_delta) * cos(target_lat)
    y = cos(guess_lat) * sin(target_lat) - sin(guess_lat) * cos(target_lat) * cos(longitude_delta)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return {"direction": "same", "arrow": "✓"}
    bearing = (degrees(atan2(x, y)) + 360) % 360
    direction_name, arrow = COMPASS_POINTS[int((bearing + 22.5) // 45) % len(COMPASS_POINTS)]
    return {"direction": direction_name, "arrow": arrow}


def _direction_feedback(target: float, guess: float) -> dict:
    return {
        "direction": direction(target, guess),
        "guess_value": guess,
        "proximity": ratio_proximity(target, guess),
    }


def compare(
    target: CountryValue,
    guess: CountryValue,
    target_profile: CountryGameplay | None = None,
    guess_profile: CountryGameplay | None = None,
) -> dict:
    feedback = {
        "population": _direction_feedback(target.population, guess.population),
        "area_km2": _direction_feedback(float(target.area_km2), float(guess.area_km2)),
        "gdp_per_capita_usd": _direction_feedback(
            float(target.gdp_per_capita_usd),
            float(guess.gdp_per_capita_usd),
        ),
        "temp_c": {
            "direction": direction(target.temp_c, guess.temp_c, 0.1),
            "guess_value": float(guess.temp_c),
            "proximity": temperature_proximity(target.temp_c, guess.temp_c),
        },
        "distance_km": capital_distance_km(target, guess),
        "capital_direction": capital_direction(target, guess),
    }
    if target_profile is not None and guess_profile is not None:
        feedback["continent"] = {
            "guess_value": guess_profile.continent,
            "match": target_profile.continent == guess_profile.continent,
        }
    return feedback
