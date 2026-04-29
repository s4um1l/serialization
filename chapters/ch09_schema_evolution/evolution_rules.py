"""Schema evolution rules — test what happens when schemas change.

For each format (JSON, MessagePack, Protobuf, Avro), we test six types of
schema changes and report whether the old reader survives:

  1. Add a field
  2. Remove a field
  3. Rename a field
  4. Change field type
  5. Add an enum value
  6. Reorder fields

Each test encodes data with the "new" schema and attempts to decode with the
"old" reader expectations. Results are PASS, PARTIAL, or FAIL.
"""

from __future__ import annotations

import json

from chapters.ch03_msgpack_cbor.msgpack_from_scratch import (
    msgpack_decode,
    msgpack_encode,
)
from chapters.ch04_protobuf.proto_from_scratch import (
    decode_message,
    encode_enum_field,
    encode_string_field,
    encode_varint_field,
)
from chapters.ch06_avro.avro_from_scratch import avro_decode, avro_encode


# ============================================================================
# Test data: a simplified order used across all tests
# ============================================================================

BASE_ORDER = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "driver_id": "driv001",
    "status": "confirmed",
    "total_cents": 2599,
    "tip_cents": 500,
    "promo_code": "SAVE20",
    "created_at": 1700000000.0,
}

# Enum values for protobuf
STATUS_MAP = {
    "placed": 1, "confirmed": 2, "preparing": 3, "ready": 4,
    "picked_up": 5, "en_route": 6, "delivered": 7, "cancelled": 8,
}

STATUS_MAP_INV = {v: k for k, v in STATUS_MAP.items()}


# ============================================================================
# Result tracking
# ============================================================================

RESULTS: dict[str, dict[str, str]] = {}

CHANGES = [
    "Add field",
    "Remove field",
    "Rename field",
    "Change type",
    "Add enum value",
    "Reorder fields",
]


def record(fmt: str, change: str, result: str, note: str = "") -> None:
    """Record a test result."""
    RESULTS.setdefault(fmt, {})[change] = result
    symbol = {"PASS": "+", "PARTIAL": "~", "FAIL": "!"}[result]
    print(f"  [{symbol}] {result:<8s} {change:<20s} {note}")


# ============================================================================
# JSON tests
# ============================================================================

def test_json() -> None:
    print("\n--- JSON ---\n")

    # 1. Add field: writer adds loyalty_points
    new_data = {**BASE_ORDER, "loyalty_points": 150}
    encoded = json.dumps(new_data).encode("utf-8")
    decoded = json.loads(encoded)
    # Old reader that only expects original fields — uses .get()
    old_id = decoded.get("id")
    # loyalty_points is just ignored if reader doesn't look for it
    if old_id == "ord001":
        record("JSON", "Add field", "PASS",
               "old reader ignores unknown keys (if using .get())")
    else:
        record("JSON", "Add field", "FAIL")

    # 2. Remove field: writer removes promo_code
    removed = {k: v for k, v in BASE_ORDER.items() if k != "promo_code"}
    encoded = json.dumps(removed).encode("utf-8")
    decoded = json.loads(encoded)
    # Old reader expects promo_code
    try:
        _ = decoded["promo_code"]
        record("JSON", "Remove field", "PASS")
    except KeyError:
        # .get() would work, direct access fails
        val = decoded.get("promo_code")
        if val is None:
            record("JSON", "Remove field", "PARTIAL",
                   ".get() returns None; dict['key'] raises KeyError")
        else:
            record("JSON", "Remove field", "FAIL")

    # 3. Rename field: writer renames driver_id to courier_id
    renamed = {("courier_id" if k == "driver_id" else k): v
               for k, v in BASE_ORDER.items()}
    encoded = json.dumps(renamed).encode("utf-8")
    decoded = json.loads(encoded)
    old_driver = decoded.get("driver_id")
    if old_driver is None:
        record("JSON", "Rename field", "FAIL",
               "old reader sees driver_id=None, data is in courier_id")
    else:
        record("JSON", "Rename field", "PASS")

    # 4. Change type: writer sends tip_cents as string "500"
    type_changed = {**BASE_ORDER, "tip_cents": "500"}
    encoded = json.dumps(type_changed).encode("utf-8")
    decoded = json.loads(encoded)
    tip = decoded.get("tip_cents")
    if isinstance(tip, int):
        record("JSON", "Change type", "PASS")
    elif isinstance(tip, str):
        record("JSON", "Change type", "FAIL",
               f"old reader expects int, got str '{tip}' -- silent corruption")
    else:
        record("JSON", "Change type", "FAIL")

    # 5. Add enum value: writer sends status="refunded"
    new_enum = {**BASE_ORDER, "status": "refunded"}
    encoded = json.dumps(new_enum).encode("utf-8")
    decoded = json.loads(encoded)
    status = decoded.get("status")
    # JSON has no enum concept — it's just a string
    if status == "refunded":
        record("JSON", "Add enum value", "PARTIAL",
               "no crash, but old reader may not handle 'refunded' in logic")
    else:
        record("JSON", "Add enum value", "FAIL")

    # 6. Reorder fields
    reordered = {
        "created_at": BASE_ORDER["created_at"],
        "id": BASE_ORDER["id"],
        "status": BASE_ORDER["status"],
        "total_cents": BASE_ORDER["total_cents"],
        "customer_id": BASE_ORDER["customer_id"],
        "restaurant_id": BASE_ORDER["restaurant_id"],
        "driver_id": BASE_ORDER["driver_id"],
        "tip_cents": BASE_ORDER["tip_cents"],
        "promo_code": BASE_ORDER["promo_code"],
    }
    encoded = json.dumps(reordered).encode("utf-8")
    decoded = json.loads(encoded)
    if decoded.get("id") == "ord001" and decoded.get("total_cents") == 2599:
        record("JSON", "Reorder fields", "PASS",
               "JSON objects are unordered by spec")


# ============================================================================
# MessagePack tests
# ============================================================================

def test_msgpack() -> None:
    print("\n--- MessagePack ---\n")

    # 1. Add field
    new_data = {**BASE_ORDER, "loyalty_points": 150}
    encoded = msgpack_encode(new_data)
    decoded = msgpack_decode(encoded)
    if decoded.get("id") == "ord001":
        record("MsgPack", "Add field", "PASS",
               "old reader ignores unknown keys (if using .get())")

    # 2. Remove field
    removed = {k: v for k, v in BASE_ORDER.items() if k != "promo_code"}
    encoded = msgpack_encode(removed)
    decoded = msgpack_decode(encoded)
    val = decoded.get("promo_code")
    if val is None:
        record("MsgPack", "Remove field", "PARTIAL",
               ".get() returns None; direct access raises KeyError")

    # 3. Rename field
    renamed = {("courier_id" if k == "driver_id" else k): v
               for k, v in BASE_ORDER.items()}
    encoded = msgpack_encode(renamed)
    decoded = msgpack_decode(encoded)
    if decoded.get("driver_id") is None:
        record("MsgPack", "Rename field", "FAIL",
               "old reader sees driver_id=None, data is in courier_id")

    # 4. Change type
    type_changed = {**BASE_ORDER, "tip_cents": "500"}
    encoded = msgpack_encode(type_changed)
    decoded = msgpack_decode(encoded)
    tip = decoded.get("tip_cents")
    if isinstance(tip, str):
        record("MsgPack", "Change type", "FAIL",
               f"old reader expects int, got str '{tip}' -- silent corruption")

    # 5. Add enum value
    new_enum = {**BASE_ORDER, "status": "refunded"}
    encoded = msgpack_encode(new_enum)
    decoded = msgpack_decode(encoded)
    if decoded.get("status") == "refunded":
        record("MsgPack", "Add enum value", "PARTIAL",
               "no crash, but old reader may not handle 'refunded' in logic")

    # 6. Reorder fields
    reordered = {
        "created_at": BASE_ORDER["created_at"],
        "id": BASE_ORDER["id"],
        "status": BASE_ORDER["status"],
        "total_cents": BASE_ORDER["total_cents"],
        "customer_id": BASE_ORDER["customer_id"],
        "restaurant_id": BASE_ORDER["restaurant_id"],
        "driver_id": BASE_ORDER["driver_id"],
        "tip_cents": BASE_ORDER["tip_cents"],
        "promo_code": BASE_ORDER["promo_code"],
    }
    encoded = msgpack_encode(reordered)
    decoded = msgpack_decode(encoded)
    if decoded.get("id") == "ord001" and decoded.get("total_cents") == 2599:
        record("MsgPack", "Reorder fields", "PASS",
               "maps are keyed by name, order is irrelevant")


# ============================================================================
# Protobuf tests (using proto_from_scratch)
# ============================================================================

def _proto_encode_base_order() -> bytes:
    """Encode the base order with our simplified proto schema.

    Field assignments:
        1: id (string)
        2: customer_id (string)
        3: restaurant_id (string)
        4: driver_id (string)
        5: status (enum)
        6: total_cents (varint)
        7: tip_cents (varint)
        8: promo_code (string)
    """
    return b"".join([
        encode_string_field(1, BASE_ORDER["id"]),
        encode_string_field(2, BASE_ORDER["customer_id"]),
        encode_string_field(3, BASE_ORDER["restaurant_id"]),
        encode_string_field(4, BASE_ORDER["driver_id"]),
        encode_enum_field(5, STATUS_MAP[BASE_ORDER["status"]]),
        encode_varint_field(6, BASE_ORDER["total_cents"]),
        encode_varint_field(7, BASE_ORDER["tip_cents"]),
        encode_string_field(8, BASE_ORDER["promo_code"]),
    ])


def _proto_decode_old(data: bytes) -> dict:
    """Decode with the 'old' reader that expects fields 1-8."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["customer_id"] = fields[2][0].decode("utf-8")
    if 3 in fields:
        result["restaurant_id"] = fields[3][0].decode("utf-8")
    if 4 in fields:
        result["driver_id"] = fields[4][0].decode("utf-8")
    if 5 in fields:
        result["status"] = STATUS_MAP_INV.get(fields[5][0], f"UNKNOWN({fields[5][0]})")
    if 6 in fields:
        result["total_cents"] = fields[6][0]
    if 7 in fields:
        result["tip_cents"] = fields[7][0]
    if 8 in fields:
        result["promo_code"] = fields[8][0].decode("utf-8")
    return result


def test_protobuf() -> None:
    print("\n--- Protobuf (from_scratch) ---\n")

    # 1. Add field: writer adds field 9 (loyalty_points)
    new_data = _proto_encode_base_order() + encode_varint_field(9, 150)
    decoded = _proto_decode_old(new_data)
    if decoded.get("id") == "ord001" and decoded.get("tip_cents") == 500:
        record("Protobuf", "Add field", "PASS",
               "unknown field 9 is silently skipped by old reader")

    # 2. Remove field: writer omits promo_code (field 8)
    removed_data = b"".join([
        encode_string_field(1, BASE_ORDER["id"]),
        encode_string_field(2, BASE_ORDER["customer_id"]),
        encode_string_field(3, BASE_ORDER["restaurant_id"]),
        encode_string_field(4, BASE_ORDER["driver_id"]),
        encode_enum_field(5, STATUS_MAP[BASE_ORDER["status"]]),
        encode_varint_field(6, BASE_ORDER["total_cents"]),
        encode_varint_field(7, BASE_ORDER["tip_cents"]),
        # field 8 omitted
    ])
    decoded = _proto_decode_old(removed_data)
    if decoded.get("id") == "ord001" and "promo_code" not in decoded:
        record("Protobuf", "Remove field", "PASS",
               "missing field gets default value (empty string/0)")

    # 3. Rename field: writer renames driver_id to courier_id but keeps field 4
    # In protobuf, only the field NUMBER matters, not the name
    renamed_data = _proto_encode_base_order()  # field 4 still has "driv001"
    decoded = _proto_decode_old(renamed_data)
    if decoded.get("driver_id") == "driv001":
        record("Protobuf", "Rename field", "PASS",
               "field names are irrelevant on wire; only tags matter")

    # 4. Change wire type: writer sends tip_cents (field 7) as string instead of varint
    type_changed = b"".join([
        encode_string_field(1, BASE_ORDER["id"]),
        encode_string_field(2, BASE_ORDER["customer_id"]),
        encode_string_field(3, BASE_ORDER["restaurant_id"]),
        encode_string_field(4, BASE_ORDER["driver_id"]),
        encode_enum_field(5, STATUS_MAP[BASE_ORDER["status"]]),
        encode_varint_field(6, BASE_ORDER["total_cents"]),
        encode_string_field(7, "500"),  # string instead of varint!
        encode_string_field(8, BASE_ORDER["promo_code"]),
    ])
    decoded = _proto_decode_old(type_changed)
    tip = decoded.get("tip_cents")
    # decode_message will decode field 7 as length-delimited bytes, not varint
    if isinstance(tip, int) and tip == 500:
        record("Protobuf", "Change type", "PASS")
    else:
        record("Protobuf", "Change type", "FAIL",
               f"wire type mismatch: old reader sees bytes, not varint (got {tip!r})")

    # 5. Add enum value: writer sends status=9 (REFUNDED, not in old enum)
    new_enum = b"".join([
        encode_string_field(1, BASE_ORDER["id"]),
        encode_string_field(2, BASE_ORDER["customer_id"]),
        encode_string_field(3, BASE_ORDER["restaurant_id"]),
        encode_string_field(4, BASE_ORDER["driver_id"]),
        encode_enum_field(5, 9),  # REFUNDED = 9
        encode_varint_field(6, BASE_ORDER["total_cents"]),
        encode_varint_field(7, BASE_ORDER["tip_cents"]),
        encode_string_field(8, BASE_ORDER["promo_code"]),
    ])
    decoded = _proto_decode_old(new_enum)
    status = decoded.get("status")
    if status and "UNKNOWN" in str(status):
        record("Protobuf", "Add enum value", "PARTIAL",
               f"no crash, but value unrecognized: {status}")
    else:
        record("Protobuf", "Add enum value", "PASS")

    # 6. Reorder fields: protobuf fields can appear in any order
    reordered = b"".join([
        encode_varint_field(7, BASE_ORDER["tip_cents"]),
        encode_string_field(1, BASE_ORDER["id"]),
        encode_enum_field(5, STATUS_MAP[BASE_ORDER["status"]]),
        encode_string_field(8, BASE_ORDER["promo_code"]),
        encode_string_field(4, BASE_ORDER["driver_id"]),
        encode_varint_field(6, BASE_ORDER["total_cents"]),
        encode_string_field(2, BASE_ORDER["customer_id"]),
        encode_string_field(3, BASE_ORDER["restaurant_id"]),
    ])
    decoded = _proto_decode_old(reordered)
    if decoded.get("id") == "ord001" and decoded.get("tip_cents") == 500:
        record("Protobuf", "Reorder fields", "PASS",
               "fields identified by tag number, not position")


# ============================================================================
# Avro tests (using avro_from_scratch)
# ============================================================================

# Writer schema v1 (base)
AVRO_SCHEMA_V1 = {
    "type": "record",
    "name": "SimpleOrder",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "customer_id", "type": "string"},
        {"name": "restaurant_id", "type": "string"},
        {"name": "driver_id", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "total_cents", "type": "int"},
        {"name": "tip_cents", "type": "int"},
        {"name": "promo_code", "type": "string"},
    ],
}

AVRO_BASE = {
    "id": "ord001",
    "customer_id": "cust001",
    "restaurant_id": "rest001",
    "driver_id": "driv001",
    "status": "confirmed",
    "total_cents": 2599,
    "tip_cents": 500,
    "promo_code": "SAVE20",
}


def test_avro() -> None:
    print("\n--- Avro (from_scratch) ---\n")

    # 1. Add field: writer schema has loyalty_points with default
    writer_add = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            *AVRO_SCHEMA_V1["fields"],
            {"name": "loyalty_points", "type": "int", "default": 0},
        ],
    }
    data_add = {**AVRO_BASE, "loyalty_points": 150}
    encoded = avro_encode(writer_add, data_add)
    # Old reader uses AVRO_SCHEMA_V1 — which has fewer fields
    # Avro schema resolution: reader ignores writer fields not in reader schema
    # But our from-scratch decoder reads fields IN ORDER from the reader schema.
    # Without resolution logic, the reader just reads its fields in order.
    # Since the writer wrote more bytes than the reader expects, the reader
    # will consume exactly its fields and ignore trailing bytes.
    try:
        decoded, end = avro_decode(AVRO_SCHEMA_V1, encoded)
        if decoded.get("id") == "ord001" and decoded.get("tip_cents") == 500:
            record("Avro", "Add field", "PASS",
                   "reader ignores trailing data from new fields (with default)")
        else:
            record("Avro", "Add field", "PARTIAL",
                   f"decoded but values shifted: id={decoded.get('id')}")
    except Exception as e:
        record("Avro", "Add field", "FAIL", str(e))

    # 2. Remove field: writer omits promo_code
    writer_remove = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "driver_id", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "total_cents", "type": "int"},
            {"name": "tip_cents", "type": "int"},
            # promo_code removed
        ],
    }
    data_remove = {k: v for k, v in AVRO_BASE.items() if k != "promo_code"}
    encoded = avro_encode(writer_remove, data_remove)
    try:
        decoded, end = avro_decode(AVRO_SCHEMA_V1, encoded)
        # Reader expects promo_code but writer didn't write it.
        # Without resolution, reader will read past end or misinterpret bytes.
        if decoded.get("promo_code") == "SAVE20":
            record("Avro", "Remove field", "PASS")
        else:
            record("Avro", "Remove field", "FAIL",
                   f"promo_code={decoded.get('promo_code')!r} (expected to fail without resolution)")
    except Exception as e:
        record("Avro", "Remove field", "FAIL",
               f"reader crashes: {type(e).__name__} (needs schema resolution)")

    # 3. Rename field: writer renames driver_id to courier_id
    writer_rename = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "courier_id", "type": "string"},  # renamed
            {"name": "status", "type": "string"},
            {"name": "total_cents", "type": "int"},
            {"name": "tip_cents", "type": "int"},
            {"name": "promo_code", "type": "string"},
        ],
    }
    encoded = avro_encode(writer_rename, {**AVRO_BASE, "courier_id": "driv001"})
    # Same position, same type — bytes are identical on wire
    try:
        decoded, end = avro_decode(AVRO_SCHEMA_V1, encoded)
        if decoded.get("driver_id") == "driv001":
            record("Avro", "Rename field", "PARTIAL",
                   "same position works by accident; proper resolution matches by NAME and fails")
        else:
            record("Avro", "Rename field", "FAIL",
                   "fields matched by name, not position — rename breaks resolution")
    except Exception as e:
        record("Avro", "Rename field", "FAIL", str(e))

    # 4. Change type: writer sends tip_cents as string
    writer_type = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "driver_id", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "total_cents", "type": "int"},
            {"name": "tip_cents", "type": "string"},  # was int
            {"name": "promo_code", "type": "string"},
        ],
    }
    data_type = {**AVRO_BASE, "tip_cents": "500"}
    encoded = avro_encode(writer_type, data_type)
    try:
        decoded, end = avro_decode(AVRO_SCHEMA_V1, encoded)
        tip = decoded.get("tip_cents")
        if isinstance(tip, int) and tip == 500:
            record("Avro", "Change type", "PASS")
        else:
            record("Avro", "Change type", "FAIL",
                   f"type mismatch: got {tip!r} ({type(tip).__name__})")
    except Exception as e:
        record("Avro", "Change type", "FAIL",
               f"reader crashes: {type(e).__name__} (string bytes misread as varint)")

    # 5. Add enum value: using string-based status, so same as JSON
    writer_enum = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "driver_id", "type": "string"},
            {"name": "status", "type": {
                "type": "enum",
                "name": "OrderStatus",
                "symbols": ["PLACED", "CONFIRMED", "PREPARING", "READY",
                            "PICKED_UP", "EN_ROUTE", "DELIVERED", "CANCELLED",
                            "REFUNDED"],  # new value
            }},
            {"name": "total_cents", "type": "int"},
            {"name": "tip_cents", "type": "int"},
            {"name": "promo_code", "type": "string"},
        ],
    }
    reader_enum = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "driver_id", "type": "string"},
            {"name": "status", "type": {
                "type": "enum",
                "name": "OrderStatus",
                "symbols": ["PLACED", "CONFIRMED", "PREPARING", "READY",
                            "PICKED_UP", "EN_ROUTE", "DELIVERED", "CANCELLED"],
            }},
            {"name": "total_cents", "type": "int"},
            {"name": "tip_cents", "type": "int"},
            {"name": "promo_code", "type": "string"},
        ],
    }
    data_enum = {**AVRO_BASE, "status": "REFUNDED"}
    encoded = avro_encode(writer_enum, data_enum)
    try:
        decoded, end = avro_decode(reader_enum, encoded)
        record("Avro", "Add enum value", "FAIL",
               f"decoded status={decoded.get('status')!r} but index 8 out of reader's range")
    except (IndexError, Exception) as e:
        record("Avro", "Add enum value", "FAIL",
               f"reader crashes: {type(e).__name__} (enum index out of range)")

    # 6. Reorder fields
    writer_reorder = {
        "type": "record",
        "name": "SimpleOrder",
        "fields": [
            {"name": "status", "type": "string"},
            {"name": "id", "type": "string"},
            {"name": "total_cents", "type": "int"},
            {"name": "customer_id", "type": "string"},
            {"name": "restaurant_id", "type": "string"},
            {"name": "driver_id", "type": "string"},
            {"name": "tip_cents", "type": "int"},
            {"name": "promo_code", "type": "string"},
        ],
    }
    reordered_data = {
        "status": "confirmed",
        "id": "ord001",
        "total_cents": 2599,
        "customer_id": "cust001",
        "restaurant_id": "rest001",
        "driver_id": "driv001",
        "tip_cents": 500,
        "promo_code": "SAVE20",
    }
    encoded = avro_encode(writer_reorder, reordered_data)
    try:
        decoded, end = avro_decode(AVRO_SCHEMA_V1, encoded)
        # Without resolution, fields are read positionally — order mismatch!
        if decoded.get("id") == "ord001":
            record("Avro", "Reorder fields", "PASS")
        else:
            record("Avro", "Reorder fields", "FAIL",
                   f"positional decoding fails: id={decoded.get('id')!r} "
                   "(with resolution by name, this would work)")
    except Exception as e:
        record("Avro", "Reorder fields", "FAIL",
               f"reader crashes: {type(e).__name__}")


# ============================================================================
# Summary matrix
# ============================================================================

def print_matrix() -> None:
    print("\n" + "=" * 80)
    print("  SCHEMA EVOLUTION COMPATIBILITY MATRIX")
    print("=" * 80)
    print()

    formats = ["JSON", "MsgPack", "Protobuf", "Avro"]
    col_width = 12

    # Header
    header = f"  {'Change':<20s}"
    for fmt in formats:
        header += f" {fmt:^{col_width}s}"
    print(header)
    print("  " + "-" * 20 + (" " + "-" * col_width) * len(formats))

    # Rows
    for change in CHANGES:
        row = f"  {change:<20s}"
        for fmt in formats:
            result = RESULTS.get(fmt, {}).get(change, "N/A")
            if result == "PASS":
                marker = "PASS"
            elif result == "PARTIAL":
                marker = "PARTIAL"
            elif result == "FAIL":
                marker = "FAIL"
            else:
                marker = "N/A"
            row += f" {marker:^{col_width}s}"
        print(row)

    print()
    print("  Legend: PASS = works correctly")
    print("          PARTIAL = works with caveats (e.g., unknown value, needs .get())")
    print("          FAIL = breaks (crash, data loss, or silent corruption)")
    print()

    # Key insights
    print("  KEY INSIGHTS:")
    print("  - JSON/MsgPack: self-describing, so add/reorder is safe.")
    print("    But rename breaks (different key) and type change silently corrupts.")
    print("  - Protobuf: tag-based, so add/remove/rename/reorder all safe.")
    print("    But wire type change breaks, and new enum values need careful handling.")
    print("  - Avro: position-based without resolution, so add-at-end works but")
    print("    remove/reorder breaks. With proper schema resolution (matching by name),")
    print("    add-with-default and remove-with-default are safe; reorder is safe.")
    print("    Rename always breaks (fields matched by name). Type changes break")
    print("    unless they are Avro-supported promotions (int->long, float->double).")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("=" * 70)
    print("  Schema Evolution Rules: What Breaks, What Survives")
    print("=" * 70)
    print()
    print("  Testing 6 schema changes across 4 formats.")
    print("  Writer uses the NEW schema, reader uses the OLD schema.")

    test_json()
    test_msgpack()
    test_protobuf()
    test_avro()
    print_matrix()


if __name__ == "__main__":
    main()
