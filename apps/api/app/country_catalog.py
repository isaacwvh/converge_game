"""Curated gameplay metadata joined to countries by stable ISO alpha-3 code.

Geography follows the UN M49 overview. Difficulty is a deliberately reviewed
Converge gameplay classification, not a claim about educational importance.
"""

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CATALOG_VERSION = "2026-09-15-v1"
SOURCE_URL = "https://unstats.un.org/unsd/methodology/m49/overview"
DIFFICULTIES = ("easy", "medium", "expert")
CONTINENTS = frozenset({"Africa", "Asia", "Europe", "North America", "South America", "Oceania"})
CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "country_gameplay.csv"


@dataclass(frozen=True)
class CountryGameplay:
    code: str
    continent: str
    subregion: str
    difficulty: str
    standard_target: bool


def _load_catalog(path: Path = CATALOG_PATH) -> dict[str, CountryGameplay]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        expected = {"code", "continent", "subregion", "difficulty", "standard_target"}
        if set(reader.fieldnames or ()) != expected:
            raise RuntimeError(f"Country gameplay catalog columns must be {sorted(expected)}")
        catalog = {}
        for line, row in enumerate(reader, start=2):
            code = row["code"].strip().upper()
            continent = row["continent"].strip()
            subregion = row["subregion"].strip()
            difficulty = row["difficulty"].strip()
            raw_standard = row["standard_target"].strip().lower()
            if len(code) != 3 or not code.isalpha():
                raise RuntimeError(f"Invalid country code at catalog line {line}: {code!r}")
            if code in catalog:
                raise RuntimeError(f"Duplicate country code in gameplay catalog: {code}")
            if difficulty not in DIFFICULTIES:
                raise RuntimeError(f"Invalid difficulty for {code}: {difficulty!r}")
            if raw_standard not in {"true", "false"}:
                raise RuntimeError(f"Invalid standard_target for {code}: {raw_standard!r}")
            standard_target = raw_standard == "true"
            if standard_target and (continent not in CONTINENTS or not subregion):
                raise RuntimeError(f"Standard target {code} requires continent and subregion")
            if standard_target != (difficulty in {"easy", "medium"}):
                raise RuntimeError(f"Standard target policy and difficulty disagree for {code}")
            catalog[code] = CountryGameplay(code, continent, subregion, difficulty, standard_target)
    if not catalog:
        raise RuntimeError("Country gameplay catalog is empty")
    return catalog


COUNTRY_GAMEPLAY = _load_catalog()
STANDARD_TARGET_CODES = frozenset(
    code for code, profile in COUNTRY_GAMEPLAY.items() if profile.standard_target
)


def profile_for(code: str) -> CountryGameplay | None:
    return COUNTRY_GAMEPLAY.get(code.strip().upper())


def difficulty_counts(codes: list[str]) -> dict[str, int]:
    counts = Counter(
        profile.difficulty if (profile := profile_for(code)) is not None else "unclassified"
        for code in codes
    )
    return {tier: counts[tier] for tier in (*DIFFICULTIES, "unclassified")}
