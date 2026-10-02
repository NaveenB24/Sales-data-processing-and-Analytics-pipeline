# Build plan

Dependency order. Each task: RED (test) → GREEN → suite → commit.

| # | Task | Deliverable | Status |
|---|---|---|---|
| 1 | Project skeleton, SPEC, plan, sample data | repo scaffold | done |
| 2 | Backend foundation | `config.py`, `db.py`, `models.py`, `schemas.py`, `security.py`, `logging_config.py`, `deps.py` | done |
| 3 | Processing core | `processing/validation.py`, `processing/metrics.py` + unit tests | done |
| 4 | Concurrency engine | `processing/events.py`, `processing/pipeline.py`, `processing/queue.py` + concurrency/retry tests | done |
| 5 | Auth API | `routers/auth.py` + tests (signup/login/me/isolation) | done |
| 6 | Jobs API | `routers/jobs.py` (upload, list, process, rows, export, progress, delete) + tests | done |
| 7 | Reports/admin/metrics API | `routers/reports.py`, `routers/admin.py` + tests | done |
| 8 | WebSocket progress | `routers/ws.py` + test | done |
| 9 | App wiring | `main.py`, rate limiting, correlation middleware, 10k-row scale test | done |
| 10 | Frontend scaffold + auth | Vite/React/TS, API client, auth context, login/signup | done |
| 11 | Dashboard + upload + live progress | jobs list, upload card, WS/polling | done |
| 12 | Job detail charts & row explorer | Recharts views, export, admin page | done |
| 13 | End-to-end verification | run both servers, Playwright walkthrough, 10k file | done |
| 14 | README, run scripts, Dockerfiles, CI | docs + tooling | done |
| 15 | Handoff handbook | `docs/handoff.html` → `docs/handoff.pdf` (39 pages) | done |
