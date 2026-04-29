"""Protocol Buffers wire format -- built from scratch, no libraries.

This is the CORE of Chapter 04. We implement the protobuf binary encoding
by hand to understand exactly what goes on the wire:

  - Varint encoding (LEB128): 7 bits per byte, MSB = continuation
  - Zigzag encoding: small negative numbers become small positive numbers
  - Wire types: varint (0), 64-bit (1), length-delimited (2), 32-bit (5)
  - Tag encoding: (field_number << 3) | wire_type
  - Full Order message encoding/decoding

The key insight vs. JSON/MsgPack: field NUMBERS replace field NAMES on the
wire. A string field name like "restaurant_id" (13 bytes) becomes a single
tag byte. This is why protobuf payloads are so much smaller.
"""

from __future__ import annotations

import json
import struct

from shared.sample_data import make_typical_order


# ============================================================================
# Varint encoding (LEB128 -- Little Endian Base 128)
# ============================================================================

def encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint.

    Each byte stores 7 bits of data. The MSB (bit 7) is the continuation
    bit: 1 means more bytes follow, 0 means this is the last byte.

    Examples:
        1       -> 0x01        (fits in 7 bits)
        127     -> 0x7f        (fits in 7 bits)
        128     -> 0x80 0x01   (needs 2 bytes: 0000001 0000000)
        300     -> 0xac 0x02   (needs 2 bytes: 0000010 0101100)
        16384   -> 0x80 0x80 0x01
    """
    if value < 0:
        raise ValueError(f"encode_varint requires unsigned int, got {value}")
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)  # low 7 bits + continuation
        value >>= 7
    parts.append(value & 0x7F)  # last byte, no continuation
    return bytes(parts)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a varint starting at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Unexpected end of data while decoding varint")
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset


def varint_size(value: int) -> int:
    """How many bytes does this value need as a varint?"""
    if value == 0:
        return 1
    size = 0
    while value > 0:
        value >>= 7
        size += 1
    return size


# ============================================================================
# Zigzag encoding (for signed integers)
# ============================================================================

def zigzag_encode(n: int) -> int:
    """Map signed integers to unsigned: 0->0, -1->1, 1->2, -2->3, 2->4, ...

    Formula: (n << 1) ^ (n >> 63)

    This ensures small-magnitude negative numbers produce small unsigned
    values, which encode as short varints. Without zigzag, -1 would be
    a 10-byte varint (all ones in two's complement).
    """
    return (n << 1) ^ (n >> 63)


def zigzag_decode(n: int) -> int:
    """Reverse zigzag: 0->0, 1->-1, 2->1, 3->-2, 4->2, ...

    Formula: (n >> 1) ^ -(n & 1)
    """
    return (n >> 1) ^ -(n & 1)


# ============================================================================
# Wire types
# ============================================================================

WIRE_VARINT = 0           # int32, int64, uint32, uint64, sint32, sint64, bool, enum
WIRE_64BIT = 1            # fixed64, sfixed64, double
WIRE_LENGTH_DELIMITED = 2  # string, bytes, embedded messages, packed repeated
WIRE_32BIT = 5            # fixed32, sfixed32, float

WIRE_TYPE_NAMES = {
    0: "VARINT",
    1: "64-BIT",
    2: "LENGTH_DELIMITED",
    5: "32-BIT",
}


# ============================================================================
# Tag encoding
# ============================================================================

def encode_tag(field_number: int, wire_type: int) -> bytes:
    """Encode a field tag: (field_number << 3) | wire_type.

    The tag is then encoded as a varint. This means:
      - Field numbers 1-15 produce a single-byte tag (value 0x08-0x7a)
      - Field numbers 16+ need 2+ bytes (value >= 0x80)
    This is why proto best practice reserves fields 1-15 for frequent fields.
    """
    return encode_varint((field_number << 3) | wire_type)


def decode_tag(data: bytes, offset: int) -> tuple[int, int, int]:
    """Decode a tag. Returns (field_number, wire_type, new_offset)."""
    tag_value, offset = decode_varint(data, offset)
    field_number = tag_value >> 3
    wire_type = tag_value & 0x07
    return field_number, wire_type, offset


# ============================================================================
# Field encoders (each writes tag + value)
# ============================================================================

def encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode an integer field (wire type 0)."""
    if value == 0:
        return b""  # proto3: default values are not serialized
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(value)


def encode_sint_field(field_number: int, value: int) -> bytes:
    """Encode a signed integer field using zigzag (wire type 0)."""
    if value == 0:
        return b""
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(zigzag_encode(value))


def encode_bool_field(field_number: int, value: bool) -> bytes:
    """Encode a bool field (wire type 0, value 0 or 1)."""
    if not value:
        return b""  # proto3: false is default, not serialized
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(1)


def encode_enum_field(field_number: int, value: int) -> bytes:
    """Encode an enum field (wire type 0)."""
    if value == 0:
        return b""  # proto3: 0 is default enum value
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(value)


def encode_string_field(field_number: int, value: str) -> bytes:
    """Encode a string field (wire type 2): tag + varint(len) + utf8."""
    if not value:
        return b""  # proto3: empty string is default
    raw = value.encode("utf-8")
    return (
        encode_tag(field_number, WIRE_LENGTH_DELIMITED)
        + encode_varint(len(raw))
        + raw
    )


def encode_bytes_field(field_number: int, value: bytes) -> bytes:
    """Encode a bytes field (wire type 2): tag + varint(len) + raw."""
    if not value:
        return b""
    return (
        encode_tag(field_number, WIRE_LENGTH_DELIMITED)
        + encode_varint(len(value))
        + value
    )


def encode_double_field(field_number: int, value: float) -> bytes:
    """Encode a double field (wire type 1): tag + 8 bytes little-endian."""
    if value == 0.0:
        return b""
    return encode_tag(field_number, WIRE_64BIT) + struct.pack("<d", value)


def encode_message_field(field_number: int, message_bytes: bytes) -> bytes:
    """Encode an embedded message (wire type 2): tag + varint(len) + bytes."""
    if not message_bytes:
        return b""
    return (
        encode_tag(field_number, WIRE_LENGTH_DELIMITED)
        + encode_varint(len(message_bytes))
        + message_bytes
    )


def encode_map_entry(field_number: int, key: str, value: str) -> bytes:
    """Encode a map<string,string> entry.

    In protobuf, map<K,V> is syntactic sugar for:
        repeated MapEntry { K key = 1; V value = 2; }
    Each entry is an embedded message with field_number from the parent.
    """
    entry = encode_string_field(1, key) + encode_string_field(2, value)
    return encode_message_field(field_number, entry)


# ============================================================================
# Encode a full FoodDash Order
# ============================================================================

# Enum value maps (matching the .proto definition)
ORDER_STATUS_MAP = {
    "placed": 1, "confirmed": 2, "preparing": 3, "ready": 4,
    "picked_up": 5, "en_route": 6, "delivered": 7, "cancelled": 8,
}

PAYMENT_METHOD_MAP = {
    "credit_card": 1, "debit_card": 2, "cash": 3, "wallet": 4,
}


def encode_geo_point(geo: dict) -> bytes:
    """Encode a GeoPoint message."""
    return (
        encode_double_field(1, geo.get("latitude", 0.0))
        + encode_double_field(2, geo.get("longitude", 0.0))
    )


def encode_menu_item(item: dict) -> bytes:
    """Encode a MenuItem message."""
    parts = [
        encode_string_field(1, item.get("id", "")),
        encode_string_field(2, item.get("name", "")),
        encode_varint_field(3, item.get("price_cents", 0)),
        encode_string_field(4, item.get("description", "")),
        encode_string_field(5, item.get("category", "")),
        encode_bool_field(6, item.get("is_vegetarian", False)),
    ]
    # repeated string allergens = 7
    for allergen in item.get("allergens", []):
        parts.append(encode_string_field(7, allergen))
    # bytes thumbnail_png = 8
    thumb = item.get("thumbnail_png", b"")
    if isinstance(thumb, str):
        # model_dump may produce strings for bytes; handle gracefully
        thumb = thumb.encode("latin-1") if thumb else b""
    parts.append(encode_bytes_field(8, thumb))
    return b"".join(parts)


def encode_order_item(oi: dict) -> bytes:
    """Encode an OrderItem message."""
    menu_item_bytes = encode_menu_item(oi.get("menu_item", {}))
    return (
        encode_message_field(1, menu_item_bytes)
        + encode_varint_field(2, oi.get("quantity", 1))
        + encode_string_field(3, oi.get("special_instructions", ""))
    )


def encode_customer(cust: dict) -> bytes:
    """Encode a Customer message."""
    parts = [
        encode_string_field(1, cust.get("id", "")),
        encode_string_field(2, cust.get("name", "")),
        encode_string_field(3, cust.get("email", "")),
        encode_string_field(4, cust.get("phone", "")),
        encode_string_field(5, cust.get("address", "")),
    ]
    loc = cust.get("location")
    if loc:
        parts.append(encode_message_field(6, encode_geo_point(loc)))
    return b"".join(parts)


def encode_order(order_dict: dict) -> bytes:
    """Encode a full FoodDash Order into protobuf wire format.

    Field assignments match fooddash.proto:
        1: id (string)
        2: platform_transaction_id (int64)
        3: customer (embedded message)
        4: restaurant_id (string)
        5: items (repeated embedded message)
        6: status (enum)
        7: payment_method (enum)
        8: driver_id (string)
        9: delivery_notes (string)
       10: promo_code (string)
       11: tip_cents (int32)
       12: created_at (double)
       13: updated_at (double)
       14: estimated_delivery_minutes (int32)
       15: metadata (map<string,string>)
    """
    parts = []

    # Field 1: id
    parts.append(encode_string_field(1, order_dict.get("id", "")))

    # Field 2: platform_transaction_id
    parts.append(encode_varint_field(2, order_dict.get("platform_transaction_id", 0)))

    # Field 3: customer (embedded message)
    cust = order_dict.get("customer")
    if cust:
        parts.append(encode_message_field(3, encode_customer(cust)))

    # Field 4: restaurant_id
    parts.append(encode_string_field(4, order_dict.get("restaurant_id", "")))

    # Field 5: items (repeated)
    for item in order_dict.get("items", []):
        parts.append(encode_message_field(5, encode_order_item(item)))

    # Field 6: status (enum)
    status = order_dict.get("status", "")
    status_val = ORDER_STATUS_MAP.get(status, 0)
    parts.append(encode_enum_field(6, status_val))

    # Field 7: payment_method (enum)
    pm = order_dict.get("payment_method", "")
    pm_val = PAYMENT_METHOD_MAP.get(pm, 0)
    parts.append(encode_enum_field(7, pm_val))

    # Field 8: driver_id
    parts.append(encode_string_field(8, order_dict.get("driver_id") or ""))

    # Field 9: delivery_notes
    parts.append(encode_string_field(9, order_dict.get("delivery_notes") or ""))

    # Field 10: promo_code
    parts.append(encode_string_field(10, order_dict.get("promo_code") or ""))

    # Field 11: tip_cents
    parts.append(encode_varint_field(11, order_dict.get("tip_cents", 0)))

    # Field 12: created_at
    parts.append(encode_double_field(12, order_dict.get("created_at", 0.0)))

    # Field 13: updated_at
    parts.append(encode_double_field(13, order_dict.get("updated_at", 0.0)))

    # Field 14: estimated_delivery_minutes
    edm = order_dict.get("estimated_delivery_minutes")
    if edm is not None:
        parts.append(encode_varint_field(14, edm))

    # Field 15: metadata (map<string,string>)
    for k, v in order_dict.get("metadata", {}).items():
        parts.append(encode_map_entry(15, k, v))

    return b"".join(parts)


# ============================================================================
# Generic message decoder
# ============================================================================

def decode_message(data: bytes) -> dict[int, list]:
    """Decode protobuf wire format into {field_number: [values]}.

    Each value is stored as a raw representation:
      - VARINT: int
      - 64-BIT: 8 bytes
      - LENGTH_DELIMITED: bytes (caller decides if string/message/bytes)
      - 32-BIT: 4 bytes

    Multiple values for the same field number (repeated fields) are
    collected into a list.
    """
    fields: dict[int, list] = {}
    offset = 0
    while offset < len(data):
        field_number, wire_type, offset = decode_tag(data, offset)

        if wire_type == WIRE_VARINT:
            value, offset = decode_varint(data, offset)
        elif wire_type == WIRE_64BIT:
            value = data[offset:offset + 8]
            offset += 8
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, offset = decode_varint(data, offset)
            value = data[offset:offset + length]
            offset += length
        elif wire_type == WIRE_32BIT:
            value = data[offset:offset + 4]
            offset += 4
        else:
            raise ValueError(f"Unknown wire type {wire_type} at offset {offset}")

        fields.setdefault(field_number, []).append(value)

    return fields


def decode_order(data: bytes) -> dict:
    """Decode protobuf bytes back into a human-readable Order dict.

    This is a higher-level decoder that knows the Order schema and converts
    raw wire values into typed Python values.
    """
    fields = decode_message(data)
    order = {}

    # Field 1: id (string)
    if 1 in fields:
        order["id"] = fields[1][0].decode("utf-8")

    # Field 2: platform_transaction_id (int64 varint)
    if 2 in fields:
        order["platform_transaction_id"] = fields[2][0]

    # Field 3: customer (embedded message)
    if 3 in fields:
        cust_fields = decode_message(fields[3][0])
        cust = {}
        if 1 in cust_fields:
            cust["id"] = cust_fields[1][0].decode("utf-8")
        if 2 in cust_fields:
            cust["name"] = cust_fields[2][0].decode("utf-8")
        if 3 in cust_fields:
            cust["email"] = cust_fields[3][0].decode("utf-8")
        if 4 in cust_fields:
            cust["phone"] = cust_fields[4][0].decode("utf-8")
        if 5 in cust_fields:
            cust["address"] = cust_fields[5][0].decode("utf-8")
        if 6 in cust_fields:
            geo_fields = decode_message(cust_fields[6][0])
            loc = {}
            if 1 in geo_fields:
                loc["latitude"] = struct.unpack("<d", geo_fields[1][0])[0]
            if 2 in geo_fields:
                loc["longitude"] = struct.unpack("<d", geo_fields[2][0])[0]
            cust["location"] = loc
        order["customer"] = cust

    # Field 4: restaurant_id
    if 4 in fields:
        order["restaurant_id"] = fields[4][0].decode("utf-8")

    # Field 5: items (repeated embedded message)
    inv_status = {v: k for k, v in ORDER_STATUS_MAP.items()}
    inv_pm = {v: k for k, v in PAYMENT_METHOD_MAP.items()}

    if 5 in fields:
        items = []
        for item_bytes in fields[5]:
            oi_fields = decode_message(item_bytes)
            oi = {}
            if 1 in oi_fields:
                mi_fields = decode_message(oi_fields[1][0])
                mi = {}
                if 1 in mi_fields:
                    mi["id"] = mi_fields[1][0].decode("utf-8")
                if 2 in mi_fields:
                    mi["name"] = mi_fields[2][0].decode("utf-8")
                if 3 in mi_fields:
                    mi["price_cents"] = mi_fields[3][0]
                if 4 in mi_fields:
                    mi["description"] = mi_fields[4][0].decode("utf-8")
                if 5 in mi_fields:
                    mi["category"] = mi_fields[5][0].decode("utf-8")
                if 6 in mi_fields:
                    mi["is_vegetarian"] = bool(mi_fields[6][0])
                if 7 in mi_fields:
                    mi["allergens"] = [a.decode("utf-8") for a in mi_fields[7]]
                if 8 in mi_fields:
                    mi["thumbnail_png"] = mi_fields[8][0]
                oi["menu_item"] = mi
            if 2 in oi_fields:
                oi["quantity"] = oi_fields[2][0]
            if 3 in oi_fields:
                oi["special_instructions"] = oi_fields[3][0].decode("utf-8")
            items.append(oi)
        order["items"] = items

    # Field 6: status (enum)
    if 6 in fields:
        order["status"] = inv_status.get(fields[6][0], f"UNKNOWN({fields[6][0]})")

    # Field 7: payment_method
    if 7 in fields:
        order["payment_method"] = inv_pm.get(fields[7][0], f"UNKNOWN({fields[7][0]})")

    # Field 8-10: strings
    if 8 in fields:
        order["driver_id"] = fields[8][0].decode("utf-8")
    if 9 in fields:
        order["delivery_notes"] = fields[9][0].decode("utf-8")
    if 10 in fields:
        order["promo_code"] = fields[10][0].decode("utf-8")

    # Field 11: tip_cents
    if 11 in fields:
        order["tip_cents"] = fields[11][0]

    # Field 12-13: doubles
    if 12 in fields:
        order["created_at"] = struct.unpack("<d", fields[12][0])[0]
    if 13 in fields:
        order["updated_at"] = struct.unpack("<d", fields[13][0])[0]

    # Field 14: estimated_delivery_minutes
    if 14 in fields:
        order["estimated_delivery_minutes"] = fields[14][0]

    # Field 15: metadata (map entries)
    if 15 in fields:
        meta = {}
        for entry_bytes in fields[15]:
            entry_fields = decode_message(entry_bytes)
            k = entry_fields.get(1, [b""])[0].decode("utf-8")
            v = entry_fields.get(2, [b""])[0].decode("utf-8")
            meta[k] = v
        order["metadata"] = meta

    return order


# ============================================================================
# Byte annotation
# ============================================================================

def annotate_bytes(data: bytes, max_bytes: int = 200) -> list[str]:
    """Produce human-readable annotations for protobuf wire format.

    Each line shows: [offset] hex_bytes  meaning
    """
    lines: list[str] = []
    offset = 0
    limit = min(len(data), max_bytes)

    while offset < limit:
        # Decode tag
        tag_start = offset
        field_number, wire_type, offset = decode_tag(data, offset)
        tag_hex = " ".join(f"{b:02x}" for b in data[tag_start:offset])
        wt_name = WIRE_TYPE_NAMES.get(wire_type, f"UNKNOWN({wire_type})")
        lines.append(
            f"  [{tag_start:4d}] {tag_hex:<12s}  "
            f"TAG: field={field_number}, wire_type={wire_type} ({wt_name})"
        )

        if wire_type == WIRE_VARINT:
            val_start = offset
            value, offset = decode_varint(data, offset)
            val_hex = " ".join(f"{b:02x}" for b in data[val_start:offset])
            lines.append(
                f"  [{val_start:4d}] {val_hex:<12s}  "
                f"VARINT: {value}"
            )

        elif wire_type == WIRE_64BIT:
            val_hex = " ".join(f"{b:02x}" for b in data[offset:offset + 8])
            dbl = struct.unpack("<d", data[offset:offset + 8])[0]
            lines.append(
                f"  [{offset:4d}] {val_hex}  "
                f"64-BIT (double): {dbl}"
            )
            offset += 8

        elif wire_type == WIRE_LENGTH_DELIMITED:
            len_start = offset
            length, offset = decode_varint(data, offset)
            len_hex = " ".join(f"{b:02x}" for b in data[len_start:offset])
            lines.append(
                f"  [{len_start:4d}] {len_hex:<12s}  "
                f"LENGTH: {length} bytes"
            )
            # Show a preview of the payload
            preview_len = min(length, 40)
            payload = data[offset:offset + preview_len]
            try:
                text = payload.decode("utf-8")
                lines.append(
                    f"  [{offset:4d}] ...            "
                    f"DATA: \"{text}\""
                    + (" ..." if length > preview_len else "")
                )
            except UnicodeDecodeError:
                hex_preview = " ".join(f"{b:02x}" for b in payload[:16])
                lines.append(
                    f"  [{offset:4d}] {hex_preview}  "
                    f"DATA: ({length} raw bytes)"
                )
            offset += length

        elif wire_type == WIRE_32BIT:
            val_hex = " ".join(f"{b:02x}" for b in data[offset:offset + 4])
            flt = struct.unpack("<f", data[offset:offset + 4])[0]
            lines.append(
                f"  [{offset:4d}] {val_hex}  "
                f"32-BIT (float): {flt}"
            )
            offset += 4

        if offset > limit:
            lines.append("  ... (truncated)")
            break

    return lines


# ============================================================================
# Helpers for preparing Order data
# ============================================================================

def _prepare_order_dict(order) -> dict:
    """Convert a Pydantic Order to a plain dict suitable for encoding."""
    d = order.model_dump()
    # Convert enum values to their string representation
    if hasattr(d.get("status", ""), "value"):
        d["status"] = d["status"].value
    if hasattr(d.get("payment_method", ""), "value"):
        d["payment_method"] = d["payment_method"].value
    return d


# ============================================================================
# main()
# ============================================================================

def main() -> None:
    print("--- Protocol Buffers wire format from scratch ---\n")

    # ------------------------------------------------------------------
    # 1. Varint encoding
    # ------------------------------------------------------------------
    print("=== Varint Encoding (LEB128) ===\n")
    print("  Protobuf encodes integers using LEB128: 7 data bits per byte,")
    print("  MSB = continuation bit (1 = more bytes, 0 = last byte).\n")

    varint_examples = [0, 1, 127, 128, 300, 16383, 16384, 100000, 2**53 + 1]
    for val in varint_examples:
        encoded = encode_varint(val)
        hex_str = " ".join(f"0x{b:02x}" for b in encoded)
        bin_str = " ".join(f"{b:08b}" for b in encoded)
        print(f"  {val:>20,d}  ->  {hex_str:<30s}  ({len(encoded)} byte{'s' if len(encoded) > 1 else ''})")
        print(f"  {'':>20s}      binary: {bin_str}")
        # Verify roundtrip
        decoded_val, _ = decode_varint(encoded)
        assert decoded_val == val, f"Roundtrip failed for {val}"

    print("\n  Key insight: values 0-127 need just 1 byte.")
    print("  Field numbers 1-15 produce tags 0x08-0x7a, all single-byte.\n")

    # ------------------------------------------------------------------
    # 2. Zigzag encoding
    # ------------------------------------------------------------------
    print("\n=== Zigzag Encoding ===\n")
    print("  Problem: -1 in two's complement is 0xFFFFFFFFFFFFFFFF (10-byte varint!).")
    print("  Zigzag maps small-magnitude numbers to small unsigned values:\n")

    zigzag_examples = [0, -1, 1, -2, 2, -3, 3, 127, -128, 2147483647, -2147483648]
    for val in zigzag_examples:
        zz = zigzag_encode(val)
        encoded = encode_varint(zz)
        print(f"  {val:>15,d}  -> zigzag {zz:>15,d}  -> {len(encoded)} byte{'s' if len(encoded) > 1 else ''}")
        # Verify roundtrip
        assert zigzag_decode(zz) == val, f"Zigzag roundtrip failed for {val}"

    print("\n  -1 becomes 1 (1 byte), not 18446744073709551615 (10 bytes)!")

    # ------------------------------------------------------------------
    # 3. Wire types and tag encoding
    # ------------------------------------------------------------------
    print("\n\n=== Wire Types & Tag Encoding ===\n")
    print("  Wire type  Value  Used for")
    print("  ---------  -----  --------")
    print("  VARINT       0    int32, int64, uint32, uint64, bool, enum")
    print("  64-BIT       1    fixed64, sfixed64, double")
    print("  LEN-DEL      2    string, bytes, embedded messages, repeated")
    print("  32-BIT       5    fixed32, sfixed32, float")

    print("\n  Tag = (field_number << 3) | wire_type, encoded as varint.\n")

    tag_examples = [
        (1, WIRE_VARINT, "field 1, varint (e.g. Order.id as int)"),
        (1, WIRE_LENGTH_DELIMITED, "field 1, length-delimited (e.g. Order.id as string)"),
        (2, WIRE_VARINT, "field 2, varint (Order.platform_transaction_id)"),
        (8, WIRE_LENGTH_DELIMITED, "field 8, length-delimited (Order.driver_id)"),
        (15, WIRE_LENGTH_DELIMITED, "field 15, length-delimited (Order.metadata)"),
        (16, WIRE_VARINT, "field 16, varint (needs 2-byte tag!)"),
    ]

    for fn, wt, desc in tag_examples:
        tag = encode_tag(fn, wt)
        tag_val = (fn << 3) | wt
        hex_str = " ".join(f"0x{b:02x}" for b in tag)
        print(f"  field={fn:>2d} wire={wt}  tag_value={tag_val:>3d}  "
              f"bytes={hex_str:<12s} ({len(tag)} byte{'s' if len(tag) > 1 else ''})  -- {desc}")

    print("\n  Field numbers 1-15: single-byte tag. Field 16+: multi-byte tag.")
    print("  This is why protobuf reserves 1-15 for your most common fields!")

    # ------------------------------------------------------------------
    # 4. Encode a FoodDash Order
    # ------------------------------------------------------------------
    print("\n\n=== Encoding a FoodDash Order ===\n")

    order = make_typical_order()
    order_dict = _prepare_order_dict(order)

    proto_bytes = encode_order(order_dict)
    print(f"  Protobuf (from scratch): {len(proto_bytes):,} bytes")

    # JSON for comparison
    import base64
    def _json_default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)

    json_bytes = json.dumps(order_dict, default=_json_default).encode("utf-8")
    print(f"  JSON:                    {len(json_bytes):,} bytes")

    # MsgPack for comparison (if available)
    try:
        import msgpack
        # Need to handle bytes fields for msgpack
        mp_bytes = msgpack.packb(order_dict, use_bin_type=True)
        print(f"  MsgPack:                 {len(mp_bytes):,} bytes")
    except ImportError:
        mp_bytes = None
        print("  MsgPack:                 (not installed)")

    savings_json = (1 - len(proto_bytes) / len(json_bytes)) * 100
    print(f"\n  Savings vs JSON:         {savings_json:.1f}%")
    if mp_bytes:
        savings_mp = (1 - len(proto_bytes) / len(mp_bytes)) * 100
        print(f"  Savings vs MsgPack:      {savings_mp:.1f}%")

    print("\n  Why smaller?")
    print("    - Field NUMBERS (1-2 bytes) replace field NAMES (5-25 bytes)")
    print("    - Integers use varints (1-10 bytes) instead of text digits")
    print("    - No delimiters (no commas, braces, colons, quotes)")
    print("    - Binary data is raw (no base64)")
    print("    - Default values (0, false, \"\") are not serialized at all")

    # ------------------------------------------------------------------
    # 5. Verify roundtrip
    # ------------------------------------------------------------------
    print("\n\n=== Roundtrip Verification ===\n")
    decoded = decode_order(proto_bytes)

    checks = [
        ("id", order_dict["id"], decoded.get("id")),
        ("platform_transaction_id",
         order_dict["platform_transaction_id"],
         decoded.get("platform_transaction_id")),
        ("customer.name", order_dict["customer"]["name"],
         decoded.get("customer", {}).get("name")),
        ("restaurant_id", order_dict["restaurant_id"],
         decoded.get("restaurant_id")),
        ("status", order_dict["status"], decoded.get("status")),
        ("driver_id", order_dict.get("driver_id", ""),
         decoded.get("driver_id", "")),
        ("tip_cents", order_dict["tip_cents"], decoded.get("tip_cents")),
        ("created_at", order_dict["created_at"], decoded.get("created_at")),
        ("items count", len(order_dict["items"]),
         len(decoded.get("items", []))),
    ]

    all_ok = True
    for name, expected, actual in checks:
        ok = expected == actual
        marker = "OK" if ok else "FAIL"
        print(f"  {marker:>4s}  {name:<30s}  {expected!r} == {actual!r}")
        if not ok:
            all_ok = False

    if decoded.get("metadata"):
        meta_ok = decoded["metadata"] == order_dict.get("metadata", {})
        marker = "OK" if meta_ok else "FAIL"
        print(f"  {marker:>4s}  {'metadata':<30s}  (matches: {meta_ok})")
        if not meta_ok:
            all_ok = False

    print(f"\n  Roundtrip: {'PASSED' if all_ok else 'FAILED'}")

    # ------------------------------------------------------------------
    # 6. Byte-level annotation
    # ------------------------------------------------------------------
    print("\n\n=== Byte-Level Annotation (first 300 bytes) ===\n")
    annotations = annotate_bytes(proto_bytes, max_bytes=300)
    for line in annotations:
        print(line)

    # ------------------------------------------------------------------
    # 7. The size story: field names vs field numbers
    # ------------------------------------------------------------------
    print("\n\n=== The Size Story: Names vs Numbers ===\n")
    print("  In JSON/MsgPack, every field carries its name:")
    print('    "platform_transaction_id": 123456789  (26 chars for the key alone)')
    print()
    print("  In Protobuf, the field number IS the identifier:")
    print("    tag=0x10 (field 2, varint) + varint(123456789)")

    # Show actual byte counts for a few fields
    field_examples = [
        ("id", "ord00002",
         len('"id":"ord00002"'.encode()),
         len(encode_string_field(1, "ord00002"))),
        ("platform_transaction_id", "123456789",
         len('"platform_transaction_id":123456789'.encode()),
         len(encode_varint_field(2, 123456789))),
        ("restaurant_id", "rest0001",
         len('"restaurant_id":"rest0001"'.encode()),
         len(encode_string_field(4, "rest0001"))),
        ("status", "en_route",
         len('"status":"en_route"'.encode()),
         len(encode_enum_field(6, 6))),
        ("tip_cents", "500",
         len('"tip_cents":500'.encode()),
         len(encode_varint_field(11, 500))),
    ]

    print(f"\n  {'Field':<30s} {'JSON bytes':>12s} {'Proto bytes':>12s} {'Savings':>10s}")
    print(f"  {'-----':<30s} {'----------':>12s} {'-----------':>12s} {'-------':>10s}")
    for name, val_repr, json_size, proto_size in field_examples:
        saving = json_size - proto_size
        print(f"  {name:<30s} {json_size:>12d} {proto_size:>12d} {saving:>+10d}")


if __name__ == "__main__":
    main()
