"""Cross-job reporting, metrics and the realtime channel."""

from __future__ import annotations

import pytest


def test_by_region_across_recent_jobs(client, auth, upload_sample):
    headers, _ = auth()
    for _ in range(2):
        upload_sample(headers)

    resp = client.get("/api/reports/by-region?limit=10", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    for entry in body:
        assert entry["status"] == "completed"
        assert {r["key"] for r in entry["by_region"]} == {"North", "South", "West"}


def test_by_region_is_scoped_to_the_caller(client, auth, upload_sample):
    alice, _ = auth(email="a@example.com")
    bob, _ = auth(email="b@example.com")
    upload_sample(alice)
    assert client.get("/api/reports/by-region", headers=bob).json() == []


def test_by_region_respects_limit(client, auth, upload_sample):
    headers, _ = auth()
    for _ in range(3):
        upload_sample(headers)
    assert len(client.get("/api/reports/by-region?limit=2", headers=headers).json()) == 2


def test_overview_aggregates_across_jobs(client, auth, upload_sample):
    headers, _ = auth()
    upload_sample(headers)
    upload_sample(headers)

    body = client.get("/api/reports/overview", headers=headers).json()
    assert body["jobs_total"] == 2
    assert body["completed_jobs"] == 2
    assert body["rows_processed"] == 14
    assert body["total_revenue"] == pytest.approx(1735.93 * 2, abs=0.05)
    assert body["discount_impact"] == pytest.approx(199.99 * 2, abs=0.05)
    north = next(r for r in body["by_region"] if r["key"] == "North")
    assert north["revenue"] == pytest.approx(1349.97 * 2, abs=0.05)
    assert north["transactions"] == 2


def test_overview_empty_for_new_user(client, auth):
    headers, _ = auth()
    body = client.get("/api/reports/overview", headers=headers).json()
    assert body == {
        "jobs_total": 0,
        "completed_jobs": 0,
        "rows_processed": 0,
        "total_revenue": 0.0,
        "discount_impact": 0.0,
        "by_region": [],
        "by_category": [],
    }


def test_metrics_scoped_for_user_and_global_for_admin(client, auth, upload_sample):
    admin, _ = auth(email="root3@example.com", role="admin")
    member, _ = auth(email="member3@example.com")
    upload_sample(member)

    mine = client.get("/api/metrics", headers=admin).json()
    assert mine["jobs_total"] == 1  # admin sees the whole system
    assert mine["rows_by_status"]["valid"] == 3

    theirs = client.get("/api/metrics", headers=member).json()
    assert theirs["jobs_total"] == 1
    assert theirs["jobs_by_status"]["completed"] == 1
    assert theirs["job_failure_rate"] == 0.0
    assert theirs["avg_row_processing_ms"] > 0
    assert theirs["rows_processed_total"] == 7
    assert theirs["uptime_seconds"] >= 0


def test_failure_rate_reflects_failed_jobs(client, auth):
    headers, _ = auth()
    from app.processing.queue import job_queue

    client.post(
        "/api/jobs/upload",
        headers=headers,
        files={"file": ("bad.json", b"<<<not json>>>", "application/json")},
    )
    assert job_queue.wait_idle(timeout=30.0)
    metrics = client.get("/api/metrics", headers=headers).json()
    assert metrics["job_failure_rate"] == 1.0


def test_admin_job_listing_names_the_owner(client, auth, upload_sample):
    admin, _ = auth(email="root4@example.com", role="admin")
    member, member_user = auth(email="member4@example.com")
    upload_sample(member)

    listing = client.get("/api/admin/jobs", headers=admin).json()
    job = next(j for j in listing["items"] if j["total_rows"] == 7)
    assert job["user_email"] == "member4@example.com"
    assert job["user_id"] == member_user["id"]
