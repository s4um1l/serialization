"""Memory allocation benchmark using tracemalloc.

Measures peak memory allocated during encode and decode for each format.
Highlights the zero-copy advantage of FlatBuffers and Cap'n Proto for
selective reads.

Usage:
    uv run python -m benchmarks.memory_allocation
"""

from __future__ import annotations

import base64
import json
import sys
import tracemalloc

from shared.sample_data import make_typical_order

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

order = make_typical_order()
order_dict = order.model_dump()


def _json_default(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


def measure_peak(fn, *args, iterations: int = 100) -> int:
    """Run fn(*args) `iterations` times and return peak memory in bytes."""
    tracemalloc.start()
    tracemalloc.reset_peak()
    for _ in range(iterations):
        fn(*args)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


# ---------------------------------------------------------------------------
# Format adapters
# ---------------------------------------------------------------------------

Row = tuple[str, int, int, int | None, int | None]  # name, enc_peak, dec_peak, selective_decode_peak, selective_field_count

rows: list[Row] = []

# -- JSON ------------------------------------------------------------------

def _json_enc():
    return json.dumps(order_dict, default=_json_default).encode("utf-8")

_json_payload = _json_enc()

def _json_dec(payload):
    return json.loads(payload)

rows.append((
    "JSON (stdlib)",
    measure_peak(_json_enc),
    measure_peak(_json_dec, _json_payload),
    None,
    None,
))

# -- orjson ----------------------------------------------------------------

try:
    import orjson

    def _orjson_enc():
        return orjson.dumps(order_dict, default=_json_default)

    _orjson_payload = _orjson_enc()

    def _orjson_dec(payload):
        return orjson.loads(payload)

    rows.append((
        "orjson",
        measure_peak(_orjson_enc),
        measure_peak(_orjson_dec, _orjson_payload),
        None,
        None,
    ))
except ImportError:
    pass

# -- MsgPack ---------------------------------------------------------------

try:
    import msgpack

    def _mp_enc():
        return msgpack.packb(order_dict, use_bin_type=True)

    _mp_payload = _mp_enc()

    def _mp_dec(payload):
        return msgpack.unpackb(payload, raw=False)

    rows.append((
        "MsgPack",
        measure_peak(_mp_enc),
        measure_peak(_mp_dec, _mp_payload),
        None,
        None,
    ))
except ImportError:
    pass

# -- CBOR ------------------------------------------------------------------

try:
    import cbor2

    def _cbor_enc():
        return cbor2.dumps(order_dict)

    _cbor_payload = _cbor_enc()

    def _cbor_dec(payload):
        return cbor2.loads(payload)

    rows.append((
        "CBOR",
        measure_peak(_cbor_enc),
        measure_peak(_cbor_dec, _cbor_payload),
        None,
        None,
    ))
except ImportError:
    pass

# -- Protobuf (from scratch) ----------------------------------------------

try:
    from chapters.ch04_protobuf.proto_from_scratch import (
        encode_order as proto_encode_order,
        decode_order as proto_decode_order,
        _prepare_order_dict,
    )

    _proto_dict = _prepare_order_dict(order)

    def _proto_enc():
        return proto_encode_order(_proto_dict)

    _proto_payload = _proto_enc()

    def _proto_dec(payload):
        return proto_decode_order(payload)

    rows.append((
        "Protobuf (scratch)",
        measure_peak(_proto_enc),
        measure_peak(_proto_dec, _proto_payload),
        None,
        None,
    ))
except ImportError:
    pass

# -- FlatBuffers (from scratch) -- selective read advantage ----------------

try:
    from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
        encode_order as fb_encode_order,
        decode_order_all_fields as fb_decode_all,
        decode_order_two_fields as fb_decode_two,
    )

    def _fb_enc():
        return fb_encode_order(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
            delivery_notes=order.delivery_notes,
        )

    _fb_payload = _fb_enc()

    def _fb_dec_all(payload):
        return fb_decode_all(payload)

    def _fb_dec_two(payload):
        return fb_decode_two(payload)

    rows.append((
        "FlatBuffers (scratch)",
        measure_peak(_fb_enc),
        measure_peak(_fb_dec_all, _fb_payload),
        measure_peak(_fb_dec_two, _fb_payload),
        2,
    ))
except ImportError:
    pass

# -- Avro (from scratch) --------------------------------------------------

try:
    from chapters.ch06_avro.avro_from_scratch import (
        avro_encode as avro_encode_fn,
        avro_decode as avro_decode_fn,
        order_to_avro_dict,
    )
    from pathlib import Path

    _avro_schema_path = Path(__file__).resolve().parent.parent / "chapters" / "ch06_avro" / "fooddash.avsc"
    with open(_avro_schema_path) as _f:
        _avro_schema = json.load(_f)

    _avro_dict = order_to_avro_dict(order)

    def _avro_enc():
        return avro_encode_fn(_avro_schema, _avro_dict)

    _avro_payload = _avro_enc()

    def _avro_dec(payload):
        return avro_decode_fn(_avro_schema, payload, 0)[0]

    rows.append((
        "Avro (scratch)",
        measure_peak(_avro_enc),
        measure_peak(_avro_dec, _avro_payload),
        None,
        None,
    ))
except (ImportError, FileNotFoundError):
    pass

# -- Cap'n Proto (from scratch) -- selective read advantage ----------------

try:
    from chapters.ch07_capnproto.capnp_from_scratch import (
        encode_order as capnp_encode_order,
        decode_order as capnp_decode_all,
        decode_order_one_field as capnp_decode_one,
    )

    def _capnp_enc():
        return capnp_encode_order(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
        )

    _capnp_payload = _capnp_enc()

    def _capnp_dec_all(payload):
        return capnp_decode_all(payload)

    def _capnp_dec_one(payload):
        return capnp_decode_one(payload)

    rows.append((
        "Cap'n Proto (scratch)",
        measure_peak(_capnp_enc),
        measure_peak(_capnp_dec_all, _capnp_payload),
        measure_peak(_capnp_dec_one, _capnp_payload),
        1,
    ))
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 80)
    print("  Memory Allocation Benchmark (tracemalloc peak)")
    print("=" * 80)
    print(f"\n  Python: {sys.version.split()[0]}")
    print(f"  Formats: {len(rows)}")
    print("  Iterations per measurement: 100")
    print()

    name_w = max(len(r[0]) for r in rows) + 2

    # Main table
    print(f"  {'Format':<{name_w}} {'Encode Peak':>14} {'Decode Peak':>14}")
    print(f"  {'-' * name_w} {'-' * 14} {'-' * 14}")

    min_enc = min(r[1] for r in rows)
    min_dec = min(r[2] for r in rows)

    for name, enc_peak, dec_peak, sel_peak, sel_count in rows:
        enc_mark = " *" if enc_peak == min_enc else ""
        dec_mark = " *" if dec_peak == min_dec else ""
        print(
            f"  {name:<{name_w}} "
            f"{enc_peak:>10,} B{enc_mark:<3s}"
            f"{dec_peak:>10,} B{dec_mark:<3s}"
        )

    print("\n  * = lowest allocation\n")

    # Selective read table (zero-copy formats only)
    selective_rows = [(n, dp, sp, sc) for n, _, dp, sp, sc in rows if sp is not None]
    if selective_rows:
        print("  --- Zero-Copy Selective Read Advantage ---\n")
        print(f"  {'Format':<{name_w}} {'Full Decode':>14} {'Selective':>14} {'Fields':>8} {'Savings':>10}")
        print(f"  {'-' * name_w} {'-' * 14} {'-' * 14} {'-' * 8} {'-' * 10}")
        for name, full_peak, sel_peak, field_count in selective_rows:
            if full_peak > 0:
                savings_pct = (1 - sel_peak / full_peak) * 100
            else:
                savings_pct = 0
            print(
                f"  {name:<{name_w}} "
                f"{full_peak:>10,} B   "
                f"{sel_peak:>10,} B   "
                f"{field_count:>6}   "
                f"{savings_pct:>8.1f}%"
            )
        print()
        print("  FlatBuffers and Cap'n Proto only allocate memory for the fields")
        print("  you actually read. Traditional formats must deserialize everything.")
        print()


if __name__ == "__main__":
    main()
