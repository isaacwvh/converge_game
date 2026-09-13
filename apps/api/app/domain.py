from math import asin, cos, radians, sin, sqrt

from .models import CountryValue



def direction(target: float, guess: float, tolerance: float = 0) -> str:
    difference = float(target) - float(guess)
    if abs(difference) <= tolerance:
        return "equal"
    return "up" if difference > 0 else "down"


def capital_distance_km(a: CountryValue, b: CountryValue) -> int:
    lat1, lon1 = radians(float(a.capital_lat)), radians(float(a.capital_lon))
    lat2, lon2 = radians(float(b.capital_lat)), radians(float(b.capital_lon))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    km = 6371.0088 * 2 * asin(min(1.0, sqrt(h)))
    return int((km + 50) // 100 * 100)


def compare(target: CountryValue, guess: CountryValue) -> dict:
    return {
        "population": {"direction": direction(target.population, guess.population), "guess_value": guess.population},
        "area_km2": {"direction": direction(target.area_km2, guess.area_km2), "guess_value": float(guess.area_km2)},
        "gdp_per_capita_usd": {"direction": direction(target.gdp_per_capita_usd, guess.gdp_per_capita_usd), "guess_value": float(guess.gdp_per_capita_usd)},
        "temp_c": {"direction": direction(target.temp_c, guess.temp_c, 0.1), "guess_value": float(guess.temp_c)},
        "distance_km": capital_distance_km(target, guess),
    }
