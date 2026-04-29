"""CSV encoder/decoder using Python's standard-library `csv` module.

Compares output and performance with the from-scratch implementation.
"""

from __future__ import annotations

import csv
import io

from shared.bench import benchmark, compare
from shared.models import Order
from shared.sample_data import make_typical_order

from . import csv_from_scratch


# ---------------------------------------------------------------------------
# stdlib CSV encode / decode
# ---------------------------------------------------------------------------


def csv_encode_row_stdlib(fields: list[str]) -> str:
    """Encode one row using csv.writer."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    return buf.getvalue().rstrip("\r\n")


def csv_decode_row_stdlib(line: str) -> list[str]:
    """Decode one row using csv.reader."""
    reader = csv.reader(io.StringIO(line))
    return next(reader)


def csv_encode_order_stdlib(order: Order) -> str:
    """Encode an Order to CSV using csv.writer (same flattening as from-scratch)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(csv_from_scratch.HEADER)

    for oi in order.items:
        mi = oi.menu_item
        writer.writerow([
            order.id,
            str(order.platform_transaction_id),
            order.customer.id,
            order.customer.name,
            order.customer.email,
            order.customer.phone,
            order.customer.address,
            order.restaurant_id,
            order.status.value,
            order.payment_method.value,
            order.driver_id or "",
            order.delivery_notes or "",
            order.promo_code or "",
            str(order.tip_cents),
            str(order.created_at),
            str(order.updated_at),
            str(order.estimated_delivery_minutes) if order.estimated_delivery_minutes is not None else "",
            mi.id,
            mi.name,
            str(mi.price_cents),
            mi.description,
            mi.category,
            str(mi.is_vegetarian),
            str(oi.quantity),
            oi.special_instructions,
        ])

    return buf.getvalue()


def csv_decode_order_stdlib(csv_text: str) -> dict:
    """Decode CSV back into a dict-of-lists using csv.DictReader."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    header = reader.fieldnames or []
    return {"header": list(header), "rows": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Byte-for-byte comparison
# ---------------------------------------------------------------------------


def compare_outputs(order: Order) -> None:
    """Compare from-scratch and stdlib CSV output."""
    scratch = csv_from_scratch.csv_encode_order(order)
    stdlib = csv_encode_order_stdlib(order)

    print("  From-scratch size:  ", len(scratch.encode("utf-8")), "bytes")
    print("  Stdlib size:        ", len(stdlib.encode("utf-8")), "bytes")
    print("  Byte-for-byte match:", scratch == stdlib)

    if scratch != stdlib:
        # Show first difference
        for i, (a, b) in enumerate(zip(scratch, stdlib)):
            if a != b:
                ctx_start = max(0, i - 20)
                print(f"  First diff at position {i}:")
                print(f"    scratch: ...{scratch[ctx_start:i+20]!r}...")
                print(f"    stdlib:  ...{stdlib[ctx_start:i+20]!r}...")
                break


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


def run_benchmarks(order: Order) -> None:
    """Benchmark from-scratch vs stdlib encode/decode."""
    # From-scratch
    scratch_result = benchmark(
        name="csv-from-scratch",
        encode_fn=lambda: csv_from_scratch.csv_encode_order(order).encode("utf-8"),
        decode_fn=lambda payload: csv_from_scratch.csv_decode_order(payload.decode("utf-8")),
        iterations=5_000,
        warmup=200,
    )

    # Stdlib
    stdlib_result = benchmark(
        name="csv-stdlib",
        encode_fn=lambda: csv_encode_order_stdlib(order).encode("utf-8"),
        decode_fn=lambda payload: csv_decode_order_stdlib(payload.decode("utf-8")),
        iterations=5_000,
        warmup=200,
    )

    scratch_result.print_report()
    stdlib_result.print_report()
    compare(scratch_result, stdlib_result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("  CH01 — CSV Stdlib vs From-Scratch Comparison")
    print("=" * 70)

    order = make_typical_order()

    # --- Row-level comparison ---
    print("\n--- Row-level encode comparison ---")
    test_fields = ["hello", "world, with comma", 'has "quotes"', "line\nbreak"]
    scratch_row = csv_from_scratch.csv_encode_row(test_fields)
    stdlib_row = csv_encode_row_stdlib(test_fields)
    print(f"  Fields:       {test_fields}")
    print(f"  From-scratch: {scratch_row!r}")
    print(f"  Stdlib:       {stdlib_row!r}")
    print(f"  Match:        {scratch_row == stdlib_row}")

    # --- Order-level comparison ---
    print("\n--- Order-level output comparison ---")
    compare_outputs(order)

    # --- Benchmarks ---
    print("\n--- Benchmarks ---")
    run_benchmarks(order)


if __name__ == "__main__":
    main()
