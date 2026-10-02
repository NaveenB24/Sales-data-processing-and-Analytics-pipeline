"""Upload → process → inspect → export lifecycle over the HTTP API."""

from __future__ import annotations

import csv
import io
import json

import pytest

from tests.conftest import SAMPLE_CSV


def test_upload_requires_authentication(client):
    resp = client.post("/api/jobs/upload", files={"file": ("a.csv", b"x", "text/csv")})
    assert resp.status_code == 401


def test_upload_rejects_unsupported_extension(client, auth):
    headers, _ = auth()
    resp = client.post(
        "/api/jobs/upload", headers=headers, files={"file": ("payload.exe", b"MZ", "application/octet-stream")}
    )
    assert resp.status_code == 415


def test_upload_rejects_empty_file(client, auth):
    headers, _ = auth()
    resp = client.post("/api/jobs/upload", headers=headers, files={"file": ("empty.csv", b"", "text/csv")})
    assert resp.status_code == 400


def test_sample_file_produces_expected_counts(client, auth, upload_sample):
    """SPEC §7 acceptance: 3 valid, 3 invalid, 1 duplicate, no crash."""
    headers, _ = auth()
    job = upload_sample(headers)

    assert job["status"] == "completed"
    assert job["total_rows"] == 7
    assert job["processed_rows"] == 7
    assert job["valid_rows"] == 3
    assert job["invalid_rows"] == 3
    assert job["duplicate_rows"] == 1
    assert job["percent"] == 100.0
    assert job["duration_ms"] is not None


def test_row_explorer_filters_and_flags_errors(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)

    all_rows = client.get(f"/api/jobs/{job['id']}/rows", headers=headers).json()
    assert all_rows["total"] == 7

    invalid = client.get(f"/api/jobs/{job['id']}/rows?status=invalid", headers=headers).json()
    assert invalid["total"] == 3
    codes = {e["code"] for row in invalid["items"] for e in row["errors"]}
    assert {"NEGATIVE_VALUE", "NOT_A_NUMBER", "FUTURE_DATE"} <= codes

    duplicates = client.get(f"/api/jobs/{job['id']}/rows?status=duplicate", headers=headers).json()
    assert duplicates["total"] == 1
    assert duplicates["items"][0]["transaction_id"] == "TXN-1005"
    assert duplicates["items"][0]["errors"][0]["code"] == "DUPLICATE_ID"

    searched = client.get(f"/api/jobs/{job['id']}/rows?q=Groceries", headers=headers).json()
    assert searched["total"] == 2


def test_report_matches_hand_computed_revenue(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    report = client.get(f"/api/jobs/{job['id']}/report", headers=headers).json()

    # valid rows: 3*499.99*0.9 = 1349.97 | 12*15.50 = 186.00 | 5*49.99*0.8 = 199.96
    summary = report["summary"]
    assert summary["transaction_count"] == 3
    assert summary["total_revenue"] == pytest.approx(1735.93, abs=0.01)
    assert summary["gross_revenue"] == pytest.approx(1836.42, abs=0.01)
    assert summary["discount_impact"] == pytest.approx(100.49, abs=0.01)
    assert summary["average_order_value"] == pytest.approx(578.64, abs=0.01)
    assert summary["median_transaction_value"] == pytest.approx(199.96, abs=0.01)
    assert summary["max_order_value"] == pytest.approx(1349.97, abs=0.01)

    regions = {r["key"]: r["revenue"] for r in report["by_region"]}
    assert regions == pytest.approx({"North": 1349.97, "South": 186.00, "West": 199.96}, abs=0.01)
    assert sum(r["share_pct"] for r in report["by_region"]) == pytest.approx(100.0, abs=0.1)

    categories = {c["key"] for c in report["by_category"]}
    assert categories == {"Electronics", "Groceries", "Apparel"}

    assert [t["transaction_id"] for t in report["top_transactions"]] == ["TXN-1001", "TXN-1004", "TXN-1002"]
    assert len(report["trend_daily"]) == 2
    assert report["trend_daily"][0]["change_pct"] is None
    assert report["trend_monthly"][0]["period"] == "2025-01"


def test_report_404_before_processing(client, auth):
    headers, _ = auth()
    job = client.post(
        "/api/jobs/upload",
        headers=headers,
        files={"file": ("later.csv", SAMPLE_CSV.encode(), "text/csv")},
        data={"auto_process": "false"},
    ).json()
    assert job["status"] == "pending"
    assert client.get(f"/api/jobs/{job['id']}/report", headers=headers).status_code == 404


def test_manual_process_and_reaggregate(client, auth):
    headers, _ = auth()
    from app.processing.queue import job_queue

    job = client.post(
        "/api/jobs/upload",
        headers=headers,
        files={"file": ("manual.csv", SAMPLE_CSV.encode(), "text/csv")},
        data={"auto_process": "false"},
    ).json()

    queued = client.post(f"/api/jobs/{job['id']}/process", headers=headers)
    assert queued.status_code == 202
    assert job_queue.wait_idle(timeout=30.0)

    done = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert done["status"] == "completed"

    before = client.get(f"/api/jobs/{job['id']}/report", headers=headers).json()["summary"]
    again = client.post(f"/api/jobs/{job['id']}/reaggregate", headers=headers)
    assert again.status_code == 200
    assert again.json()["summary"]["total_revenue"] == before["total_revenue"]


def test_reprocessing_is_idempotent(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    from app.processing.queue import job_queue

    client.post(f"/api/jobs/{job['id']}/process", headers=headers)
    assert job_queue.wait_idle(timeout=30.0)
    again = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert (again["total_rows"], again["valid_rows"], again["invalid_rows"]) == (7, 3, 3)
    assert client.get(f"/api/jobs/{job['id']}/rows", headers=headers).json()["total"] == 7


def test_malformed_file_fails_the_job_without_crashing(client, auth):
    headers, _ = auth()
    from app.processing.queue import job_queue

    client.post(
        "/api/jobs/upload",
        headers=headers,
        files={"file": ("broken.json", b"{not valid json", "application/json")},
        data={"auto_process": "true"},
    )
    assert job_queue.wait_idle(timeout=30.0)
    job = client.get("/api/jobs", headers=headers).json()["items"][0]
    assert job["status"] == "failed"
    assert job["error_message"]
    # the API stays healthy afterwards
    assert client.get("/api/health").status_code == 200


def test_progress_endpoint(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    progress = client.get(f"/api/jobs/{job['id']}/progress", headers=headers).json()
    assert progress["percent"] == 100.0
    assert progress["status"] == "completed"
    assert progress["processed_rows"] == 7


def test_export_csv_annotates_every_row(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    resp = client.get(f"/api/jobs/{job['id']}/export?format=csv", headers=headers)
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 7
    statuses = [r["status"] for r in rows]
    assert statuses.count("valid") == 3 and statuses.count("invalid") == 3 and statuses.count("duplicate") == 1
    bad = next(r for r in rows if r["transaction_id"] == "TXN-1006")
    assert "NOT_A_NUMBER" in bad["errors"]
    good = next(r for r in rows if r["transaction_id"] == "TXN-1001")
    assert float(good["net_amount"]) == pytest.approx(1349.97, abs=0.01)


def test_export_json(client, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    resp = client.get(f"/api/jobs/{job['id']}/export?format=json", headers=headers)
    payload = json.loads(resp.text)
    assert payload["job_id"] == job["id"]
    assert len(payload["rows"]) == 7


def test_json_upload_is_supported(client, auth):
    headers, _ = auth()
    from app.processing.queue import job_queue

    body = json.dumps(
        [
            {
                "transaction_id": "J-1",
                "region": "North",
                "product_category": "Toys",
                "quantity": 2,
                "unit_price": 10.0,
                "discount_percent": 50,
                "transaction_date": "2025-02-01",
            }
        ]
    ).encode()
    job = client.post(
        "/api/jobs/upload", headers=headers, files={"file": ("rows.json", body, "application/json")}
    ).json()
    assert job_queue.wait_idle(timeout=30.0)
    report = client.get(f"/api/jobs/{job['id']}/report", headers=headers).json()
    assert report["summary"]["total_revenue"] == pytest.approx(10.0, abs=0.01)


def test_jobs_are_isolated_between_users(client, auth, upload_sample):
    alice, _ = auth(email="alice@example.com")
    bob, _ = auth(email="bob@example.com")
    job = upload_sample(alice)

    assert client.get("/api/jobs", headers=bob).json()["total"] == 0
    for path in (
        f"/api/jobs/{job['id']}",
        f"/api/jobs/{job['id']}/rows",
        f"/api/jobs/{job['id']}/report",
        f"/api/jobs/{job['id']}/progress",
        f"/api/jobs/{job['id']}/export",
    ):
        assert client.get(path, headers=bob).status_code == 404, path
    assert client.post(f"/api/jobs/{job['id']}/process", headers=bob).status_code == 404
    assert client.delete(f"/api/jobs/{job['id']}", headers=bob).status_code == 404
    # owner still has it
    assert client.get(f"/api/jobs/{job['id']}", headers=alice).status_code == 200


def test_admin_can_read_another_users_job(client, auth, upload_sample):
    admin, _ = auth(email="root2@example.com", role="admin")
    member, _ = auth(email="member2@example.com")
    job = upload_sample(member)
    assert client.get(f"/api/jobs/{job['id']}", headers=admin).status_code == 200


def test_delete_removes_job_rows_and_reports(client, db, auth, upload_sample):
    headers, _ = auth()
    job = upload_sample(headers)
    from app.models import Report, Transaction

    assert client.delete(f"/api/jobs/{job['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).status_code == 404
    assert db.query(Transaction).filter(Transaction.job_id == job["id"]).count() == 0
    assert db.query(Report).filter(Report.job_id == job["id"]).count() == 0


def test_job_list_pagination_and_status_filter(client, auth, upload_sample):
    headers, _ = auth()
    for _ in range(3):
        upload_sample(headers)
    page = client.get("/api/jobs?limit=2&offset=0", headers=headers).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    completed = client.get("/api/jobs?status=completed", headers=headers).json()
    assert completed["total"] == 3
    assert client.get("/api/jobs?status=failed", headers=headers).json()["total"] == 0


def test_upload_rate_limit_returns_429(client, auth, monkeypatch):
    headers, _ = auth()
    from app.deps import upload_limiter

    monkeypatch.setattr(upload_limiter, "capacity", 2)
    monkeypatch.setattr(upload_limiter, "window_seconds", 60.0)
    upload_limiter.reset()

    codes = []
    for _ in range(3):
        resp = client.post(
            "/api/jobs/upload",
            headers=headers,
            files={"file": ("rl.csv", SAMPLE_CSV.encode(), "text/csv")},
            data={"auto_process": "false"},
        )
        codes.append(resp.status_code)
        if resp.status_code == 429:
            assert resp.headers.get("Retry-After")
    assert codes[-1] == 429
