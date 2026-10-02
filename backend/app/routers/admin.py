"""Administrator views and system-wide observability metrics."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.config import settings
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import Job, Transaction, User
from app.schemas import HealthOut, JobListOut, JobOut, SystemMetricsOut, UserOut

router = APIRouter(tags=["admin"])
_STARTED_AT = time.monotonic()


@router.get("/api/health", response_model=HealthOut)
def health(db: DbSession) -> HealthOut:
    try:
        db.execute(select(1))
        db_state = "ok"
    except Exception:  # pragma: no cover - only on a broken database file
        db_state = "error"
    return HealthOut(status="ok", version=settings.version, db=db_state)


@router.get("/api/metrics", response_model=SystemMetricsOut)
def metrics(user: CurrentUser, db: DbSession) -> SystemMetricsOut:
    """Operational metrics. Admins see the whole system, users see their own jobs."""
    scope = [] if user.role == "admin" else [Job.user_id == user.id]

    by_status = {
        status: count
        for status, count in db.execute(
            select(Job.status, func.count()).where(*scope).group_by(Job.status)
        ).all()
    }
    jobs_total = sum(by_status.values())
    failed = by_status.get("failed", 0)

    avg_row_ms = db.scalar(select(func.avg(Job.avg_row_ms)).where(*scope, Job.avg_row_ms.is_not(None)))
    avg_duration = db.scalar(
        select(func.avg(Job.duration_ms)).where(*scope, Job.duration_ms.is_not(None))
    )
    rows_total = db.scalar(select(func.sum(Job.processed_rows)).where(*scope)) or 0

    row_scope = (
        select(Transaction.status, func.count()).group_by(Transaction.status)
        if user.role == "admin"
        else select(Transaction.status, func.count())
        .join(Job, Job.id == Transaction.job_id)
        .where(Job.user_id == user.id)
        .group_by(Transaction.status)
    )
    rows_by_status = {s: c for s, c in db.execute(row_scope).all()}

    return SystemMetricsOut(
        jobs_total=jobs_total,
        jobs_by_status=by_status,
        job_failure_rate=round(failed / jobs_total, 4) if jobs_total else 0.0,
        avg_row_processing_ms=round(float(avg_row_ms or 0.0), 4),
        avg_job_duration_ms=round(float(avg_duration or 0.0), 2),
        rows_processed_total=int(rows_total),
        rows_by_status=rows_by_status,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 2),
    )


@router.get("/api/admin/users", response_model=list[UserOut])
def list_users(_admin: AdminUser, db: DbSession) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/api/admin/jobs", response_model=JobListOut)
def list_all_jobs(
    _admin: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListOut:
    total = db.scalar(select(func.count()).select_from(Job)) or 0
    jobs = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
    items = []
    for job in jobs:
        out = JobOut.model_validate(job)
        out.percent = job.percent
        items.append(out)
    return JobListOut(items=items, total=total)
