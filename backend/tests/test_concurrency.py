"""Worker-pool speedup and per-row retry behaviour (SPEC 2.4, 5)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import Transaction
from app.processing import pipeline
from app.processing.validation import validate_row as real_validate_row

from tests.test_pipeline import make_job

HEADER = "transaction_id,region,product_category,quantity,unit_price,discount_percent,transaction_date\n"


def write_rows(path: Path, count: int) -> Path:
    """Distinct rows: the unit price varies so content de-duplication stays out
    of the way — these tests are about the worker pool, not about duplicates."""
    lines = [HEADER]
    for i in range(1, count + 1):
        lines.append(f"TXN-{i},North,Electronics,2,{10 + i}.00,0,2025-01-15\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


@pytest.mark.slow
def test_pool_beats_sequential_wall_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = 120
    monkeypatch.setattr(settings, "row_processing_delay_ms", 25.0)
    monkeypatch.setattr(settings, "worker_pool_size", 8)
    monkeypatch.setattr(settings, "progress_emit_every", 1000)
    job_id = make_job(write_rows(tmp_path / "many.csv", rows), filename="many.csv")

    started = time.perf_counter()
    pipeline.process_job(job_id)
    elapsed = time.perf_counter() - started

    sequential = rows * settings.row_processing_delay_ms / 1000.0
    assert sequential == pytest.approx(3.0)
    assert elapsed < 1.5, f"took {elapsed:.2f}s, expected well under the sequential {sequential:.1f}s"

    with SessionLocal() as db:
        stored = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    assert len(stored) == rows
    assert all(r.status == "valid" for r in stored)


@pytest.mark.slow
def test_transient_worker_failure_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "row_retry_backoff_ms", 1.0)
    attempts: dict[int, int] = {}
    lock = threading.Lock()

    def flaky(raw, row_number, *, today=None):
        with lock:
            attempts[row_number] = attempts.get(row_number, 0) + 1
            count = attempts[row_number]
        if count == 1:
            raise RuntimeError("transient boom")
        return real_validate_row(raw, row_number, today=today)

    monkeypatch.setattr(pipeline, "validate_row", flaky)
    job_id = make_job(write_rows(tmp_path / "flaky.csv", 5), filename="flaky.csv")

    pipeline.process_job(job_id)

    with SessionLocal() as db:
        stored = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    assert len(stored) == 5
    assert all(r.status == "valid" for r in stored)
    assert all(count == 2 for count in attempts.values())  # one failure, one success


@pytest.mark.slow
def test_exhausted_retries_land_as_processing_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "row_retry_backoff_ms", 1.0)
    monkeypatch.setattr(settings, "row_max_retries", 2)
    calls: list[int] = []
    lock = threading.Lock()

    def always_fails(raw, row_number, *, today=None):
        with lock:
            calls.append(row_number)
        raise RuntimeError("permanent boom")

    monkeypatch.setattr(pipeline, "validate_row", always_fails)
    job_id = make_job(write_rows(tmp_path / "broken.csv", 3), filename="broken.csv")

    pipeline.process_job(job_id)  # the job survives bad rows

    with SessionLocal() as db:
        stored = db.query(Transaction).filter(Transaction.job_id == job_id).all()
        job_status = db.query(Transaction).filter(Transaction.status == "invalid").count()

    assert len(calls) == 3 * (settings.row_max_retries + 1)
    assert len(stored) == 3 and job_status == 3
    codes = [json.loads(r.errors)[0]["code"] for r in stored]
    assert codes == ["PROCESSING_ERROR"] * 3

    from app.models import Job

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "completed"
        assert job.invalid_rows == 3
        assert job.valid_rows == 0
