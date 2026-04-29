"""Compatibility matrix: backward, forward, and full compatibility by format.

Tests each format for:
  - Backward compatible: new reader can read old data
  - Forward compatible: old reader can read new data
  - Full compatible: both directions work

Also explains Confluent Schema Registry compatibility modes.
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
# Shared test schemas: "old" and "new" versions
# ============================================================================

# Old schema: id, name, price_cents
OLD_DATA = {"id": "item001", "name": "Burger", "price_cents": 1299}
# New schema: id, name, price_cents, discount_pct (added with default 0)
NEW_DATA = {"id": "item001", "name": "Burger", "price_cents": 1299, "discount_pct": 10}


# ============================================================================
# JSON compatibility tests
# ============================================================================

def test_json_compat() -> dict[str, str]:
    print("\n--- JSON Compatibility ---\n")
    results = {}

    # Backward: new reader reads old data
    old_bytes = json.dumps(OLD_DATA).encode("utf-8")
    decoded = json.loads(old_bytes)
    discount = decoded.get("discount_pct", 0)
    if decoded["id"] == "item001" and discount == 0:
        results["backward"] = "PASS"
        print("  Backward (new reader, old data): PASS")
        print("    new reader uses .get('discount_pct', 0) -> gets default")
    else:
        results["backward"] = "FAIL"
        print("  Backward: FAIL")

    # Forward: old reader reads new data
    new_bytes = json.dumps(NEW_DATA).encode("utf-8")
    decoded = json.loads(new_bytes)
    if decoded["id"] == "item001" and decoded["price_cents"] == 1299:
        results["forward"] = "PASS"
        print("  Forward  (old reader, new data): PASS")
        print("    old reader ignores discount_pct (if using .get())")
    else:
        results["forward"] = "FAIL"
        print("  Forward: FAIL")

    # Full: both directions
    if results["backward"] == "PASS" and results["forward"] == "PASS":
        results["full"] = "PASS"
        print("  Full     (both directions):       PASS")
    else:
        results["full"] = "PARTIAL"
        print("  Full: PARTIAL")

    print("\n  Caveat: JSON compat depends entirely on application-level discipline.")
    print("  The FORMAT provides no enforcement. You must always use .get() with defaults.")

    return results


# ============================================================================
# MessagePack compatibility tests
# ============================================================================

def test_msgpack_compat() -> dict[str, str]:
    print("\n--- MessagePack Compatibility ---\n")
    results = {}

    # Backward: new reader reads old data
    old_bytes = msgpack_encode(OLD_DATA)
    decoded = msgpack_decode(old_bytes)
    discount = decoded.get("discount_pct", 0)
    if decoded["id"] == "item001" and discount == 0:
        results["backward"] = "PASS"
        print("  Backward (new reader, old data): PASS")
        print("    new reader uses .get('discount_pct', 0) -> gets default")
    else:
        results["backward"] = "FAIL"

    # Forward: old reader reads new data
    new_bytes = msgpack_encode(NEW_DATA)
    decoded = msgpack_decode(new_bytes)
    if decoded["id"] == "item001" and decoded["price_cents"] == 1299:
        results["forward"] = "PASS"
        print("  Forward  (old reader, new data): PASS")
        print("    old reader ignores discount_pct")
    else:
        results["forward"] = "FAIL"

    if results["backward"] == "PASS" and results["forward"] == "PASS":
        results["full"] = "PASS"
        print("  Full     (both directions):       PASS")
    else:
        results["full"] = "PARTIAL"

    print("\n  Same caveats as JSON: compat depends on application discipline, not format.")

    return results


# ============================================================================
# Protobuf compatibility tests
# ============================================================================

def _proto_encode_old() -> bytes:
    """Old schema: 1=id, 2=name, 3=price_cents"""
    return b"".join([
        encode_string_field(1, OLD_DATA["id"]),
        encode_string_field(2, OLD_DATA["name"]),
        encode_varint_field(3, OLD_DATA["price_cents"]),
    ])


def _proto_encode_new() -> bytes:
    """New schema: 1=id, 2=name, 3=price_cents, 4=discount_pct"""
    return b"".join([
        encode_string_field(1, NEW_DATA["id"]),
        encode_string_field(2, NEW_DATA["name"]),
        encode_varint_field(3, NEW_DATA["price_cents"]),
        encode_varint_field(4, NEW_DATA["discount_pct"]),
    ])


def _proto_read_new(data: bytes) -> dict:
    """New reader that expects fields 1-4."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["name"] = fields[2][0].decode("utf-8")
    if 3 in fields:
        result["price_cents"] = fields[3][0]
    if 4 in fields:
        result["discount_pct"] = fields[4][0]
    else:
        result["discount_pct"] = 0  # default
    return result


def _proto_read_old(data: bytes) -> dict:
    """Old reader that expects fields 1-3."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["name"] = fields[2][0].decode("utf-8")
    if 3 in fields:
        result["price_cents"] = fields[3][0]
    return result


def test_protobuf_compat() -> dict[str, str]:
    print("\n--- Protobuf Compatibility ---\n")
    results = {}

    # Backward: new reader reads old data
    old_bytes = _proto_encode_old()
    decoded = _proto_read_new(old_bytes)
    if decoded["id"] == "item001" and decoded["discount_pct"] == 0:
        results["backward"] = "PASS"
        print("  Backward (new reader, old data): PASS")
        print("    field 4 missing -> new reader uses default 0")
    else:
        results["backward"] = "FAIL"

    # Forward: old reader reads new data
    new_bytes = _proto_encode_new()
    decoded = _proto_read_old(new_bytes)
    if decoded["id"] == "item001" and decoded["price_cents"] == 1299:
        results["forward"] = "PASS"
        print("  Forward  (old reader, new data): PASS")
        print("    field 4 (discount_pct) silently skipped by old reader")
    else:
        results["forward"] = "FAIL"

    if results["backward"] == "PASS" and results["forward"] == "PASS":
        results["full"] = "PASS"
        print("  Full     (both directions):       PASS")
    else:
        results["full"] = "PARTIAL"

    print("\n  Protobuf provides structural enforcement: unknown tags are skipped,")
    print("  missing tags get default values. This is built into the wire format.")

    return results


# ============================================================================
# Avro compatibility tests
# ============================================================================

AVRO_OLD = {
    "type": "record",
    "name": "Item",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "name", "type": "string"},
        {"name": "price_cents", "type": "int"},
    ],
}

AVRO_NEW = {
    "type": "record",
    "name": "Item",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "name", "type": "string"},
        {"name": "price_cents", "type": "int"},
        {"name": "discount_pct", "type": "int", "default": 0},
    ],
}


def test_avro_compat() -> dict[str, str]:
    print("\n--- Avro Compatibility ---\n")
    results = {}

    # Backward: new reader (AVRO_NEW) reads old data (written with AVRO_OLD)
    old_data = {"id": "item001", "name": "Burger", "price_cents": 1299}
    old_bytes = avro_encode(AVRO_OLD, old_data)

    # Without resolution: just read old bytes with new schema
    # The new schema has 4 fields but old bytes only have 3 fields of data.
    # Reading field 4 (discount_pct) will read past the data -> fail.
    # With resolution: reader knows to use default for missing fields.
    try:
        decoded, end = avro_decode(AVRO_NEW, old_bytes)
        # If old bytes happen to have exactly enough data, check values
        if decoded.get("id") == "item001" and end <= len(old_bytes):
            results["backward"] = "PASS"
            print("  Backward (new reader, old data): PASS")
        else:
            results["backward"] = "FAIL"
            print(f"  Backward: FAIL (got {decoded})")
    except Exception as e:
        results["backward"] = "FAIL*"
        print("  Backward (new reader, old data): FAIL without resolution")
        print(f"    {type(e).__name__}: reader tries to read 4 fields from 3-field data")
        print("    With Schema Registry resolution: PASS (default used for discount_pct)")

    # Forward: old reader (AVRO_OLD) reads new data (written with AVRO_NEW)
    new_data = {"id": "item001", "name": "Burger", "price_cents": 1299, "discount_pct": 10}
    new_bytes = avro_encode(AVRO_NEW, new_data)

    try:
        decoded, end = avro_decode(AVRO_OLD, new_bytes)
        if decoded.get("id") == "item001" and decoded.get("price_cents") == 1299:
            results["forward"] = "PASS"
            print("  Forward  (old reader, new data): PASS")
            print("    old reader reads its 3 fields, ignores trailing bytes")
        else:
            results["forward"] = "FAIL"
            print(f"  Forward: FAIL (got {decoded})")
    except Exception as e:
        results["forward"] = "FAIL"
        print(f"  Forward: FAIL ({type(e).__name__})")

    # Full
    if "FAIL" not in results.get("backward", "FAIL") and "FAIL" not in results.get("forward", "FAIL"):
        results["full"] = "PASS"
        print("  Full     (both directions):       PASS")
    else:
        results["full"] = "PARTIAL"
        print("  Full     (both directions):       PARTIAL")
        if "FAIL" in results.get("backward", ""):
            print("    Backward fails without resolution but works with Schema Registry")

    print("\n  Avro compatibility depends on schema resolution:")
    print("    - Adding field WITH default: backward + forward compatible")
    print("    - Adding field WITHOUT default: breaks backward compatibility")
    print("    - Removing field WITH default: backward + forward compatible")
    print("    - Removing field WITHOUT default: breaks forward compatibility")

    return results


# ============================================================================
# Schema Registry compatibility modes
# ============================================================================

def explain_schema_registry() -> None:
    print("\n" + "=" * 70)
    print("  Confluent Schema Registry: Compatibility Modes")
    print("=" * 70)

    modes = [
        ("BACKWARD", [
            "New schema can read data written by the LAST schema version.",
            "Rule: you can ADD fields (with defaults) and REMOVE fields.",
            "Use case: consumers are upgraded before producers.",
        ]),
        ("BACKWARD_TRANSITIVE", [
            "New schema can read data written by ALL previous schema versions.",
            "Same rules as BACKWARD, but checked against every version, not just the last.",
            "Use case: analytics pipelines with historical data from all versions.",
        ]),
        ("FORWARD", [
            "LAST schema version can read data written by the new schema.",
            "Rule: you can REMOVE fields (with defaults) and ADD fields.",
            "Use case: producers are upgraded before consumers.",
        ]),
        ("FORWARD_TRANSITIVE", [
            "ALL previous schema versions can read data written by the new schema.",
            "Strictest forward rule: every old reader must handle new data.",
        ]),
        ("FULL", [
            "Both BACKWARD and FORWARD compatible with the last version.",
            "Rule: only ADD or REMOVE fields that have defaults.",
            "Use case: independent deployment of readers and writers.",
        ]),
        ("FULL_TRANSITIVE", [
            "Both BACKWARD_TRANSITIVE and FORWARD_TRANSITIVE.",
            "The gold standard: any version can talk to any other version.",
            "Most restrictive: only add/remove fields with defaults.",
        ]),
        ("NONE", [
            "No compatibility checking. Any schema change is allowed.",
            "Use case: development/testing only. Never use in production.",
        ]),
    ]

    for mode, details in modes:
        print(f"\n  {mode}:")
        for detail in details:
            print(f"    - {detail}")


# ============================================================================
# Comprehensive matrix
# ============================================================================

def print_comprehensive_matrix(
    json_r: dict, msgpack_r: dict, proto_r: dict, avro_r: dict
) -> None:
    print("\n" + "=" * 70)
    print("  COMPREHENSIVE COMPATIBILITY MATRIX")
    print("=" * 70)
    print()
    print("  Test: add a field with a default value to the schema.")
    print("  This is the most common schema evolution operation.\n")

    formats = ["JSON", "MsgPack", "Protobuf", "Avro"]
    all_results = [json_r, msgpack_r, proto_r, avro_r]
    compat_types = ["backward", "forward", "full"]

    # Header
    header = f"  {'Compat Type':<22s}"
    for fmt in formats:
        header += f" {fmt:^12s}"
    print(header)
    print("  " + "-" * 22 + (" " + "-" * 12) * len(formats))

    for ct in compat_types:
        row = f"  {ct.title():<22s}"
        for r in all_results:
            val = r.get(ct, "N/A")
            row += f" {val:^12s}"
        print(row)

    print()
    print("  Notes:")
    print("  - JSON/MsgPack: PASS requires application-level discipline (.get() with defaults)")
    print("  - Protobuf: PASS is enforced by the wire format (tags + defaults)")
    print("  - Avro FAIL*: fails without resolution; PASS with Schema Registry")

    # Extended matrix for different change types
    print("\n\n  EXTENDED MATRIX: All change types\n")

    changes = [
        ("Add field (with default)", ["PASS", "PASS", "PASS", "PASS*"]),
        ("Add field (no default)",   ["PASS", "PASS", "PASS", "FAIL"]),
        ("Remove field",             ["PARTIAL", "PARTIAL", "PASS", "PASS*"]),
        ("Rename field",             ["FAIL", "FAIL", "PASS", "FAIL"]),
        ("Change type",              ["FAIL", "FAIL", "FAIL", "FAIL"]),
        ("Add enum value",           ["PARTIAL", "PARTIAL", "PARTIAL", "FAIL"]),
        ("Reorder fields",           ["PASS", "PASS", "PASS", "PASS*"]),
    ]

    header = f"  {'Change':<28s}"
    for fmt in formats:
        header += f" {fmt:^12s}"
    print(header)
    print("  " + "-" * 28 + (" " + "-" * 12) * len(formats))

    for change, vals in changes:
        row = f"  {change:<28s}"
        for v in vals:
            row += f" {v:^12s}"
        print(row)

    print()
    print("  * Avro: requires Schema Registry for resolution. Without it, most changes break.")
    print("    With resolution: add/remove with defaults = PASS; reorder by name = PASS.")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("=" * 70)
    print("  Compatibility Matrix: Backward, Forward, Full")
    print("=" * 70)
    print()
    print("  For each format, we test the most common evolution operation:")
    print("  adding a new field with a default value.")

    json_r = test_json_compat()
    msgpack_r = test_msgpack_compat()
    proto_r = test_protobuf_compat()
    avro_r = test_avro_compat()

    print_comprehensive_matrix(json_r, msgpack_r, proto_r, avro_r)
    explain_schema_registry()


if __name__ == "__main__":
    main()
