# Sales Data Processing & Analytics Pipeline

A self-contained full-stack system that ingests bulk sales files, validates and processes
rows **concurrently**, computes analytical metrics, and streams live progress to a React
dashboard.

- **Backend** — Python 3.12+ · FastAPI · SQLAlchemy 2 · SQLite (WAL) · thread worker pool · WebSockets
- **Frontend** — React 18 · TypeScript · Vite · Recharts
- **No external services required.** No Redis, no Postgres, no network calls, fully deterministic.

---

## Quick start

```bash
git clone <repo> sales-data-processor
cd sales-data-processor

./scripts/setup.sh     # creates .venv, installs backend + frontend deps
./scripts/dev.sh       # starts API on :8000 and the dashboard on :5173
```

Open **http://localhost:5173**, create an account, and upload
`sample_data/sample_sales.csv`.

> The **first account created becomes the administrator** — that is what unlocks the
> `/admin` page on a fresh install. Every account after it is a normal user.

### Manual setup

<details>
<summary>If you'd rather not use the scripts</summary>

```bash
# Backend
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend && npm install && npm run dev
```

Python builds that ship `venv` without `ensurepip` (some Debian/Ubuntu images) need a
manual pip bootstrap — `scripts/setup.sh` already handles that case.
</details>

### Docker

```bash
JWT_SECRET=$(openssl rand -hex 32) docker compose up --build
# dashboard: http://localhost:8080   ·   API: http://localhost:8000/api/docs
```

### Tests

```bash
./scripts/test.sh          # fast suite
./scripts/test.sh --slow   # + concurrency timing and the 10 000-row end-to-end run
```

Interactive API docs (OpenAPI): **http://localhost:8000/api/docs**

---

## What it does

### 1. Authentication & user management
Email + password signup with **bcrypt** hashing and HS256 **JWTs**. Every job, row and report
query is scoped to the caller's `user_id`; a request for someone else's job returns **404
rather than 403**, so job ids cannot be enumerated. Role-based access is included — the first
account is promoted to `admin` and gains `/api/admin/*` plus a system-wide metrics view.

### 2. Upload & processing engine
CSV and JSON (array or NDJSON) uploads, streamed to disk in chunks with the size cap enforced
mid-write. Headers are matched case-insensitively. Every row is validated for required
fields, numeric sanity, date validity, future dates, and duplicate `transaction_id`s — then
`net_amount = quantity × unit_price × (1 − discount_percent/100)` is derived for valid rows.
Each row pays a configurable artificial processing cost so the worker pool is doing real work.

**Nothing in a bad file can crash the pipeline.** Malformed rows become `invalid` rows with
error codes; an unparseable *file* marks the job `failed` with a message and the API keeps
serving.

### 3. Aggregation & math
Total revenue, revenue by region and category, average order value, median transaction value,
sample standard deviation with a coefficient-of-variation **variance flag**, top 5
transactions, day-over-day and month-over-month trends, and total revenue lost to discounts.
All computed from the stored rows, so **re-running aggregation is independent of
re-processing**.

### 4. Concurrency & scheduling
Rows are validated and derived in a `ThreadPoolExecutor` worker pool, fed in bounded batches.
Jobs themselves are queued and dispatched by a background thread, so a user can upload and
keep working. Processing can be triggered on upload or on demand, and aggregation re-run at
any time. Failed row processing is retried with backoff before the row is demoted.

### 5. Database
SQLite in WAL mode with four tables and indexes chosen for the queries that actually run —
including the brief's "revenue-by-region for this user's last 10 jobs", which resolves to one
indexed join. Verified end to end on 10 000-row files.

### 6. Dashboard
Upload with drag-and-drop, a **live progress bar over WebSockets** (with automatic polling
fallback), job summary counts, revenue-by-region bar chart, revenue-by-category pie chart,
revenue-trend line chart with daily/monthly toggle, top-5 table, a paginated row explorer
with status filters and per-row error chips, and one-click export of the annotated results.

### 7. Logging & observability
Structured JSON logs with levels, a **correlation ID per job** traced across request →
queue → worker → aggregation, and `GET /api/metrics` reporting job counts by status, job
failure rate, average row-processing time and average job duration.

---

## Validation rules

| Field | Rule | Error code |
|---|---|---|
| `transaction_id` | required, non-empty | `MISSING_FIELD` |
| `region` | required, non-empty | `MISSING_FIELD` |
| `product_category` | required, non-empty | `MISSING_FIELD` |
| `quantity` | required, numeric, integral, `> 0` | `MISSING_FIELD` · `NOT_A_NUMBER` · `NEGATIVE_VALUE` |
| `unit_price` | required, numeric, `>= 0` | `MISSING_FIELD` · `NOT_A_NUMBER` · `NEGATIVE_VALUE` |
| `discount_percent` | optional (blank ⇒ `0`), numeric, `0–100` | `NOT_A_NUMBER` · `OUT_OF_RANGE` |
| `transaction_date` | required, parseable, not in the future | `MISSING_FIELD` · `INVALID_DATE` · `FUTURE_DATE` |
| repeat `transaction_id` | first occurrence wins | `DUPLICATE_ID` |
| repeat of an earlier row under a new id | first occurrence wins | `DUPLICATE_RECORD` |
| unreadable line | never aborts the run | `MALFORMED_ROW` |
| worker exhausted retries | row demoted, job continues | `PROCESSING_ERROR` |

Duplicates have their money fields nulled, so a repeated transaction can never inflate
revenue.

**Two duplicate signals, and why.** The brief asks for duplicate `transaction_id`s to be
flagged — but its own sample file calls `TXN-1005` a duplicate of `TXN-1001`, and those two
ids are *different*; only the contents repeat. Implementing only the stated rule would fail
the brief's own acceptance note, so both are implemented: a repeated id (`DUPLICATE_ID`) and
a repeated row under a fresh id (`DUPLICATE_RECORD`). Content matching could in principle
collide with two genuinely separate sales agreeing on every field, so it is configurable —
`DUPLICATE_DETECTION=id` restores id-only matching.

### The brief's sample file

`sample_data/sample_sales.csv` yields **3 valid · 3 invalid · 1 duplicate**:

| Row | Outcome | Why |
|---|---|---|
| TXN-1001 | valid | 3 × 499.99 − 10% = **1 349.97** |
| TXN-1002 | valid | 12 × 15.50 = **186.00** |
| TXN-1003 | invalid | negative quantity |
| TXN-1004 | valid | 5 × 49.99 − 20% = **199.96** |
| TXN-1005 | duplicate | identical to TXN-1001 on every field but the id |
| TXN-1006 | invalid | `unit_price` is `abc` |
| TXN-1007 | invalid | date `2099-01-01` is in the future |

Total revenue **1 735.93** · gross **1 935.92** · AOV **578.64** · median **199.96** · discount impact **199.99**.
This is asserted as a test, not just documented.

---

## API

Full interactive reference at `/api/docs`. Summary:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/signup` · `/api/auth/login` | obtain a JWT |
| `GET` | `/api/auth/me` | current user |
| `POST` | `/api/jobs/upload` | multipart upload (`auto_process` optional) |
| `GET` | `/api/jobs` | caller's jobs, paginated, status filter |
| `GET` | `/api/jobs/{id}` · `/progress` | job state / live counters |
| `POST` | `/api/jobs/{id}/process` | trigger or re-run processing |
| `POST` | `/api/jobs/{id}/reaggregate` | recompute metrics only |
| `GET` | `/api/jobs/{id}/rows` | row explorer (status filter, search, pagination) |
| `GET` | `/api/jobs/{id}/report` | all computed metrics |
| `GET` | `/api/jobs/{id}/export?format=csv\|json` | annotated results download |
| `DELETE` | `/api/jobs/{id}` | delete job + rows + reports |
| `GET` | `/api/reports/by-region?limit=10` | revenue-by-region across recent jobs |
| `GET` | `/api/reports/overview` | cross-job portfolio totals |
| `GET` | `/api/metrics` · `/api/health` | observability |
| `GET` | `/api/admin/users` · `/api/admin/jobs` | admin only |
| `WS` | `/ws/jobs/{id}?token=<jwt>` | live progress events |

---

## Configuration

Copy `backend/.env.example` to `backend/.env`. Everything has a working default.

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET` | dev value | **change in production** |
| `DATABASE_URL` | `sqlite:///backend/data/sales.db` | any SQLAlchemy URL |
| `WORKER_POOL_SIZE` | `8` | row workers per job |
| `ROW_PROCESSING_DELAY_MS` | `2` | simulated per-row cost |
| `ROW_MAX_RETRIES` | `2` | retries before a row is demoted |
| `MAX_UPLOAD_MB` | `50` | upload size cap |
| `UPLOAD_RATE_LIMIT` / `_WINDOW_SECONDS` | `20` / `60` | per-user upload throttle |
| `VARIANCE_CV_THRESHOLD` | `1.0` | CV above which variance is flagged |
| `DUPLICATE_DETECTION` | `id_and_content` | `id` matches repeated ids only |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | logging |

Generate load-test fixtures:

```bash
.venv/bin/python scripts/generate_sample_data.py --rows 10000 --out sample_data/large_sales.csv
```

---

## Documentation

| Document | What it is |
|---|---|
| **[docs/handoff.pdf](docs/handoff.pdf)** | **The project handbook** — a 39-page walkthrough written for someone with no prior context: how to run it, the repository map, architecture, business rules, API, UI, testing evidence, design tradeoffs, how AI tooling was used, and troubleshooting. Start here. |
| [SPEC.md](SPEC.md) | The written contract the code was built against. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Deeper architectural notes: diagram, concurrency model, index rationale, security posture. |
| `/api/docs` | Interactive API reference, generated from the code, live while the backend runs. |

The handbook is generated from `docs/handoff.html`; edit that and re-print to PDF to regenerate it.

---

## Design decisions & tradeoffs

**SQLite over Postgres.** The brief allows it and it removes every setup step — `git clone`
to running dashboard with no daemon. The cost is one writer at a time, which shaped the
concurrency model below. `DATABASE_URL` is the only change needed to move to Postgres;
nothing else in the code assumes SQLite.

**Threads over asyncio or multiprocessing for row work.** The simulated per-row cost is
I/O-shaped (a sleep), and the real work — parsing, arithmetic, validation — is short. Threads
give genuine wall-clock speedup without process spawn cost, pickling, or rewriting the
synchronous SQLAlchemy layer. If row processing ever became CPU-bound, the swap to
`ProcessPoolExecutor` is contained to one module.

**Jobs serialized, rows parallel.** SQLite permits a single writer. Running jobs one at a time
through a dispatcher thread, while parallelising rows *inside* each job, gets the concurrency
the brief asks for without lock contention. The queue interface is deliberately the same shape
as Redis/RQ's, so swapping in a distributed broker is a module replacement.

**In-process queue and event hub instead of Redis.** Redis would buy multi-process workers and
survive restarts, at the cost of a service to install and run. For a self-contained
deliverable the in-process versions are the honest trade — and both sit behind narrow
interfaces (`JobQueue`, `EventHub`) specifically so they can be replaced.

**Duplicate detection outside the workers.** Workers finish out of order, so detecting
duplicates inside them would make "which row is the original" depend on thread scheduling.
Instead each completed batch is re-sorted by row number and passed through the tracker
serially. Slightly more code, fully deterministic output.

**Reports stored per metric family, not as one blob.** Six small rows per job instead of one
large JSON document. That lets the cross-job endpoint join straight to the `by_region` payload
without deserialising unrelated metrics, and makes `reaggregate` an upsert rather than a
rewrite.

**Invalid rows are stored, not dropped.** They cost space, but they are the error report —
and the annotated export is just a dump of the same table.

**404 instead of 403 for other users' resources.** Slightly less informative to a legitimate
user who mistyped a URL; meaningfully harder for an attacker probing for valid job ids.

**WebSockets with a polling fallback.** Proxies and corporate networks drop WebSocket
upgrades. The hook opens a socket, and transparently falls back to polling `/progress` if the
socket fails to open or closes abnormally, so progress never silently stalls.

**Known limits.** Single process — job state lives in memory, so a restart mid-job leaves that
job in `processing` (re-trigger it; processing is idempotent). The rate limiter is per
process. There are no DB migrations (`create_all` only), which is fine for a greenfield
schema and would need Alembic in production.

---

## How AI tools were used

This project was built with **Claude Code (Opus)** driving the whole lifecycle — not as
autocomplete, but as the engineer of record under human direction.

**Process.** The brief was first turned into a written contract (`SPEC.md`): validation rules
with named error codes, the exact data model with its indexes, the full API surface, and
numeric acceptance criteria for the sample file. Everything after that was built against the
spec rather than against a vague memory of the requirements — which is what made it safe to
parallelise.

**Parallel agents.** Once the foundation (settings, ORM models, schemas, security, logging)
was in place and the module contracts were pinned down, two specialised sub-agents worked
concurrently on independent surfaces — the processing engine (validation, metrics, worker
pool, queue, event hub) and the React dashboard — while the main session built the API layer.
Precise interface contracts in each agent's brief are what kept the three streams composable;
integration was a matter of running the suite, not rewriting.

**Verification over assertion.** Every requirement is backed by an executable check rather
than a claim: the sample file's 3/3/1 split, the hand-computed revenue figures, tenant
isolation across every endpoint, the concurrency speedup measured against a sequential
baseline, retry exhaustion, rate limiting, WebSocket event ordering, and a full 10 000-row
run. The UI was exercised in a real browser — signup, upload, live progress, charts, export —
rather than assumed to work from a clean compile.

**Where human judgment stayed in charge.** Stack choices, the concurrency model, the
duplicate-ordering decision, the 404-over-403 call, and the scope of what to build versus
document as a limit were directed, reviewed and corrected — the model's first instinct was not
always the right one, and the tradeoffs section above records the reasoning that survived
review.
