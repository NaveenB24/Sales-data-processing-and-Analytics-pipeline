# Architecture

## 1. Shape of the system

```
┌──────────────────────────┐        HTTP/JSON  +  WebSocket        ┌───────────────────────────────┐
│  React 18 + TS (Vite)    │ ─────────────────────────────────────▶│  FastAPI (Uvicorn, 1 process) │
│                          │                                       │                               │
│  • AuthContext (JWT)     │  POST /api/jobs/upload                │  ┌─────────────────────────┐  │
│  • Dashboard / Upload    │  GET  /api/jobs, /report, /rows       │  │ routers/                │  │
│  • Recharts views        │  WS   /ws/jobs/{id}?token=…           │  │  auth jobs reports      │  │
│  • useJobProgress hook   │◀──────────────────────────────────────│  │  admin ws               │  │
└──────────────────────────┘        progress / completed events    │  └───────────┬─────────────┘  │
                                                                    │              │                │
                                                                    │   enqueue(job_id)             │
                                                                    │              ▼                │
                                                                    │  ┌─────────────────────────┐  │
                                                                    │  │ JobQueue                │  │
                                                                    │  │ (daemon dispatcher thr.)│  │
                                                                    │  └───────────┬─────────────┘  │
                                                                    │              ▼                │
                                                                    │  ┌─────────────────────────┐  │
                                                                    │  │ pipeline.process_job    │  │
                                                                    │  │  ThreadPoolExecutor ×N  │  │
                                                                    │  │  validate → derive →    │  │
                                                                    │  │  bulk insert → aggregate│  │
                                                                    │  └───────┬────────┬────────┘  │
                                                                    │          │        │           │
                                                                    │    EventHub    SQLAlchemy     │
                                                                    │  (thread→loop)      │         │
                                                                    └─────────────────────┼─────────┘
                                                                                          ▼
                                                                                 ┌────────────────┐
                                                                                 │ SQLite (WAL)   │
                                                                                 │ users · jobs   │
                                                                                 │ transactions   │
                                                                                 │ reports        │
                                                                                 └────────────────┘
```

## 2. Request → result, step by step

1. **Upload.** `POST /api/jobs/upload` streams the body to disk in 1 MB chunks, enforcing the
   size cap *while* writing so an oversized file never lands. A `Job` row is created in
   `pending`, stamped with a `correlation_id` that every later log line carries. A token-bucket
   limiter (per user) guards the endpoint.
2. **Queue.** If `auto_process` is set — or when the user later calls `POST /{id}/process` —
   the job id goes onto `JobQueue`. A single daemon dispatcher thread pulls ids one at a time,
   so jobs are serialized while *rows inside a job* run in parallel. That keeps SQLite's
   single-writer model happy without giving up row-level concurrency.
3. **Process.** `pipeline.process_job` streams the file, submits bounded batches of rows to a
   `ThreadPoolExecutor` of `WORKER_POOL_SIZE` workers, and each worker simulates real per-row
   cost (`ROW_PROCESSING_DELAY_MS`) before validating. Transient worker exceptions are retried
   with backoff; exhausted retries demote the row to `invalid` with code `PROCESSING_ERROR`
   rather than failing the job.
4. **Order-independent duplicates.** Workers complete out of order, so duplicate detection is
   *not* done inside the worker. Each completed batch is re-sorted by `row_number` and passed
   through a `DuplicateTracker` on the dispatcher thread — first occurrence wins, repeats are
   marked `duplicate` and have their money fields nulled so they can never inflate revenue.
   The result is deterministic regardless of thread scheduling.
5. **Persist + progress.** Rows are bulk-inserted in chunks of `DB_INSERT_CHUNK_SIZE`. Counters
   on the `Job` row advance as batches land, and a progress event is published every
   `PROGRESS_EMIT_EVERY` rows.
6. **Aggregate.** `aggregate_job` streams the stored rows back (`yield_per`) and writes one
   `Report` row per metric family. Separating aggregation from row processing is what makes
   "re-run aggregation on demand" a cheap, independent operation.
7. **Deliver.** The dashboard reads `/report` for charts and `/rows` for the paginated
   explorer; `/export` re-streams rows as annotated CSV or JSON.

## 3. Concurrency model

| Concern | Mechanism | Why |
|---|---|---|
| Row validation throughput | `ThreadPoolExecutor(WORKER_POOL_SIZE)` | The simulated cost is a sleep (I/O-shaped), so threads give real wall-clock speedup without process overhead or pickling. |
| Job isolation | one dispatcher thread, jobs run serially | SQLite allows one writer; serializing jobs avoids write contention while rows still run in parallel. |
| Memory ceiling | bounded in-flight futures + chunked inserts + `yield_per` reads | A 100k-row file never materialises in full. |
| Determinism | duplicate pass applied in `row_number` order | Same file ⇒ same report, every run. |
| Thread → async handoff | `EventHub.publish` → `loop.call_soon_threadsafe` | Worker threads can feed WebSocket subscribers without touching the loop directly. |

If this ever outgrows one box, the seam is already cut: replace `JobQueue` with Redis/RQ or
Celery and `EventHub` with a Redis pub/sub channel. Nothing in the routers or the pipeline
changes.

## 4. Data model and query shapes

Four tables (`users`, `jobs`, `transactions`, `reports`) — see `SPEC.md` §3 for columns.
Indexes exist because specific queries need them, not by reflex:

| Query | Index used |
|---|---|
| "my jobs, newest first" | `ix_jobs_user_created (user_id, created_at)` |
| row explorer filtered by status | `ix_tx_job_status (job_id, status)` |
| top-N transactions | `ix_tx_job_net (job_id, net_amount)` |
| daily/monthly trend scan | `ix_tx_job_date (job_id, transaction_date)` |
| "revenue-by-region for my last 10 jobs" | `ix_jobs_user_created` ⋈ `uq_reports_job_kind` |

Reports are stored **one row per metric family** rather than as a single blob, so a chart can
be fetched without reading every other metric, and the cross-job endpoint joins straight to
the `by_region` payload.

SQLite runs with `journal_mode=WAL` (readers never block on the writer), `synchronous=NORMAL`,
`foreign_keys=ON` and a 30 s busy timeout.

## 5. Observability

Structured JSON lines via structlog, to stdout and `backend/logs/app.log`. A middleware mints
or accepts an `X-Correlation-ID` per request and binds it to a contextvar; the pipeline binds
the job's own correlation id, so a single id traces upload → queue → workers → aggregation.
Events: `upload.received`, `job.queued`, `job.started`, `job.completed`, `job.failed`,
`row.invalid`, `auth.login`, `rate_limit.exceeded`, `http.request`.
`GET /api/metrics` exposes job counts by status, failure rate, average row-processing time,
average job duration and rows processed.

## 6. Security posture

- bcrypt password hashing (72-byte guard against silent truncation); passwords never logged.
- HS256 JWTs carrying `sub` + `role`; expiry enforced; tokens for deleted users rejected.
- Every job/row/report query is scoped by `user_id`; a non-owner gets **404, not 403**, so job
  ids cannot be enumerated. Admins are the single exception.
- Uploads: extension allow-list, streaming size cap, per-user rate limit, and files stored
  under a server-generated UUID name — the client-supplied filename is never used as a path.
- Errors return a flat `{"detail": …}`; unhandled exceptions never leak a traceback.
