"""End-to-end job processing: parse -> validate concurrently -> store -> aggregate."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.logging_config import get_logger, set_correlation_id
from app.models import REPORT_KINDS, Job, Report, Transaction
from app.processing.events import hub
from app.processing.metrics import compute_report
from app.processing.validation import (
    DuplicateTracker,
    RowError,
    ValidatedRow,
    apply_duplicate,
    count_data_rows,
    parse_file,
    validate_row,
)

log = get_logger("processing.pipeline")

#: How many rows may be in flight in the worker pool at once.
BATCH_SIZE = 2000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _batched(
    source: Iterable[tuple[int, dict[str, str]]], size: int
) -> Iterator[list[tuple[int, dict[str, str]]]]:
    batch: list[tuple[int, dict[str, str]]] = []
    for item in source:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _processing_error_row(row_number: int, raw: dict[str, str], exc: BaseException | None) -> ValidatedRow:
    return ValidatedRow(
        row_number=row_number,
        raw={k: ("" if v is None else str(v)) for k, v in raw.items()},
        status="invalid",
        errors=[RowError("PROCESSING_ERROR", f"row processing failed: {exc}")],
    )


def _process_row(row_number: int, raw: dict[str, str], today: date) -> ValidatedRow:
    """Worker unit: simulated I/O cost + validation, with bounded retries."""
    attempts = max(1, settings.row_max_retries + 1)
    delay = settings.row_processing_delay_ms / 1000.0
    backoff = settings.row_retry_backoff_ms / 1000.0
    last_exc: BaseException | None = None

    for attempt in range(attempts):
        try:
            if delay > 0:
                time.sleep(delay)
            return validate_row(raw, row_number, today=today)
        except Exception as exc:  # noqa: BLE001 - a bad row must never kill the job
            last_exc = exc
            if attempt < attempts - 1 and backoff > 0:
                time.sleep(backoff)

    log.warning("row.processing_error", row_number=row_number, error=str(last_exc))
    return _processing_error_row(row_number, raw, last_exc)


def _publish(job: Job, event_type: str) -> None:
    hub.publish(
        job.id,
        {
            "type": event_type,
            "payload": {
                "job_id": job.id,
                "status": job.status,
                "total_rows": job.total_rows,
                "processed_rows": job.processed_rows,
                "valid_rows": job.valid_rows,
                "invalid_rows": job.invalid_rows,
                "duplicate_rows": job.duplicate_rows,
                "percent": job.percent,
                "error_message": job.error_message,
            },
        },
    )


def process_job(job_id: str) -> None:
    """Run one job to completion. Safe to call from a background thread; never raises."""
    db = SessionLocal()
    job: Job | None = None
    try:
        job = db.get(Job, job_id)
        if job is None:
            log.warning("job.missing", job_id=job_id)
            return

        set_correlation_id(job.correlation_id)
        log.info("job.started", job_id=job.id, filename=job.original_filename)

        started = time.perf_counter()
        # Re-processing is idempotent: drop whatever a previous run produced.
        db.execute(delete(Transaction).where(Transaction.job_id == job_id))
        db.execute(delete(Report).where(Report.job_id == job_id))

        job.status = "processing"
        job.started_at = _utcnow()
        job.finished_at = None
        job.duration_ms = None
        job.avg_row_ms = None
        job.error_message = None
        job.processed_rows = 0
        job.valid_rows = 0
        job.invalid_rows = 0
        job.duplicate_rows = 0
        job.total_rows = count_data_rows(job.stored_path)
        db.commit()
        _publish(job, "status")

        today = _utcnow().date()
        tracker = DuplicateTracker()
        pending: list[dict[str, Any]] = []
        since_emit = 0

        def flush(force: bool) -> None:
            nonlocal pending
            chunk_size = max(1, settings.db_insert_chunk_size)
            while pending and (force or len(pending) >= chunk_size):
                chunk, pending = pending[:chunk_size], pending[chunk_size:]
                db.execute(insert(Transaction), chunk)
                db.commit()

        with ThreadPoolExecutor(
            max_workers=max(1, settings.worker_pool_size), thread_name_prefix=f"job-{job_id[:8]}"
        ) as pool:
            for batch in _batched(parse_file(job.stored_path), BATCH_SIZE):
                futures = [pool.submit(_process_row, rn, raw, today) for rn, raw in batch]
                # Results are collected in submission order, so duplicate detection
                # stays deterministic no matter which worker finished first.
                rows = [f.result() for f in futures]
                rows.sort(key=lambda r: r.row_number)

                for row in rows:
                    apply_duplicate(row, tracker)
                    pending.append(row.to_orm_kwargs(job_id))
                    job.processed_rows += 1
                    if row.status == "valid":
                        job.valid_rows += 1
                    elif row.status == "duplicate":
                        job.duplicate_rows += 1
                    else:
                        job.invalid_rows += 1
                        log.debug("row.invalid", job_id=job_id, row_number=row.row_number)

                    since_emit += 1
                    if since_emit >= max(1, settings.progress_emit_every):
                        since_emit = 0
                        flush(force=False)
                        db.commit()
                        _publish(job, "progress")

                flush(force=True)
                db.commit()
                _publish(job, "progress")
                since_emit = 0

        flush(force=True)

        aggregate_job(job_id, db)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        job.status = "completed"
        job.finished_at = _utcnow()
        job.duration_ms = round(elapsed_ms, 2)
        job.avg_row_ms = round(elapsed_ms / job.processed_rows, 3) if job.processed_rows else 0.0
        db.commit()

        log.info(
            "job.completed",
            job_id=job.id,
            total_rows=job.total_rows,
            valid_rows=job.valid_rows,
            invalid_rows=job.invalid_rows,
            duplicate_rows=job.duplicate_rows,
            duration_ms=job.duration_ms,
        )
        _publish(job, "completed")

    except Exception as exc:  # noqa: BLE001 - a failed job must not escape the worker
        log.error("job.failed", job_id=job_id, error=str(exc), exc_info=True)
        try:
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)[:2000]
                job.finished_at = _utcnow()
                db.commit()
                _publish(job, "failed")
        except Exception:  # pragma: no cover - bookkeeping must not raise either
            db.rollback()
    finally:
        set_correlation_id(None)
        db.close()


def aggregate_job(job_id: str, db: Session | None = None) -> dict[str, Any]:
    """Recompute and persist the six report kinds from the stored rows."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        stmt = (
            select(Transaction)
            .where(Transaction.job_id == job_id, Transaction.status == "valid")
            .order_by(Transaction.row_number)
            .execution_options(yield_per=500)
        )
        report = compute_report(session.scalars(stmt))

        existing = {
            r.kind: r for r in session.scalars(select(Report).where(Report.job_id == job_id)).all()
        }
        now = _utcnow()
        for kind in REPORT_KINDS:
            payload = json.dumps(report[kind])
            row = existing.get(kind)
            if row is None:
                session.add(Report(job_id=job_id, kind=kind, payload=payload, created_at=now))
            else:
                row.payload = payload
                row.created_at = now
        session.commit()

        return {"job_id": job_id, "generated_at": now.isoformat(), **report}
    finally:
        if owns_session:
            session.close()


def load_report(job_id: str, db: Session) -> dict[str, Any] | None:
    """Read the persisted reports back into the full report dict; None if absent."""
    rows = db.scalars(select(Report).where(Report.job_id == job_id)).all()
    if not rows:
        return None

    generated_at = max((r.created_at for r in rows if r.created_at is not None), default=_utcnow())
    out: dict[str, Any] = {"job_id": job_id, "generated_at": generated_at.isoformat()}
    stored = {r.kind: json.loads(r.payload) for r in rows}
    for kind in REPORT_KINDS:
        out[kind] = stored.get(kind, {} if kind == "summary" else [])
    return out
