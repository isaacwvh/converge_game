"""Fetch a reproducible country snapshot from World Bank public datasets."""
from collections import Counter
import json
from datetime import datetime, timezone
from math import isfinite

import httpx

COUNTRIES = "https://api.worldbank.org/v2/country"
INDICATORS = {"population": "SP.POP.TOTL", "area_km2": "AG.LND.TOTL.K2", "gdp_per_capita_usd": "NY.GDP.PCAP.CD"}
CLIMATE = "https://cckpapi.worldbank.org/cckp/v1/cru-x0.5_climatology_tas_climatology_annual_1991-2020_mean_historical_cru_ts4.07_mean/all_countries?_format=json"


def _wb_pages(client, url, params):
    page = 1
    records = []
    while True:
        response = client.get(url, params={**params, "page": page})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
            raise ValueError(f"Unexpected World Bank response from {url}")
        records.extend(payload[1])
        if page >= int(payload[0]["pages"]):
            return records
        page += 1


def fetch_country_rows(client=None, min_countries=120):
    """Return CSV-compatible rows and manifest. Fail closed if sources lose coverage."""
    owned = client is None
    if owned:
        client = httpx.Client(timeout=60, follow_redirects=True)
    try:
        countries = _wb_pages(client, COUNTRIES, {"format": "json", "per_page": 500})
        exclusions = Counter()
        eligible = {}
        for country in countries:
            code = country.get("id", "")
            if country.get("region", {}).get("id") == "NA":
                exclusions["aggregate_or_unclassified"] += 1
                continue
            if len(code) != 3 or not code.isalpha() or not str(country.get("name", "")).strip():
                exclusions["invalid_code_or_name"] += 1
                continue
            try:
                lat, lon = float(country["latitude"]), float(country["longitude"])
            except (ValueError, TypeError, KeyError):
                exclusions["missing_capital_coordinates"] += 1
                continue
            if not country.get("capitalCity") or not all(isfinite(value) for value in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                exclusions["invalid_capital_or_coordinates"] += 1
                continue
            eligible[code] = (country, lat, lon)

        current_year = datetime.now(timezone.utc).year
        years = f"{current_year - 7}:{current_year - 1}"
        metrics = {}
        for key, indicator in INDICATORS.items():
            data = _wb_pages(client, f"{COUNTRIES}/all/indicator/{indicator}", {"format": "json", "date": years, "per_page": 20000})
            metrics[key] = {(r["countryiso3code"], int(r["date"])): r["value"] for r in data if r.get("value") is not None and r.get("countryiso3code") in eligible}

        climate_response = client.get(CLIMATE)
        climate_response.raise_for_status()
        climate_payload = climate_response.json()
        if climate_payload.get("metadata", {}).get("status") != "success" or not isinstance(climate_payload.get("data"), dict):
            raise ValueError("Unexpected climate response")
        temperatures = {}
        for code, values in climate_payload["data"].items():
            if isinstance(values, dict):
                candidates = [v for v in values.values() if isinstance(v, (int, float))]
                if candidates:
                    temperatures[code] = candidates[0]

        selected_year = None
        selected_codes = []
        for year in range(current_year - 1, current_year - 8, -1):
            codes = [code for code in eligible if code in temperatures and all((code, year) in data and isfinite(float(data[code, year])) and float(data[code, year]) > 0 for data in metrics.values())]
            if len(codes) >= min_countries:
                selected_year, selected_codes = year, sorted(codes)
                break
        if selected_year is None:
            raise ValueError(f"No common World Bank reference year has {min_countries} complete countries")
        exclusions["missing_common_year_metric_or_temperature"] += len(eligible) - len(selected_codes)

        rows = []
        for code in selected_codes:
            country, lat, lon = eligible[code]
            temp = float(temperatures[code])
            if not isfinite(temp) or not -80 <= temp <= 60:
                exclusions["invalid_temperature"] += 1
                continue
            rows.append({"code": code, "name": country["name"], "aliases": "", "population": str(int(metrics["population"][(code, selected_year)])), "area_km2": str(metrics["area_km2"][(code, selected_year)]), "gdp_per_capita_usd": str(metrics["gdp_per_capita_usd"][(code, selected_year)]), "temp_c": str(temp), "capital": country["capitalCity"], "capital_lat": str(lat), "capital_lon": str(lon), "provenance": json.dumps({"world_bank_indicator_year": selected_year, "climate_period": "1991-2020", "climate_source": "CRU TS4.07 via World Bank CCKP"})})
        if len(rows) < min_countries:
            raise ValueError(f"Insufficient valid countries: {len(rows)}")
        return rows, {
            "sources": {"countries": COUNTRIES, "indicators": INDICATORS, "climate": CLIMATE},
            "indicator_year": selected_year,
            "climate_period": "1991-2020",
            "source_country_count": len(countries),
            "metadata_complete_count": len(eligible),
            "count": len(rows),
            "exclusions": dict(sorted(exclusions.items())),
        }
    finally:
        if owned:
            client.close()
