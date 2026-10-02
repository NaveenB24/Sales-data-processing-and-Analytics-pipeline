"""Aggregate analytics over validated rows (stdlib `statistics` only)."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, Protocol

from app.config import settings


class RowLike(Protocol):
    """Anything shaped like `app.models.Transaction` / `ValidatedRow`."""

    net_amount: float | None
    gross_amount: float | None
    discount_amount: float | None
    region: str | None
    product_category: str | None
    transaction_date: date | None
    transaction_id: str | None
    quantity: int | None
    unit_price: float | None
    discount_percent: float | None
    status: str


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def std_dev(values: Sequence[float]) -> float:
    """Sample standard deviation (n-1); 0.0 for fewer than two values."""
    return statistics.stdev(values) if len(values) > 1 else 0.0


def percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 2)


def _empty_summary() -> dict[str, Any]:
    return {
        "transaction_count": 0,
        "total_revenue": 0.0,
        "gross_revenue": 0.0,
        "discount_impact": 0.0,
        "discount_rate_pct": 0.0,
        "average_order_value": 0.0,
        "median_transaction_value": 0.0,
        "std_dev_order_value": 0.0,
        "coefficient_of_variation": 0.0,
        "variance_flag": False,
        "min_order_value": 0.0,
        "max_order_value": 0.0,
    }


def _breakdown(buckets: dict[str, dict[str, float]], total_revenue: float) -> list[dict[str, Any]]:
    items = [
        {
            "key": key,
            "revenue": round(agg["revenue"], 2),
            "transactions": int(agg["transactions"]),
            "share_pct": round(agg["revenue"] / total_revenue * 100.0, 2) if total_revenue else 0.0,
        }
        for key, agg in buckets.items()
    ]
    items.sort(key=lambda item: (-item["revenue"], item["key"]))
    return items


def _trend(buckets: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    previous: float | None = None
    for period in sorted(buckets):
        revenue = buckets[period]["revenue"]
        points.append(
            {
                "period": period,
                "revenue": round(revenue, 2),
                "transactions": int(buckets[period]["transactions"]),
                "change_pct": None if previous is None else percent_change(revenue, previous),
            }
        )
        previous = revenue
    return points


def compute_report(rows: Iterable[RowLike]) -> dict[str, Any]:
    """Full JSON-safe report for the `valid` rows of one job. Single pass over `rows`."""
    nets: list[float] = []
    gross_total = 0.0
    discount_total = 0.0
    by_region: dict[str, dict[str, float]] = {}
    by_category: dict[str, dict[str, float]] = {}
    daily: dict[str, dict[str, float]] = {}
    monthly: dict[str, dict[str, float]] = {}
    top: list[dict[str, Any]] = []

    for row in rows:
        if getattr(row, "status", None) != "valid":
            continue
        net = float(row.net_amount or 0.0)
        nets.append(net)
        gross_total += float(row.gross_amount or 0.0)
        discount_total += float(row.discount_amount or 0.0)

        for bucket, key in ((by_region, row.region), (by_category, row.product_category)):
            name = key or "Unknown"
            agg = bucket.setdefault(name, {"revenue": 0.0, "transactions": 0.0})
            agg["revenue"] += net
            agg["transactions"] += 1

        if row.transaction_date is not None:
            day = row.transaction_date.isoformat()
            month = day[:7]
            for bucket, period in ((daily, day), (monthly, month)):
                agg = bucket.setdefault(period, {"revenue": 0.0, "transactions": 0.0})
                agg["revenue"] += net
                agg["transactions"] += 1

        top.append(
            {
                "transaction_id": row.transaction_id,
                "region": row.region,
                "product_category": row.product_category,
                "quantity": row.quantity,
                "unit_price": round(float(row.unit_price), 2) if row.unit_price is not None else None,
                "discount_percent": (
                    round(float(row.discount_percent), 2) if row.discount_percent is not None else None
                ),
                "transaction_date": (
                    row.transaction_date.isoformat() if row.transaction_date is not None else None
                ),
                "net_amount": round(net, 2),
            }
        )
        top.sort(key=lambda item: item["net_amount"], reverse=True)
        del top[5:]

    if not nets:
        return {
            "summary": _empty_summary(),
            "by_region": [],
            "by_category": [],
            "trend_daily": [],
            "trend_monthly": [],
            "top_transactions": [],
        }

    total_revenue = sum(nets)
    avg = mean(nets)
    stddev = std_dev(nets)
    cv = stddev / avg if avg else 0.0

    summary = {
        "transaction_count": len(nets),
        "total_revenue": round(total_revenue, 2),
        "gross_revenue": round(gross_total, 2),
        "discount_impact": round(discount_total, 2),
        "discount_rate_pct": round(discount_total / gross_total * 100.0, 2) if gross_total else 0.0,
        "average_order_value": round(avg, 2),
        "median_transaction_value": round(median(nets), 2),
        "std_dev_order_value": round(stddev, 2),
        "coefficient_of_variation": round(cv, 2),
        "variance_flag": cv > settings.variance_cv_threshold,
        "min_order_value": round(min(nets), 2),
        "max_order_value": round(max(nets), 2),
    }

    return {
        "summary": summary,
        "by_region": _breakdown(by_region, total_revenue),
        "by_category": _breakdown(by_category, total_revenue),
        "trend_daily": _trend(daily),
        "trend_monthly": _trend(monthly),
        "top_transactions": top,
    }
