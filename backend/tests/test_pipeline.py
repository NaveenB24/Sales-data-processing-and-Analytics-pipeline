"""End-to-end processing tests against the SPEC 7 acceptance file."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.models import Job, Report, Transaction, User, REPORT_KINDS
from app.processing.events import hub
from app.processing.pipeline import aggregate_job, load_report, process_job

# The brief's sample file. Row 5 repeats row 1's transaction_id, which is what makes
# it the duplicate SPEC 7 expects: 3 valid, 3 invalid, 1 duplicate.
SAMPLE_CSV = """transaction_id,region,product_category,quantity,unit_price,discount_percent,transaction_date
TXN-1001,North,Electronics,3,499.99,10,2025-01-15
TXN-1002,South,Groceries,12,15.50,0,2025-01-15
TXN-1003,East,Electronics,-2,299.00,5,2025-01-16
TXN-1004,West,Apparel,5,49.99,20,2025-01-16
TXN-1001,North,Electronics,3,499.99,10,2025-01-15
TXN-1006,South,Groceries,7,abc,0,2025-01-17
TXN-1007,East,Apparel,1,89.99,,2099-01-01
"""


def make_user() -> str:
    user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash="x", role="user")
    with SessionLocal() as db:
        db.add(user)
        db.commit()
        return user.id


def make_job(path: Path, *, filename: str = "sample.csv") -> str:
    job = Job(
        user_id=make_user(),
        original_filename=filename,
        stored_path=str(path),
        content_type="text/csv",
        size_bytes=path.stat().st_size if path.exists() else 0,
        status="queued",
    )
    with SessionLocal() as db:
        db.add(job)
        db.commit()
        return job.id


@pytest.fixture
def sample_job(tmp_path: Path) -> str:
    path = tmp_path / "sample.csv"
    path.write_text(SAMPLE_CSV, encoding="utf-8")
    return make_job(path)


def get_job(job_id: str) -> Job:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        return job


# ------------------------------------------------------------------ acceptance


def test_acceptance_counts(sample_job: str):
    process_job(sample_job)
    job = get_job(sample_job)

    assert job.status == "completed"
    assert job.total_rows == 7
    assert job.processed_rows == 7
    assert job.valid_rows == 3
    assert job.invalid_rows == 3
    assert job.duplicate_rows == 1
    assert job.error_message is None
    assert job.started_at is not None and job.finished_at is not None
    assert job.duration_ms is not None and job.duration_ms > 0
    assert job.avg_row_ms is not None
    assert job.percent == 100.0


def test_rows_are_persisted_with_statuses_and_errors(sample_job: str):
    process_job(sample_job)
    with SessionLocal() as db:
        rows = db.query(Transaction).order_by(Transaction.row_number).all()

    assert [r.row_number for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert [r.status for r in rows] == [
        "valid", "valid", "invalid", "valid", "duplicate", "invalid", "invalid",
    ]
    assert rows[0].net_amount == 1349.97
    assert rows[4].net_amount is None  # duplicates must not double-count revenue
    assert json.loads(rows[4].errors)[0]["code"] == "DUPLICATE_ID"
    assert json.loads(rows[2].errors)[0]["code"] == "NEGATIVE_VALUE"
    assert json.loads(rows[5].errors)[0]["code"] == "NOT_A_NUMBER"
    assert json.loads(rows[6].errors)[0]["code"] == "FUTURE_DATE"
    assert json.loads(rows[0].raw)["region"] == "North"


def test_reports_persisted_for_every_kind(sample_job: str):
    process_job(sample_job)
    with SessionLocal() as db:
        reports = db.query(Report).filter(Report.job_id == sample_job).all()

    assert {r.kind for r in reports} == set(REPORT_KINDS)
    payloads = {r.kind: json.loads(r.payload) for r in reports}
    assert payloads["summary"]["transaction_count"] == 3
    assert payloads["summary"]["total_revenue"] == 1735.93  # 1349.97 + 186.00 + 199.96
    assert {item["key"] for item in payloads["by_region"]} == {"North", "South", "West"}
    assert len(payloads["top_transactions"]) == 3
    assert payloads["top_transactions"][0]["transaction_id"] == "TXN-1001"


def test_events_published(sample_job: str):
    process_job(sample_job)
    last = hub.last_message(sample_job)
    assert last is not None
    assert last["type"] == "completed"
    assert last["payload"]["valid_rows"] == 3
    assert last["payload"]["duplicate_rows"] == 1


# ------------------------------------------------------------------ aggregation


def test_aggregate_job_is_idempotent(sample_job: str):
    process_job(sample_job)
    first = aggregate_job(sample_job)
    second = aggregate_job(sample_job)

    assert first["summary"] == second["summary"]
    assert first["by_region"] == second["by_region"]
    assert first["trend_daily"] == second["trend_daily"]
    with SessionLocal() as db:
        assert db.query(Report).filter(Report.job_id == sample_job).count() == len(REPORT_KINDS)


def test_aggregate_job_accepts_an_existing_session(sample_job: str):
    process_job(sample_job)
    with SessionLocal() as db:
        report = aggregate_job(sample_job, db)
    assert report["job_id"] == sample_job
    assert report["generated_at"]
    assert report["summary"]["transaction_count"] == 3


def test_load_report_round_trip(sample_job: str):
    process_job(sample_job)
    stored = aggregate_job(sample_job)
    with SessionLocal() as db:
        loaded = load_report(sample_job, db)

    assert loaded is not None
    for key in ("summary", "by_region", "by_category", "trend_daily", "trend_monthly",
                "top_transactions"):
        assert loaded[key] == stored[key]


def test_load_report_returns_none_when_nothing_stored(tmp_path: Path):
    job_id = make_job(tmp_path / "never.csv", filename="never.csv")
    with SessionLocal() as db:
        assert load_report(job_id, db) is None


def test_reprocessing_does_not_duplicate_rows(sample_job: str):
    process_job(sample_job)
    process_job(sample_job)
    with SessionLocal() as db:
        assert db.query(Transaction).filter(Transaction.job_id == sample_job).count() == 7
        assert db.query(Report).filter(Report.job_id == sample_job).count() == len(REPORT_KINDS)
    job = get_job(sample_job)
    assert (job.valid_rows, job.invalid_rows, job.duplicate_rows) == (3, 3, 1)


# ---------------------------------------------------------------------- errors


def test_unparseable_file_fails_the_job_without_raising(tmp_path: Path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    job_id = make_job(path, filename="empty.csv")

    process_job(job_id)  # must not raise

    job = get_job(job_id)
    assert job.status == "failed"
    assert job.error_message
    assert hub.last_message(job_id)["type"] == "failed"


def test_missing_file_fails_the_job(tmp_path: Path):
    job_id = make_job(tmp_path / "gone.csv", filename="gone.csv")
    process_job(job_id)
    assert get_job(job_id).status == "failed"


def test_unknown_job_is_ignored():
    process_job("does-not-exist")  # must not raise


def test_json_input_is_processed(tmp_path: Path):
    payload = [
        {"transaction_id": "A", "region": "North", "product_category": "Toys",
         "quantity": 2, "unit_price": 10, "discount_percent": 50, "transaction_date": "2025-01-15"},
        {"transaction_id": "A", "region": "North", "product_category": "Toys",
         "quantity": 2, "unit_price": 10, "discount_percent": 50, "transaction_date": "2025-01-15"},
        {"transaction_id": "B", "region": "South", "product_category": "Toys",
         "quantity": 0, "unit_price": 10, "transaction_date": "2025-01-15"},
    ]
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    job_id = make_job(path, filename="rows.json")

    process_job(job_id)

    job = get_job(job_id)
    assert (job.status, job.valid_rows, job.duplicate_rows, job.invalid_rows) == ("completed", 1, 1, 1)
    with SessionLocal() as db:
        report = load_report(job_id, db)
    assert report["summary"]["total_revenue"] == 10.0


# ---------------------------------------------------------------------- events


def test_hub_is_a_noop_without_a_loop_but_records_the_last_message():
    from app.processing.events import EventHub

    h = EventHub()
    h.publish("j1", {"type": "status", "payload": {}})  # must not raise
    assert h.last_message("j1") == {"type": "status", "payload": {}}
    assert h.last_message("other") is None


def test_hub_delivers_to_subscribers_on_the_loop():
    import asyncio
    import threading

    from app.processing.events import EventHub

    async def main() -> None:
        h = EventHub(max_queue_size=2)
        h.bind_loop(asyncio.get_running_loop())
        queue = h.subscribe("j1")
        assert h.subscriber_count("j1") == 1

        worker = threading.Thread(target=h.publish, args=("j1", {"type": "progress", "n": 1}))
        worker.start()
        worker.join()

        message = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert message == {"type": "progress", "n": 1}

        h.unsubscribe("j1", queue)
        assert h.subscriber_count("j1") == 0
        h.publish("j1", {"type": "progress", "n": 2})  # no subscribers left

    asyncio.run(main())


def test_hub_drops_oldest_when_a_subscriber_is_full():
    import asyncio

    from app.processing.events import EventHub

    async def main() -> None:
        h = EventHub(max_queue_size=2)
        h.bind_loop(asyncio.get_running_loop())
        queue = h.subscribe("j1")
        for n in range(4):
            h.publish("j1", {"type": "progress", "n": n})
        await asyncio.sleep(0.05)

        assert queue.qsize() == 2
        assert [queue.get_nowait()["n"] for _ in range(2)] == [2, 3]

    asyncio.run(main())
