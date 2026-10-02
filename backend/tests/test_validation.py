"""Unit tests for row parsing and validation (SPEC 2.1-2.3)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.processing.validation import (
    ALL_COLUMNS,
    REQUIRED_COLUMNS,
    DuplicateTracker,
    RowError,
    apply_duplicate,
    count_data_rows,
    normalize_header,
    parse_file,
    validate_row,
)

TODAY = date(2025, 6, 1)


def good_row(**overrides: str) -> dict[str, str]:
    row = {
        "transaction_id": "TXN-1001",
        "region": "North",
        "product_category": "Electronics",
        "quantity": "3",
        "unit_price": "499.99",
        "discount_percent": "10",
        "transaction_date": "2025-01-15",
    }
    row.update(overrides)
    return row


def codes(row) -> list[str]:
    return [e.code for e in row.errors]


# --------------------------------------------------------------------- columns


def test_column_constants():
    assert REQUIRED_COLUMNS == (
        "transaction_id",
        "region",
        "product_category",
        "quantity",
        "unit_price",
        "transaction_date",
    )
    assert ALL_COLUMNS == (
        "transaction_id",
        "region",
        "product_category",
        "quantity",
        "unit_price",
        "discount_percent",
        "transaction_date",
    )
    assert "discount_percent" not in REQUIRED_COLUMNS


@pytest.mark.parametrize(
    "raw,expected",
    [
        (" Transaction ID ", "transaction_id"),
        ("Product-Category", "product_category"),
        ("﻿TRANSACTION_ID", "transaction_id"),
        ("unit price", "unit_price"),
    ],
)
def test_normalize_header(raw: str, expected: str):
    assert normalize_header(raw) == expected


# ------------------------------------------------------------------ happy path


def test_valid_row_arithmetic():
    row = validate_row(good_row(), 1, today=TODAY)
    assert row.status == "valid"
    assert row.errors == []
    assert row.quantity == 3
    assert row.unit_price == 499.99
    assert row.transaction_date == date(2025, 1, 15)
    assert row.gross_amount == 1499.97
    assert row.discount_amount == 150.0
    assert row.net_amount == 1349.97  # 3 x 499.99 x 0.9


def test_blank_discount_defaults_to_zero():
    row = validate_row(good_row(discount_percent=""), 2, today=TODAY)
    assert row.status == "valid"
    assert row.discount_percent == 0.0
    assert row.net_amount == row.gross_amount == 1499.97


def test_absent_discount_column_is_optional():
    raw = good_row()
    raw.pop("discount_percent")
    row = validate_row(raw, 3, today=TODAY)
    assert row.status == "valid"
    assert row.discount_percent == 0.0


def test_headers_are_normalized_inside_validate_row():
    raw = {"Transaction ID": "TXN-9", "Region": "North", "Product-Category": "Toys",
           "QUANTITY": "2", "unit price": "10", "Transaction Date": "2025-01-15"}
    row = validate_row(raw, 1, today=TODAY)
    assert row.status == "valid"
    assert row.net_amount == 20.0


def test_date_formats_accepted():
    for value, expected in [
        ("2025-01-15", date(2025, 1, 15)),
        ("15/01/2025", date(2025, 1, 15)),
        ("01/15/2025", date(2025, 1, 15)),
        ("2025-01-15T10:30:00Z", date(2025, 1, 15)),
    ]:
        row = validate_row(good_row(transaction_date=value), 1, today=TODAY)
        assert row.status == "valid", (value, codes(row))
        assert row.transaction_date == expected


def test_today_defaults_to_utc_today():
    row = validate_row(good_row(transaction_date="2025-01-15"), 1)
    assert row.status == "valid"


# ----------------------------------------------------------------- error codes


@pytest.mark.parametrize("field", ["transaction_id", "region", "product_category", "quantity",
                                   "unit_price", "transaction_date"])
def test_missing_field(field: str):
    row = validate_row(good_row(**{field: "   "}), 1, today=TODAY)
    assert row.status == "invalid"
    assert "MISSING_FIELD" in codes(row)
    assert any(e.field == field for e in row.errors)
    assert row.net_amount is None


@pytest.mark.parametrize("field,value", [("quantity", "abc"), ("unit_price", "abc"),
                                         ("discount_percent", "abc"), ("quantity", "2.5")])
def test_not_a_number(field: str, value: str):
    row = validate_row(good_row(**{field: value}), 1, today=TODAY)
    assert row.status == "invalid"
    assert "NOT_A_NUMBER" in codes(row)


@pytest.mark.parametrize("field,value", [("quantity", "-2"), ("quantity", "0"), ("unit_price", "-1")])
def test_negative_value(field: str, value: str):
    row = validate_row(good_row(**{field: value}), 1, today=TODAY)
    assert row.status == "invalid"
    assert "NEGATIVE_VALUE" in codes(row)


@pytest.mark.parametrize("value", ["101", "-5", "250"])
def test_discount_out_of_range(value: str):
    row = validate_row(good_row(discount_percent=value), 1, today=TODAY)
    assert row.status == "invalid"
    assert "OUT_OF_RANGE" in codes(row)


def test_discount_bounds_are_inclusive():
    assert validate_row(good_row(discount_percent="0"), 1, today=TODAY).status == "valid"
    assert validate_row(good_row(discount_percent="100"), 1, today=TODAY).status == "valid"


def test_invalid_date():
    row = validate_row(good_row(transaction_date="not-a-date"), 1, today=TODAY)
    assert row.status == "invalid"
    assert "INVALID_DATE" in codes(row)


def test_future_date():
    row = validate_row(good_row(transaction_date="2099-01-01"), 1, today=TODAY)
    assert row.status == "invalid"
    assert "FUTURE_DATE" in codes(row)
    assert row.transaction_date is None


def test_malformed_row_when_nothing_parses():
    row = validate_row({"junk": "   "}, 7, today=TODAY)
    assert row.status == "invalid"
    assert codes(row) == ["MALFORMED_ROW"]


def test_malformed_row_for_short_csv_line():
    raw = {"transaction_id": "TXN-1", "region": "North", "product_category": "Toys",
           "quantity": "1", "unit_price": None, "discount_percent": None, "transaction_date": None}
    row = validate_row(raw, 2, today=TODAY)
    assert row.status == "invalid"
    assert "MALFORMED_ROW" in codes(row)
    assert "MISSING_FIELD" in codes(row)


def test_malformed_row_for_long_csv_line():
    raw = good_row()
    raw["_extra"] = ["spill", "over"]  # type: ignore[assignment]
    row = validate_row(raw, 2, today=TODAY)
    assert row.status == "invalid"
    assert "MALFORMED_ROW" in codes(row)


def test_multiple_errors_are_all_reported():
    row = validate_row(good_row(quantity="-1", unit_price="abc", transaction_date="2099-01-01"),
                       1, today=TODAY)
    assert set(codes(row)) == {"NEGATIVE_VALUE", "NOT_A_NUMBER", "FUTURE_DATE"}


# ------------------------------------------------------------------ duplicates


def test_duplicate_tracker_first_wins():
    tracker = DuplicateTracker()
    assert tracker.is_duplicate("TXN-1") is False
    assert tracker.is_duplicate("TXN-1") is True
    assert tracker.is_duplicate("TXN-2") is False
    assert tracker.is_duplicate(None) is False
    assert tracker.is_duplicate("") is False


def test_apply_duplicate_marks_second_occurrence():
    tracker = DuplicateTracker()
    first = apply_duplicate(validate_row(good_row(), 1, today=TODAY), tracker)
    second = apply_duplicate(validate_row(good_row(), 2, today=TODAY), tracker)

    assert first.status == "valid" and first.net_amount == 1349.97
    assert second.status == "duplicate"
    assert codes(second) == ["DUPLICATE_ID"]
    assert second.gross_amount is None
    assert second.discount_amount is None
    assert second.net_amount is None


def test_invalid_row_stays_invalid_when_repeated():
    tracker = DuplicateTracker()
    first = apply_duplicate(validate_row(good_row(quantity="-1"), 1, today=TODAY), tracker)
    second = apply_duplicate(validate_row(good_row(quantity="-1"), 2, today=TODAY), tracker)

    assert first.status == "invalid"
    assert "DUPLICATE_ID" not in codes(first)
    assert second.status == "invalid"  # field errors win over duplicate status
    assert "DUPLICATE_ID" in codes(second)
    assert "NEGATIVE_VALUE" in codes(second)


def test_invalid_first_occurrence_still_registers_the_id():
    tracker = DuplicateTracker()
    apply_duplicate(validate_row(good_row(unit_price="abc"), 1, today=TODAY), tracker)
    later = apply_duplicate(validate_row(good_row(), 2, today=TODAY), tracker)
    assert later.status == "duplicate"


# ------------------------------------------------------------------- orm/dicts


def test_row_error_to_dict():
    assert RowError("X", "boom", "quantity").to_dict() == {
        "code": "X", "message": "boom", "field": "quantity"
    }


def test_to_orm_kwargs_matches_model_columns():
    from app.models import Transaction

    row = validate_row(good_row(), 1, today=TODAY)
    kwargs = row.to_orm_kwargs("job-1")
    columns = {c.name for c in Transaction.__table__.columns}
    assert set(kwargs) <= columns
    assert kwargs["job_id"] == "job-1"
    assert kwargs["status"] == "valid"
    assert json.loads(kwargs["errors"]) == []
    assert json.loads(kwargs["raw"])["transaction_id"] == "TXN-1001"


# --------------------------------------------------------------------- parsing

CSV_TEXT = (
    "transaction_id,region,product_category,quantity,unit_price,discount_percent,transaction_date\n"
    "TXN-1,North,Electronics,3,499.99,10,2025-01-15\n"
    "TXN-2,South,Groceries,12,15.50,0,2025-01-15\n"
)


def write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def test_parse_csv(tmp_path: Path):
    rows = list(parse_file(write(tmp_path, "a.csv", CSV_TEXT)))
    assert [n for n, _ in rows] == [1, 2]
    assert rows[0][1]["transaction_id"] == "TXN-1"
    assert count_data_rows(tmp_path / "a.csv") == 2


def test_parse_csv_normalizes_headers_and_bom(tmp_path: Path):
    text = "Transaction ID,Region,Product-Category,Quantity,Unit Price,Discount Percent,Transaction Date\n"
    text += "TXN-1,North,Toys,1,10,0,2025-01-15\n"
    path = write(tmp_path, "bom.csv", "﻿" + text)
    (_, record), = list(parse_file(path))
    assert set(record) == set(ALL_COLUMNS)
    assert validate_row(record, 1, today=TODAY).status == "valid"


def test_parse_csv_blank_lines_are_skipped(tmp_path: Path):
    path = write(tmp_path, "blank.csv", CSV_TEXT + "\n\n")
    assert len(list(parse_file(path))) == 2
    assert count_data_rows(path) == 2


def test_parse_csv_short_and_long_rows_do_not_raise(tmp_path: Path):
    text = CSV_TEXT + "TXN-3,East\nTXN-4,West,Apparel,1,2,0,2025-01-15,extra,more\n"
    rows = list(parse_file(write(tmp_path, "ragged.csv", text)))
    assert len(rows) == 4
    short = validate_row(rows[2][1], 3, today=TODAY)
    long_row = validate_row(rows[3][1], 4, today=TODAY)
    assert "MALFORMED_ROW" in codes(short)
    assert "MALFORMED_ROW" in codes(long_row)


def test_parse_json_array(tmp_path: Path):
    payload = [{"Transaction ID": "TXN-1", "region": "North", "product_category": "Toys",
                "quantity": 2, "unit_price": 5.5, "discount_percent": 0,
                "transaction_date": "2025-01-15"}]
    path = write(tmp_path, "a.json", json.dumps(payload))
    (number, record), = list(parse_file(path))
    assert number == 1
    assert record["transaction_id"] == "TXN-1"
    assert validate_row(record, 1, today=TODAY).net_amount == 11.0
    assert count_data_rows(path) == 1


def test_parse_json_rows_wrapper(tmp_path: Path):
    payload = {"rows": [{"transaction_id": "A"}, {"transaction_id": "B"}]}
    rows = list(parse_file(write(tmp_path, "w.json", json.dumps(payload))))
    assert [r[1]["transaction_id"] for r in rows] == ["A", "B"]


def test_parse_ndjson(tmp_path: Path):
    text = '{"transaction_id": "A"}\n{"transaction_id": "B"}\n'
    rows = list(parse_file(write(tmp_path, "a.ndjson", text)))
    assert [n for n, _ in rows] == [1, 2]
    assert rows[1][1]["transaction_id"] == "B"


def test_empty_file_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        list(parse_file(write(tmp_path, "empty.csv", "")))
    with pytest.raises(ValueError):
        count_data_rows(write(tmp_path, "empty2.csv", ""))
    with pytest.raises(ValueError):
        list(parse_file(write(tmp_path, "empty.json", "   ")))


def test_invalid_json_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        list(parse_file(write(tmp_path, "bad.json", "{not json at all")))


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        list(parse_file(tmp_path / "nope.csv"))
