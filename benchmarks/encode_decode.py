"""Encode/decode speed benchmark across all installed serialization formats.

Usage:
    uv run python -m benchmarks.encode_decode
"""

from __future__ import annotations

import base64
import json
import sys

from shared.bench import benchmark, compare
from shared.sample_data import make_typical_order

# ---------------------------------------------------------------------------
# Prepare the order data once
# ---------------------------------------------------------------------------

order = make_typical_order()
order_dict = order.model_dump()


def _json_default(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


# ---------------------------------------------------------------------------
# Format adapters -- each guarded by try/except for optional libraries
# ---------------------------------------------------------------------------

results = []

# -- JSON (stdlib) ---------------------------------------------------------

def _json_encode():
    return json.dumps(order_dict, default=_json_default).encode("utf-8")

def _json_decode(payload):
    return json.loads(payload)

results.append(
    benchmark("JSON (stdlib)", _json_encode, _json_decode, iterations=5_000)
)

# -- orjson (optional) -----------------------------------------------------

try:
    import orjson

    def _orjson_encode():
        return orjson.dumps(order_dict, default=_json_default)

    def _orjson_decode(payload):
        return orjson.loads(payload)

    results.append(
        benchmark("orjson", _orjson_encode, _orjson_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] orjson not installed")

# -- MsgPack ---------------------------------------------------------------

try:
    import msgpack

    def _msgpack_encode():
        return msgpack.packb(order_dict, use_bin_type=True)

    def _msgpack_decode(payload):
        return msgpack.unpackb(payload, raw=False)

    results.append(
        benchmark("MsgPack", _msgpack_encode, _msgpack_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] msgpack not installed")

# -- CBOR ------------------------------------------------------------------

try:
    import cbor2

    def _cbor_encode():
        return cbor2.dumps(order_dict)

    def _cbor_decode(payload):
        return cbor2.loads(payload)

    results.append(
        benchmark("CBOR", _cbor_encode, _cbor_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] cbor2 not installed")

# -- Protobuf (from scratch) ----------------------------------------------

try:
    from chapters.ch04_protobuf.proto_from_scratch import (
        encode_order as proto_encode_order,
        decode_order as proto_decode_order,
        _prepare_order_dict,
    )

    proto_dict = _prepare_order_dict(order)

    def _proto_encode():
        return proto_encode_order(proto_dict)

    def _proto_decode(payload):
        return proto_decode_order(payload)

    results.append(
        benchmark("Protobuf (scratch)", _proto_encode, _proto_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] Protobuf from_scratch not available")

# -- FlatBuffers (from scratch) --------------------------------------------

try:
    from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
        encode_order as fb_encode_order,
        decode_order_all_fields as fb_decode_order,
    )

    def _fb_encode():
        return fb_encode_order(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,  # EN_ROUTE
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
            delivery_notes=order.delivery_notes,
        )

    def _fb_decode(payload):
        return fb_decode_order(payload)

    results.append(
        benchmark("FlatBuffers (scratch)", _fb_encode, _fb_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] FlatBuffers from_scratch not available")

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

    avro_dict = order_to_avro_dict(order)

    def _avro_encode():
        return avro_encode_fn(_avro_schema, avro_dict)

    def _avro_decode(payload):
        return avro_decode_fn(_avro_schema, payload, 0)[0]

    results.append(
        benchmark("Avro (scratch)", _avro_encode, _avro_decode, iterations=5_000)
    )
except (ImportError, FileNotFoundError) as e:
    print(f"  [skip] Avro from_scratch not available: {e}")

# -- Cap'n Proto (from scratch) -------------------------------------------

try:
    from chapters.ch07_capnproto.capnp_from_scratch import (
        encode_order as capnp_encode_order,
        decode_order as capnp_decode_order,
    )

    def _capnp_encode():
        return capnp_encode_order(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,  # EN_ROUTE
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
        )

    def _capnp_decode(payload):
        return capnp_decode_order(payload)

    results.append(
        benchmark("Cap'n Proto (scratch)", _capnp_encode, _capnp_decode, iterations=5_000)
    )
except ImportError:
    print("  [skip] Cap'n Proto from_scratch not available")

# ---------------------------------------------------------------------------
# Print comparison table
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  Encode/Decode Speed Benchmark -- Typical Order")
    print("=" * 70)
    print(f"\n  Formats tested: {len(results)}")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    for r in results:
        r.print_report()

    print("\n  --- Comparison Table ---")
    compare(*results)
