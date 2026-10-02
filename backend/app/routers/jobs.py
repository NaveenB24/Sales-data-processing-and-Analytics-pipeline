"""Upload, job lifecycle, row inspection and export endpoints."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.config import settings
from app.deps import CurrentUser, DbSession, get_owned_job, upload_limiter
from app.logging_config import get_logger
from app.models import Job, Transaction
from app.processing.pipeline import aggregate_job, load_report
from app.processing.queue import job_queue
from app.processing.validation import ALL_COLUMNS
from app.schemas import (
    JobListOut,
    JobOut,
    ProgressOut,
    ReportOut,
    TransactionListOut,
    TransactionOut,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
log = get_logger("jobs")

ALLOWED_SUFFIXES = {".csv", ".json", ".ndjson", ".txt"}
ACTIVE_STATUSES = ("queued", "processing")

_CHUNK = 1024 * 1024


def _job_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.percent = job.percent
    return out


def _parse_errors(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw or "[]")
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


# --------------------------------------------------------------------- upload


@router.post("/upload", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def upload(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV or JSON sales transactions")],
    auto_process: Annotated[bool, Form()] = True,
) -> JobOut:
    allowed, retry_after = upload_limiter.allow(user.id)
    if not allowed:
        log.warning("rate_limit.exceeded", user_id=user.id, retry_after=retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload rate limit exceeded. Please retry shortly.",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )

    original_name = Path(file.filename or "upload.csv").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{suffix or 'unknown'}'. Upload a .csv or .json file.",
        )

    job_id = str(uuid.uuid4())
    stored_path = settings.upload_dir / f"{job_id}{suffix}"
    size = 0
    try:
        with stored_path.open("wb") as fh:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    fh.close()
                    stored_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
                    )
                fh.write(chunk)
    finally:
        await file.close()

    if size == 0:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    job = Job(
        id=job_id,
        user_id=user.id,
        original_filename=original_name,
        stored_path=str(stored_path),
        content_type=file.content_type or "text/csv",
        size_bytes=size,
        status="pending",
        correlation_id=str(uuid.uuid4()),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    log.info(
        "upload.received",
        job_id=job.id,
        user_id=user.id,
        filename=original_name,
        size_bytes=size,
        correlation_id=job.correlation_id,
    )

    if auto_process:
        job.status = "queued"
        db.commit()
        db.refresh(job)
        job_queue.enqueue(job.id)

    return _job_out(job)


# ----------------------------------------------------------------------- list


@router.get("", response_model=JobListOut)
def list_jobs(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    job_status: Annotated[str | None, Query(alias="status")] = None,
) -> JobListOut:
    conditions = [] if user.role == "admin" and job_status == "__all__" else [Job.user_id == user.id]
    if job_status and job_status != "__all__":
        conditions.append(Job.status == job_status)

    total = db.scalar(select(func.count()).select_from(Job).where(*conditions)) or 0
    rows = db.scalars(
        select(Job).where(*conditions).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return JobListOut(items=[_job_out(j) for j in rows], total=total)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: CurrentUser, db: DbSession) -> JobOut:
    return _job_out(get_owned_job(job_id, db, user))


@router.get("/{job_id}/progress", response_model=ProgressOut)
def get_progress(job_id: str, user: CurrentUser, db: DbSession) -> ProgressOut:
    job = get_owned_job(job_id, db, user)
    db.refresh(job)
    return ProgressOut(
        job_id=job.id,
        status=job.status,
        total_rows=job.total_rows,
        processed_rows=job.processed_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        duplicate_rows=job.duplicate_rows,
        percent=job.percent,
        error_message=job.error_message,
    )


# -------------------------------------------------------------------- actions


@router.post("/{job_id}/process", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def process(job_id: str, user: CurrentUser, db: DbSession) -> JobOut:
    job = get_owned_job(job_id, db, user)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Job is already {job.status}."
        )
    if not Path(job.stored_path).exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="The uploaded file is no longer available."
        )
    job.status = "queued"
    job.error_message = None
    job.processed_rows = 0
    db.commit()
    db.refresh(job)
    job_queue.enqueue(job.id)
    log.info("job.queued", job_id=job.id, user_id=user.id, correlation_id=job.correlation_id)
    return _job_out(job)


@router.post("/{job_id}/reaggregate", response_model=ReportOut)
def reaggregate(job_id: str, user: CurrentUser, db: DbSession) -> ReportOut:
    job = get_owned_job(job_id, db, user)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot re-aggregate while the job is still processing.",
        )
    report = aggregate_job(job.id, db)
    log.info("job.reaggregated", job_id=job.id, user_id=user.id)
    return ReportOut.model_validate(report)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str, user: CurrentUser, db: DbSession) -> Response:
    job = get_owned_job(job_id, db, user)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot delete a job that is still running."
        )
    Path(job.stored_path).unlink(missing_ok=True)
    db.delete(job)
    db.commit()
    log.info("job.deleted", job_id=job_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- rows & report


@router.get("/{job_id}/rows", response_model=TransactionListOut)
def list_rows(
    job_id: str,
    user: CurrentUser,
    db: DbSession,
    row_status: Annotated[str | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionListOut:
    job = get_owned_job(job_id, db, user)
    conditions = [Transaction.job_id == job.id]
    if row_status in ("valid", "invalid", "duplicate"):
        conditions.append(Transaction.status == row_status)
    if q:
        needle = f"%{q.strip()}%"
        conditions.append(
            or_(
                Transaction.transaction_id.ilike(needle),
                Transaction.region.ilike(needle),
                Transaction.product_category.ilike(needle),
            )
        )

    total = db.scalar(select(func.count()).select_from(Transaction).where(*conditions)) or 0
    rows = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.row_number)
        .limit(limit)
        .offset(offset)
    ).all()

    # `errors` is a JSON text column, so the ORM object cannot be validated
    # wholesale — the list has to be decoded first.
    items = [
        TransactionOut(
            id=row.id,
            row_number=row.row_number,
            transaction_id=row.transaction_id,
            region=row.region,
            product_category=row.product_category,
            quantity=row.quantity,
            unit_price=row.unit_price,
            discount_percent=row.discount_percent,
            transaction_date=row.transaction_date,
            gross_amount=row.gross_amount,
            discount_amount=row.discount_amount,
            net_amount=row.net_amount,
            status=row.status,
            errors=_parse_errors(row.errors),
        )
        for row in rows
    ]
    return TransactionListOut(items=items, total=total)


@router.get("/{job_id}/report", response_model=ReportOut)
def get_report(job_id: str, user: CurrentUser, db: DbSession) -> ReportOut:
    job = get_owned_job(job_id, db, user)
    report = load_report(job.id, db)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No report yet — run processing for this job first.",
        )
    return ReportOut.model_validate(report)


# -------------------------------------------------------------------- export

EXPORT_HEADER = (*ALL_COLUMNS, "row_number", "status", "gross_amount", "discount_amount", "net_amount", "errors")


@router.get("/{job_id}/export")
def export_rows(
    job_id: str,
    user: CurrentUser,
    db: DbSession,
    fmt: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
) -> StreamingResponse:
    job = get_owned_job(job_id, db, user)
    stem = Path(job.original_filename).stem or "results"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    def _rows():
        # yield_per keeps a 10k+ row export at constant memory.
        yield from db.scalars(
            select(Transaction)
            .where(Transaction.job_id == job.id)
            .order_by(Transaction.row_number)
            .execution_options(yield_per=500)
        )

    if fmt == "json":

        def _json_stream():
            yield '{"job_id":%s,"original_filename":%s,"rows":[' % (
                json.dumps(job.id),
                json.dumps(job.original_filename),
            )
            first = True
            for row in _rows():
                payload = {
                    "row_number": row.row_number,
                    "transaction_id": row.transaction_id,
                    "region": row.region,
                    "product_category": row.product_category,
                    "quantity": row.quantity,
                    "unit_price": row.unit_price,
                    "discount_percent": row.discount_percent,
                    "transaction_date": row.transaction_date.isoformat() if row.transaction_date else None,
                    "gross_amount": row.gross_amount,
                    "discount_amount": row.discount_amount,
                    "net_amount": row.net_amount,
                    "status": row.status,
                    "errors": _parse_errors(row.errors),
                }
                yield ("" if first else ",") + json.dumps(payload)
                first = False
            yield "]}"

        return StreamingResponse(
            _json_stream(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{stem}-{stamp}.json"'},
        )

    def _csv_stream():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_HEADER)
        for row in _rows():
            raw = {}
            try:
                raw = json.loads(row.raw or "{}")
            except json.JSONDecodeError:
                raw = {}
            errors = "; ".join(
                f"{e.get('code')}:{e.get('message')}" for e in _parse_errors(row.errors)
            )
            writer.writerow(
                [
                    row.transaction_id if row.transaction_id is not None else raw.get("transaction_id", ""),
                    row.region if row.region is not None else raw.get("region", ""),
                    row.product_category
                    if row.product_category is not None
                    else raw.get("product_category", ""),
                    row.quantity if row.quantity is not None else raw.get("quantity", ""),
                    row.unit_price if row.unit_price is not None else raw.get("unit_price", ""),
                    row.discount_percent
                    if row.discount_percent is not None
                    else raw.get("discount_percent", ""),
                    row.transaction_date.isoformat()
                    if row.transaction_date
                    else raw.get("transaction_date", ""),
                    row.row_number,
                    row.status,
                    row.gross_amount if row.gross_amount is not None else "",
                    row.discount_amount if row.discount_amount is not None else "",
                    row.net_amount if row.net_amount is not None else "",
                    errors,
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        _csv_stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}-{stamp}.csv"'},
    )
