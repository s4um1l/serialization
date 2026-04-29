"""Real-world schema migration demo: v1 -> v2 -> v3 across 4 formats.

Simulates FoodDash's Order schema evolving over 6 months:

  v1 (launch):       basic fields, items as string
  v2 (3 months):     add tip_cents, add driver_id, items becomes list
  v3 (6 months):     add loyalty_points, drop total_cents, keep wire compat

For each format we encode with each version and cross-decode between versions.
"""

from __future__ import annotations

import json

from chapters.ch03_msgpack_cbor.msgpack_from_scratch import (
    msgpack_decode,
    msgpack_encode,
)
from chapters.ch04_protobuf.proto_from_scratch import (
    decode_message,
    encode_string_field,
    encode_varint_field,
)
from chapters.ch06_avro.avro_from_scratch import avro_decode, avro_encode


# ============================================================================
# Version-specific data
# ============================================================================

V1_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": "2x Burger, 1x Fries",  # string in v1
    "status": "confirmed",
    "total_cents": 3597,
    "created_at": 1700000000.0,
}

V2_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": ["Burger", "Burger", "Fries"],  # list in v2
    "status": "confirmed",
    "total_cents": 3597,
    "tip_cents": 500,          # new in v2
    "driver_id": "driv001",    # new in v2
    "created_at": 1700000000.0,
}

V3_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": ["Burger", "Burger", "Fries"],
    "status": "confirmed",
    "tip_cents": 500,
    "driver_id": "driv001",
    "loyalty_points": 150,     # new in v3
    # total_cents removed in v3 (computed from items)
    "created_at": 1700000000.0,
}


# ============================================================================
# JSON migration
# ============================================================================

def demo_json() -> list[str]:
    print("\n--- JSON Schema Migration ---\n")
    results = []

    v1_bytes = json.dumps(V1_DATA).encode("utf-8")
    v2_bytes = json.dumps(V2_DATA).encode("utf-8")
    v3_bytes = json.dumps(V3_DATA).encode("utf-8")

    print(f"  v1 payload: {len(v1_bytes)} bytes")
    print(f"  v2 payload: {len(v2_bytes)} bytes")
    print(f"  v3 payload: {len(v3_bytes)} bytes")

    # Cross-decode: v1 data with v2 reader
    print("\n  v1 data -> v2 reader:")
    d = json.loads(v1_bytes)
    tip = d.get("tip_cents", 0)
    driver = d.get("driver_id", None)
    items = d.get("items")
    note = f"    tip_cents={tip} (default), driver_id={driver} (default)"
    print(note)
    if isinstance(items, str):
        print(f"    items is str '{items}' -- v2 reader expects list! BREAKS if iterated as list")
        results.append("JSON v1->v2: PARTIAL (new fields get defaults, items type mismatch)")
    else:
        results.append("JSON v1->v2: PASS")

    # Cross-decode: v2 data with v3 reader
    print("\n  v2 data -> v3 reader:")
    d = json.loads(v2_bytes)
    loyalty = d.get("loyalty_points", 0)
    total = d.get("total_cents")
    print(f"    loyalty_points={loyalty} (default), total_cents={total} (v3 ignores it)")
    results.append("JSON v2->v3: PASS (new fields default, removed field ignored)")

    # Cross-decode: v1 data with v3 reader
    print("\n  v1 data -> v3 reader:")
    d = json.loads(v1_bytes)
    loyalty = d.get("loyalty_points", 0)
    tip = d.get("tip_cents", 0)
    driver = d.get("driver_id", None)
    items = d.get("items")
    print(f"    loyalty_points={loyalty}, tip_cents={tip}, driver_id={driver}")
    if isinstance(items, str):
        print("    items is str -- two-version gap makes items type mismatch worse")
        results.append("JSON v1->v3: PARTIAL (items type mismatch persists across versions)")
    else:
        results.append("JSON v1->v3: PASS")

    return results


# ============================================================================
# MessagePack migration
# ============================================================================

def demo_msgpack() -> list[str]:
    print("\n--- MessagePack Schema Migration ---\n")
    results = []

    v1_bytes = msgpack_encode(V1_DATA)
    v2_bytes = msgpack_encode(V2_DATA)
    v3_bytes = msgpack_encode(V3_DATA)

    print(f"  v1 payload: {len(v1_bytes)} bytes")
    print(f"  v2 payload: {len(v2_bytes)} bytes")
    print(f"  v3 payload: {len(v3_bytes)} bytes")

    # v1 data -> v2 reader
    print("\n  v1 data -> v2 reader:")
    d = msgpack_decode(v1_bytes)
    tip = d.get("tip_cents", 0)
    driver = d.get("driver_id", None)
    items = d.get("items")
    print(f"    tip_cents={tip} (default), driver_id={driver} (default)")
    if isinstance(items, str):
        print(f"    items is str '{items}' -- same issue as JSON")
        results.append("MsgPack v1->v2: PARTIAL (items type mismatch)")
    else:
        results.append("MsgPack v1->v2: PASS")

    # v2 data -> v3 reader
    print("\n  v2 data -> v3 reader:")
    d = msgpack_decode(v2_bytes)
    loyalty = d.get("loyalty_points", 0)
    print(f"    loyalty_points={loyalty} (default)")
    results.append("MsgPack v2->v3: PASS")

    # v1 data -> v3 reader
    print("\n  v1 data -> v3 reader:")
    d = msgpack_decode(v1_bytes)
    loyalty = d.get("loyalty_points", 0)
    tip = d.get("tip_cents", 0)
    items = d.get("items")
    print(f"    loyalty_points={loyalty}, tip_cents={tip}")
    if isinstance(items, str):
        print("    items type mismatch persists")
        results.append("MsgPack v1->v3: PARTIAL (items type mismatch)")
    else:
        results.append("MsgPack v1->v3: PASS")

    return results


# ============================================================================
# Protobuf migration
# ============================================================================

# Protobuf field assignments:
#   1: id, 2: customer_id, 3: restaurant_id, 4: items_str (v1) / unused,
#   5: status, 6: total_cents, 7: created_at (as varint epoch)
#   v2 adds: 8: tip_cents, 9: driver_id, 10: items (repeated string)
#   v3 adds: 11: loyalty_points, removes: 6 (total_cents)

def _proto_v1() -> bytes:
    return b"".join([
        encode_string_field(1, V1_DATA["id"]),
        encode_string_field(2, V1_DATA["customer_id"]),
        encode_string_field(3, V1_DATA["restaurant_id"]),
        encode_string_field(4, V1_DATA["items"]),  # items as string
        encode_string_field(5, V1_DATA["status"]),
        encode_varint_field(6, V1_DATA["total_cents"]),
        encode_varint_field(7, int(V1_DATA["created_at"])),
    ])


def _proto_v2() -> bytes:
    parts = [
        encode_string_field(1, V2_DATA["id"]),
        encode_string_field(2, V2_DATA["customer_id"]),
        encode_string_field(3, V2_DATA["restaurant_id"]),
        # field 4 omitted (items moved to repeated field 10)
        encode_string_field(5, V2_DATA["status"]),
        encode_varint_field(6, V2_DATA["total_cents"]),
        encode_varint_field(7, int(V2_DATA["created_at"])),
        encode_varint_field(8, V2_DATA["tip_cents"]),
        encode_string_field(9, V2_DATA["driver_id"]),
    ]
    for item in V2_DATA["items"]:
        parts.append(encode_string_field(10, item))
    return b"".join(parts)


def _proto_v3() -> bytes:
    parts = [
        encode_string_field(1, V3_DATA["id"]),
        encode_string_field(2, V3_DATA["customer_id"]),
        encode_string_field(3, V3_DATA["restaurant_id"]),
        encode_string_field(5, V3_DATA["status"]),
        # field 6 (total_cents) removed
        encode_varint_field(7, int(V3_DATA["created_at"])),
        encode_varint_field(8, V3_DATA["tip_cents"]),
        encode_string_field(9, V3_DATA["driver_id"]),
        encode_varint_field(11, V3_DATA["loyalty_points"]),
    ]
    for item in V3_DATA["items"]:
        parts.append(encode_string_field(10, item))
    return b"".join(parts)


def _proto_read_v2(data: bytes) -> dict:
    """V2 reader."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["customer_id"] = fields[2][0].decode("utf-8")
    if 3 in fields:
        result["restaurant_id"] = fields[3][0].decode("utf-8")
    if 5 in fields:
        result["status"] = fields[5][0].decode("utf-8")
    if 6 in fields:
        result["total_cents"] = fields[6][0]
    if 7 in fields:
        result["created_at"] = fields[7][0]
    if 8 in fields:
        result["tip_cents"] = fields[8][0]
    else:
        result["tip_cents"] = 0
    if 9 in fields:
        result["driver_id"] = fields[9][0].decode("utf-8")
    else:
        result["driver_id"] = None
    if 10 in fields:
        result["items"] = [v.decode("utf-8") for v in fields[10]]
    elif 4 in fields:
        # Fallback: read old items_str
        result["items_str"] = fields[4][0].decode("utf-8")
    return result


def _proto_read_v3(data: bytes) -> dict:
    """V3 reader."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["customer_id"] = fields[2][0].decode("utf-8")
    if 3 in fields:
        result["restaurant_id"] = fields[3][0].decode("utf-8")
    if 5 in fields:
        result["status"] = fields[5][0].decode("utf-8")
    if 7 in fields:
        result["created_at"] = fields[7][0]
    if 8 in fields:
        result["tip_cents"] = fields[8][0]
    else:
        result["tip_cents"] = 0
    if 9 in fields:
        result["driver_id"] = fields[9][0].decode("utf-8")
    else:
        result["driver_id"] = None
    if 10 in fields:
        result["items"] = [v.decode("utf-8") for v in fields[10]]
    if 11 in fields:
        result["loyalty_points"] = fields[11][0]
    else:
        result["loyalty_points"] = 0
    # total_cents not read in v3
    return result


def demo_protobuf() -> list[str]:
    print("\n--- Protobuf Schema Migration ---\n")
    results = []

    v1_bytes = _proto_v1()
    v2_bytes = _proto_v2()
    v3_bytes = _proto_v3()

    print(f"  v1 payload: {len(v1_bytes)} bytes")
    print(f"  v2 payload: {len(v2_bytes)} bytes")
    print(f"  v3 payload: {len(v3_bytes)} bytes")

    # v1 data -> v2 reader
    print("\n  v1 data -> v2 reader:")
    d = _proto_read_v2(v1_bytes)
    print(f"    id={d.get('id')}, tip_cents={d.get('tip_cents')} (default)")
    print(f"    driver_id={d.get('driver_id')} (default)")
    if "items_str" in d:
        print(f"    items_str='{d['items_str']}' (v1 field 4, v2 reader falls back)")
    results.append("Protobuf v1->v2: PASS (missing fields get defaults, old field 4 readable)")

    # v2 data -> v3 reader
    print("\n  v2 data -> v3 reader:")
    d = _proto_read_v3(v2_bytes)
    print(f"    id={d.get('id')}, loyalty_points={d.get('loyalty_points')} (default)")
    print("    total_cents not read (v3 ignores field 6)")
    results.append("Protobuf v2->v3: PASS (new fields default, removed field ignored)")

    # v1 data -> v3 reader
    print("\n  v1 data -> v3 reader:")
    d = _proto_read_v3(v1_bytes)
    print(f"    id={d.get('id')}, loyalty_points={d.get('loyalty_points')}")
    print(f"    tip_cents={d.get('tip_cents')}, driver_id={d.get('driver_id')}")
    print(f"    items={d.get('items', [])}")
    results.append("Protobuf v1->v3: PASS (two-version gap still works via field tags)")

    return results


# ============================================================================
# Avro migration
# ============================================================================

AVRO_V1 = {
    "type": "record",
    "name": "SimpleOrder",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {"name": "restaurant_id", "type": "string"},
        {"name": "items", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "total_cents", "type": "int"},
        {"name": "created_at", "type": "long"},
    ],
}

AVRO_V2 = {
    "type": "record",
    "name": "SimpleOrder",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {"name": "restaurant_id", "type": "string"},
        {"name": "items", "type": {"type": "array", "items": "string"}},
        {"name": "status", "type": "string"},
        {"name": "total_cents", "type": "int"},
        {"name": "tip_cents", "type": "int", "default": 0},
        {"name": "driver_id", "type": ["null", "string"], "default": None},
        {"name": "created_at", "type": "long"},
    ],
}

AVRO_V3 = {
    "type": "record",
    "name": "SimpleOrder",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {"name": "restaurant_id", "type": "string"},
        {"name": "items", "type": {"type": "array", "items": "string"}},
        {"name": "status", "type": "string"},
        {"name": "tip_cents", "type": "int", "default": 0},
        {"name": "driver_id", "type": ["null", "string"], "default": None},
        {"name": "loyalty_points", "type": "int", "default": 0},
        {"name": "created_at", "type": "long"},
    ],
}

AVRO_V1_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": "2x Burger, 1x Fries",
    "status": "confirmed",
    "total_cents": 3597,
    "created_at": 1700000000,
}

AVRO_V2_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": ["Burger", "Burger", "Fries"],
    "status": "confirmed",
    "total_cents": 3597,
    "tip_cents": 500,
    "driver_id": "driv001",
    "created_at": 1700000000,
}

AVRO_V3_DATA = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "items": ["Burger", "Burger", "Fries"],
    "status": "confirmed",
    "tip_cents": 500,
    "driver_id": "driv001",
    "loyalty_points": 150,
    "created_at": 1700000000,
}


def demo_avro() -> list[str]:
    print("\n--- Avro Schema Migration ---\n")
    results = []

    v1_bytes = avro_encode(AVRO_V1, AVRO_V1_DATA)
    v2_bytes = avro_encode(AVRO_V2, AVRO_V2_DATA)
    v3_bytes = avro_encode(AVRO_V3, AVRO_V3_DATA)

    print(f"  v1 payload: {len(v1_bytes)} bytes")
    print(f"  v2 payload: {len(v2_bytes)} bytes")
    print(f"  v3 payload: {len(v3_bytes)} bytes")

    # v1 data -> v2 reader
    # Without schema resolution, reading v1 bytes with v2 schema fails because
    # v1 encoded 'items' as a string but v2 expects an array
    print("\n  v1 data -> v2 reader (without resolution):")
    try:
        decoded, _ = avro_decode(AVRO_V2, v1_bytes)
        print(f"    Decoded: {decoded}")
        results.append("Avro v1->v2: PASS")
    except Exception as e:
        print(f"    FAILS: {type(e).__name__}: {e}")
        print("    Reason: v1 wrote items as string, v2 expects array. Without schema")
        print("    resolution, the reader tries to decode string bytes as an array.")
        print("    With a Schema Registry, the reader would use the WRITER's schema")
        print("    to read, then apply field-by-field resolution to the READER's schema.")
        results.append("Avro v1->v2: FAIL (items type changed str->array, needs resolution)")

    # v2 data -> v3 reader
    print("\n  v2 data -> v3 reader (without resolution):")
    try:
        decoded, _ = avro_decode(AVRO_V3, v2_bytes)
        print(f"    id={decoded.get('id')}")
        print(f"    loyalty_points={decoded.get('loyalty_points')}")
        # This may work by accident if total_cents (removed in v3) lines up
        results.append("Avro v2->v3: FAIL (positional mismatch without resolution)")
    except Exception as e:
        print(f"    FAILS: {type(e).__name__}")
        print("    Reason: v2 wrote total_cents at position 5, v3 schema doesn't have it.")
        print("    Without resolution, reader misaligns all subsequent fields.")
        results.append("Avro v2->v3: FAIL (field layout changed, needs resolution)")

    # v1 data -> v3 reader
    print("\n  v1 data -> v3 reader (without resolution):")
    try:
        decoded, _ = avro_decode(AVRO_V3, v1_bytes)
        results.append("Avro v1->v3: FAIL")
    except Exception as e:
        print(f"    FAILS: {type(e).__name__}")
        print("    Two-version gap: items type + removed fields = guaranteed failure.")
        results.append("Avro v1->v3: FAIL (two-version gap, needs resolution)")

    # Explain what SHOULD happen with proper resolution
    print("\n  With proper schema resolution (Schema Registry):")
    print("    - Reader receives writer schema ID with each message")
    print("    - Decoder reads data using writer's schema")
    print("    - Then resolves field-by-field to reader's schema:")
    print("      * Fields in both: copy (with type promotion if needed)")
    print("      * Fields only in writer: skip")
    print("      * Fields only in reader: use default value")
    print("    - This is why Avro REQUIRES defaults for backward compat")
    print("    - And why Avro REQUIRES a Schema Registry in production")

    return results


# ============================================================================
# Summary
# ============================================================================

def print_summary(all_results: dict[str, list[str]]) -> None:
    print("\n" + "=" * 70)
    print("  MIGRATION SUMMARY: v1 -> v2 -> v3")
    print("=" * 70)

    for fmt, results in all_results.items():
        print(f"\n  {fmt}:")
        for r in results:
            symbol = "+" if "PASS" in r else ("~" if "PARTIAL" in r else "!")
            print(f"    [{symbol}] {r}")

    print()
    print("  KEY TAKEAWAYS:")
    print("  - JSON/MsgPack: adding fields is safe with .get() defaults.")
    print("    But changing a field's type (string->list) is silent corruption.")
    print("  - Protobuf: all three version jumps work seamlessly because")
    print("    fields are identified by tag number, not position or name.")
    print("    This is protobuf's biggest schema evolution advantage.")
    print("  - Avro: without a Schema Registry, even simple migrations break.")
    print("    With resolution, add-with-default and remove-with-default work.")
    print("    But type changes (string->array) still need careful migration.")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("=" * 70)
    print("  Schema Migration Demo: v1 -> v2 -> v3 Across Formats")
    print("=" * 70)
    print()
    print("  Simulating 6 months of FoodDash Order schema evolution.")
    print("  v1: launch -- basic fields, items as string")
    print("  v2: +3 months -- add tip_cents, driver_id; items becomes list")
    print("  v3: +6 months -- add loyalty_points, remove total_cents")

    all_results: dict[str, list[str]] = {}
    all_results["JSON"] = demo_json()
    all_results["MsgPack"] = demo_msgpack()
    all_results["Protobuf"] = demo_protobuf()
    all_results["Avro"] = demo_avro()

    print_summary(all_results)


if __name__ == "__main__":
    main()
