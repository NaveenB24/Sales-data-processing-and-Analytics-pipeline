"""Pydantic request/response models — the wire contract for the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import settings

# --------------------------------------------------------------------------- auth


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < settings.password_min_length:
            raise ValueError(f"password must be at least {settings.password_min_length} characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------------------- jobs


JobStatus = Literal["pending", "queued", "processing", "completed", "failed"]
RowStatus = Literal["valid", "invalid", "duplicate"]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    status: JobStatus
    total_rows: int
    processed_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    size_bytes: int
    error_message: str | None = None
    correlation_id: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None
    avg_row_ms: float | None = None
    percent: float = 0.0


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int


class ProgressOut(BaseModel):
    job_id: str
    status: JobStatus
    total_rows: int
    processed_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    percent: float
    error_message: str | None = None


class RowErrorOut(BaseModel):
    field: str | None = None
    code: str
    message: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row_number: int
    transaction_id: str | None = None
    region: str | None = None
    product_category: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    discount_percent: float | None = None
    transaction_date: date | None = None
    gross_amount: float | None = None
    discount_amount: float | None = None
    net_amount: float | None = None
    status: RowStatus
    errors: list[RowErrorOut] = Field(default_factory=list)


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int


# --------------------------------------------------------------------------- reports


class BreakdownItem(BaseModel):
    key: str
    revenue: float
    transactions: int
    share_pct: float


class TrendPoint(BaseModel):
    period: str
    revenue: float
    transactions: int
    change_pct: float | None = None


class TopTransaction(BaseModel):
    transaction_id: str | None = None
    region: str | None = None
    product_category: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    discount_percent: float | None = None
    transaction_date: date | None = None
    net_amount: float


class SummaryMetrics(BaseModel):
    transaction_count: int = 0
    total_revenue: float = 0.0
    gross_revenue: float = 0.0
    discount_impact: float = 0.0
    discount_rate_pct: float = 0.0
    average_order_value: float = 0.0
    median_transaction_value: float = 0.0
    std_dev_order_value: float = 0.0
    coefficient_of_variation: float = 0.0
    variance_flag: bool = False
    min_order_value: float = 0.0
    max_order_value: float = 0.0


class ReportOut(BaseModel):
    job_id: str
    generated_at: datetime
    summary: SummaryMetrics
    by_region: list[BreakdownItem] = Field(default_factory=list)
    by_category: list[BreakdownItem] = Field(default_factory=list)
    trend_daily: list[TrendPoint] = Field(default_factory=list)
    trend_monthly: list[TrendPoint] = Field(default_factory=list)
    top_transactions: list[TopTransaction] = Field(default_factory=list)


class JobRegionReport(BaseModel):
    job_id: str
    original_filename: str
    created_at: datetime
    status: JobStatus
    by_region: list[BreakdownItem] = Field(default_factory=list)


class OverviewOut(BaseModel):
    jobs_total: int
    completed_jobs: int
    rows_processed: int
    total_revenue: float
    discount_impact: float
    by_region: list[BreakdownItem] = Field(default_factory=list)
    by_category: list[BreakdownItem] = Field(default_factory=list)


class SystemMetricsOut(BaseModel):
    jobs_total: int
    jobs_by_status: dict[str, int]
    job_failure_rate: float
    avg_row_processing_ms: float
    avg_job_duration_ms: float
    rows_processed_total: int
    rows_by_status: dict[str, int]
    uptime_seconds: float


class HealthOut(BaseModel):
    status: str
    version: str
    db: str


class MessageOut(BaseModel):
    detail: str


class WSMessage(BaseModel):
    type: Literal["progress", "status", "completed", "failed", "ping"]
    payload: dict[str, Any] = Field(default_factory=dict)
