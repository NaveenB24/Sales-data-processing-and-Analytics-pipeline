"""Row-level parsing, validation and duplicate detection.

Everything here is pure and thread-safe so the worker pool can validate rows in
parallel; the only shared state is :class:`DuplicateTracker`, which guards itself
with a lock.
"""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

REQUIRED_COLUMNS: tuple[str, ...] = (
    "transaction_id",
    "region",
    "product_category",
    "quantity",
    "unit_price",
    "transaction_date",
)
ALL_COLUMNS: tuple[str, ...] = (
    "transaction_id",
    "region",
    "product_category",
    "quantity",
    "unit_price",
    "discount_percent",
    "transaction_date",
)

#: Key under which CSV cells beyond the header width are collected (DictReader restkey).
EXTRA_KEY = "_extra"

_JSON_SUFFIXES = {".json", ".ndjson", ".jsonl"}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")


@dataclass(frozen=True, slots=True)
class RowError:
    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass(slots=True)
class ValidatedRow:
    row_number: int
    raw: dict[str, str]
    status: str
    errors: list[RowError] = field(default_factory=list)
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

    @property
    def codes(self) -> list[str]:
        return [e.code for e in self.errors]

    def to_orm_kwargs(self, job_id: str) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "row_number": self.row_number,
            "transaction_id": self.transaction_id,
            "region": self.region,
            "product_category": self.product_category,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "discount_percent": self.discount_percent,
            "transaction_date": self.transaction_date,
            "gross_amount": self.gross_amount,
            "discount_amount": self.discount_amount,
            "net_amount": self.net_amount,
            "status": self.status,
            "errors": json.dumps([e.to_dict() for e in self.errors]),
            "raw": json.dumps(self.raw, default=str),
        }


def normalize_header(name: str) -> str:
    """`" Transaction-ID "` -> `"transaction_id"` (BOM tolerant)."""
    cleaned = str(name).replace("﻿", "").strip().lower()
    for ch in (" ", "-", "\t"):
        cleaned = cleaned.replace(ch, "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned


def _text(value: Any) -> str | None:
    """Trimmed string, or ``None`` for absent/blank values."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    return value or None


def _parse_date(raw: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        return datetime.fromisoformat(candidate).date()
    except ValueError:
        return None


def validate_row(
    raw: Mapping[str, Any],
    row_number: int,
    *,
    today: date | None = None,
) -> ValidatedRow:
    """Validate one input record. Pure: no duplicate detection, no I/O."""
    today = today or datetime.now(timezone.utc).date()

    data: dict[str, Any] = {}
    extras: list[Any] = []
    for key, value in raw.items():
        if key is None or key == EXTRA_KEY:
            if value:
                extras.extend(value if isinstance(value, list) else [value])
            continue
        data[normalize_header(key)] = value

    raw_snapshot: dict[str, str] = {
        k: ("" if v is None else v if isinstance(v, str) else str(v)) for k, v in data.items()
    }
    if extras:
        raw_snapshot[EXTRA_KEY] = json.dumps([str(e) for e in extras])

    errors: list[RowError] = []
    row = ValidatedRow(row_number=row_number, raw=raw_snapshot, status="invalid", errors=errors)

    present = [c for c in REQUIRED_COLUMNS if _text(data.get(c)) is not None]
    if not present:
        errors.append(
            RowError(code="MALFORMED_ROW", message="row could not be parsed into the expected columns")
        )
        return row

    # A short CSV line leaves required cells as the restval sentinel (None) while a
    # long line spills into EXTRA_KEY; both are "malformed" per SPEC 2.2.
    short = any(c in data and data[c] is None for c in REQUIRED_COLUMNS)
    if extras or short:
        errors.append(
            RowError(code="MALFORMED_ROW", message="row has a different number of fields than the header")
        )

    transaction_id = _text(data.get("transaction_id"))
    if transaction_id is None:
        errors.append(RowError("MISSING_FIELD", "transaction_id is required", "transaction_id"))
    row.transaction_id = transaction_id

    region = _text(data.get("region"))
    if region is None:
        errors.append(RowError("MISSING_FIELD", "region is required", "region"))
    row.region = region

    category = _text(data.get("product_category"))
    if category is None:
        errors.append(RowError("MISSING_FIELD", "product_category is required", "product_category"))
    row.product_category = category

    quantity_text = _text(data.get("quantity"))
    quantity: int | None = None
    if quantity_text is None:
        errors.append(RowError("MISSING_FIELD", "quantity is required", "quantity"))
    else:
        try:
            numeric = float(quantity_text)
        except ValueError:
            errors.append(RowError("NOT_A_NUMBER", f"quantity {quantity_text!r} is not a number", "quantity"))
        else:
            if numeric != int(numeric):
                errors.append(RowError("NOT_A_NUMBER", "quantity must be a whole number", "quantity"))
            elif numeric <= 0:
                errors.append(RowError("NEGATIVE_VALUE", "quantity must be greater than 0", "quantity"))
            else:
                quantity = int(numeric)
    row.quantity = quantity

    price_text = _text(data.get("unit_price"))
    unit_price: float | None = None
    if price_text is None:
        errors.append(RowError("MISSING_FIELD", "unit_price is required", "unit_price"))
    else:
        try:
            parsed_price = float(price_text)
        except ValueError:
            errors.append(
                RowError("NOT_A_NUMBER", f"unit_price {price_text!r} is not a number", "unit_price")
            )
        else:
            if parsed_price < 0:
                errors.append(RowError("NEGATIVE_VALUE", "unit_price must not be negative", "unit_price"))
            else:
                unit_price = parsed_price
    row.unit_price = unit_price

    discount_text = _text(data.get("discount_percent"))
    discount: float | None = 0.0
    if discount_text is not None:
        try:
            parsed_discount = float(discount_text)
        except ValueError:
            discount = None
            errors.append(
                RowError(
                    "NOT_A_NUMBER",
                    f"discount_percent {discount_text!r} is not a number",
                    "discount_percent",
                )
            )
        else:
            if not 0.0 <= parsed_discount <= 100.0:
                discount = None
                errors.append(
                    RowError(
                        "OUT_OF_RANGE",
                        "discount_percent must be between 0 and 100",
                        "discount_percent",
                    )
                )
            else:
                discount = parsed_discount
    row.discount_percent = discount

    date_text = _text(data.get("transaction_date"))
    parsed_date: date | None = None
    if date_text is None:
        errors.append(RowError("MISSING_FIELD", "transaction_date is required", "transaction_date"))
    else:
        parsed_date = _parse_date(date_text)
        if parsed_date is None:
            errors.append(
                RowError("INVALID_DATE", f"transaction_date {date_text!r} is not a date", "transaction_date")
            )
        elif parsed_date > today:
            errors.append(
                RowError("FUTURE_DATE", "transaction_date must not be in the future", "transaction_date")
            )
            parsed_date = None
    row.transaction_date = parsed_date

    if errors:
        return row

    row.status = "valid"
    gross = float(quantity) * float(unit_price)  # type: ignore[arg-type]
    discount_amount = gross * (float(discount) / 100.0)  # type: ignore[arg-type]
    row.gross_amount = round(gross, 2)
    row.discount_amount = round(discount_amount, 2)
    row.net_amount = round(gross - discount_amount, 2)
    return row


Fingerprint = tuple[str, str, int | None, float | None, float | None, str]


class DuplicateTracker:
    """Thread-safe first-wins registry of the rows seen in one job.

    Two signals are tracked, because the brief asks for both:

    * a repeated ``transaction_id`` — the same record submitted twice;
    * a repeated *business fingerprint* (every field except the id) — the same
      sale re-submitted under a fresh id, which is what the brief's own sample
      file calls a duplicate of ``TXN-1001`` even though its id differs.

    Content matching can in principle collide with two genuinely separate sales
    of the same item, quantity, price and date in one region. That is the stated
    trade; ``DUPLICATE_DETECTION=id`` turns it off and keeps id-only matching.
    """

    __slots__ = ("_lock", "_seen_ids", "_seen_rows", "mode")

    def __init__(self, mode: str | None = None) -> None:
        self._lock = threading.Lock()
        self._seen_ids: set[str] = set()
        self._seen_rows: set[Fingerprint] = set()
        self.mode = mode or settings.duplicate_detection

    @staticmethod
    def fingerprint(row: ValidatedRow) -> Fingerprint:
        return (
            (row.region or "").strip().casefold(),
            (row.product_category or "").strip().casefold(),
            row.quantity,
            row.unit_price,
            row.discount_percent,
            row.transaction_date.isoformat() if row.transaction_date else "",
        )

    def is_duplicate(self, transaction_id: str | None) -> bool:
        """Register an id; True when it was already present."""
        if not transaction_id:
            return False
        with self._lock:
            if transaction_id in self._seen_ids:
                return True
            self._seen_ids.add(transaction_id)
            return False

    def check(self, row: ValidatedRow) -> str | None:
        """Register `row` and return the duplicate code it triggers, if any.

        The id is always registered first so that an id repeat wins over a
        content repeat when a row would trigger both.
        """
        if self.is_duplicate(row.transaction_id):
            return "DUPLICATE_ID"
        if self.mode != "id_and_content":
            return None
        # Only rows carrying complete, parsed values can be compared by content.
        if row.quantity is None or row.unit_price is None or row.transaction_date is None:
            return None
        key = self.fingerprint(row)
        with self._lock:
            if key in self._seen_rows:
                return "DUPLICATE_RECORD"
            self._seen_rows.add(key)
            return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen_ids)


_DUPLICATE_MESSAGES = {
    "DUPLICATE_ID": "transaction_id {id!r} already seen in this job",
    "DUPLICATE_RECORD": (
        "identical transaction already seen in this job (same region, category, "
        "quantity, unit price, discount and date as an earlier row)"
    ),
}


def apply_duplicate(row: ValidatedRow, tracker: DuplicateTracker) -> ValidatedRow:
    """Mark `row` as a duplicate of an earlier row in the same job."""
    code = tracker.check(row)
    if code is None:
        return row

    row.errors.append(
        RowError(
            code,
            _DUPLICATE_MESSAGES[code].format(id=row.transaction_id),
            "transaction_id" if code == "DUPLICATE_ID" else None,
        )
    )
    if row.status == "valid":
        row.status = "duplicate"
        # Duplicates must not be counted twice in revenue.
        row.gross_amount = None
        row.discount_amount = None
        row.net_amount = None
    return row


def _coerce_json_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value)


def _is_blank_record(record: Mapping[str, Any]) -> bool:
    """True for lines that carry no content at all (DictReader keeps ',,,' lines)."""
    for key, value in record.items():
        if key == EXTRA_KEY:
            if any(str(v).strip() for v in (value or [])):
                return False
            continue
        if value is not None and str(value).strip():
            return False
    return True


def _iter_csv(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        sniff = csv.reader(fh)
        try:
            header = next(sniff)
        except StopIteration:
            raise ValueError(f"{path.name}: file is empty — a CSV header row is required") from None
        if not header or not any(cell.strip() for cell in header):
            raise ValueError(f"{path.name}: missing or blank CSV header row")

        fieldnames = [normalize_header(cell) for cell in header]
        reader = csv.DictReader(fh, fieldnames=fieldnames, restkey=EXTRA_KEY, restval=None)
        row_number = 0
        for record in reader:
            if _is_blank_record(record):
                continue
            row_number += 1
            yield row_number, dict(record)


def _json_records(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"{path.name}: file is empty")

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        records: list[Any] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                raise ValueError(
                    f"{path.name}: invalid JSON (line {line_no}: {exc.msg})"
                ) from exc
        if not records:
            raise ValueError(f"{path.name}: invalid JSON ({exc.msg})") from exc
        return records

    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        rows = document.get("rows")
        if isinstance(rows, list):
            return rows
        return [document]
    raise ValueError(f"{path.name}: JSON must be an array of objects, an NDJSON stream or {{'rows': [...]}}")


def _iter_json(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    for row_number, item in enumerate(_json_records(path), start=1):
        if isinstance(item, Mapping):
            record = {normalize_header(k): _coerce_json_value(v) for k, v in item.items()}
        else:
            record = {"_raw": _coerce_json_value(item)}
        yield row_number, record  # type: ignore[misc]


def parse_file(path: str | Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield ``(row_number, raw_record)`` pairs; row numbers start at 1."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"{p}: file not found")
    if p.suffix.lower() in _JSON_SUFFIXES:
        return _iter_json(p)
    return _iter_csv(p)


def count_data_rows(path: str | Path) -> int:
    """Cheap pre-count of data rows, used for progress totals."""
    p = Path(path)
    if p.suffix.lower() in _JSON_SUFFIXES:
        return sum(1 for _ in _iter_json(p))

    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{p.name}: file is empty — a CSV header row is required") from None
        if not header or not any(cell.strip() for cell in header):
            raise ValueError(f"{p.name}: missing or blank CSV header row")
        return sum(1 for cells in reader if any(c.strip() for c in cells))
