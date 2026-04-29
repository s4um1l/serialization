"""Appendix B: NDJSON (Newline-Delimited JSON) streaming serialization.

Demonstrates:
  - Encoding a list of orders as NDJSON (one JSON object per line)
  - Decoding NDJSON line by line (streaming-friendly)
  - Benchmarking time-to-first-record: full JSON array vs NDJSON

Run:
    uv run python -m appendices.appendix_b_streaming_serialization.ndjson_streaming
"""

from __future__ import annotations

import json
import time

from shared.sample_data import make_typical_order


# ---------------------------------------------------------------------------
# NDJSON encode / decode
# ---------------------------------------------------------------------------

def ndjson_encode_stream(orders: list[dict]) -> bytes:
    """Encode a list of order dicts as NDJSON: one JSON object per line.

    Each line is a complete, self-contained JSON object terminated by \\n.
    """
    lines: list[bytes] = []
    for order in orders:
        line = json.dumps(order, separators=(",", ":"), default=str)
        lines.append(line.encode("utf-8"))
    return b"\n".join(lines) + b"\n"


def ndjson_decode_stream(data: bytes) -> list[dict]:
    """Decode NDJSON bytes, yielding one dict per line.

    Blank lines are skipped (common at EOF).
    In a real streaming scenario, you would read line-by-line from a socket
    or file handle instead of splitting a buffer.
    """
    records: list[dict] = []
    for line in data.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_to_dict(order) -> dict:
    """Convert a Pydantic Order to a JSON-safe dict (simplified).

    We build the dict manually to avoid issues with binary fields
    (thumbnail_png) that cannot be JSON-serialized.
    """
    return {
        "order_id": order.id,
        "restaurant_id": order.restaurant_id,
        "status": order.status.value,
        "total_cents": order.total_cents,
        "customer_name": order.customer.name,
        "item_count": len(order.items),
        "created_at": order.created_at,
        "driver_id": order.driver_id,
        "tip_cents": order.tip_cents,
    }


def _make_orders(n: int) -> list[dict]:
    """Generate n order dicts from our sample data factory."""
    base = make_typical_order()
    template = _order_to_dict(base)
    orders = []
    for i in range(n):
        d = dict(template)
        d["order_id"] = f"order-{i:06d}"
        d["total_cents"] = base.total_cents + i
        orders.append(d)
    return orders


# ---------------------------------------------------------------------------
# Time-to-first-record benchmark
# ---------------------------------------------------------------------------

def benchmark_ttfr(num_orders: int = 1000) -> None:
    """Compare time-to-first-record for JSON array vs NDJSON."""

    orders = _make_orders(num_orders)

    # --- JSON array ---
    json_start = time.perf_counter_ns()
    json_bytes = json.dumps(orders, separators=(",", ":"), default=str).encode()
    json_encode_ns = time.perf_counter_ns() - json_start

    json_start = time.perf_counter_ns()
    all_records = json.loads(json_bytes)
    json_decode_ns = time.perf_counter_ns() - json_start
    _first = all_records[0]  # can only access after full parse
    json_ttfr_ns = json_decode_ns  # TTFR = full decode time

    # --- NDJSON ---
    ndjson_start = time.perf_counter_ns()
    ndjson_bytes = ndjson_encode_stream(orders)
    ndjson_encode_ns = time.perf_counter_ns() - ndjson_start

    # Simulate streaming: measure time to get first record
    ndjson_start = time.perf_counter_ns()
    first_newline = ndjson_bytes.index(b"\n")
    first_line = ndjson_bytes[:first_newline]
    _first_record = json.loads(first_line)
    ndjson_ttfr_ns = time.perf_counter_ns() - ndjson_start

    # Full decode for comparison
    ndjson_start = time.perf_counter_ns()
    _all_ndjson = ndjson_decode_stream(ndjson_bytes)
    ndjson_decode_ns = time.perf_counter_ns() - ndjson_start

    return {
        "num_orders": num_orders,
        "json_size": len(json_bytes),
        "ndjson_size": len(ndjson_bytes),
        "json_encode_us": json_encode_ns / 1000,
        "ndjson_encode_us": ndjson_encode_ns / 1000,
        "json_decode_us": json_decode_ns / 1000,
        "ndjson_decode_us": ndjson_decode_ns / 1000,
        "json_ttfr_us": json_ttfr_ns / 1000,
        "ndjson_ttfr_us": ndjson_ttfr_ns / 1000,
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo() -> None:
    print("=" * 64)
    print("  NDJSON Streaming Serialization")
    print("=" * 64)

    # Basic encode/decode demo
    orders = _make_orders(3)
    encoded = ndjson_encode_stream(orders)

    print(f"\n  Encoded {len(orders)} orders as NDJSON ({len(encoded)} bytes)")
    print("\n  First 200 bytes of NDJSON output:")
    preview = encoded[:200].decode("utf-8", errors="replace")
    for line in preview.split("\n")[:3]:
        if line.strip():
            print(f"    {line[:90]}{'...' if len(line) > 90 else ''}")

    decoded = ndjson_decode_stream(encoded)
    print(f"\n  Decoded {len(decoded)} records")

    # Verify roundtrip
    for i, (orig, dec) in enumerate(zip(orders, decoded)):
        if orig == dec:
            print(f"    Record {i}: roundtrip OK")
        else:
            print(f"    Record {i}: MISMATCH")

    # Benchmark
    print(f"\n{'='*64}")
    print("  Time-to-First-Record Benchmark")
    print(f"{'='*64}")

    for n in [100, 1_000, 10_000]:
        stats = benchmark_ttfr(n)
        print(f"\n  {n:>6,} orders:")
        print(f"    JSON array:  {stats['json_size']:>10,} bytes  "
              f"encode {stats['json_encode_us']:>10,.0f} us  "
              f"decode {stats['json_decode_us']:>10,.0f} us  "
              f"TTFR {stats['json_ttfr_us']:>10,.0f} us")
        print(f"    NDJSON:      {stats['ndjson_size']:>10,} bytes  "
              f"encode {stats['ndjson_encode_us']:>10,.0f} us  "
              f"decode {stats['ndjson_decode_us']:>10,.0f} us  "
              f"TTFR {stats['ndjson_ttfr_us']:>10,.0f} us")
        speedup = stats['json_ttfr_us'] / max(stats['ndjson_ttfr_us'], 0.001)
        print(f"    NDJSON TTFR is {speedup:,.0f}x faster")


if __name__ == "__main__":
    demo()
