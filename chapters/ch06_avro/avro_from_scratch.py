"""Apache Avro encoding -- built from scratch, no libraries.

This is the CORE of Chapter 06. We implement Avro's binary encoding by hand
to understand exactly what goes on the wire:

  - Zigzag varints for ALL integers (int and long)
  - Strings: zigzag varint length + UTF-8 bytes
  - Bytes: zigzag varint length + raw bytes
  - Booleans: single byte (0 or 1)
  - Doubles: 8 bytes, little-endian IEEE 754
  - Arrays: series of blocks (count + items), terminated by 0-count block
  - Maps: same block structure, each entry is string key + value
  - Unions: zigzag varint type-index + value
  - Enums: zigzag varint symbol index
  - Records: fields encoded in schema order. NO tags, NO framing.

The key insight vs. Protobuf: there are NO field tags on the wire at all.
The reader MUST have the schema to know which bytes belong to which field.
This makes Avro payloads even smaller than Protobuf.
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Any

from shared.sample_data import make_typical_order


# ============================================================================
# Zigzag varint encoding (Avro uses zigzag for ALL integers)
# ============================================================================

def zigzag_encode(n: int) -> int:
    """Map signed integers to unsigned: 0->0, -1->1, 1->2, -2->3, 2->4, ..."""
    return (n << 1) ^ (n >> 63)


def zigzag_decode(n: int) -> int:
    """Reverse zigzag: 0->0, 1->-1, 2->1, 3->-2, 4->2, ..."""
    return (n >> 1) ^ -(n & 1)


def encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a variable-length integer.

    Same LEB128 encoding as protobuf, but Avro ALWAYS applies zigzag first.
    """
    if value < 0:
        raise ValueError(f"encode_varint requires unsigned int, got {value}")
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
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


def encode_long(n: int) -> bytes:
    """Encode a signed long/int as zigzag varint (Avro's integer encoding)."""
    return encode_varint(zigzag_encode(n))


def decode_long(data: bytes, offset: int) -> tuple[int, int]:
    """Decode a zigzag-encoded varint. Returns (signed_value, new_offset)."""
    unsigned, offset = decode_varint(data, offset)
    return zigzag_decode(unsigned), offset


# ============================================================================
# Avro encoder: schema-driven, recursive
# ============================================================================

def avro_encode(schema: dict | str, obj: Any) -> bytes:
    """Encode a Python object according to an Avro schema.

    This is the heart of Avro: the schema tells us how to interpret the
    object, and we encode fields IN SCHEMA ORDER with NO tags.
    """
    # Handle schema references (named types as strings)
    if isinstance(schema, str):
        return _encode_primitive(schema, obj)

    schema_type = schema.get("type") if isinstance(schema, dict) else schema

    # Union: list of types
    if isinstance(schema, list):
        return _encode_union(schema, obj)

    if schema_type == "record":
        return _encode_record(schema, obj)
    elif schema_type == "array":
        return _encode_array(schema, obj)
    elif schema_type == "map":
        return _encode_map(schema, obj)
    elif schema_type == "enum":
        return _encode_enum(schema, obj)
    else:
        return _encode_primitive(schema_type, obj)


def _encode_primitive(type_name: str, obj: Any) -> bytes:
    """Encode a primitive Avro type."""
    if type_name == "null":
        return b""  # null is zero bytes
    elif type_name == "boolean":
        return b"\x01" if obj else b"\x00"
    elif type_name == "int" or type_name == "long":
        return encode_long(obj)
    elif type_name == "float":
        return struct.pack("<f", obj)
    elif type_name == "double":
        return struct.pack("<d", obj)
    elif type_name == "string":
        raw = obj.encode("utf-8") if isinstance(obj, str) else obj
        return encode_long(len(raw)) + raw
    elif type_name == "bytes":
        if isinstance(obj, str):
            obj = obj.encode("latin-1")
        return encode_long(len(obj)) + obj
    else:
        raise ValueError(f"Unknown primitive type: {type_name}")


def _encode_union(schema: list, obj: Any) -> bytes:
    """Encode a union type: zigzag varint index + value.

    Avro unions are ordered lists of types. The encoder must pick the
    correct branch and write its index first.
    """
    for i, branch in enumerate(schema):
        try:
            if obj is None and (branch == "null" or (isinstance(branch, dict) and branch.get("type") == "null")):
                return encode_long(i)  # null branch: just the index, no payload
            elif obj is not None and branch != "null" and not (isinstance(branch, dict) and branch.get("type") == "null"):
                # Try to encode with this branch
                encoded = avro_encode(branch, obj)
                return encode_long(i) + encoded
        except (TypeError, ValueError, KeyError, AttributeError):
            continue

    raise ValueError(f"No matching union branch for {type(obj).__name__}: {obj!r}")


def _encode_record(schema: dict, obj: dict) -> bytes:
    """Encode a record: just encode each field in order. No framing, no tags."""
    parts = []
    for field in schema["fields"]:
        field_name = field["name"]
        field_schema = field["type"]
        value = obj.get(field_name, field.get("default"))
        parts.append(avro_encode(field_schema, value))
    return b"".join(parts)


def _encode_array(schema: dict, obj: list) -> bytes:
    """Encode an array: block of count + items, terminated by 0-count.

    Each block starts with a zigzag varint count (>0), followed by that
    many items. A 0-count block signals the end.
    """
    if not obj:
        return encode_long(0)  # empty array: just a 0-count block
    # Single block with all items
    parts = [encode_long(len(obj))]
    for item in obj:
        parts.append(avro_encode(schema["items"], item))
    parts.append(encode_long(0))  # terminating 0-count block
    return b"".join(parts)


def _encode_map(schema: dict, obj: dict) -> bytes:
    """Encode a map: same block structure as arrays, entries are key+value."""
    if not obj:
        return encode_long(0)  # empty map: just a 0-count block
    parts = [encode_long(len(obj))]
    for key, value in obj.items():
        # Key is always a string
        key_bytes = key.encode("utf-8")
        parts.append(encode_long(len(key_bytes)) + key_bytes)
        parts.append(avro_encode(schema["values"], value))
    parts.append(encode_long(0))  # terminating 0-count block
    return b"".join(parts)


def _encode_enum(schema: dict, obj: str) -> bytes:
    """Encode an enum: zigzag varint index of the symbol."""
    symbols = schema["symbols"]
    if obj in symbols:
        return encode_long(symbols.index(obj))
    raise ValueError(f"Unknown enum symbol: {obj!r} (expected one of {symbols})")


# ============================================================================
# Avro decoder: schema-driven, recursive
# ============================================================================

def avro_decode(schema: dict | str, data: bytes, offset: int = 0) -> tuple[Any, int]:
    """Decode Avro binary data according to a schema.

    Returns (decoded_value, new_offset).
    """
    if isinstance(schema, str):
        return _decode_primitive(schema, data, offset)

    if isinstance(schema, list):
        return _decode_union(schema, data, offset)

    schema_type = schema.get("type") if isinstance(schema, dict) else schema

    if schema_type == "record":
        return _decode_record(schema, data, offset)
    elif schema_type == "array":
        return _decode_array(schema, data, offset)
    elif schema_type == "map":
        return _decode_map(schema, data, offset)
    elif schema_type == "enum":
        return _decode_enum(schema, data, offset)
    else:
        return _decode_primitive(schema_type, data, offset)


def _decode_primitive(type_name: str, data: bytes, offset: int) -> tuple[Any, int]:
    """Decode a primitive Avro type."""
    if type_name == "null":
        return None, offset
    elif type_name == "boolean":
        return data[offset] != 0, offset + 1
    elif type_name == "int" or type_name == "long":
        return decode_long(data, offset)
    elif type_name == "float":
        return struct.unpack("<f", data[offset:offset + 4])[0], offset + 4
    elif type_name == "double":
        return struct.unpack("<d", data[offset:offset + 8])[0], offset + 8
    elif type_name == "string":
        length, offset = decode_long(data, offset)
        s = data[offset:offset + length].decode("utf-8")
        return s, offset + length
    elif type_name == "bytes":
        length, offset = decode_long(data, offset)
        return data[offset:offset + length], offset + length
    else:
        raise ValueError(f"Unknown primitive type: {type_name}")


def _decode_union(schema: list, data: bytes, offset: int) -> tuple[Any, int]:
    """Decode a union: read type index, then decode that branch."""
    branch_index, offset = decode_long(data, offset)
    branch = schema[branch_index]
    return avro_decode(branch, data, offset)


def _decode_record(schema: dict, data: bytes, offset: int) -> tuple[dict, int]:
    """Decode a record: read each field in schema order."""
    result = {}
    for field in schema["fields"]:
        value, offset = avro_decode(field["type"], data, offset)
        result[field["name"]] = value
    return result, offset


def _decode_array(schema: dict, data: bytes, offset: int) -> tuple[list, int]:
    """Decode an array: read blocks until 0-count."""
    items = []
    while True:
        count, offset = decode_long(data, offset)
        if count == 0:
            break
        if count < 0:
            # Negative count means the block also includes byte-size (skip it)
            count = -count
            _block_size, offset = decode_long(data, offset)
        for _ in range(count):
            item, offset = avro_decode(schema["items"], data, offset)
            items.append(item)
    return items, offset


def _decode_map(schema: dict, data: bytes, offset: int) -> tuple[dict, int]:
    """Decode a map: read blocks of key-value pairs until 0-count."""
    result = {}
    while True:
        count, offset = decode_long(data, offset)
        if count == 0:
            break
        if count < 0:
            count = -count
            _block_size, offset = decode_long(data, offset)
        for _ in range(count):
            # Key is always a string
            key_len, offset = decode_long(data, offset)
            key = data[offset:offset + key_len].decode("utf-8")
            offset += key_len
            # Value
            value, offset = avro_decode(schema["values"], data, offset)
            result[key] = value
    return result, offset


def _decode_enum(schema: dict, data: bytes, offset: int) -> tuple[str, int]:
    """Decode an enum: read the symbol index."""
    index, offset = decode_long(data, offset)
    return schema["symbols"][index], offset


# ============================================================================
# Order conversion helpers
# ============================================================================

# Map Pydantic enum values to Avro enum symbols
STATUS_TO_AVRO = {
    "placed": "PLACED", "confirmed": "CONFIRMED", "preparing": "PREPARING",
    "ready": "READY", "picked_up": "PICKED_UP", "en_route": "EN_ROUTE",
    "delivered": "DELIVERED", "cancelled": "CANCELLED",
}

PAYMENT_TO_AVRO = {
    "credit_card": "CREDIT_CARD", "debit_card": "DEBIT_CARD",
    "cash": "CASH", "wallet": "WALLET",
}


def order_to_avro_dict(order) -> dict:
    """Convert a Pydantic Order to a dict suitable for Avro encoding.

    - Enum values become their UPPER_CASE Avro symbol strings
    - bytes fields stay as bytes (Avro supports bytes natively)
    - None values stay as None (for union ["null", ...] fields)
    """
    d = order.model_dump()
    d["status"] = STATUS_TO_AVRO[d["status"]]
    d["payment_method"] = PAYMENT_TO_AVRO[d["payment_method"]]

    # Handle optional string fields: convert empty strings to None for unions
    for field_name in ("driver_id", "delivery_notes", "promo_code"):
        if d.get(field_name) == "" or d.get(field_name) is None:
            d[field_name] = None

    # Customer optional fields
    cust = d["customer"]
    for field_name in ("email", "phone", "address"):
        if cust.get(field_name) == "":
            cust[field_name] = None

    # OrderItem special_instructions
    for item in d["items"]:
        if item.get("special_instructions") == "":
            item["special_instructions"] = None
        mi = item["menu_item"]
        if mi.get("description") == "":
            mi["description"] = None
        if mi.get("category") == "":
            mi["category"] = None

    return d


# ============================================================================
# Byte annotation
# ============================================================================

def annotate_avro_bytes(schema: dict | str, data: bytes, offset: int = 0,
                        prefix: str = "", max_depth: int = 3,
                        annotations: list[str] | None = None) -> list[str]:
    """Produce human-readable annotations for Avro binary data.

    Each line shows: [offset] hex_bytes  meaning
    """
    if annotations is None:
        annotations = []

    if isinstance(schema, str):
        _annotate_primitive(schema, data, offset, prefix, annotations)
        return annotations

    if isinstance(schema, list):
        start = offset
        idx, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        branch = schema[idx]
        branch_name = branch if isinstance(branch, str) else branch.get("name", branch.get("type", "?"))
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}UNION index={idx} -> {branch_name}")
        if branch != "null" and not (isinstance(branch, dict) and branch.get("type") == "null"):
            annotate_avro_bytes(branch, data, new_off, prefix, max_depth, annotations)
        return annotations

    schema_type = schema.get("type")

    if schema_type == "record" and max_depth > 0:
        for field in schema["fields"]:
            field_prefix = f"{prefix}{field['name']}: "
            annotate_avro_bytes(field["type"], data, offset, field_prefix, max_depth - 1, annotations)
            # Advance offset by decoding
            _, offset = avro_decode(field["type"], data, offset)
        return annotations

    if schema_type == "enum":
        start = offset
        idx, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        symbol = schema["symbols"][idx]
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}ENUM {symbol} (index={idx})")
        return annotations

    if schema_type == "array":
        start = offset
        count, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}ARRAY block count={count}")
        return annotations

    if schema_type == "map":
        start = offset
        count, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}MAP block count={count}")
        return annotations

    _annotate_primitive(schema_type, data, offset, prefix, annotations)
    return annotations


def _annotate_primitive(type_name: str, data: bytes, offset: int,
                        prefix: str, annotations: list[str]) -> None:
    """Annotate a single primitive value."""
    start = offset
    if type_name == "null":
        annotations.append(f"  [{start:4d}] {'':20s}  {prefix}NULL (0 bytes)")
    elif type_name == "boolean":
        val = data[offset]
        annotations.append(f"  [{start:4d}] {val:02x}                    {prefix}BOOLEAN {'true' if val else 'false'}")
    elif type_name in ("int", "long"):
        val, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}{type_name.upper()} {val}")
    elif type_name == "double":
        val = struct.unpack("<d", data[offset:offset + 8])[0]
        hex_str = _hex_range(data, offset, offset + 8)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}DOUBLE {val}")
    elif type_name == "string":
        length, new_off = decode_long(data, offset)
        s = data[new_off:new_off + min(length, 30)].decode("utf-8", errors="replace")
        hex_str = _hex_range(data, offset, new_off)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}STRING len={length} \"{s}\"{'...' if length > 30 else ''}")
    elif type_name == "bytes":
        length, new_off = decode_long(data, offset)
        hex_str = _hex_range(data, offset, new_off)
        annotations.append(f"  [{start:4d}] {hex_str:<20s}  {prefix}BYTES len={length}")


def _hex_range(data: bytes, start: int, end: int) -> str:
    """Hex dump of a byte range, truncated for display."""
    chunk = data[start:end]
    if len(chunk) > 8:
        return " ".join(f"{b:02x}" for b in chunk[:8]) + " ..."
    return " ".join(f"{b:02x}" for b in chunk)


# ============================================================================
# main()
# ============================================================================

def main() -> None:
    print("--- Avro binary encoding from scratch ---\n")

    # Load the schema
    schema_path = Path(__file__).parent / "fooddash.avsc"
    with open(schema_path) as f:
        schema = json.load(f)

    # ------------------------------------------------------------------
    # 1. Zigzag varint encoding
    # ------------------------------------------------------------------
    print("=== Zigzag Varint Encoding ===\n")
    print("  Avro uses zigzag encoding for ALL integers (int AND long).")
    print("  Unlike Protobuf, there's no unsigned varint option -- always zigzag.\n")

    zigzag_examples = [0, -1, 1, -2, 2, 127, -128, 300, 100000, 2**53 + 1]
    for val in zigzag_examples:
        zz = zigzag_encode(val)
        encoded = encode_varint(zz)
        hex_str = " ".join(f"0x{b:02x}" for b in encoded)
        print(f"  {val:>20,d}  -> zigzag {zz:>20,d}  -> {hex_str} ({len(encoded)} byte{'s' if len(encoded) > 1 else ''})")

    print("\n  Key difference from Protobuf: Avro ALWAYS uses zigzag.")
    print("  Protobuf has separate int32 (no zigzag) and sint32 (zigzag).\n")

    # ------------------------------------------------------------------
    # 2. String encoding: NO null terminator
    # ------------------------------------------------------------------
    print("\n=== String Encoding ===\n")
    print("  Avro strings: zigzag_varint(length) + UTF-8 bytes")
    print("  No null terminator, no field tag.\n")

    string_examples = ["", "hello", "Burger", "Spicy Tuna Roll"]
    for s in string_examples:
        encoded = _encode_primitive("string", s)
        hex_str = " ".join(f"{b:02x}" for b in encoded[:20])
        print(f"  \"{s}\"  -> {hex_str} ({len(encoded)} bytes)")

    # ------------------------------------------------------------------
    # 3. The key insight: NO field tags
    # ------------------------------------------------------------------
    print("\n\n=== The Key Insight: NO Field Tags ===\n")
    print("  In Protobuf, every field starts with a tag:")
    print("    [tag: field_num << 3 | wire_type] [value]")
    print()
    print("  In Avro, fields are just concatenated IN SCHEMA ORDER:")
    print("    [value1][value2][value3]...")
    print()
    print("  The reader MUST have the schema to know which bytes are which.")
    print("  This trade-off gives Avro smaller payloads.\n")

    # Demonstrate with a simple record
    simple_schema = {
        "type": "record",
        "name": "Point",
        "fields": [
            {"name": "x", "type": "int"},
            {"name": "y", "type": "int"},
            {"name": "label", "type": "string"},
        ]
    }

    point = {"x": 42, "y": -7, "label": "origin"}
    avro_bytes = avro_encode(simple_schema, point)
    hex_str = " ".join(f"{b:02x}" for b in avro_bytes)

    print("  Point(x=42, y=-7, label='origin')")
    print(f"  Avro bytes: {hex_str} ({len(avro_bytes)} bytes)")
    print()

    # Annotate
    x_enc = encode_long(42)
    y_enc = encode_long(-7)
    label_enc = _encode_primitive("string", "origin")
    print("  Breakdown:")
    print(f"    x=42:            {' '.join(f'{b:02x}' for b in x_enc)} (zigzag varint)")
    print(f"    y=-7:            {' '.join(f'{b:02x}' for b in y_enc)} (zigzag varint)")
    print(f"    label='origin':  {' '.join(f'{b:02x}' for b in label_enc)} (length + UTF-8)")
    print()
    print(f"  Total: {len(avro_bytes)} bytes. Protobuf would need 3 extra tag bytes = {len(avro_bytes) + 3} bytes.")

    # Roundtrip the simple record
    decoded_point, _ = avro_decode(simple_schema, avro_bytes, 0)
    print(f"\n  Decoded: {decoded_point}")
    assert decoded_point == point, "Simple record roundtrip failed!"
    print("  Roundtrip: OK")

    # ------------------------------------------------------------------
    # 4. Union encoding
    # ------------------------------------------------------------------
    print("\n\n=== Union Encoding ===\n")
    print("  Avro unions: zigzag_varint(type_index) + value")
    print("  ['null', 'string'] -> index 0 for null, index 1 for string\n")

    union_schema = ["null", "string"]

    null_val = avro_encode(union_schema, None)
    string_val = avro_encode(union_schema, "hello")
    print(f"  null   -> {' '.join(f'{b:02x}' for b in null_val)} ({len(null_val)} byte: just index 0)")
    print(f"  'hello' -> {' '.join(f'{b:02x}' for b in string_val)} ({len(string_val)} bytes: index 1 + string)")

    # ------------------------------------------------------------------
    # 5. Array encoding
    # ------------------------------------------------------------------
    print("\n\n=== Array/Map Blocked Encoding ===\n")
    print("  Arrays: [block_count][items...][0]")
    print("  A 0-count block terminates the array.\n")

    arr_schema = {"type": "array", "items": "int"}
    arr = [1, 2, 3, 4, 5]
    arr_bytes = avro_encode(arr_schema, arr)
    print(f"  [1,2,3,4,5] -> {' '.join(f'{b:02x}' for b in arr_bytes)} ({len(arr_bytes)} bytes)")
    print(f"    block count=5: {' '.join(f'{b:02x}' for b in encode_long(5))}")
    for v in arr:
        print(f"    item {v}: {' '.join(f'{b:02x}' for b in encode_long(v))}")
    print(f"    terminator 0: {' '.join(f'{b:02x}' for b in encode_long(0))}")

    # ------------------------------------------------------------------
    # 6. Encode a full FoodDash Order
    # ------------------------------------------------------------------
    print("\n\n=== Encoding a FoodDash Order ===\n")

    order = make_typical_order()
    order_dict = order_to_avro_dict(order)

    avro_bytes = avro_encode(schema, order_dict)
    print(f"  Avro (from scratch): {len(avro_bytes):,} bytes")

    # Compare with fastavro
    try:
        import fastavro
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, order_dict)
        fastavro_bytes = buf.getvalue()
        print(f"  fastavro (library): {len(fastavro_bytes):,} bytes")

        if avro_bytes == fastavro_bytes:
            print("\n  EXACT MATCH with fastavro output!")
        else:
            print(f"\n  Differs from fastavro by {abs(len(avro_bytes) - len(fastavro_bytes))} bytes")
            # Find first difference
            for i in range(min(len(avro_bytes), len(fastavro_bytes))):
                if avro_bytes[i] != fastavro_bytes[i]:
                    print(f"  First difference at offset {i}: ours=0x{avro_bytes[i]:02x} fastavro=0x{fastavro_bytes[i]:02x}")
                    break
    except ImportError:
        print("  fastavro: not installed")

    # Compare with Protobuf from-scratch
    try:
        from chapters.ch04_protobuf.proto_from_scratch import encode_order, _prepare_order_dict
        proto_dict = _prepare_order_dict(order)
        proto_bytes = encode_order(proto_dict)
        print(f"  Protobuf (from scratch): {len(proto_bytes):,} bytes")
        savings = len(proto_bytes) - len(avro_bytes)
        pct = (savings / len(proto_bytes)) * 100 if proto_bytes else 0
        print(f"\n  Avro is {savings:,} bytes smaller than Protobuf ({pct:.1f}% savings)")
        print("  Reason: Avro has NO field tags at all -- pure data in schema order.")
    except ImportError:
        print("  Protobuf chapter not available for comparison.")

    # JSON comparison
    import base64
    def _json_default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)
    json_dict = order.model_dump()
    json_dict["status"] = json_dict["status"]
    json_dict["payment_method"] = json_dict["payment_method"]
    json_bytes = json.dumps(json_dict, default=_json_default).encode("utf-8")
    print(f"  JSON:                    {len(json_bytes):,} bytes")
    savings_json = (1 - len(avro_bytes) / len(json_bytes)) * 100
    print(f"\n  Savings vs JSON: {savings_json:.1f}%")

    # ------------------------------------------------------------------
    # 7. Verify roundtrip
    # ------------------------------------------------------------------
    print("\n\n=== Roundtrip Verification ===\n")
    decoded, end_offset = avro_decode(schema, avro_bytes, 0)

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
        ("driver_id", order_dict.get("driver_id"),
         decoded.get("driver_id")),
        ("tip_cents", order_dict["tip_cents"], decoded.get("tip_cents")),
        ("created_at", order_dict["created_at"], decoded.get("created_at")),
        ("items count", len(order_dict["items"]),
         len(decoded.get("items", []))),
        ("metadata", order_dict.get("metadata", {}),
         decoded.get("metadata", {})),
    ]

    all_ok = True
    for name, expected, actual in checks:
        ok = expected == actual
        marker = "OK" if ok else "FAIL"
        if name == "metadata":
            print(f"  {marker:>4s}  {name:<30s}  (matches: {ok})")
        else:
            print(f"  {marker:>4s}  {name:<30s}  {expected!r} == {actual!r}")
        if not ok:
            all_ok = False

    print(f"\n  Bytes consumed: {end_offset} / {len(avro_bytes)}")
    print(f"  Roundtrip: {'PASSED' if all_ok else 'FAILED'}")

    # ------------------------------------------------------------------
    # 8. Byte-level annotation (first portion)
    # ------------------------------------------------------------------
    print("\n\n=== Byte-Level Annotation (first fields) ===\n")
    print("  Note: NO tag bytes. Fields are identified purely by position")
    print("  in the schema. The reader must have the same schema.\n")

    annotations = annotate_avro_bytes(schema, avro_bytes, 0, "", max_depth=2)
    for line in annotations[:40]:
        print(line)
    if len(annotations) > 40:
        print(f"  ... ({len(annotations) - 40} more annotations)")

    # ------------------------------------------------------------------
    # 9. Why smaller than Protobuf
    # ------------------------------------------------------------------
    print("\n\n=== Why Avro Is Smaller Than Protobuf ===\n")
    print("  Protobuf wire format per field:")
    print("    [tag: field_num << 3 | wire_type] [value]")
    print("    Tag is 1-2 bytes per field (field numbers 1-15 = 1 byte)")
    print()
    print("  Avro wire format per field:")
    print("    [value]")
    print("    No tag at all. Zero overhead per field.")
    print()

    # Count approximate tag overhead in protobuf
    field_count = 0

    def _count_fields(d):
        nonlocal field_count
        if isinstance(d, dict):
            for v in d.values():
                field_count += 1
                _count_fields(v)
        elif isinstance(d, list):
            for item in d:
                field_count += 1
                _count_fields(item)

    _count_fields(order_dict)
    print(f"  Our typical order has ~{field_count} field values on the wire.")
    print(f"  Protobuf uses ~{field_count} tag bytes for these fields.")
    print("  Avro uses 0 tag bytes. That's the entire size difference.\n")
    print("  The trade-off: Avro REQUIRES the schema to decode.")
    print("  Protobuf is self-describing enough to skip unknown fields.")
    print("  This is why Avro pairs with a Schema Registry.")


if __name__ == "__main__":
    main()
