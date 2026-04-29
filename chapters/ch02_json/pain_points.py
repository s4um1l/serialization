"""Demonstrate JSON's specific failure modes in a production context.

Each demo shows a real-world problem that has caused production incidents
at companies running JSON at scale.
"""

from __future__ import annotations

import base64
import json

from shared.sample_data import make_large_order, make_typical_order


# ---------------------------------------------------------------------------
# Custom encoder for bytes
# ---------------------------------------------------------------------------

class _BytesEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            return f'$base64:{base64.b64encode(o).decode("ascii")}'
        return super().default(o)


def _bytes_to_base64(obj):
    """Recursively convert bytes to base64 strings for size measurement."""
    if isinstance(obj, dict):
        return {k: _bytes_to_base64(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_bytes_to_base64(v) for v in obj]
    if isinstance(obj, bytes):
        return f'$base64:{base64.b64encode(obj).decode("ascii")}'
    return obj


def _strip_bytes(obj):
    """Recursively remove bytes values (replace with empty string)."""
    if isinstance(obj, dict):
        return {k: _strip_bytes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_bytes(v) for v in obj]
    if isinstance(obj, bytes):
        return ""
    return obj


# ---------------------------------------------------------------------------
# 1. Float precision
# ---------------------------------------------------------------------------

def demo_float_precision() -> None:
    print("=" * 60)
    print("  PAIN POINT 1: Float Precision")
    print("=" * 60)

    # The classic 0.1 + 0.2 problem
    a = 0.1
    b = 0.2
    c = a + b
    print(f"\nPython:  0.1 + 0.2 = {c}")
    print(f"         0.1 + 0.2 == 0.3? {c == 0.3}")

    # Round-trip through JSON
    payload = json.dumps({"total": c})
    decoded = json.loads(payload)
    print(f"\nJSON:    {payload}")
    print(f"Decoded: {decoded['total']}")
    print(f"         Still != 0.3? {decoded['total'] != 0.3}")

    # Real-world danger: price as float vs int
    print("\n--- Price as float (DANGEROUS) ---")
    price_float = 19.99
    payload = json.dumps({"price": price_float})
    decoded = json.loads(payload)
    print(f"  Encode: {payload}")
    print(f"  Decoded price: {decoded['price']}")
    print(f"  price * 100 = {decoded['price'] * 100}  (expected: 1999)")
    print(f"  int(price * 100) = {int(decoded['price'] * 100)}  (may be 1998!)")

    print("\n--- Price as integer cents (SAFE) ---")
    price_cents = 1999
    payload = json.dumps({"price_cents": price_cents})
    decoded = json.loads(payload)
    print(f"  Encode: {payload}")
    print(f"  Decoded price_cents: {decoded['price_cents']}")
    print("  Exact integer: always safe")
    print()


# ---------------------------------------------------------------------------
# 2. Large integer precision (the 2^53 problem)
# ---------------------------------------------------------------------------

def demo_large_integer() -> None:
    print("=" * 60)
    print("  PAIN POINT 2: Large Integer Precision (2^53 boundary)")
    print("=" * 60)

    txn_id = 9007199254740993  # 2^53 + 1
    print(f"\nOriginal transaction ID:   {txn_id}")
    print(f"This is 2^53 + 1:          {2**53 + 1}")

    # JSON encodes it fine
    payload = json.dumps({"platform_transaction_id": txn_id})
    print(f"\nJSON payload: {payload}")

    # Python decodes it fine (Python int has arbitrary precision)
    decoded = json.loads(payload)
    print(f"Python decoded: {decoded['platform_transaction_id']}")
    print(f"Python matches: {decoded['platform_transaction_id'] == txn_id}")

    # But JavaScript uses IEEE 754 double for all numbers
    # Simulate what JavaScript does:
    js_number = float(txn_id)  # IEEE 754 double
    js_int = int(js_number)     # Back to int
    print("\nJavaScript Number (IEEE 754 double):")
    print(f"  float({txn_id}) = {js_number}")
    print(f"  int(float(...)) = {js_int}")
    print(f"  Lost precision:  {txn_id} != {js_int}")
    print(f"  Difference:      {txn_id - js_int}")

    print("\n  Production impact: billing reconciliation fails silently.")
    print(f"  The frontend shows transaction {js_int}, the database has {txn_id}.")

    # Show the boundary
    print("\n--- The 2^53 boundary ---")
    for offset in range(-2, 4):
        val = 2**53 + offset
        as_float = float(val)
        roundtrip = int(as_float)
        ok = "OK" if val == roundtrip else f"LOST -> {roundtrip}"
        print(f"  2^53 + {offset:+d} = {val}  -> float -> int = {ok}")
    print()


# ---------------------------------------------------------------------------
# 3. Binary data overhead (base64 bloat)
# ---------------------------------------------------------------------------

def demo_binary_overhead() -> None:
    print("=" * 60)
    print("  PAIN POINT 3: Binary Data Overhead (base64)")
    print("=" * 60)

    order = make_large_order()
    order_dict = order.model_dump()

    # Count raw binary bytes in the order
    raw_binary_bytes = 0
    thumbnail_count = 0

    def count_bytes(obj):
        nonlocal raw_binary_bytes, thumbnail_count
        if isinstance(obj, dict):
            for v in obj.values():
                count_bytes(v)
        elif isinstance(obj, list):
            for v in obj:
                count_bytes(v)
        elif isinstance(obj, bytes):
            raw_binary_bytes += len(obj)
            thumbnail_count += 1

    count_bytes(order_dict)

    # Encode with base64
    json_with_binary = json.dumps(order_dict, cls=_BytesEncoder)
    json_bytes = json_with_binary.encode('utf-8')

    # Encode without binary (stripped)
    stripped = _strip_bytes(order_dict)
    json_without_binary = json.dumps(stripped).encode('utf-8')

    # base64 math: 3 raw bytes -> 4 base64 chars
    expected_b64_size = (raw_binary_bytes + 2) // 3 * 4  # ceiling division

    print(f"\nLarge order: {thumbnail_count} thumbnails")
    print(f"  Raw binary data:     {raw_binary_bytes:>10,} bytes")
    print(f"  Expected base64:     {expected_b64_size:>10,} bytes (33% inflation)")
    print(f"  Actual overhead:     {len(json_bytes) - len(json_without_binary):>10,} bytes")
    print(f"\n  JSON without binary: {len(json_without_binary):>10,} bytes")
    print(f"  JSON with binary:    {len(json_bytes):>10,} bytes")
    print(f"  Binary portion:      {(len(json_bytes) - len(json_without_binary)) / len(json_bytes) * 100:>9.1f}%")

    print("\n  base64 math: every 3 bytes of binary become 4 bytes of text")
    print(f"  So {raw_binary_bytes:,} bytes -> ~{expected_b64_size:,} base64 chars + quotes + prefix")
    print(f"  That's a {(expected_b64_size - raw_binary_bytes) / raw_binary_bytes * 100:.0f}% inflation for binary data")
    print()


# ---------------------------------------------------------------------------
# 4. Repeated field names
# ---------------------------------------------------------------------------

def demo_repeated_field_names() -> None:
    print("=" * 60)
    print("  PAIN POINT 4: Repeated Field Names")
    print("=" * 60)

    order = make_typical_order()
    order_dict = order.model_dump()

    # Strip bytes to keep things cleaner for this analysis
    order_dict = _strip_bytes(order_dict)

    single_json = json.dumps(order_dict)
    single_size = len(single_json.encode('utf-8'))

    # Count field name bytes in a single order
    def count_field_name_bytes(obj, counts=None):
        if counts is None:
            counts = {"field_name_bytes": 0, "field_name_count": 0}
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Each key appears as "key": in JSON -> len(key) + 2 (quotes) + 1 (colon)
                counts["field_name_bytes"] += len(key) + 3  # quotes + colon
                counts["field_name_count"] += 1
                count_field_name_bytes(value, counts)
        elif isinstance(obj, list):
            for item in obj:
                count_field_name_bytes(item, counts)
        return counts

    single_counts = count_field_name_bytes(order_dict)

    print(f"\nSingle order JSON size: {single_size:,} bytes")
    print(f"  Field names:          {single_counts['field_name_bytes']:,} bytes ({single_counts['field_name_count']} fields)")
    print(f"  Field name overhead:  {single_counts['field_name_bytes'] / single_size * 100:.1f}%")

    # Now batch 1000 orders
    print("\n--- Batch of 1000 identical orders ---")
    batch = [order_dict] * 1000
    batch_json = json.dumps(batch)
    batch_size = len(batch_json.encode('utf-8'))

    total_fn_bytes = single_counts['field_name_bytes'] * 1000
    total_fn_count = single_counts['field_name_count'] * 1000

    print(f"  Batch JSON size:      {batch_size:>12,} bytes")
    print(f"  Total field names:    {total_fn_bytes:>12,} bytes ({total_fn_count:,} field instances)")
    print(f"  Field name overhead:  {total_fn_bytes / batch_size * 100:>11.1f}%")
    print(f"\n  Unique field names:   {single_counts['field_name_count']}")
    print(f"  Repeated instances:   {total_fn_count:,}")
    print(f"  Waste: the same ~{single_counts['field_name_count']} field names repeated 1000 times")

    # Show the most common field names
    print("\n--- Most common field names in one order ---")
    name_freq: dict[str, int] = {}

    def collect_names(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                name_freq[key] = name_freq.get(key, 0) + 1
                collect_names(value)
        elif isinstance(obj, list):
            for item in obj:
                collect_names(item)

    collect_names(order_dict)
    for name, freq in sorted(name_freq.items(), key=lambda x: -x[1])[:10]:
        bytes_per = len(name) + 3
        print(f"  {name:30s}  x{freq:<3d}  = {bytes_per * freq:>5,} bytes/order  -> {bytes_per * freq * 1000:>8,} bytes/1000")
    print()


# ---------------------------------------------------------------------------
# 5. No schema enforcement
# ---------------------------------------------------------------------------

def demo_no_schema() -> None:
    print("=" * 60)
    print("  PAIN POINT 5: No Schema Enforcement")
    print("=" * 60)

    # Create a valid order JSON
    valid = {
        "id": "ord00001",
        "status": "placed",
        "customer": {"id": "cust0001", "name": "Alice"},
        "items": [],
    }
    print(f"\nValid order:   {json.dumps(valid)}")

    # Introduce a typo
    typo = {
        "id": "ord00001",
        "statsu": "placed",     # typo: "statsu" instead of "status"
        "cusotmer": {"id": "cust0001", "name": "Alice"},  # typo: "cusotmer"
        "items": [],
    }
    typo_json = json.dumps(typo)
    print(f"Typo order:    {typo_json}")

    # JSON happily accepts it
    decoded = json.loads(typo_json)
    print("\nJSON parsed it without error: True")
    print(f"  decoded['statsu'] = {decoded.get('statsu')!r}")
    print(f"  decoded['status'] = {decoded.get('status')!r}  <- silently missing!")
    print(f"  decoded['cusotmer'] = {decoded.get('cusotmer')!r}")
    print(f"  decoded['customer'] = {decoded.get('customer')!r}  <- silently missing!")

    # Wrong types
    wrong_types = {
        "id": 12345,           # Should be string
        "status": True,        # Should be string enum
        "customer": "Alice",   # Should be object
        "items": "none",       # Should be array
        "price_cents": "free", # Should be int
    }
    wrong_json = json.dumps(wrong_types)
    decoded = json.loads(wrong_json)
    print(f"\nWrong types:   {wrong_json}")
    print("JSON parsed it without error: True")
    print(f"  id is int instead of string:      {type(decoded['id']).__name__}")
    print(f"  status is bool instead of string:  {type(decoded['status']).__name__}")
    print(f"  customer is string instead of obj: {type(decoded['customer']).__name__}")
    print(f"  items is string instead of array:  {type(decoded['items']).__name__}")

    print("\n  JSON has no concept of schema. Any valid JSON is 'correct'.")
    print("  Typos, missing fields, wrong types: all accepted silently.")
    print("  You only discover the error when code crashes downstream.")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    demo_float_precision()
    demo_large_integer()
    demo_binary_overhead()
    demo_repeated_field_names()
    demo_no_schema()


if __name__ == "__main__":
    main()
