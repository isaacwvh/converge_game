# Converge administrator guide

The administrator console is available at `/admin`. It operates the database configured for that deployment only. It does not copy snapshots, schedules, players, or rounds between local, staging, and production environments.

## Configure administrator password

Set a long random administrator password and an independent session-signing secret in `.env`:

```dotenv
APP_ENV=local
DEPLOYMENT_ID=converge-local
ADMIN_PASSWORD=<long-random-password>
ADMIN_SESSION_SECRET=<at-least-32-random-characters>
```

Restart after changing authentication configuration:

```sh
docker compose up --build -d
```

Open `http://localhost:5173/admin` and enter `ADMIN_PASSWORD`. A successful login creates an eight-hour signed HttpOnly session and a CSRF token. Every administrator API validates the session; mutations also validate the CSRF token.

The password is shared, so audit records identify the fixed subject `password-admin`, not an individual person. Use HTTPS with `COOKIE_SECURE=true` in production. When rotating the password, rotate `ADMIN_SESSION_SECRET` at the same time to invalidate existing sessions.


## Understand the environment banner

The banner is always visible after login and shows:

- `APP_ENV`: local, staging, or production
- `DEPLOYMENT_ID`: stable identity expected by this database
- database driver, host, and database name

The `installation` database row permanently records the environment and deployment identity on first initialization. API and worker startup fail if configuration points at a database marked for a different environment or deployment. This prevents a local process with production credentials from operating silently.

Local Compose uses its own `pgdata` volume. Local imports and schedules never appear in production unless a production database is deliberately copied or configured. Use a unique database, deployment ID, daily salt, administrator password, and session secret for every environment.

Production additionally refuses to start when:

- `SEED_DEMO=true`
- the development daily salt is configured
- cookies are not secure
- the admin session secret is weak/default
- the administrator password is weak/default

Production also refuses to publish or schedule a demo dataset.

## Dashboard overview

The top cards show:

- whether today's UTC challenge is scheduled
- scheduled-day coverage for the current month
- staged and active dataset counts
- player, round, and guess totals

**Needs attention** lists actionable safety and readiness warnings, including demo data, the development salt, and `SEED_DEMO` status.

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
- source, searchable, and standard-target counts
- easy, medium, expert, and unclassified counts
- gameplay catalog version
- exclusion reasons
- indicator year and climate period
- every searchable country, its gameplay values, geography, difficulty, and target status
- countries added, removed, or renamed relative to the previous snapshot

Review source coverage, confirm that `unclassified` is zero, and spot-check values. An unclassified country is retained and searchable but excluded from standard target selection. Closing the view does not change state.

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

## Country difficulty and guidance

Country measurements remain in immutable World Bank snapshots. A separate version-controlled gameplay catalog joins them by stable ISO alpha-3 code. Geography follows the [United Nations M49 classification](https://unstats.un.org/unsd/methodology/m49/overview); difficulty is a curated Converge recognizability classification:

- `easy`: globally familiar countries and strong geographic anchors
- `medium`: countries an average geography player can reasonably place with feedback
- `expert`: obscure sovereign states, microstates, island states, territories, and dependencies

Only easy and medium entries marked as standard targets can be selected for a newly scheduled standard daily puzzle. Expert and unclassified entries remain stored and searchable guesses, preserving the complete snapshot for future expert or themed modes. Classification does not change snapshot facts.

The administrator does not assign tiers during routine imports. Review the displayed distribution and investigate only unclassified codes. Classification changes are reviewed source changes to `apps/api/data/country_gameplay.csv`, not mutable dashboard actions.

Gameplay now provides:

- same/different continent feedback for each guess
- higher/lower plus exact, very close, close, far, or very far proximity
- capital-to-capital distance plus an eight-way compass direction toward the answer
- an automatic target-subregion hint after five incorrect guesses
- the target's difficulty tier when a round is won or its answer is otherwise disclosed

No database migration or snapshot republish is required. Existing scheduled puzzles keep their pinned targets, including expert targets scheduled before this policy. The enhanced feedback applies when those puzzles are played. The standard target restriction applies only to future unscheduled puzzles.

## Balanced target rotation

`balanced-standard-lru-v2` is category/question neutral. For the selected daily category/question it:

1. Retrieves standard target IDs allowed by that question from its active snapshot.
2. Excludes recently used eligible targets when alternatives exist.
3. Prioritizes eligible entities that have never appeared.
4. Otherwise selects the least recently used eligible entity.
5. Uses the salted date hash only to break ties deterministically.

Every currently eligible standard target appears before one repeats when the eligible set and history permit. Play continues indefinitely through balanced rotations.

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

Targets are hidden by default. **Reveal** is available only for stored dates, requires a confirmation, creates an audit record, and returns the target's difficulty tier. Do not reveal upcoming targets during normal operation.

## Operator jobs and audit trail

The worker persists jobs in `operator_jobs`. Queued/running work survives API restarts, and a worker can reclaim work left running for more than 30 minutes after a crash.

The audit trail records:

- password login/logout
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

Cancellation leaves state unchanged. An authenticated administrator session and matching text are both required; frontend prompts are convenience only, because the API independently enforces both checks.

## Troubleshooting

### Password login fails

Confirm `ADMIN_PASSWORD` is present in the environment used by the API, restart the API after changing it, and enter the value exactly. Production rejects the documented placeholder and passwords shorter than 16 characters.

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
