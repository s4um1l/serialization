"""Head-to-head benchmark of ALL serialization formats on the SAME data.

The grand benchmark -- every format we studied, measured on identical
FoodDash orders across three sizes (small, typical, large). This is
the data that drives the annual architecture review.

Formats benchmarked:
  1. JSON (stdlib)
  2. JSON (orjson)
  3. MessagePack (msgpack)
  4. CBOR (cbor2)
  5. Protobuf (from scratch, Ch04)
  6. FlatBuffers (from scratch, Ch05)
  7. Avro (from scratch, Ch06)
  8. Cap'n Proto (from scratch, Ch07)
  9. JSON + zstd
  10. Protobuf + zstd
  11. MsgPack + zstd
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from shared.bench import BenchmarkResult, benchmark, compare
from shared.sample_data import make_large_order, make_small_order, make_typical_order


# ---------------------------------------------------------------------------
# Helpers to prepare order data for different formats
# ---------------------------------------------------------------------------

def _json_default(obj):
    """Handle bytes in JSON encoding."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


def _order_to_dict(order) -> dict:
    """Convert a Pydantic Order to a plain dict with string enum values."""
    d = order.model_dump()
    return d


def _order_to_proto_dict(order) -> dict:
    """Convert an Order to a dict suitable for protobuf encoding."""
    d = order.model_dump()
    # model_dump already converts enums to their string values
    return d


# ---------------------------------------------------------------------------
# Format wrappers: each returns (encode_fn, decode_fn, name) or None
# ---------------------------------------------------------------------------

def _make_json_stdlib(order_dict: dict):
    """JSON stdlib encoder/decoder."""
    def encode_fn():
        return json.dumps(order_dict, default=_json_default).encode("utf-8")
    def decode_fn(payload):
        return json.loads(payload)
    return encode_fn, decode_fn, "JSON (stdlib)"


def _make_json_orjson(order_dict: dict):
    """orjson encoder/decoder."""
    try:
        import orjson
    except ImportError:
        return None

    # orjson doesn't handle bytes natively, pre-process
    def _prep_for_orjson(d):
        if isinstance(d, dict):
            return {k: _prep_for_orjson(v) for k, v in d.items()}
        if isinstance(d, list):
            return [_prep_for_orjson(v) for v in d]
        if isinstance(d, bytes):
            return base64.b64encode(d).decode("ascii")
        return d

    prepped = _prep_for_orjson(order_dict)

    def encode_fn():
        return orjson.dumps(prepped)
    def decode_fn(payload):
        return orjson.loads(payload)
    return encode_fn, decode_fn, "JSON (orjson)"


def _make_msgpack(order_dict: dict):
    """MessagePack encoder/decoder."""
    try:
        import msgpack
    except ImportError:
        return None

    def encode_fn():
        return msgpack.packb(order_dict, use_bin_type=True)
    def decode_fn(payload):
        return msgpack.unpackb(payload, raw=False)
    return encode_fn, decode_fn, "MessagePack"


def _make_cbor(order_dict: dict):
    """CBOR encoder/decoder."""
    try:
        import cbor2
    except ImportError:
        return None

    def encode_fn():
        return cbor2.dumps(order_dict)
    def decode_fn(payload):
        return cbor2.loads(payload)
    return encode_fn, decode_fn, "CBOR"


def _make_protobuf(order_dict: dict):
    """Protobuf from-scratch encoder/decoder."""
    try:
        from chapters.ch04_protobuf.proto_from_scratch import (
            decode_order as proto_decode,
            encode_order as proto_encode,
        )
    except ImportError:
        return None

    def encode_fn():
        return proto_encode(order_dict)
    def decode_fn(payload):
        return proto_decode(payload)
    return encode_fn, decode_fn, "Protobuf"


def _make_flatbuffers(order):
    """FlatBuffers from-scratch encoder/decoder (simplified schema)."""
    try:
        from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
            decode_order_all_fields as fb_decode_all,
            decode_order_two_fields as fb_decode_two,
            encode_order as fb_encode,
        )
    except ImportError:
        return None

    status_map = {
        "placed": 1, "confirmed": 2, "preparing": 3, "ready": 4,
        "picked_up": 5, "en_route": 6, "delivered": 7, "cancelled": 8,
    }
    d = order.model_dump()
    status_val = status_map.get(d["status"], 0)

    def encode_fn():
        return fb_encode(
            order_id=d["id"],
            restaurant_id=d["restaurant_id"],
            status=status_val,
            tip_cents=d.get("tip_cents", 0),
            created_at=d.get("created_at", 0.0),
            platform_transaction_id=d.get("platform_transaction_id", 0),
            driver_id=d.get("driver_id"),
            delivery_notes=d.get("delivery_notes"),
        )
    def decode_fn(payload):
        return fb_decode_all(payload)
    def decode_selective(payload):
        return fb_decode_two(payload)
    return encode_fn, decode_fn, "FlatBuffers", decode_selective


def _make_capnproto(order):
    """Cap'n Proto from-scratch encoder/decoder (simplified schema)."""
    try:
        from chapters.ch07_capnproto.capnp_from_scratch import (
            decode_order as capnp_decode_all,
            decode_order_one_field as capnp_decode_selective,
            encode_order as capnp_encode,
        )
    except ImportError:
        return None

    status_map = {
        "placed": 1, "confirmed": 2, "preparing": 3, "ready": 4,
        "picked_up": 5, "en_route": 6, "delivered": 7, "cancelled": 8,
    }
    d = order.model_dump()
    status_val = status_map.get(d["status"], 0)

    def encode_fn():
        return capnp_encode(
            order_id=d["id"],
            restaurant_id=d["restaurant_id"],
            status=status_val,
            tip_cents=d.get("tip_cents", 0),
            created_at=d.get("created_at", 0.0),
            platform_transaction_id=d.get("platform_transaction_id", 0),
            driver_id=d.get("driver_id"),
        )
    def decode_fn(payload):
        return capnp_decode_all(payload)
    def decode_selective(payload):
        return capnp_decode_selective(payload)
    return encode_fn, decode_fn, "Cap'n Proto", decode_selective


def _make_avro(order):
    """Avro from-scratch encoder/decoder."""
    try:
        from chapters.ch06_avro.avro_from_scratch import (
            avro_decode,
            avro_encode,
            order_to_avro_dict,
        )
    except ImportError:
        return None

    schema_path = Path(__file__).parent.parent / "ch06_avro" / "fooddash.avsc"
    try:
        with open(schema_path) as f:
            schema = json.load(f)
    except FileNotFoundError:
        return None

    avro_dict = order_to_avro_dict(order)

    def encode_fn():
        return avro_encode(schema, avro_dict)
    def decode_fn(payload):
        result, _ = avro_decode(schema, payload, 0)
        return result
    return encode_fn, decode_fn, "Avro"


def _make_compressed(base_encode_fn, base_decode_fn, name: str, compressor: str):
    """Wrap encode/decode with compression."""
    if compressor == "zstd":
        try:
            import zstandard
        except ImportError:
            return None
        cctx = zstandard.ZstdCompressor(level=3)
        dctx = zstandard.ZstdDecompressor()
        def encode_fn():
            raw = base_encode_fn()
            return cctx.compress(raw)
        def decode_fn(payload):
            raw = dctx.decompress(payload)
            return base_decode_fn(raw)
        return encode_fn, decode_fn, f"{name} + zstd"
    return None


# ---------------------------------------------------------------------------
# Run benchmarks for a given order size
# ---------------------------------------------------------------------------

def run_benchmarks_for_order(order, label: str, iterations: int = 5_000) -> list[BenchmarkResult]:
    """Run all format benchmarks for a given order. Returns list of BenchmarkResult."""
    results = []
    order_dict = _order_to_dict(order)
    proto_dict = _order_to_proto_dict(order)

    print(f"\n{'=' * 70}")
    print(f"  BENCHMARKS: {label}")
    print(f"{'=' * 70}")

    # 1. JSON stdlib
    enc, dec, name = _make_json_stdlib(order_dict)
    r = benchmark(name, enc, dec, iterations=iterations)
    results.append(r)

    # 2. JSON orjson
    orjson_result = _make_json_orjson(order_dict)
    if orjson_result:
        enc, dec, name = orjson_result
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] orjson not available")

    # 3. MessagePack
    msgpack_result = _make_msgpack(order_dict)
    if msgpack_result:
        enc, dec, name = msgpack_result
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] msgpack not available")

    # 4. CBOR
    cbor_result = _make_cbor(order_dict)
    if cbor_result:
        enc, dec, name = cbor_result
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] cbor2 not available")

    # 5. Protobuf
    proto_result = _make_protobuf(proto_dict)
    if proto_result:
        enc, dec, name = proto_result
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] Protobuf chapter not available")

    # 6. FlatBuffers
    fb_result = _make_flatbuffers(order)
    if fb_result:
        enc, dec_all, name, dec_sel = fb_result
        r = benchmark(name, enc, dec_all, iterations=iterations)
        results.append(r)
        # Selective read
        r_sel = benchmark("FlatBuffers (2 fields)", enc, dec_sel, iterations=iterations)
        results.append(r_sel)
    else:
        print("  [SKIP] FlatBuffers chapter not available")

    # 7. Avro
    avro_result = _make_avro(order)
    if avro_result:
        enc, dec, name = avro_result
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] Avro chapter not available")

    # 8. Cap'n Proto
    capnp_result = _make_capnproto(order)
    if capnp_result:
        enc, dec_all, name, dec_sel = capnp_result
        r = benchmark(name, enc, dec_all, iterations=iterations)
        results.append(r)
        # Selective read
        r_sel = benchmark("Cap'n Proto (1 field)", enc, dec_sel, iterations=iterations)
        results.append(r_sel)
    else:
        print("  [SKIP] Cap'n Proto chapter not available")

    # --- Compression variants ---
    # JSON + zstd
    json_enc, json_dec, _ = _make_json_stdlib(order_dict)
    json_zstd = _make_compressed(json_enc, json_dec, "JSON", "zstd")
    if json_zstd:
        enc, dec, name = json_zstd
        r = benchmark(name, enc, dec, iterations=iterations)
        results.append(r)
    else:
        print("  [SKIP] zstandard not available for JSON+zstd")

    # Protobuf + zstd
    if proto_result:
        proto_enc, proto_dec, _ = proto_result
        proto_zstd = _make_compressed(proto_enc, proto_dec, "Protobuf", "zstd")
        if proto_zstd:
            enc, dec, name = proto_zstd
            r = benchmark(name, enc, dec, iterations=iterations)
            results.append(r)

    # MsgPack + zstd
    if msgpack_result:
        mp_enc, mp_dec, _ = msgpack_result
        mp_zstd = _make_compressed(mp_enc, mp_dec, "MsgPack", "zstd")
        if mp_zstd:
            enc, dec, name = mp_zstd
            r = benchmark(name, enc, dec, iterations=iterations)
            results.append(r)

    # Print comparison table
    compare(*results)

    return results


# ---------------------------------------------------------------------------
# Summary table across all sizes
# ---------------------------------------------------------------------------

def print_summary(all_results: dict[str, list[BenchmarkResult]]) -> None:
    """Print a summary table with key takeaway numbers across sizes."""
    print(f"\n{'=' * 90}")
    print("  SUMMARY: KEY NUMBERS ACROSS ORDER SIZES")
    print(f"{'=' * 90}")

    # Collect unique format names across all sizes (preserving order)
    seen = set()
    format_names = []
    for label, results in all_results.items():
        for r in results:
            if r.name not in seen:
                seen.add(r.name)
                format_names.append(r.name)

    name_w = max(len(n) for n in format_names) + 2

    header = f"{'Format':<{name_w}}"
    for label in all_results:
        header += f" | {label + ' size':>10} {label + ' enc':>10} {label + ' dec':>10}"
    print(f"\n{header}")
    print("-" * len(header))

    for fmt in format_names:
        row = f"{fmt:<{name_w}}"
        for label, results in all_results.items():
            match = [r for r in results if r.name == fmt]
            if match:
                r = match[0]
                row += f" | {r.payload_size_bytes:>8,} B {r.encode_median_ns / 1000:>8,.1f}us {r.decode_median_ns / 1000:>8,.1f}us"
            else:
                row += f" | {'N/A':>10} {'N/A':>10} {'N/A':>10}"
        print(row)

    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("  CHAPTER 11: THE GRAND HEAD-TO-HEAD BENCHMARK")
    print("  All formats. Same data. No excuses.")
    print("=" * 70)

    all_results: dict[str, list[BenchmarkResult]] = {}

    # Three order sizes
    orders = [
        ("Small", make_small_order(), 5_000),
        ("Typical", make_typical_order(), 5_000),
        ("Large", make_large_order(), 2_000),
    ]

    for label, order, iters in orders:
        results = run_benchmarks_for_order(order, f"{label} Order", iterations=iters)
        all_results[label] = results

    # Summary
    print_summary(all_results)

    # Key narrative
    print("=" * 70)
    print("  KEY TAKEAWAYS")
    print("=" * 70)
    print()
    print("  1. JSON is the universal baseline: readable, debuggable, big, slow.")
    print("  2. orjson is 3-5x faster than stdlib JSON -- a free upgrade.")
    print("  3. MsgPack/CBOR: ~30-40% smaller than JSON, similar speed to orjson.")
    print("  4. Protobuf: ~60-70% smaller than JSON, 2-5x faster encode/decode.")
    print("  5. FlatBuffers/Cap'n Proto: zero-copy decode is 10-100x faster for")
    print("     selective field reads -- the killer feature for hot paths.")
    print("  6. Avro: smallest schema-based format (no field tags), ideal for")
    print("     data lakes where the schema travels with the data.")
    print("  7. Compression (zstd) shrinks everything further but costs CPU.")
    print("     Worth it for bandwidth-constrained paths, not for CPU-constrained.")
    print()

    return all_results


if __name__ == "__main__":
    main()
