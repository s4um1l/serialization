"""Cap'n Proto library demo with benchmarks and graceful fallback.

Tries to use pycapnp (the official Python binding), but falls back to our
from-scratch implementation if the C++ library isn't installed.

Either way, we benchmark the from-scratch implementation and compare with
previous formats using shared.bench.
"""

from __future__ import annotations

import os
import time

try:
    import capnp

    HAS_PYCAPNP = True
except ImportError:
    HAS_PYCAPNP = False

from shared.bench import BenchmarkResult, benchmark, compare

from chapters.ch07_capnproto.capnp_from_scratch import (
    ORDER_DATA_WORDS,
    ORDER_PTR_WORDS,
    decode_order,
    decode_order_one_field,
    encode_order,
)


# ─────────────────────────────────────────────────────────────────────
# pycapnp demo (if available)
# ─────────────────────────────────────────────────────────────────────

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "fooddash.capnp")


def pycapnp_demo() -> BenchmarkResult | None:
    """Demonstrate pycapnp if available, return benchmark result."""
    if not HAS_PYCAPNP:
        print("  pycapnp not available (requires Cap'n Proto C++ library).")
        print("  Install: brew install capnp && pip install pycapnp")
        print("  Falling back to from-scratch implementation.\n")
        return None

    print("  pycapnp IS available! Using the official library.\n")

    # Load schema
    food_schema = capnp.load(SCHEMA_PATH)

    # Build a message
    msg = food_schema.Order.new_message()
    msg.id = "ord00042"
    msg.platformTransactionId = 9007199254740993
    msg.restaurantId = "rest0001"
    msg.status = "enRoute"
    msg.paymentMethod = "creditCard"
    msg.driverId = "driv0001"
    msg.deliveryNotes = "Ring doorbell twice"
    msg.tipCents = 500
    msg.createdAt = 1700000000.0
    msg.updatedAt = 1700000300.0
    msg.estimatedDeliveryMinutes = 25

    # Set up customer
    customer = msg.init("customer")
    customer.id = "cust0001"
    customer.name = "Alice Nakamura"
    customer.email = "alice@example.com"
    customer.phone = "+1-555-0101"
    customer.address = "350 5th Ave, New York, NY 10118"
    loc = customer.init("location")
    loc.latitude = 40.748817
    loc.longitude = -73.985428

    # Serialize to bytes
    data = msg.to_bytes()
    print(f"  pycapnp message size: {len(data)} bytes")

    # Read it back
    with food_schema.Order.from_bytes(data) as reader:
        print(f"  id: {reader.id}")
        print(f"  restaurantId: {reader.restaurantId}")
        print(f"  status: {reader.status}")
        print(f"  tipCents: {reader.tipCents}")
        print(f"  platformTransactionId: {reader.platformTransactionId}")
        print(f"  customer.name: {reader.customer.name}")
        print(f"  driverId: {reader.driverId}")

    # Benchmark
    def encode_fn():
        m = food_schema.Order.new_message()
        m.id = "ord00042"
        m.platformTransactionId = 9007199254740993
        m.restaurantId = "rest0001"
        m.status = "enRoute"
        m.tipCents = 500
        m.createdAt = 1700000000.0
        m.updatedAt = 1700000300.0
        return m.to_bytes()

    def decode_fn(payload):
        with food_schema.Order.from_bytes(payload) as r:
            _ = r.id
            _ = r.tipCents
            _ = r.status
        return r

    result = benchmark(
        name="capnproto (pycapnp)",
        encode_fn=encode_fn,
        decode_fn=decode_fn,
        iterations=5_000,
    )
    result.print_report()
    return result


# ─────────────────────────────────────────────────────────────────────
# From-scratch benchmark
# ─────────────────────────────────────────────────────────────────────

def from_scratch_benchmark() -> BenchmarkResult:
    """Benchmark our from-scratch Cap'n Proto implementation."""
    print("  --- From-scratch Cap'n Proto benchmark ---\n")

    def encode_fn():
        return encode_order(
            order_id="ord00042",
            restaurant_id="rest0001",
            status=5,
            tip_cents=500,
            created_at=1700000000.0,
            platform_transaction_id=9007199254740993,
            driver_id="driv0001",
        )

    def decode_fn(payload):
        return decode_order(payload)

    result = benchmark(
        name="capnproto (from scratch)",
        encode_fn=encode_fn,
        decode_fn=decode_fn,
        iterations=10_000,
        check_roundtrip=lambda d: d["id"] == "ord00042" and d["tip_cents"] == 500,
    )
    result.print_report()
    return result


def selective_read_benchmark() -> None:
    """Show the advantage of reading only the fields you need."""
    print("  --- Selective read benchmark ---\n")

    buf = encode_order(
        order_id="ord00042",
        restaurant_id="rest0001",
        status=5,
        tip_cents=500,
        created_at=1700000000.0,
        platform_transaction_id=9007199254740993,
        driver_id="driv0001",
    )

    iterations = 50_000

    # Read all fields
    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order(buf)
    all_ns = time.perf_counter_ns() - start

    # Read one field
    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order_one_field(buf)
    one_ns = time.perf_counter_ns() - start

    print(f"    Read all fields:  {all_ns / iterations:>8.1f} ns/op")
    print(f"    Read 1 field:     {one_ns / iterations:>8.1f} ns/op")
    if one_ns > 0:
        print(f"    Ratio:            {all_ns / one_ns:.1f}x")
    print()
    print("    Key insight: with Cap'n Proto, you only pay for the fields you")
    print("    actually read.  Fields you skip cost literally zero CPU time.\n")


# ─────────────────────────────────────────────────────────────────────
# Cross-format comparison
# ─────────────────────────────────────────────────────────────────────

def cross_format_comparison(capnp_result: BenchmarkResult) -> None:
    """Compare Cap'n Proto with previous formats."""
    print("  --- Cross-format comparison ---\n")

    results = [capnp_result]

    # Try importing previous format benchmarks
    try:
        import json
        from shared.sample_data import make_typical_order

        order = make_typical_order()

        json_result = benchmark(
            name="json",
            encode_fn=lambda: json.dumps(order.model_dump(), default=str).encode(),
            decode_fn=lambda p: json.loads(p),
            iterations=5_000,
        )
        results.append(json_result)
    except Exception:
        pass

    try:
        from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
            encode_order as fb_encode,
            decode_order_all_fields as fb_decode,
        )

        fb_result = benchmark(
            name="flatbuffers (from scratch)",
            encode_fn=lambda: fb_encode(
                order_id="ord00042",
                restaurant_id="rest0001",
                status=5,
                tip_cents=500,
                created_at=1700000000.0,
                platform_transaction_id=9007199254740993,
                driver_id="driv0001",
                delivery_notes="Ring doorbell twice",
            ),
            decode_fn=lambda p: fb_decode(p),
            iterations=5_000,
        )
        results.append(fb_result)
    except Exception:
        pass

    if len(results) > 1:
        compare(*results)
    else:
        capnp_result.print_report()


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  Cap'n Proto Library Demo + Benchmarks")
    print("=" * 70)

    # Try pycapnp
    print("\n  --- pycapnp library ---\n")
    pycapnp_result = pycapnp_demo()

    # From-scratch benchmark
    print()
    scratch_result = from_scratch_benchmark()

    # Selective read
    print()
    selective_read_benchmark()

    # Cross-format comparison
    print()
    best_result = pycapnp_result if pycapnp_result is not None else scratch_result
    cross_format_comparison(best_result)

    # Wire size analysis
    print("  --- Wire Size Analysis ---\n")
    buf = encode_order(
        order_id="ord00042",
        restaurant_id="rest0001",
        status=5,
        tip_cents=500,
        created_at=1700000000.0,
        platform_transaction_id=9007199254740993,
        driver_id="driv0001",
    )
    print(f"    Cap'n Proto message: {len(buf)} bytes")
    print("      Segment table:     8 bytes (overhead)")
    print("      Root pointer:      8 bytes")
    print(f"      Data section:      {ORDER_DATA_WORDS * 8} bytes ({ORDER_DATA_WORDS} words)")
    print(f"      Pointer section:   {ORDER_PTR_WORDS * 8} bytes ({ORDER_PTR_WORDS} words)")
    text_bytes = len(buf) - 8 - 8 - ORDER_DATA_WORDS * 8 - ORDER_PTR_WORDS * 8
    print(f"      Text content:      {text_bytes} bytes (word-aligned, NUL-terminated)")
    print()
    print("    Cap'n Proto trades wire size for encode/decode speed.")
    print("    Word alignment means more padding, but the format can be")
    print("    used directly as in-memory data without any transformation.")
    print()


if __name__ == "__main__":
    main()
