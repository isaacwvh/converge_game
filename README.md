# Converge

Daily category-based deduction game. FastAPI owns global daily selection, category-specific comparisons, anonymous rounds, and immutable dataset snapshots. Countries are the only registered playable category; React is a minimal metadata-driven client.

## Quick start

1. Copy `.env.example` to `.env`.
2. For immediate local access, set `ADMIN_LOCAL_LOGIN_ENABLED=true`; configure allowlisted OIDC later as described in [docs/admin.md](docs/admin.md).
3. Run `docker compose up --build`.
4. Open http://localhost:5173. Administrator console: http://localhost:5173/admin. API docs: http://localhost:8000/docs.

The included country CSV is **demo data**, with approximate values for development. It is not suitable for a public daily game. The API now includes an operator-run World Bank import, described in [docs/data.md](docs/data.md). It uses public World Bank indicators and a climate climatology feed; no API key is required.

The Compose `init` job migrates the database and optionally loads the demo snapshot into an empty local database. Live country fetch, review, publication, and global scheduling are authenticated administrator operations. The durable worker performs source fetches; publication and scheduling remain explicit. See the [administrator usage guide](docs/admin.md).

Anonymous identity uses a first-party HttpOnly cookie. Progress is tied to that browser profile and is lost if its cookies are removed. There is one global daily challenge per UTC date and one round per anonymous browser for that challenge. The scheduler chooses a registered category/question and target once, then stores that selection; restarts and different visitors reuse it.

`GET /api/v1/daily` opens today's global challenge. `GET /api/v1/challenges?month=YYYY-MM` lists globally scheduled dates in the rolling 12-calendar-month archive, and `GET /api/v1/challenges/YYYY-MM-DD` opens an exact date. The legacy `/api/v1/daily/countries` and `/api/v1/challenges/countries...` URLs are compatibility aliases for those global endpoints. They do **not** promise that a future selected challenge is a country challenge. `/api/v1/entities/countries/search` remains country-specific; supply `round_id` so search uses that round's pinned snapshot. `/api/v1/stats/countries` remains country-filtered, while `/api/v1/stats` covers all daily categories. Archive entitlement is a future extension; the current archive is open.

## Local tests

From `apps/api`: `pip install -r requirements-dev.txt` then `pytest`.

## Production notes

Use managed PostgreSQL and set `DATABASE_URL`. Run database migrations/initialization as a release step before scaling API replicas; see `docs/deployment.md`. Set `COOKIE_SECURE=true` behind HTTPS and serve the frontend and API from the same site (or configure credentialed CORS and cookie scope deliberately).

## Category engine

`apps/api/app/category.py` defines `CategoryDefinition` and `CategoryRegistry`. A game is explicitly identified by `(category_id, question_id)`. A definition owns its category/question metadata, dimensions and display rules, fixed guess limit, dataset eligibility/search, comparison feedback, and answer serialization. `apps/api/app/service.py` owns the category-neutral lifecycle: active snapshot lookup, persisted global scheduling, anonymous rounds, idempotent guesses, result state, answer disclosure, archive data, and statistics.

Countries implement that contract in `apps/api/app/country_category.py`. Their calculations remain in `apps/api/app/domain.py`; immutable values remain in `CountryValue`; public source fetching and strict complete-record validation remain in `country_sources.py` and `import_countries.py`. `apps/api/app/categories.py` is the explicit composition root. This is a small in-process registry, not runtime plugin discovery.

Each scheduled `Puzzle` stores both category and question IDs plus its dataset and target. `Puzzle.day` is globally unique when non-null, so practice puzzles can coexist while only one challenge can be selected for a UTC date. A scheduled puzzle never follows a later active dataset.

Daily target rotation is category/question neutral and uses stable entity identity across snapshots. It avoids recently used eligible targets, prioritizes never-used entities, then selects the least recently used entity with a deterministic salted tie-breaker. Removed entities leave rotation immediately; new entities enter once without being repeated to catch up.

### Adding animals later

Do not put animal behavior into country branches. Add it as follows:

1. Choose an immutable animal snapshot shape. Add an `AnimalValue` model and Alembic migration if relational columns fit; otherwise implement a category-specific storage table while retaining `DatasetVersion`, `Entity`, and puzzle references.
2. Add `apps/api/app/animal_sources.py` for source adapters. It must return only records complete for the animal question; it must not weaken `import_countries.py` validation.
3. Add `apps/api/app/import_animals.py` for staging, validation, provenance, and explicit publication of `DatasetVersion(category=\"animals\", ...)`. Import and publication remain operator actions.
4. Add `apps/api/app/animal_category.py` implementing `CategoryDefinition`. Give each animal question a stable `question_id`; define dimensions/display metadata, `guess_limit`, eligible IDs, pinned-snapshot search, comparison, and final-answer serialization there.
5. Register the definition explicitly in `apps/api/app/categories.py`. Once an active exact-month animal snapshot exists, the monthly scheduler can select it without any duplicate round or guess lifecycle.
6. Extend `apps/web/src/main.tsx` only for display kinds or answer details not already described by category metadata. Use the category ID from the round for search; do not infer gameplay from a legacy URL.
7. Add adapter tests plus one shared-lifecycle test like `apps/api/tests/test_category_engine.py`. Do not add payments or themed access as part of category registration.

Future themed mode needs a separate entitlement decision and endpoints that enumerate questions within a chosen category. The explicit category/question keys support that later work, but the current daily and archive routes perform no entitlement check beyond the existing open archive window.
