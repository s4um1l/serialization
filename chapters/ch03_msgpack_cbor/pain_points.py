"""Pain points of MessagePack/CBOR — the walls that push us to schemas.

These are the real production problems that binary-JSON formats don't solve:
1. Still self-describing: field names eat bytes at scale
2. No schema: adding a field surprises old readers
3. No evolution contract: removing a field breaks old readers
4. Not human-readable: debugging requires tooling
5. Field name overhead at 1M msg/s scale
"""

from __future__ import annotations

import base64
import json
from typing import Any

import msgpack

from shared.sample_data import make_batch_orders, make_typical_order


def _json_default(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


def _prepare(obj: Any) -> Any:
    """Recursively convert enums to their string values."""
    if isinstance(obj, dict):
        return {k: _prepare(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return obj


# ---------------------------------------------------------------------------
# 1. Still self-describing: field name bytes vs total bytes
# ---------------------------------------------------------------------------

def pain_self_describing() -> None:
    """Even in binary, field names consume significant bandwidth."""
    print("--- Pain Point 1: Still self-describing ---\n")

    orders = make_batch_orders(1000)
    total_bytes = 0
    field_name_bytes = 0

    for order in orders:
        order_dict = _prepare(order.model_dump())
        encoded = msgpack.packb(order_dict, use_bin_type=True)
        total_bytes += len(encoded)

        # Count bytes that are field name strings
        field_name_bytes += _count_field_name_bytes(order_dict)

    pct = field_name_bytes / total_bytes * 100
    print("  1,000 orders encoded with MessagePack:")
    print(f"    Total payload:      {total_bytes:>12,} bytes")
    print(f"    Field name bytes:   {field_name_bytes:>12,} bytes")
    print(f"    Field name share:   {pct:>11.1f}%")
    print()
    print(f"  At 1M msg/s, that's ~{field_name_bytes / 1000 * 1_000_000 / 1_000_000:.0f} MB/s just for field names.")
    print("  A schema-based format uses numeric tags (1-2 bytes) instead of")
    print("  string names (5-25 bytes each). That's a 5-20x reduction in")
    print("  field identifier overhead.")


def _count_field_name_bytes(obj: Any) -> int:
    """Recursively count bytes used by dict keys (field names) in msgpack."""
    total = 0
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                key_utf8_len = len(key.encode("utf-8"))
                # msgpack: fixstr = 1 byte header + string bytes
                #          str8   = 2 byte header + string bytes
                if key_utf8_len <= 31:
                    total += 1 + key_utf8_len
                elif key_utf8_len <= 0xFF:
                    total += 2 + key_utf8_len
                else:
                    total += 3 + key_utf8_len
            total += _count_field_name_bytes(value)
    elif isinstance(obj, list):
        for item in obj:
            total += _count_field_name_bytes(item)
    return total


# ---------------------------------------------------------------------------
# 2. No schema: adding a field surprises old readers
# ---------------------------------------------------------------------------

def pain_no_schema() -> None:
    """The kitchen service adds prep_time_minutes. What happens?"""
    print("\n--- Pain Point 2: No schema (the 'add a field' problem) ---\n")

    # Original order as all services know it
    order = make_typical_order()
    order_dict = _prepare(order.model_dump())

    # Kitchen service adds a new field
    order_dict_v2 = dict(order_dict)
    order_dict_v2["prep_time_minutes"] = 18

    encoded_v2 = msgpack.packb(order_dict_v2, use_bin_type=True)
    decoded_v2 = msgpack.unpackb(encoded_v2, raw=False)

    print("  Scenario: Kitchen service adds 'prep_time_minutes' to Order.")
    print()
    print("  The GOOD news: msgpack doesn't crash on unknown fields.")
    print(f"    Decoded keys: {len(decoded_v2)} (was {len(order_dict)}, now +1)")
    print(f"    New field:    prep_time_minutes = {decoded_v2['prep_time_minutes']}")
    print()
    print("  The BAD news: every consumer must be written defensively.")
    print("  If any service does this:")
    print()
    print('    total = order["total_cents"]  # KeyError if field is removed!')
    print('    # or: for key in expected_keys: assert key in order')
    print()
    print("  ...then adding OR removing a field requires coordinated deploys")
    print("  across all 20 microservices. There's no contract that says")
    print('  "this field is optional" or "this field was added in v2."')


# ---------------------------------------------------------------------------
# 3. No schema evolution: removing a field breaks old readers
# ---------------------------------------------------------------------------

def pain_no_evolution() -> None:
    """Remove a field that old code depends on. KeyError."""
    print("\n--- Pain Point 3: No schema evolution (the 'remove a field' problem) ---\n")

    order = make_typical_order()
    order_dict = _prepare(order.model_dump())

    # New version removes 'promo_code' (deprecated feature)
    order_dict_v3 = {k: v for k, v in order_dict.items() if k != "promo_code"}
    encoded_v3 = msgpack.packb(order_dict_v3, use_bin_type=True)
    decoded_v3 = msgpack.unpackb(encoded_v3, raw=False)

    print("  Scenario: promo_code is deprecated and removed from new Order messages.")
    print()
    print("  Old billing service code:")
    print('    promo = order["promo_code"]')
    print()

    try:
        _ = decoded_v3["promo_code"]
        print("  Result: (unexpectedly succeeded)")
    except KeyError as e:
        print(f"  Result: KeyError: {e}")

    print()
    print("  With a schema-based format (like Protobuf), you would have:")
    print("    - Field numbers: promo_code = field 10")
    print("    - Default values: missing field 10 -> empty string")
    print("    - Unknown field skipping: new fields are silently ignored")
    print("    - Evolution rules: never reuse a field number")
    print()
    print("  With MessagePack, you have none of that. Every reader must")
    print("  use .get('promo_code', '') defensively, and there's nothing")
    print("  enforcing that convention across 20 teams.")


# ---------------------------------------------------------------------------
# 4. Not human-readable: debugging requires tooling
# ---------------------------------------------------------------------------

def pain_not_readable() -> None:
    """Show a MsgPack payload as hex — you need tooling to read it."""
    print("\n--- Pain Point 4: Not human-readable ---\n")

    order = make_typical_order()
    order_dict = _prepare(order.model_dump())

    mp_bytes = msgpack.packb(order_dict, use_bin_type=True)
    json_str = json.dumps(order.model_dump(), indent=2, default=_json_default)

    print("  JSON (first 300 chars):")
    print("  " + "-" * 50)
    for line in json_str[:300].split("\n"):
        print(f"    {line}")
    print("    ...")
    print()

    print("  MessagePack (first 120 bytes as hex):")
    print("  " + "-" * 50)
    hex_dump = mp_bytes[:120].hex()
    # Format as rows of 32 hex chars (16 bytes)
    for i in range(0, len(hex_dump), 32):
        row = hex_dump[i:i + 32]
        # Add spaces between byte pairs
        spaced = " ".join(row[j:j+2] for j in range(0, len(row), 2))
        print(f"    {spaced}")
    print("    ...")
    print()
    print("  JSON: you can cat the file and read it.")
    print("  MsgPack: you need a hex viewer + the spec to understand a single byte.")
    print("  When a message is malformed at 3 AM, this matters.")


# ---------------------------------------------------------------------------
# 5. Field name overhead at scale
# ---------------------------------------------------------------------------

def pain_field_name_overhead() -> None:
    """Calculate the bandwidth cost of string field names at 1M msg/s."""
    print("\n--- Pain Point 5: Field name overhead at scale ---\n")

    order = make_typical_order()
    order_dict = _prepare(order.model_dump())

    # Collect all field names recursively
    field_names = _collect_field_names(order_dict)
    unique_names = sorted(set(field_names))

    total_name_bytes = sum(len(n.encode("utf-8")) for n in field_names)
    # Add msgpack header bytes (1 byte each for fixstr)
    total_with_headers = total_name_bytes + len(field_names)

    print(f"  A typical order has {len(field_names)} field name occurrences")
    print(f"  ({len(unique_names)} unique names)")
    print()
    print("  Field names and their byte costs:")
    name_counts: dict[str, int] = {}
    for n in field_names:
        name_counts[n] = name_counts.get(n, 0) + 1
    for name in unique_names:
        utf8_len = len(name.encode("utf-8"))
        count = name_counts[name]
        print(f"    {name:<30} {utf8_len:>3} bytes x{count}")

    print()
    print(f"  Total field name bytes per message: {total_with_headers:,}")
    print()
    msg_per_sec = 1_000_000
    bytes_per_sec = total_with_headers * msg_per_sec
    mb_per_sec = bytes_per_sec / (1024 * 1024)
    print("  At 1M msg/s:")
    print(f"    Field name bandwidth: {mb_per_sec:,.0f} MB/s")
    print(f"    That's {mb_per_sec / 1024:.1f} GB/s just for field names!")
    print()
    print("  With Protobuf numeric tags (1-2 bytes each):")
    proto_bytes_per_msg = len(field_names) * 1  # ~1 byte per tag
    proto_mb_per_sec = proto_bytes_per_msg * msg_per_sec / (1024 * 1024)
    print(f"    Tag bandwidth:        {proto_mb_per_sec:,.0f} MB/s")
    print(f"    Savings:              {mb_per_sec - proto_mb_per_sec:,.0f} MB/s ({(1 - proto_mb_per_sec/mb_per_sec)*100:.0f}%)")


def _collect_field_names(obj: Any) -> list[str]:
    """Recursively collect all dict keys from a nested structure."""
    names: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                names.append(key)
            names.extend(_collect_field_names(value))
    elif isinstance(obj, list):
        for item in obj:
            names.extend(_collect_field_names(item))
    return names


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    pain_self_describing()
    pain_no_schema()
    pain_no_evolution()
    pain_not_readable()
    pain_field_name_overhead()

    print("\n" + "=" * 60)
    print("  SUMMARY: Why MessagePack/CBOR aren't enough")
    print("=" * 60)
    print()
    print("  We got binary efficiency: 30-50% smaller, 2-3x faster.")
    print("  But we still have:")
    print("    - String field names in every message (bandwidth waste)")
    print("    - No schema (no contract between services)")
    print("    - No evolution rules (add/remove fields = coordinated deploy)")
    print("    - No human readability (debugging needs tooling)")
    print()
    print("  Next: Protocol Buffers — schemas, numeric tags, evolution rules.")
    print()


if __name__ == "__main__":
    main()
