"""Cross-job reporting endpoints built on the persisted per-job reports."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Job, Report
from app.schemas import BreakdownItem, JobRegionReport, OverviewOut

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _payload(raw: str) -> object:
    try:
        return json.loads(raw or "null")
    except json.JSONDecodeError:
        return None


def _recent_job_ids(db, user_id: str, limit: int) -> list[str]:
    return list(
        db.scalars(
            select(Job.id)
            .where(Job.user_id == user_id, Job.status == "completed")
            .order_by(Job.created_at.desc())
            .limit(limit)
        ).all()
    )


def _merge(items: list[dict], bucket: dict[str, dict]) -> None:
    for entry in items:
        key = str(entry.get("key", "Unknown"))
        slot = bucket.setdefault(key, {"key": key, "revenue": 0.0, "transactions": 0})
        slot["revenue"] += float(entry.get("revenue") or 0.0)
        slot["transactions"] += int(entry.get("transactions") or 0)


def _finalize(bucket: dict[str, dict]) -> list[BreakdownItem]:
    total = sum(v["revenue"] for v in bucket.values())
    items = [
        BreakdownItem(
            key=v["key"],
            revenue=round(v["revenue"], 2),
            transactions=v["transactions"],
            share_pct=round(v["revenue"] / total * 100, 2) if total else 0.0,
        )
        for v in bucket.values()
    ]
    return sorted(items, key=lambda i: i.revenue, reverse=True)


@router.get("/by-region", response_model=list[JobRegionReport])
def revenue_by_region(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[JobRegionReport]:
    """Revenue-by-region reports for the caller's last N completed jobs.

    One indexed join — jobs(user_id, created_at) picks the jobs, the unique
    (job_id, kind) index on reports picks the stored payloads.
    """
    rows = db.execute(
        select(Job, Report.payload)
        .join(Report, (Report.job_id == Job.id) & (Report.kind == "by_region"))
        .where(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    ).all()

    out: list[JobRegionReport] = []
    for job, payload in rows:
        items = _payload(payload) or []
        out.append(
            JobRegionReport(
                job_id=job.id,
                original_filename=job.original_filename,
                created_at=job.created_at,
                status=job.status,
                by_region=[BreakdownItem(**i) for i in items if isinstance(i, dict)],
            )
        )
    return out


@router.get("/overview", response_model=OverviewOut)
def overview(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> OverviewOut:
    """Portfolio view across the caller's most recent completed jobs."""
    job_ids = _recent_job_ids(db, user.id, limit)
    all_jobs = db.scalars(select(Job).where(Job.user_id == user.id)).all()

    total_revenue = 0.0
    discount_impact = 0.0
    rows_processed = sum(j.processed_rows for j in all_jobs)
    region_bucket: dict[str, dict] = {}
    category_bucket: dict[str, dict] = {}

    if job_ids:
        reports = db.execute(
            select(Report.job_id, Report.kind, Report.payload).where(
                Report.job_id.in_(job_ids),
                Report.kind.in_(("summary", "by_region", "by_category")),
            )
        ).all()
        for _job_id, kind, payload in reports:
            data = _payload(payload)
            if kind == "summary" and isinstance(data, dict):
                total_revenue += float(data.get("total_revenue") or 0.0)
                discount_impact += float(data.get("discount_impact") or 0.0)
            elif kind == "by_region" and isinstance(data, list):
                _merge(data, region_bucket)
            elif kind == "by_category" and isinstance(data, list):
                _merge(data, category_bucket)

    return OverviewOut(
        jobs_total=len(all_jobs),
        completed_jobs=sum(1 for j in all_jobs if j.status == "completed"),
        rows_processed=rows_processed,
        total_revenue=round(total_revenue, 2),
        discount_impact=round(discount_impact, 2),
        by_region=_finalize(region_bucket),
        by_category=_finalize(category_bucket),
    )
