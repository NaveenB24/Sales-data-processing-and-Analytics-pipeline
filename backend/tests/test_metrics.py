"""Unit tests for the aggregate metrics (SPEC 2.5)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pytest

from app.config import settings
from app.processing.metrics import compute_report, mean, median, percent_change, std_dev


@dataclass
class Row:
    """Minimal RowLike stand-in."""

    net_amount: float | None = 0.0
    gross_amount: float | None = None
    discount_amount: float | None = 0.0
    region: str | None = "North"
    product_category: str | None = "Electronics"
    transaction_date: date | None = date(2025, 1, 15)
    transaction_id: str | None = "TXN-1"
    quantity: int | None = 1
    unit_price: float | None = None
    discount_percent: float | None = 0.0
    status: str = "valid"

    def __post_init__(self) -> None:
        if self.gross_amount is None:
            self.gross_amount = self.net_amount
        if self.unit_price is None:
            self.unit_price = self.net_amount


# ----------------------------------------------------------------- primitives


def test_mean():
    assert mean([2, 4, 4, 4, 5, 5, 7, 9]) == 5.0
    assert mean([1.5, 2.5]) == 2.0
    assert mean([]) == 0.0


def test_median_odd_and_even():
    assert median([10, 1, 3]) == 3.0
    assert median([1, 3, 5, 9]) == 4.0
    assert median([]) == 0.0


def test_sample_std_dev():
    # sample stdev of [2,4,4,4,5,5,7,9] is sqrt(32/7)
    assert std_dev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(math.sqrt(32 / 7))
    assert std_dev([5]) == 0.0
    assert std_dev([]) == 0.0
    assert std_dev([10, 20]) == pytest.approx(math.sqrt(50))


def test_percent_change():
    assert percent_change(150, 100) == 50.0
    assert percent_change(50, 100) == -50.0
    assert percent_change(100, 100) == 0.0
    assert percent_change(10, 0) is None


# -------------------------------------------------------------------- summary


def test_empty_input():
    report = compute_report([])
    assert report["summary"]["transaction_count"] == 0
    assert report["summary"]["total_revenue"] == 0.0
    assert report["summary"]["median_transaction_value"] == 0.0
    assert report["summary"]["std_dev_order_value"] == 0.0
    assert report["summary"]["variance_flag"] is False
    for key in ("by_region", "by_category", "trend_daily", "trend_monthly", "top_transactions"):
        assert report[key] == []


def test_only_valid_rows_are_counted():
    rows = [
        Row(net_amount=100.0),
        Row(net_amount=999.0, status="invalid"),
        Row(net_amount=999.0, status="duplicate"),
    ]
    summary = compute_report(rows)["summary"]
    assert summary["transaction_count"] == 1
    assert summary["total_revenue"] == 100.0


def test_summary_numbers():
    rows = [
        Row(net_amount=90.0, gross_amount=100.0, discount_amount=10.0),
        Row(net_amount=180.0, gross_amount=200.0, discount_amount=20.0),
        Row(net_amount=270.0, gross_amount=300.0, discount_amount=30.0),
    ]
    summary = compute_report(rows)["summary"]
    assert summary["transaction_count"] == 3
    assert summary["total_revenue"] == 540.0
    assert summary["gross_revenue"] == 600.0
    assert summary["discount_impact"] == 60.0
    assert summary["discount_rate_pct"] == 10.0
    assert summary["average_order_value"] == 180.0
    assert summary["median_transaction_value"] == 180.0
    assert summary["std_dev_order_value"] == 90.0
    assert summary["min_order_value"] == 90.0
    assert summary["max_order_value"] == 270.0
    assert summary["coefficient_of_variation"] == 0.5
    assert summary["variance_flag"] is False


def test_variance_flag_trips_above_threshold():
    rows = [Row(net_amount=1.0), Row(net_amount=1.0), Row(net_amount=100.0)]
    summary = compute_report(rows)["summary"]
    assert summary["coefficient_of_variation"] > settings.variance_cv_threshold
    assert summary["variance_flag"] is True


# ----------------------------------------------------------------- breakdowns


def test_breakdowns_sorted_with_shares_summing_to_100():
    rows = [
        Row(net_amount=100.0, region="North", product_category="Electronics"),
        Row(net_amount=300.0, region="South", product_category="Groceries"),
        Row(net_amount=100.0, region="North", product_category="Electronics"),
    ]
    report = compute_report(rows)

    by_region = report["by_region"]
    assert [item["key"] for item in by_region] == ["South", "North"]
    assert by_region[0] == {"key": "South", "revenue": 300.0, "transactions": 1, "share_pct": 60.0}
    assert by_region[1]["transactions"] == 2
    assert sum(item["share_pct"] for item in by_region) == pytest.approx(100.0, abs=0.05)
    assert sum(item["share_pct"] for item in report["by_category"]) == pytest.approx(100.0, abs=0.05)


# --------------------------------------------------------------------- trends


def test_daily_and_monthly_trends():
    rows = [
        Row(net_amount=100.0, transaction_date=date(2025, 1, 10)),
        Row(net_amount=150.0, transaction_date=date(2025, 1, 11)),
        Row(net_amount=75.0, transaction_date=date(2025, 2, 1)),
    ]
    report = compute_report(rows)

    daily = report["trend_daily"]
    assert [p["period"] for p in daily] == ["2025-01-10", "2025-01-11", "2025-02-01"]
    assert daily[0]["change_pct"] is None
    assert daily[1]["change_pct"] == 50.0
    assert daily[2]["change_pct"] == -50.0
    assert daily[1]["transactions"] == 1

    monthly = report["trend_monthly"]
    assert [p["period"] for p in monthly] == ["2025-01", "2025-02"]
    assert monthly[0]["revenue"] == 250.0
    assert monthly[0]["change_pct"] is None
    assert monthly[1]["change_pct"] == -70.0


def test_rows_without_a_date_are_left_out_of_trends():
    report = compute_report([Row(net_amount=10.0, transaction_date=None)])
    assert report["trend_daily"] == []
    assert report["summary"]["transaction_count"] == 1


# ------------------------------------------------------------------- top five


def test_top_transactions_ordered_and_truncated():
    rows = [Row(net_amount=float(i), transaction_id=f"T-{i}") for i in range(1, 9)]
    top = compute_report(rows)["top_transactions"]
    assert len(top) == 5
    assert [t["transaction_id"] for t in top] == ["T-8", "T-7", "T-6", "T-5", "T-4"]
    assert [t["net_amount"] for t in top] == [8.0, 7.0, 6.0, 5.0, 4.0]


def test_report_is_json_safe():
    import json

    rows = [Row(net_amount=10.0, transaction_date=date(2025, 3, 4))]
    report = compute_report(rows)
    assert json.loads(json.dumps(report))["top_transactions"][0]["transaction_date"] == "2025-03-04"


def test_shape_matches_schemas():
    from app.schemas import BreakdownItem, SummaryMetrics, TopTransaction, TrendPoint

    rows = [
        Row(net_amount=90.0, gross_amount=100.0, discount_amount=10.0, transaction_date=date(2025, 1, 1)),
        Row(net_amount=45.0, gross_amount=50.0, discount_amount=5.0, transaction_date=date(2025, 2, 1)),
    ]
    report = compute_report(rows)
    assert set(report) == {"summary", "by_region", "by_category", "trend_daily",
                           "trend_monthly", "top_transactions"}
    SummaryMetrics(**report["summary"])
    [BreakdownItem(**item) for item in report["by_region"] + report["by_category"]]
    [TrendPoint(**p) for p in report["trend_daily"] + report["trend_monthly"]]
    [TopTransaction(**t) for t in report["top_transactions"]]
