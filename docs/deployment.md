# Deployment

Local: configure allowlisted OIDC as described in [admin.md](admin.md), then run `docker compose up --build`. Compose uses its own PostgreSQL `pgdata` volume and a dedicated operator worker. The demo dataset seeds only when `SEED_DEMO=true` and the database has no dataset.

Use the same built application code in every environment, but use separate databases, deployment identities, OIDC clients, salts, and secrets. Required deployment settings are `APP_ENV`, `DEPLOYMENT_ID`, `DATABASE_URL`, `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`, `DAILY_SALT`, `ADMIN_SESSION_SECRET`, the four `ADMIN_OIDC_*` values, and `COOKIE_SECURE`.

The first initialization stores `APP_ENV` and `DEPLOYMENT_ID` in the database. API, init, and worker processes refuse to operate if their configuration does not match that marker. This is the guard against a local process accidentally operating a production database.

For production, build the API and web images in CI. Use a managed PostgreSQL database with a TLS-enabled connection string. Set `APP_ENV=production`, a unique `DEPLOYMENT_ID`, `SEED_DEMO=false`, `COOKIE_SECURE=true`, a strong random `DAILY_SALT`, a strong independent `ADMIN_SESSION_SECRET`, production OIDC credentials/subjects, and the actual HTTPS origins. Production startup rejects unsafe settings, and production publication/scheduling rejects demo datasets.

Run the `init` job once per release before API and worker replicas. It validates production settings, applies Alembic migrations, establishes the database identity, and seeds demo data only when explicitly allowed. Keep the API and worker private except through intended ingress and operations paths. Back up PostgreSQL and test restoration.

Run exactly one or a safely horizontally coordinated set of operator workers. Jobs are claimed with database row locking; stale running jobs can be reclaimed after 30 minutes. Do not run ad hoc imports in every API replica. Previously created daily puzzles retain their category, question, dataset version, and target.

The administrator console performs fetch/stage, review, publication, schedule preview, and immutable application. Production mutations require a recent OIDC login and exact confirmation text. Serve the React build from a CDN or included web image. All player, administrator job, audit, and schedule state resides in PostgreSQL.
