"""Schema evolution -- the killer feature of Protocol Buffers.

Demonstrates how protobuf handles schema changes gracefully:
  1. Adding a field (new writer, old reader)
  2. Removing a field (new writer skips it, old reader gets defaults)
  3. Unknown fields (new fields silently skipped by old readers)
  4. Renaming a field (only number matters on the wire)
  5. Changing field type (DANGEROUS -- wire types don't match)
  6. Reserved fields (preventing accidental reuse)

All demos use the from-scratch encoder/decoder -- no library dependency.
"""

from __future__ import annotations

import struct

from chapters.ch04_protobuf.proto_from_scratch import (
    encode_string_field,
    encode_varint_field,
    encode_double_field,
    encode_enum_field,
    decode_message,
)


# ============================================================================
# Simple message builders for evolution demos
# ============================================================================

def encode_order_v1(order: dict) -> bytes:
    """Encode using 'v1' schema -- the original fields, no tip_cents.

    Fields:
        1: id (string)
        2: platform_transaction_id (int64)
        4: restaurant_id (string)
        6: status (enum)
        8: driver_id (string)
        9: delivery_notes (string)
        10: promo_code (string)
        12: created_at (double)
    """
    parts = [
        encode_string_field(1, order.get("id", "")),
        encode_varint_field(2, order.get("platform_transaction_id", 0)),
        encode_string_field(4, order.get("restaurant_id", "")),
        encode_enum_field(6, order.get("status_val", 0)),
        encode_string_field(8, order.get("driver_id", "")),
        encode_string_field(9, order.get("delivery_notes", "")),
        encode_string_field(10, order.get("promo_code", "")),
        encode_double_field(12, order.get("created_at", 0.0)),
    ]
    return b"".join(parts)


def encode_order_v2(order: dict) -> bytes:
    """Encode using 'v2' schema -- adds tip_cents (field 11), drops promo_code (field 10).

    Fields:
        1: id (string)
        2: platform_transaction_id (int64)
        4: restaurant_id (string)
        6: status (enum)
        8: driver_id (string)
        9: delivery_notes (string)
        -- field 10 (promo_code) is REMOVED --
        11: tip_cents (int32)           <-- NEW
        12: created_at (double)
    """
    parts = [
        encode_string_field(1, order.get("id", "")),
        encode_varint_field(2, order.get("platform_transaction_id", 0)),
        encode_string_field(4, order.get("restaurant_id", "")),
        encode_enum_field(6, order.get("status_val", 0)),
        encode_string_field(8, order.get("driver_id", "")),
        encode_string_field(9, order.get("delivery_notes", "")),
        # No field 10!
        encode_varint_field(11, order.get("tip_cents", 0)),
        encode_double_field(12, order.get("created_at", 0.0)),
    ]
    return b"".join(parts)


def encode_order_v3(order: dict) -> bytes:
    """Encode using 'v3' schema -- adds a brand new field 20 (priority_score).

    This field is completely unknown to v1 and v2 readers.
    """
    parts = [
        encode_string_field(1, order.get("id", "")),
        encode_varint_field(2, order.get("platform_transaction_id", 0)),
        encode_string_field(4, order.get("restaurant_id", "")),
        encode_enum_field(6, order.get("status_val", 0)),
        encode_string_field(8, order.get("driver_id", "")),
        encode_varint_field(11, order.get("tip_cents", 0)),
        encode_double_field(12, order.get("created_at", 0.0)),
        # New field 20: priority_score (varint)
        encode_varint_field(20, order.get("priority_score", 0)),
    ]
    return b"".join(parts)


def read_order_v1(data: bytes) -> dict:
    """Read using v1 schema. Only knows about the original fields."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["platform_transaction_id"] = fields[2][0]
    if 4 in fields:
        result["restaurant_id"] = fields[4][0].decode("utf-8")
    if 6 in fields:
        result["status_val"] = fields[6][0]
    if 8 in fields:
        result["driver_id"] = fields[8][0].decode("utf-8")
    if 9 in fields:
        result["delivery_notes"] = fields[9][0].decode("utf-8")
    if 10 in fields:
        result["promo_code"] = fields[10][0].decode("utf-8")
    if 12 in fields:
        result["created_at"] = struct.unpack("<d", fields[12][0])[0]

    # Collect unknown fields
    known = {1, 2, 4, 6, 8, 9, 10, 12}
    unknown = {fn: vals for fn, vals in fields.items() if fn not in known}
    if unknown:
        result["_unknown_fields"] = {fn: len(vals) for fn, vals in unknown.items()}

    return result


def read_order_v2(data: bytes) -> dict:
    """Read using v2 schema. Knows about tip_cents (11), no promo_code (10)."""
    fields = decode_message(data)
    result = {}
    if 1 in fields:
        result["id"] = fields[1][0].decode("utf-8")
    if 2 in fields:
        result["platform_transaction_id"] = fields[2][0]
    if 4 in fields:
        result["restaurant_id"] = fields[4][0].decode("utf-8")
    if 6 in fields:
        result["status_val"] = fields[6][0]
    if 8 in fields:
        result["driver_id"] = fields[8][0].decode("utf-8")
    if 9 in fields:
        result["delivery_notes"] = fields[9][0].decode("utf-8")
    if 11 in fields:
        result["tip_cents"] = fields[11][0]
    if 12 in fields:
        result["created_at"] = struct.unpack("<d", fields[12][0])[0]

    known = {1, 2, 4, 6, 8, 9, 11, 12}
    unknown = {fn: vals for fn, vals in fields.items() if fn not in known}
    if unknown:
        result["_unknown_fields"] = {fn: len(vals) for fn, vals in unknown.items()}

    return result


# ============================================================================
# Demo data
# ============================================================================

SAMPLE_ORDER = {
    "id": "ord00042",
    "platform_transaction_id": 123456789,
    "restaurant_id": "rest0001",
    "status_val": 6,        # EN_ROUTE
    "driver_id": "driv0001",
    "delivery_notes": "Ring doorbell twice",
    "promo_code": "SAVE20",
    "tip_cents": 500,
    "created_at": 1700000000.0,
    "priority_score": 85,
}


# ============================================================================
# main()
# ============================================================================

def main() -> None:
    print("--- Schema Evolution: the killer feature ---\n")

    # ------------------------------------------------------------------
    # 1. Adding a field
    # ------------------------------------------------------------------
    print("=" * 60)
    print("  DEMO 1: Adding a field")
    print("=" * 60)
    print()
    print("  Scenario: v1 writer produces data without tip_cents.")
    print("  v2 reader expects tip_cents (field 11).")
    print("  What happens?\n")

    v1_data = encode_order_v1(SAMPLE_ORDER)
    v2_read = read_order_v2(v1_data)

    print(f"  v1 encoded: {len(v1_data)} bytes (no tip_cents field)")
    print(f"  v2 reads tip_cents: {v2_read.get('tip_cents', '<missing>')}")
    print(f"  v2 reads id:        {v2_read.get('id')}")
    print(f"  v2 reads driver_id: {v2_read.get('driver_id')}")
    print()
    print("  Result: tip_cents is simply absent from the decoded dict.")
    print("  In proto3, the default is 0 for int32. The reader continues fine.")
    print("  BACKWARD COMPATIBLE: new reader handles old data.")

    # ------------------------------------------------------------------
    # 2. Removing a field
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  DEMO 2: Removing a field")
    print("=" * 60)
    print()
    print("  Scenario: v2 writer skips promo_code (field 10).")
    print("  v1 reader expects promo_code.")
    print("  What happens?\n")

    v2_data = encode_order_v2(SAMPLE_ORDER)
    v1_read = read_order_v1(v2_data)

    print(f"  v2 encoded: {len(v2_data)} bytes (no promo_code)")
    print(f"  v1 reads promo_code: {v1_read.get('promo_code', '<missing>')}")
    print(f"  v1 reads id:         {v1_read.get('id')}")
    print(f"  v1 reads driver_id:  {v1_read.get('driver_id')}")
    print()
    print("  Result: promo_code is absent. Default is empty string.")
    print("  FORWARD COMPATIBLE: old reader handles new data.")

    # ------------------------------------------------------------------
    # 3. Unknown fields are preserved
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  DEMO 3: Unknown fields are skipped (not crash)")
    print("=" * 60)
    print()
    print("  Scenario: v3 writer adds priority_score (field 20).")
    print("  v1 reader has never heard of field 20.")
    print("  What happens?\n")

    v3_data = encode_order_v3(SAMPLE_ORDER)
    v1_read = read_order_v1(v3_data)

    print(f"  v3 encoded: {len(v3_data)} bytes (includes field 20)")
    print(f"  v1 reads id:         {v1_read.get('id')}")
    print(f"  v1 reads driver_id:  {v1_read.get('driver_id')}")
    print(f"  v1 sees unknown:     {v1_read.get('_unknown_fields', {})}")
    print()
    print("  Result: field 20 is silently skipped. No crash, no data loss")
    print("  for the fields v1 knows about. The wire format is self-describing")
    print("  enough (tag tells you wire type, wire type tells you how many")
    print("  bytes to skip) that unknown fields can be passed over safely.")

    # Demonstrate the mechanism
    print("\n  How it works:")
    print("    1. Decoder reads tag: (20 << 3) | 0 = 160 (varint 0xa0 0x01)")
    print("    2. Wire type = 0 (VARINT) -- decoder knows to read a varint")
    print("    3. Decoder reads the varint value (85)")
    print("    4. Decoder doesn't know field 20 -- it just moves on")
    print("    5. No crash. The self-describing wire format is the key.")

    # ------------------------------------------------------------------
    # 4. Renaming a field
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  DEMO 4: Renaming a field")
    print("=" * 60)
    print()
    print("  Scenario: Rename 'driver_id' to 'courier_id'.")
    print("  Both use field number 8. Wire format is identical.\n")

    # Encode with "driver_id"
    data_v1 = encode_string_field(8, "driv0001")
    # Decode as "courier_id" (same field number)
    fields = decode_message(data_v1)
    courier_id = fields[8][0].decode("utf-8")

    print("  Writer encodes field 8 as 'driver_id':  'driv0001'")
    print(f"  Reader decodes field 8 as 'courier_id': '{courier_id}'")
    print(f"  Wire bytes: {' '.join(f'{b:02x}' for b in data_v1)}")
    print()
    print("  Result: SAFE. Only field NUMBERS appear on the wire, not names.")
    print("  You can rename fields freely in your .proto file without")
    print("  breaking wire compatibility. This is by design.")

    # ------------------------------------------------------------------
    # 5. Changing field type (DANGEROUS)
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  DEMO 5: Changing field type (DANGEROUS)")
    print("=" * 60)
    print()
    print("  Scenario: Change field 11 (tip_cents) from int32 to string.")
    print("  int32 uses wire type 0 (VARINT).")
    print("  string uses wire type 2 (LENGTH_DELIMITED).\n")

    # Writer encodes tip_cents as int32 (varint)
    int_data = encode_varint_field(11, 500)
    print(f"  int32 encoding:  {' '.join(f'{b:02x}' for b in int_data)}")
    print("                   tag=0x58 (field 11, wire_type=0 VARINT)")
    print("                   value=0xf4 0x03 (varint 500)")

    # New writer encodes tip_cents as string
    str_data = encode_string_field(11, "500")
    print(f"\n  string encoding: {' '.join(f'{b:02x}' for b in str_data)}")
    print("                   tag=0x5a (field 11, wire_type=2 LENGTH_DELIMITED)")
    print("                   length=3, data='500'")

    print("\n  The TAG BYTES are different: 0x58 vs 0x5a")
    print("  Wire type changed: 0 (VARINT) vs 2 (LENGTH_DELIMITED)")
    print()

    # Show what happens when old reader gets new data
    print("  What happens when an int32 reader gets string data?")
    try:
        fields = decode_message(str_data)
        val = fields[11][0]
        if isinstance(val, bytes):
            print(f"    Raw decode: field 11 = {val!r} (bytes, not int!)")
            print("    Reader expecting int gets bytes -- TYPE MISMATCH")
        else:
            print(f"    Raw decode: field 11 = {val!r}")
    except Exception as e:
        print(f"    Decode error: {e}")

    print()
    print("  RESULT: BREAKS. Changing a field's wire type is a breaking change.")
    print("  The tag encodes the wire type, so the decoder reads the wrong")
    print("  number of bytes and either gets garbage or crashes.")
    print()
    print("  RULE: Never change a field's type in a way that changes its")
    print("  wire type. int32 -> int64 is OK (both varint). int32 -> string is NOT.")

    # ------------------------------------------------------------------
    # 6. Reserved fields
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  DEMO 6: Reserved fields")
    print("=" * 60)
    print()
    print("  When you remove a field, you should RESERVE its number to prevent")
    print("  accidental reuse. If a new developer reuses field 10 for a")
    print("  different type, old data with field 10 (promo_code as string)")
    print("  would be misinterpreted.\n")
    print("  In your .proto file:")
    print()
    print('    message Order {')
    print('      reserved 10;')
    print('      reserved "promo_code";')
    print('      // ... other fields ...')
    print('    }')
    print()
    print("  The protoc compiler will error if anyone tries to use field 10")
    print("  or the name 'promo_code' again. This is a safety net.")
    print()

    # Demonstrate the danger of reusing field numbers
    print("  Danger of reusing field 10 as int32 (was string):")
    old_data = encode_string_field(10, "SAVE20")
    fields = decode_message(old_data)
    raw_val = fields[10][0]
    print(f"    Old data (promo_code='SAVE20'): {' '.join(f'{b:02x}' for b in old_data)}")
    print(f"    Wire type 2 (length-delimited), value = {raw_val!r}")
    print("    If new schema says field 10 is int32 (wire type 0),")
    print("    the tag byte would be different and parsing breaks.")
    print()
    print("  RULE: When you delete a field, reserve its number forever.")
    print("  Protobuf field numbers are like database migration version numbers --")
    print("  once used, they can never mean something different.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n")
    print("=" * 60)
    print("  Summary: Schema Evolution Rules")
    print("=" * 60)
    print()
    print("  SAFE:")
    print("    + Add new fields (old readers skip unknown fields)")
    print("    + Stop sending a field (readers get default values)")
    print("    + Rename fields (only numbers matter on the wire)")
    print("    + Change int32 <-> int64 (both use varint wire type)")
    print()
    print("  DANGEROUS:")
    print("    - Change a field's wire type (int32 -> string)")
    print("    - Reuse a deleted field number for a new field")
    print("    - Change the meaning of a field number")
    print()
    print("  BEST PRACTICES:")
    print("    * Reserve deleted field numbers and names")
    print("    * Never change field numbers")
    print("    * Use field numbers 1-15 for frequent fields (1-byte tag)")
    print("    * Start enums at 0 (UNSPECIFIED) for safe defaults")


if __name__ == "__main__":
    main()
