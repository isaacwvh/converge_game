# Deployment

Local: `docker compose up --build`. The demo dataset seeds only when the database has no dataset.

For production, build the API and web images in CI. Use a managed PostgreSQL database and set `DATABASE_URL` to its TLS-enabled connection string. Configure `COOKIE_SECURE=true`, a strong random `DAILY_SALT`, and the actual `FRONTEND_ORIGIN`. Put both applications behind HTTPS on the same site where possible. Keep the API container private except through the reverse proxy. Back up and test restore of PostgreSQL.

The `init` job applies Alembic migrations and seeds demo data only when `SEED_DEMO=true` and the database is empty. Set `SEED_DEMO=false` in production. Run `alembic upgrade head` once per release before deploying new API replicas; import a reviewed country snapshot separately. Do not run migrations in each API instance.

Run country imports as one-off jobs using the API image. Never run imports in every API replica. Previously created daily puzzles retain their dataset version and target. Serve the React build from a CDN or the included web image. Scale API replicas horizontally; all round state is in PostgreSQL.
