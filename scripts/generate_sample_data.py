#!/usr/bin/env python3
"""Generate deterministic sales CSV/JSON fixtures for load testing the pipeline.

    python scripts/generate_sample_data.py --rows 10000 --out sample_data/large_sales.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

REGIONS = ("North", "South", "East", "West")
CATEGORIES = ("Electronics", "Groceries", "Apparel", "Home & Garden", "Sports", "Books")
HEADER = (
    "transaction_id",
    "region",
    "product_category",
    "quantity",
    "unit_price",
    "discount_percent",
    "transaction_date",
)


def build_rows(count: int, seed: int, bad_ratio: float, dup_ratio: float) -> list[dict[str, object]]:
    rng = random.Random(seed)
    start = date(2025, 1, 1)
    rows: list[dict[str, object]] = []
    minted: list[str] = []

    for i in range(count):
        roll = rng.random()
        if minted and roll < dup_ratio:
            transaction_id = rng.choice(minted)  # exact repeat -> flagged duplicate
        else:
            transaction_id = f"TXN-{i:07d}"
            minted.append(transaction_id)

        row: dict[str, object] = {
            "transaction_id": transaction_id,
            "region": rng.choice(REGIONS),
            "product_category": rng.choice(CATEGORIES),
            "quantity": rng.randint(1, 25),
            "unit_price": round(rng.uniform(4.99, 1299.99), 2),
            "discount_percent": rng.choice((0, 0, 0, 5, 10, 15, 20, 25, 30)),
            "transaction_date": (start + timedelta(days=rng.randint(0, 240))).isoformat(),
        }

        if rng.random() < bad_ratio:
            match rng.randint(0, 4):
                case 0:
                    row["quantity"] = -rng.randint(1, 5)
                case 1:
                    row["unit_price"] = "n/a"
                case 2:
                    row["transaction_date"] = "2099-12-31"
                case 3:
                    row["discount_percent"] = 150
                case _:
                    row["region"] = ""

        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bad-ratio", type=float, default=0.04, help="fraction of invalid rows")
    parser.add_argument("--dup-ratio", type=float, default=0.02, help="fraction of duplicate ids")
    parser.add_argument("--out", type=Path, default=Path("sample_data/large_sales.csv"))
    args = parser.parse_args()

    rows = build_rows(args.rows, args.seed, args.bad_ratio, args.dup_ratio)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.out.suffix.lower() == ".json":
        args.out.write_text(json.dumps(rows, indent=None), encoding="utf-8")
    else:
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)

    print(f"wrote {len(rows):,} rows -> {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
