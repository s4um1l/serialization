"""Wire payload size comparison across all installed serialization formats.

Encodes small, typical, and large orders in each format and prints a table
showing byte counts and percentage relative to JSON (the baseline).

Usage:
    uv run python -m benchmarks.payload_size
"""

from __future__ import annotations

import base64
import json
import sys

from shared.sample_data import make_small_order, make_typical_order, make_large_order

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_default(obj):
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


def _json_encode(order) -> bytes:
    return json.dumps(order.model_dump(), default=_json_default).encode("utf-8")


# ---------------------------------------------------------------------------
# Collect encoders -- each returns bytes for a given order
# ---------------------------------------------------------------------------

encoders: dict[str, callable] = {}

# JSON (stdlib)
encoders["JSON"] = _json_encode

# orjson
try:
    import orjson

    def _orjson_encode(order):
        return orjson.dumps(order.model_dump(), default=_json_default)

    encoders["orjson"] = _orjson_encode
except ImportError:
    pass

# MsgPack
try:
    import msgpack

    def _msgpack_encode(order):
        return msgpack.packb(order.model_dump(), use_bin_type=True)

    encoders["MsgPack"] = _msgpack_encode
except ImportError:
    pass

# CBOR
try:
    import cbor2

    def _cbor_encode(order):
        return cbor2.dumps(order.model_dump())

    encoders["CBOR"] = _cbor_encode
except ImportError:
    pass

# Protobuf (from scratch)
try:
    from chapters.ch04_protobuf.proto_from_scratch import (
        encode_order as proto_encode,
        _prepare_order_dict,
    )

    def _proto_encode(order):
        return proto_encode(_prepare_order_dict(order))

    encoders["Protobuf"] = _proto_encode
except ImportError:
    pass

# FlatBuffers (from scratch) -- simplified schema, only certain fields
try:
    from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
        encode_order as fb_encode,
    )

    def _fb_encode(order):
        return fb_encode(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
            delivery_notes=order.delivery_notes,
        )

    encoders["FlatBuf*"] = _fb_encode
except ImportError:
    pass

# Avro (from scratch)
try:
    from chapters.ch06_avro.avro_from_scratch import (
        avro_encode,
        order_to_avro_dict,
    )
    from pathlib import Path

    _avro_schema_path = Path(__file__).resolve().parent.parent / "chapters" / "ch06_avro" / "fooddash.avsc"
    with open(_avro_schema_path) as _f:
        _avro_schema = json.load(_f)

    def _avro_encode(order):
        return avro_encode(_avro_schema, order_to_avro_dict(order))

    encoders["Avro"] = _avro_encode
except (ImportError, FileNotFoundError):
    pass

# Cap'n Proto (from scratch) -- simplified schema
try:
    from chapters.ch07_capnproto.capnp_from_scratch import (
        encode_order as capnp_encode,
    )

    def _capnp_encode(order):
        return capnp_encode(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=6,
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
        )

    encoders["Cap'nProto*"] = _capnp_encode
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Run and print table
# ---------------------------------------------------------------------------

def main() -> None:
    orders = {
        "small": make_small_order(),
        "typical": make_typical_order(),
        "large": make_large_order(),
    }

    print("\n" + "=" * 80)
    print("  Payload Size Comparison")
    print("=" * 80)
    print(f"\n  Python: {sys.version.split()[0]}")
    print(f"  Formats: {len(encoders)}")
    print()
    print("  * FlatBuf and Cap'nProto use a simplified schema (fewer fields),")
    print("    so their sizes are not directly comparable to full-schema formats.")
    print()

    # Compute sizes
    sizes: dict[str, dict[str, int]] = {}
    for fmt_name, encode_fn in encoders.items():
        sizes[fmt_name] = {}
        for order_name, order_obj in orders.items():
            try:
                payload = encode_fn(order_obj)
                sizes[fmt_name][order_name] = len(payload)
            except Exception as e:
                sizes[fmt_name][order_name] = -1
                print(f"  [error] {fmt_name} / {order_name}: {e}")

    # Get JSON baseline sizes
    json_sizes = sizes.get("JSON", {})

    # Print table
    name_w = max(len(n) for n in sizes) + 2
    print(f"  {'Format':<{name_w}} {'Small':>10} {'%JSON':>7}  {'Typical':>10} {'%JSON':>7}  {'Large':>10} {'%JSON':>7}")
    print(f"  {'-' * name_w} {'-' * 10} {'-' * 7}  {'-' * 10} {'-' * 7}  {'-' * 10} {'-' * 7}")

    for fmt_name in encoders:
        parts = [f"  {fmt_name:<{name_w}}"]
        for order_name in ("small", "typical", "large"):
            sz = sizes[fmt_name][order_name]
            json_sz = json_sizes.get(order_name, 0)
            if sz < 0:
                parts.append(f" {'ERROR':>10} {'':>7} ")
            else:
                pct = (sz / json_sz * 100) if json_sz > 0 else 0
                parts.append(f" {sz:>8,} B {pct:>5.1f}% ")
            if order_name != "large":
                parts.append("")
        print("".join(parts))

    print()
    print("  100% = JSON baseline. Lower is smaller.")
    print()


if __name__ == "__main__":
    main()
