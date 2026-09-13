# Country data contract

CSV columns: `code` (unique ISO alpha-3), `name`, `aliases` (pipe-separated), `population` (people), `area_km2` (km²), `gdp_per_capita_usd` (USD per person), `temp_c` (annual mean Celsius), `capital`, `capital_lat`, `capital_lon` (WGS84 degrees), and `provenance` (JSON object describing each source and reference year).

Country eligibility is a completeness rule, not a jurisdiction checklist: code, name, population, land area, GDP per capita, annual mean temperature, capital name, and both capital coordinates must all be present and valid. The importer rejects incomplete, non-finite, non-positive, or out-of-range required values. It does not synthesize estimates or `N/A` feedback, and publication does not require every official territory.

Use a reviewed common reference year for economic metrics and a stated climate reference period. Choose one capital per country and retain it consistently. Imports validate shape, ranges, and unique country codes. The operator publishes a new immutable label. Existing puzzles keep their old dataset version. A scheduled production process should import and review data, then explicitly activate a new version before scheduling future puzzles.

The bundled CSV is only a development fixture. Its values are approximate and must be replaced before public launch.

## Monthly public-data workflow

The fetch job reads World Bank's [country metadata](https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries) for capitals and coordinates, its [indicator API](https://datahelpdesk.worldbank.org/knowledgebase/articles/898581) for population (`SP.POP.TOTL`), land area (`AG.LND.TOTL.K2`) and GDP per capita (`NY.GDP.PCAP.CD`), and the [Climate Change Knowledge Portal](https://climateknowledgeportal.worldbank.org/download-data) CRU TS4.07 1991–2020 mean annual temperature. It selects the newest common indicator year with at least 120 complete places; the latest available year may lag the snapshot month. The live feed returned 196 complete places for reference year 2023 when checked on 2026-09-13. These include some World Bank territories; curate the eligible list and country names before public release. Source attribution should appear in the public UI before launch.

The primary operator workflow is the authenticated `/admin` console described in [admin.md](admin.md). It queues fetches in the durable worker, displays validation and source diagnostics, records review identity, publishes explicitly, previews the immutable schedule, and applies only a matching plan fingerprint.

Run these inside the API container after migrations (substitute the intended month):

```sh
docker compose exec api python -m app.import_countries fetch 2026-10
docker compose exec api python -m app.import_countries publish worldbank-2026-10-<printed-hash>
docker compose exec api python -m app.schedule_challenges 2026-10
```

The first command stages a snapshot and prints its label. Review its country count, source manifest, and spot-check values before publishing. Publishing is explicit; it does not rewrite existing puzzles. The schedule command creates every date in the month, is idempotent, and requires a published snapshot for that exact month. Run this workflow monthly before the month begins, using a cloud cron job for fetch/stage and an operator approval step for publish/schedule. A published snapshot for a month cannot be replaced; corrections require a deliberate migration strategy because puzzles already reference it. Keep snapshots referenced by puzzles even after the 12-month access window expires. At roughly 200 rows per month, storage growth is small; retention should be driven by puzzle references, not a fixed deletion of 12 versions.

The schedule command operates on the global daily calendar. It considers every registered category/question with a published snapshot for that exact month, chooses one game and target deterministically for each date, and stores the result. With only countries registered, every scheduled challenge remains a country challenge.

Target selection uses category/question-specific least-recently-used rotation over stable entity IDs, with recent targets excluded when alternatives exist and a deterministic salted tie-breaker. It continues indefinitely without exhausting a category and adapts when a later snapshot adds, removes, or restores eligible entities.
