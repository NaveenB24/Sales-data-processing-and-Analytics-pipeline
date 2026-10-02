# SPEC — Sales Data Processing & Analytics Pipeline

Version: 1.0 · Status: approved

A self-contained full-stack system that ingests bulk sales transaction files,
validates and processes rows **concurrently**, computes analytical metrics, and
presents them on a live dashboard.

## 1. Stack (decided)

| Layer | Choice | Rationale |
|---|---|---|
| Backend | Python 3.14 + FastAPI + Uvicorn | async HTTP + native WebSockets + typed DTOs |
| ORM/DB | SQLAlchemy 2.0 (sync) + SQLite (WAL) | zero-install, single file, meets the brief's "sqlite if it works" |
| Auth | PyJWT (HS256) + bcrypt | stateless tokens, hashed passwords |
| Concurrency | `ThreadPoolExecutor` worker pool + single dispatcher thread job queue | real parallelism for the simulated per-row I/O cost; no Redis dependency |
| Realtime | WebSocket (`/ws/jobs/{job_id}`) with polling fallback | live progress |
| Logging | structlog, JSON lines, correlation IDs | structured observability |
| Frontend | React 18 + TypeScript + Vite + Recharts | fast dev loop, typed API client |

## 2. Domain rules

### 2.1 Input columns
`transaction_id, region, product_category, quantity, unit_price, discount_percent, transaction_date`
CSV (header required) or JSON (array of objects). Header matching is
case-insensitive and whitespace-trimmed.

### 2.2 Row validation
A row is assigned exactly one `status`:

- `duplicate` — `transaction_id` already seen earlier **in the same job**. Takes
  precedence over field errors only after field validation passes; a row that is
  both malformed and a repeat is reported as `invalid` with the duplicate error
  also listed. First occurrence stays `valid`.
- `invalid` — one or more field errors.
- `valid` — no errors.

Field rules (error `code` in parentheses):

| Field | Rule | Code |
|---|---|---|
| transaction_id | required, non-empty after trim | `MISSING_FIELD` |
| region | required, non-empty | `MISSING_FIELD` |
| product_category | required, non-empty | `MISSING_FIELD` |
| quantity | required, parses as number, integral, `> 0` | `MISSING_FIELD` / `NOT_A_NUMBER` / `NEGATIVE_VALUE` |
| unit_price | required, parses as number, `>= 0` | `MISSING_FIELD` / `NOT_A_NUMBER` / `NEGATIVE_VALUE` |
| discount_percent | optional — blank/absent ⇒ `0.0`; if present must parse and be `0 <= d <= 100` | `NOT_A_NUMBER` / `OUT_OF_RANGE` |
| transaction_date | required, parseable date (`YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, ISO-8601 datetime), not in the future (compared to UTC today) | `MISSING_FIELD` / `INVALID_DATE` / `FUTURE_DATE` |
| — | unknown `transaction_id` repeat | `DUPLICATE_ID` |

Unparseable/short/long CSV lines never abort the run; they become `invalid` rows
with code `MALFORMED_ROW`.

### 2.3 Derived values (valid rows only)
```
gross_amount    = quantity * unit_price
discount_amount = gross_amount * (discount_percent / 100)
net_amount      = gross_amount - discount_amount
```
All money values rounded to 2 decimals at storage time.

### 2.4 Simulated processing cost
Each row sleeps `ROW_PROCESSING_DELAY_MS` (default 2 ms, configurable) inside the
worker, so a sequential run of 10k rows would take ≥ 20 s while the pool
finishes in a fraction of that. A concurrency test asserts wall-clock speedup.

### 2.5 Aggregate metrics (computed over `valid` rows of one job)
- `total_revenue` = Σ net_amount
- `gross_revenue` = Σ gross_amount
- `discount_impact` = Σ discount_amount (revenue lost to discounts) + `discount_rate_pct`
- `average_order_value` = mean(net_amount)
- `median_transaction_value` = median(net_amount)
- `std_dev_order_value` = sample standard deviation (n-1); `variance_flag = true`
  when coefficient of variation (`stddev / mean`) > `VARIANCE_CV_THRESHOLD` (default 1.0)
- `revenue_by_region` / `revenue_by_category` — `{key, revenue, transactions, share_pct}`, sorted desc
- `top_transactions` — top 5 by net_amount desc
- `trend_daily` — per day `{period, revenue, transactions, change_pct}` where
  `change_pct` is day-over-day vs the previous **present** period (null for first)
- `trend_monthly` — same, per `YYYY-MM`, month-over-month
- `min_order_value`, `max_order_value`, `transaction_count`

Empty valid set ⇒ all numeric metrics `0`, collections empty, `median`/`stddev` `0`.

## 3. Data model (SQLite)

- **users** — `id`, `email` (unique, lowercased), `password_hash`, `role` (`user`|`admin`), `created_at`
- **jobs** — `id` (uuid4 str), `user_id`→users, `original_filename`, `stored_path`, `status`
  (`pending`|`queued`|`processing`|`completed`|`failed`), `total_rows`, `processed_rows`,
  `valid_rows`, `invalid_rows`, `duplicate_rows`, `error_message`, `correlation_id`,
  `created_at`, `started_at`, `finished_at`, `duration_ms`, `avg_row_ms`, `retry_count`
- **transactions** — `id`, `job_id`→jobs (cascade), `row_number`, `transaction_id`, `region`,
  `product_category`, `quantity`, `unit_price`, `discount_percent`, `transaction_date`,
  `gross_amount`, `discount_amount`, `net_amount`, `status` (`valid`|`invalid`|`duplicate`),
  `errors` (JSON text), `raw` (JSON text)
- **reports** — `id`, `job_id`→jobs (cascade), `kind` (`summary`|`by_region`|`by_category`|
  `trend_daily`|`trend_monthly`|`top_transactions`), `payload` (JSON text), `created_at`

Indexes: `jobs(user_id, created_at desc)`, `jobs(status)`, `transactions(job_id, status)`,
`transactions(job_id, net_amount desc)`, `transactions(job_id, transaction_date)`,
`transactions(job_id, transaction_id)`, unique `reports(job_id, kind)`.

This shape answers "all revenue-by-region reports for this user's last 10 jobs" with a
single indexed join: `reports ⋈ jobs WHERE jobs.user_id = ? AND reports.kind='by_region'
ORDER BY jobs.created_at DESC LIMIT 10`.

## 4. API contract

All JSON. Errors: `{"detail": "..."}` with proper status codes. Auth header:
`Authorization: Bearer <token>`. Every response carries `X-Correlation-ID`.

### Auth
| Method | Path | Body / Query | Returns |
|---|---|---|---|
| POST | `/api/auth/signup` | `{email, password}` (password ≥ 8 chars) | `201 {access_token, token_type, user}` |
| POST | `/api/auth/login` | `{email, password}` | `200 {access_token, token_type, user}` |
| GET | `/api/auth/me` | — | `200 User` |

`User = {id, email, role, created_at}`

### Jobs
| Method | Path | Notes |
|---|---|---|
| POST | `/api/jobs/upload` | multipart `file`; optional `auto_process=true`; rate-limited; `201 Job` |
| GET | `/api/jobs?limit=&offset=&status=` | caller's jobs, newest first → `{items, total}` |
| GET | `/api/jobs/{id}` | `Job` (404 if not owner and not admin) |
| POST | `/api/jobs/{id}/process` | enqueue processing → `202 Job`; 409 if already running/queued |
| POST | `/api/jobs/{id}/reaggregate` | recompute reports from stored rows → `200 Report` |
| DELETE | `/api/jobs/{id}` | cascade delete → `204` |
| GET | `/api/jobs/{id}/rows?status=&limit=&offset=&q=` | → `{items, total}` |
| GET | `/api/jobs/{id}/report` | full `Report` (all six kinds merged) |
| GET | `/api/jobs/{id}/export?format=csv\|json` | annotated results download |
| GET | `/api/jobs/{id}/progress` | polling fallback → `{status, processed_rows, total_rows, percent, valid_rows, invalid_rows, duplicate_rows}` |
| WS | `/ws/jobs/{id}?token=<jwt>` | pushes `{type:"progress"\|"status"\|"completed"\|"failed", ...}` |

`Job = {id, original_filename, status, total_rows, processed_rows, valid_rows, invalid_rows,
duplicate_rows, error_message, correlation_id, created_at, started_at, finished_at,
duration_ms, avg_row_ms, percent}`

### Reports & admin
| Method | Path | Notes |
|---|---|---|
| GET | `/api/reports/by-region?limit=10` | revenue-by-region report across the caller's last N jobs |
| GET | `/api/reports/overview` | cross-job totals for the caller |
| GET | `/api/admin/users` | admin only |
| GET | `/api/admin/jobs` | admin only, all users' jobs |
| GET | `/api/metrics` | `{jobs_total, jobs_by_status, job_failure_rate, avg_row_processing_ms, avg_job_duration_ms, rows_processed_total, uptime_seconds}` |
| GET | `/api/health` | `{status:"ok", version, db:"ok"}` |

## 5. Non-functional

- **Ownership isolation** — every job/row/report query filters by `user_id` unless the
  caller is `admin`. Cross-user access returns 404 (not 403) to avoid id enumeration.
- **Rate limiting** — token bucket, `UPLOAD_RATE_LIMIT` (default 20) uploads per
  `UPLOAD_RATE_WINDOW_SECONDS` (default 60) per user; 429 with `Retry-After`.
- **Retry** — a row whose processing raises is retried `ROW_MAX_RETRIES` (default 2) times
  with 10 ms backoff before being marked `invalid` with code `PROCESSING_ERROR`.
- **Limits** — `MAX_UPLOAD_MB` (default 50); files above are rejected 413.
- **Logging** — JSON lines to stdout and `backend/logs/app.log`; levels info/warn/error;
  `correlation_id` bound per request and per job; logged events: `upload.received`,
  `row.invalid`, `job.started`, `job.completed`, `job.failed`, `auth.login`, `rate_limit.exceeded`.
- **Scale** — must process a 10 000-row file end to end; rows are bulk-inserted in chunks.

## 6. UI

Routes: `/login`, `/signup`, `/` (jobs dashboard), `/jobs/:id` (job detail), `/admin`.

- Upload card with drag-and-drop, file picker, and "process on upload" toggle.
- Live progress bar + row counter driven by WebSocket, falling back to 2 s polling.
- Job list: status pill, filename, rows, created-at, actions (view / process / delete).
- Job detail: summary tiles (total rows, valid, invalid, duplicates, total revenue, AOV,
  median, std dev + variance flag, discount impact), bar chart revenue-by-region, pie/bar
  revenue-by-category, line chart revenue trend (daily/monthly toggle), top-5 table,
  paginated row explorer with status filter and inline error chips, export buttons.
- Admin page (admin role only): all users, all jobs, system metrics.
- Accessible, responsive, light/dark aware, keyboard-navigable.

## 7. Acceptance

The sample file from the brief (7 rows) must yield: 4 valid, 2 invalid
(`TXN-1003` negative quantity, `TXN-1006` malformed price), 1 duplicate
(`TXN-1005`), 1 invalid future date (`TXN-1007`) — i.e. **3 invalid, 1 duplicate,
3 valid** — with no crash, and a complete report rendered in the UI.
