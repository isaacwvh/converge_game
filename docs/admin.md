# Converge administrator guide

The administrator console is available at `/admin`. It operates the database configured for that deployment only. It does not copy snapshots, schedules, players, or rounds between local, staging, and production environments.

## Configure allowlisted OIDC

Register Converge as a confidential web application with an OpenID Connect provider. Configure this redirect URI exactly for local use:

```text
http://localhost:5173/api/v1/admin/auth/callback
```

Set these values in `.env`:

```dotenv
APP_ENV=local
DEPLOYMENT_ID=converge-local
PUBLIC_BASE_URL=http://localhost:5173
ADMIN_SESSION_SECRET=<at-least-32-random-characters>
ADMIN_OIDC_DISCOVERY_URL=https://provider.example/.well-known/openid-configuration
ADMIN_OIDC_CLIENT_ID=<client-id>
ADMIN_OIDC_CLIENT_SECRET=<client-secret>
ADMIN_OIDC_ALLOWED_SUBJECTS=<oidc-subject-id>[,<second-subject-id>]
```

`ADMIN_OIDC_ALLOWED_SUBJECTS` contains stable OIDC `sub` claim values, not display names. The configured issuer and subject together identify an administrator. Authentication by the provider is not enough unless the returned subject is in this allowlist.

Restart after changing authentication configuration:

```sh
docker compose up --build -d
```

Open `http://localhost:5173/admin` and select **Sign in with OIDC**. The API validates the authorization response and ID token through the provider metadata, checks the subject allowlist, creates an eight-hour signed HttpOnly session, and issues a CSRF token. Every administrator API validates the session; mutations also validate the CSRF token.

Production publication, fetch, schedule, and target-reveal actions require OIDC authentication within the preceding five minutes. The console redirects through OIDC with `prompt=login` when reauthentication is stale.

## Temporary local administrator login

OIDC can remain unconfigured during local development. Set this explicit development-only switch in the root `.env`:

```dotenv
APP_ENV=local
ADMIN_LOCAL_LOGIN_ENABLED=true
```

Restart with `docker compose up --build -d`, open `http://localhost:5173/admin`, and select **Continue as local administrator**. This creates the same signed administrator session and CSRF protection used by the OIDC path, under the audited subject `local-development-admin`.

The switch works only when `APP_ENV=local`. Production refuses to start if it is enabled, and staging never accepts it. Anyone who can reach the locally exposed application can select this button, so do not expose the development ports to an untrusted network.

When OIDC is ready, configure the OIDC values described above and change:

```dotenv
ADMIN_LOCAL_LOGIN_ENABLED=false
```

Restart the stack. Existing local-login sessions are rejected immediately, and **Sign in with OIDC** becomes the access path. No database, API, or frontend migration is required.


## Understand the environment banner

The banner is always visible after login and shows:

- `APP_ENV`: local, staging, or production
- `DEPLOYMENT_ID`: stable identity expected by this database
- database driver, host, and database name

The `installation` database row permanently records the environment and deployment identity on first initialization. API and worker startup fail if configuration points at a database marked for a different environment or deployment. This prevents a local process with production credentials from operating silently.

Local Compose uses its own `pgdata` volume. Local imports and schedules never appear in production unless a production database is deliberately copied or configured. Use a unique database, deployment ID, daily salt, OIDC client, and session secret for every environment.

Production additionally refuses to start when:

- `SEED_DEMO=true`
- the development daily salt is configured
- cookies are not secure
- the admin session secret is weak/default
- allowlisted OIDC is incomplete

Production also refuses to publish or schedule a demo dataset.

## Dashboard overview

The top cards show:

- whether today's UTC challenge is scheduled
- scheduled-day coverage for the current month
- staged and active dataset counts
- player, round, and guess totals

**Needs attention** lists actionable safety and readiness warnings, including demo data, development salt, missing OIDC configuration, and `SEED_DEMO` status.

The **Categories and questions** section is generated from the category registry. It shows each stable category/question ID, guess limit, and feedback dimensions. Only Countries appears until another complete category implementation is explicitly registered.

## Import the first live country snapshot

The console implements a deliberate five-step workflow. Fetching does not publish or schedule anything.

### 1. Fetch

In **Country snapshots**:

1. Choose the snapshot's effective month.
2. Select **Fetch live snapshot**.
3. Watch **Operator jobs** until `countries.fetch` becomes `succeeded`.

The API only queues the request. The dedicated `worker` Compose service downloads World Bank metadata, indicators, and climate data, applies the strict complete-record filter, fingerprints the result, and stages an inactive immutable dataset.

Only records with valid code, name, population, land area, GDP per capita, annual mean temperature, capital name, and capital coordinates are retained. The importer does not create estimates or `N/A` values.

A failed job remains visible with its error. Correct the source/configuration issue and queue a new job; failed jobs do not partially publish data.

### 2. Inspect

Select the staged snapshot label. The review view shows:

- source manifest and fingerprint
- source and eligible counts
- exclusion reasons
- indicator year and climate period
- every eligible country and gameplay value
- countries added, removed, or renamed relative to the previous snapshot

Review source coverage and spot-check values. Closing the view does not change state.

### 3. Review

Select **Review** only after inspection. This records the administrator subject and UTC review time. Review does not make the snapshot playable.

### 4. Publish

Select **Publish**. Publication is allowed only when:

- the snapshot was reviewed
- it has an effective month
- no other active snapshot exists for the same category/month
- production safety rules permit the dataset

Publication marks the immutable snapshot active. It does not alter existing puzzles. Existing puzzles retain their original dataset IDs and answers.

### 5. Preview and schedule

In **Global daily schedule**:

1. Choose the month.
2. Select **Preview month**.
3. Inspect preserved dates, proposed dates, datasets, category/question distribution, repeat count, and policy version.
4. Select **Schedule N days** only when the plan is correct.

Preview is read-only and hides targets. It returns a fingerprint covering the scheduler policy, registry, eligible entity IDs, active datasets, and existing scheduled dates. Apply recomputes the plan and rejects a stale fingerprint, forcing a new preview if anything changed.

Apply creates only missing dates. Existing puzzles are immutable and preserved. Concurrent schedulers are also constrained by the database's one-puzzle-per-day uniqueness rule.

## Balanced target rotation

`balanced-least-used-v1` is category/question neutral. For the selected daily category/question it:

1. Retrieves eligible stable entity IDs from that question's active snapshot.
2. Excludes recently used eligible targets when alternatives exist.
3. Prioritizes eligible entities that have never appeared.
4. Otherwise selects the least recently used eligible entity.
5. Uses the salted date hash only to break ties deterministically.

With a stable set of 120 countries, every country appears before one repeats. Play continues indefinitely through balanced rotations.

When data changes:

- removed entities immediately leave the candidate set
- a newly eligible entity appears once, then joins normal least-recently-used rotation rather than being repeated to catch up with historical counts
- reintroduced entities retain their stable `Entity.id` and historical last-use position
- each category/question has isolated history, so adding a category cannot corrupt another category's target rotation

The daily category/question itself is still selected deterministically and equally across registered question definitions. The selected puzzle is stored, so later registry or dataset changes never rewrite it.

## Schedule calendar

Each calendar cell shows:

- UTC day
- category and question
- pinned dataset label
- `planned` or `scheduled` state

Targets are hidden by default. **Reveal** is available only for stored dates, requires a confirmation, and creates an audit record. Do not reveal upcoming targets during normal operation.

## Operator jobs and audit trail

The worker persists jobs in `operator_jobs`. Queued/running work survives API restarts, and a worker can reclaim work left running for more than 30 minutes after a crash.

The audit trail records:

- OIDC login/logout
- job requests and outcomes
- dataset review
- dataset publication
- schedule application
- target reveal

Entries include the administrator subject, UTC timestamp, action, and relevant IDs. There are no destructive reschedule or dataset-delete actions in the console.

## Local scheduling safety

A local schedule modifies only the local PostgreSQL volume. Verify the banner says `LOCAL` and `converge-local` before importing or scheduling.

To start with a completely empty local database, the following deletes all local Compose database state and cannot be undone:

```sh
docker compose down -v
docker compose up --build -d
```

With `SEED_DEMO=true`, the new empty local database receives `demo-v1`. That fixture supports the daily page but is not accepted as an exact-month live scheduling snapshot. The live workflow above stages a separate World Bank snapshot and requires review/publication before scheduling.

Set `SEED_DEMO=false` if the local environment should begin with no dataset at all.

## Production confirmations

In production the console asks for exact confirmation text:

```text
PRODUCTION FETCH YYYY-MM
PRODUCTION PUBLISH <dataset-label>
PRODUCTION SCHEDULE YYYY-MM
```

Cancellation leaves state unchanged. A recent OIDC login and matching text are both required; frontend prompts are convenience only, because the API independently enforces both checks.

## Troubleshooting

### OIDC is not configured

All four OIDC settings and at least one allowed subject are required. Restart the API after changing `.env`.

### Redirect URI mismatch

The provider redirect URI must equal `PUBLIC_BASE_URL` plus `/api/v1/admin/auth/callback` exactly, including scheme and port.

### Authenticated identity is not an administrator

The verified token's `sub` is not in `ADMIN_OIDC_ALLOWED_SUBJECTS`. Add the stable subject deliberately; do not allowlist by an unverified display name.

### Fetch remains queued

Confirm the `worker` service is running:

```sh
docker compose ps
```

Inspect worker logs without re-running the import. The existing job remains authoritative.

### Snapshot cannot be published

The table displays the blocker: review missing, effective month missing, already active, or another active snapshot for that category/month.

### Month cannot be previewed

At least one registered category/question needs an active exact-month snapshot with eligible entities.

### Schedule state changed after preview

Another action changed datasets, eligibility, registry state, or scheduled dates. Preview again and review the replacement plan.
