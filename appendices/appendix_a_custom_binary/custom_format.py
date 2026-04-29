"""Appendix A: A simple TLV (Type-Length-Value) binary format from scratch.

Wire layout per field:
    [type: 1 byte][field_id: 1 byte][length: 2 bytes LE][value: `length` bytes]

Type codes:
    0x01 = uint32   (4 bytes, little-endian)
    0x02 = string   (UTF-8 encoded bytes)
    0x03 = bytes    (raw binary)
    0x04 = nested   (another TLV message)
    0x05 = float64  (8 bytes, IEEE 754 LE)
    0x06 = bool     (1 byte: 0x00 or 0x01)

Run:
    uv run python -m appendices.appendix_a_custom_binary.custom_format
"""

from __future__ import annotations

import struct
from typing import Any

# ---------------------------------------------------------------------------
# Type codes
# ---------------------------------------------------------------------------

TLV_UINT32  = 0x01
TLV_STRING  = 0x02
TLV_BYTES   = 0x03
TLV_NESTED  = 0x04
TLV_FLOAT64 = 0x05
TLV_BOOL    = 0x06

TYPE_NAMES = {
    TLV_UINT32:  "uint32",
    TLV_STRING:  "string",
    TLV_BYTES:   "bytes",
    TLV_NESTED:  "nested",
    TLV_FLOAT64: "float64",
    TLV_BOOL:    "bool",
}

# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def _encode_value(type_code: int, value: Any) -> bytes:
    """Encode a Python value into raw bytes according to type_code."""
    if type_code == TLV_UINT32:
        return struct.pack("<I", value)
    elif type_code == TLV_STRING:
        return value.encode("utf-8")
    elif type_code == TLV_BYTES:
        return value if isinstance(value, (bytes, bytearray)) else bytes(value)
    elif type_code == TLV_NESTED:
        # value is already a list of (type_code, field_id, python_value) tuples
        return tlv_encode(value)
    elif type_code == TLV_FLOAT64:
        return struct.pack("<d", value)
    elif type_code == TLV_BOOL:
        return b"\x01" if value else b"\x00"
    else:
        raise ValueError(f"Unknown type code: 0x{type_code:02X}")


def tlv_encode(fields: list[tuple[int, int, Any]]) -> bytes:
    """Encode a list of (type_code, field_id, value) into TLV bytes.

    Each field becomes:
        [type: 1B][field_id: 1B][length: 2B LE][value: length B]
    """
    parts: list[bytes] = []
    for type_code, field_id, value in fields:
        value_bytes = _encode_value(type_code, value)
        length = len(value_bytes)
        if length > 0xFFFF:
            raise ValueError(
                f"Value too large for 2-byte length prefix: {length} bytes "
                f"(max 65535). Field ID: {field_id}"
            )
        header = struct.pack("<BBH", type_code, field_id, length)
        parts.append(header + value_bytes)
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def _decode_value(type_code: int, raw: bytes) -> Any:
    """Decode raw bytes into a Python value according to type_code."""
    if type_code == TLV_UINT32:
        return struct.unpack("<I", raw)[0]
    elif type_code == TLV_STRING:
        return raw.decode("utf-8")
    elif type_code == TLV_BYTES:
        return raw
    elif type_code == TLV_NESTED:
        return tlv_decode(raw)
    elif type_code == TLV_FLOAT64:
        return struct.unpack("<d", raw)[0]
    elif type_code == TLV_BOOL:
        return raw[0] != 0
    else:
        raise ValueError(f"Unknown type code: 0x{type_code:02X}")


def tlv_decode(data: bytes) -> list[tuple[int, int, Any]]:
    """Decode TLV bytes back into a list of (type_code, field_id, value)."""
    fields: list[tuple[int, int, Any]] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"Incomplete header at offset {offset}")
        type_code, field_id, length = struct.unpack_from("<BBH", data, offset)
        offset += 4
        if offset + length > len(data):
            raise ValueError(
                f"Value overflows buffer: need {length} bytes at offset {offset}, "
                f"but only {len(data) - offset} remain"
            )
        raw = data[offset : offset + length]
        offset += length
        value = _decode_value(type_code, raw)
        fields.append((type_code, field_id, value))
    return fields


# ---------------------------------------------------------------------------
# Hex dump
# ---------------------------------------------------------------------------

def hex_dump(data: bytes, label: str = "") -> None:
    """Print a colored hex dump with TLV structure annotations."""
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

    offset = 0
    field_num = 0
    while offset < len(data):
        if offset + 4 > len(data):
            print(f"  [incomplete header at offset {offset}]")
            break

        type_code, field_id, length = struct.unpack_from("<BBH", data, offset)
        type_name = TYPE_NAMES.get(type_code, f"0x{type_code:02X}")

        # Header bytes
        hdr = data[offset : offset + 4]
        hdr_hex = " ".join(f"{b:02X}" for b in hdr)

        # Value bytes
        val = data[offset + 4 : offset + 4 + length]
        val_hex = " ".join(f"{b:02X}" for b in val)

        print(f"\n  Field #{field_num} (id={field_id}, type={type_name}, len={length})")
        print(f"    Header:  [{hdr_hex}]")
        print(f"    Value:   [{val_hex}]")

        if type_code == TLV_UINT32:
            print(f"    Decoded: {struct.unpack('<I', val)[0]}")
        elif type_code == TLV_STRING:
            print(f"    Decoded: \"{val.decode('utf-8')}\"")
        elif type_code == TLV_FLOAT64:
            print(f"    Decoded: {struct.unpack('<d', val)[0]}")
        elif type_code == TLV_BOOL:
            print(f"    Decoded: {val[0] != 0}")

        offset += 4 + length
        field_num += 1

    print(f"\n  Total: {len(data)} bytes")


# ---------------------------------------------------------------------------
# Demo: encode a simplified FoodDash Order
# ---------------------------------------------------------------------------

def demo() -> None:
    """Encode a simplified order, hex-dump it, decode it, verify roundtrip."""

    # Field IDs for our simplified Order schema:
    #   1 = order_id (uint32)
    #   2 = restaurant_name (string)
    #   3 = total_cents (uint32)
    #   4 = latitude (float64)
    #   5 = longitude (float64)
    #   6 = is_delivered (bool)
    #   7 = delivery_notes (string)
    #   8 = items (nested -- contains sub-fields)

    # Nested item: field_id 1=name, 2=price_cents, 3=quantity
    item1 = [
        (TLV_STRING, 1, "Classic Smash Burger"),
        (TLV_UINT32, 2, 1299),
        (TLV_UINT32, 3, 2),
    ]
    item2 = [
        (TLV_STRING, 1, "Truffle Fries"),
        (TLV_UINT32, 2, 899),
        (TLV_UINT32, 3, 1),
    ]

    order_fields: list[tuple[int, int, Any]] = [
        (TLV_UINT32,  1, 42),
        (TLV_STRING,  2, "Burger Palace"),
        (TLV_UINT32,  3, 3497),
        (TLV_FLOAT64, 4, 40.748817),
        (TLV_FLOAT64, 5, -73.985428),
        (TLV_BOOL,    6, True),
        (TLV_STRING,  7, "Ring doorbell, leave at door"),
        (TLV_NESTED,  8, item1),
        (TLV_NESTED,  8, item2),  # repeated field (same field_id)
    ]

    # Encode
    encoded = tlv_encode(order_fields)
    hex_dump(encoded, "Simplified FoodDash Order (TLV encoded)")

    # Decode
    decoded = tlv_decode(encoded)

    # Verify roundtrip
    print("\n" + "=" * 60)
    print("  Roundtrip Verification")
    print("=" * 60)

    # Re-encode decoded fields and compare bytes
    re_encoded = tlv_encode(decoded)
    if re_encoded == encoded:
        print("  PASS: re-encoded bytes match original")
    else:
        print("  FAIL: re-encoded bytes differ!")
        print(f"    Original:   {len(encoded)} bytes")
        print(f"    Re-encoded: {len(re_encoded)} bytes")

    # Print decoded fields
    print("\n  Decoded fields:")
    for type_code, field_id, value in decoded:
        type_name = TYPE_NAMES.get(type_code, f"0x{type_code:02X}")
        if type_code == TLV_NESTED:
            print(f"    id={field_id} ({type_name}): [nested message with {len(value)} fields]")
            for sub_type, sub_id, sub_val in value:
                sub_name = TYPE_NAMES.get(sub_type, f"0x{sub_type:02X}")
                print(f"      id={sub_id} ({sub_name}): {sub_val!r}")
        else:
            print(f"    id={field_id} ({type_name}): {value!r}")

    # Size comparison
    import json
    order_dict = {
        "order_id": 42,
        "restaurant_name": "Burger Palace",
        "total_cents": 3497,
        "latitude": 40.748817,
        "longitude": -73.985428,
        "is_delivered": True,
        "delivery_notes": "Ring doorbell, leave at door",
        "items": [
            {"name": "Classic Smash Burger", "price_cents": 1299, "quantity": 2},
            {"name": "Truffle Fries", "price_cents": 899, "quantity": 1},
        ],
    }
    json_bytes = json.dumps(order_dict, separators=(",", ":")).encode()
    print("\n  Size comparison:")
    print(f"    TLV:          {len(encoded):>4} bytes")
    print(f"    JSON compact: {len(json_bytes):>4} bytes")
    print(f"    Savings:      {len(json_bytes) - len(encoded):>4} bytes "
          f"({(1 - len(encoded)/len(json_bytes))*100:.1f}%)")


if __name__ == "__main__":
    demo()
