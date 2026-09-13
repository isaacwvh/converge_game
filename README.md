# Converge

Daily country deduction game. FastAPI owns the answer, comparisons, anonymous rounds, and immutable dataset snapshots. React is a minimal client.

## Quick start

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Open http://localhost:5173. API docs: http://localhost:8000/docs.

The included country CSV is **demo data**, with approximate values for development. It is not suitable for a public daily game. Replace it with a reviewed, licensed dataset before launch, then run `python -m app.import_countries path/to/countries.csv` inside the API container. Required CSV columns are documented in `docs/data.md`.

The Compose `init` job loads the demo snapshot into an empty database. `POST /api/v1/admin/import` does not exist; imports are operator-only CLI commands. This prevents public users from changing puzzle data.

Anonymous identity uses a first-party HttpOnly cookie. Progress is tied to that browser profile and is lost if its cookies are removed. A daily puzzle is shared by all visitors per UTC date; one round per anonymous browser and category.

## Local tests

From `apps/api`: `pip install -r requirements-dev.txt` then `pytest`.

## Production notes

Use managed PostgreSQL and set `DATABASE_URL`. Run database migrations/initialization as a release step before scaling API replicas; see `docs/deployment.md`. Set `COOKIE_SECURE=true` behind HTTPS and serve the frontend and API from the same site (or configure credentialed CORS and cookie scope deliberately).
