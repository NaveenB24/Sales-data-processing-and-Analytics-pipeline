"""Large-file behaviour: 10k rows end to end through the HTTP API."""

from __future__ import annotations

import io
import random
import time

import pytest

REGIONS = ("North", "South", "East", "West")
CATEGORIES = ("Electronics", "Groceries", "Apparel", "Home", "Sports")


def _make_csv(rows: int, seed: int = 7) -> bytes:
    rng = random.Random(seed)
    buf = io.StringIO()
    buf.write(
        "transaction_id,region,product_category,quantity,unit_price,discount_percent,transaction_date\n"
    )
    for i in range(rows):
        # Deterministic sprinkle of bad data: every 50th row is invalid,
        # every 97th repeats an earlier id.
        tx_id = f"TXN-{i % 97 if i % 97 == 0 and i else i:06d}"
        quantity = -1 if i % 50 == 0 else rng.randint(1, 20)
        day = 1 + (i % 28)
        month = 1 + (i % 6)
        buf.write(
            f"{tx_id},{rng.choice(REGIONS)},{rng.choice(CATEGORIES)},{quantity},"
            f"{rng.randint(5, 900)}.99,{rng.choice((0, 5, 10, 25))},2025-{month:02d}-{day:02d}\n"
        )
    return buf.getvalue().encode("utf-8")


@pytest.mark.slow
def test_ten_thousand_rows_end_to_end(client, auth):
    headers, _ = auth()
    from app.processing.queue import job_queue

    payload = _make_csv(10_000)
    started = time.perf_counter()
    job = client.post(
        "/api/jobs/upload", headers=headers, files={"file": ("big.csv", payload, "text/csv")}
    ).json()
    assert job_queue.wait_idle(timeout=300.0), "10k-row job did not finish in time"
    elapsed = time.perf_counter() - started

    final = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert final["status"] == "completed", final["error_message"]
    assert final["total_rows"] == 10_000
    assert final["processed_rows"] == 10_000
    assert final["valid_rows"] + final["invalid_rows"] + final["duplicate_rows"] == 10_000
    assert final["invalid_rows"] >= 200  # the seeded negative quantities

    # A sequential run would cost 10_000 * row delay; the pool must beat that
    # comfortably even including upload, inserts and aggregation.
    assert elapsed < 120, f"10k rows took {elapsed:.1f}s"

    report = client.get(f"/api/jobs/{job['id']}/report", headers=headers).json()
    assert report["summary"]["transaction_count"] == final["valid_rows"]
    assert report["summary"]["total_revenue"] > 0
    assert len(report["top_transactions"]) == 5
    assert len(report["by_region"]) == 4

    # Row explorer stays responsive on a large job.
    page = client.get(f"/api/jobs/{job['id']}/rows?limit=50&offset=5000", headers=headers).json()
    assert page["total"] == 10_000
    assert len(page["items"]) == 50

    export = client.get(f"/api/jobs/{job['id']}/export?format=csv", headers=headers)
    assert export.status_code == 200
    assert export.text.count("\n") >= 10_000
