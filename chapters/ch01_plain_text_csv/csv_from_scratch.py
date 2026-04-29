"""CSV encoder/decoder built from scratch — no `csv` module.

Demonstrates:
- RFC 4180 quoting rules (fields with commas, quotes, newlines)
- Flattening nested Order -> OrderItem -> MenuItem into flat rows
- Information loss when round-tripping nested data through CSV
"""

from __future__ import annotations

from shared.models import Order
from shared.sample_data import make_typical_order


# ---------------------------------------------------------------------------
# Low-level: single row encode / decode
# ---------------------------------------------------------------------------


def csv_encode_row(fields: list[str]) -> str:
    """Encode a list of string fields into a single CSV line (no trailing newline).

    RFC 4180 quoting rules:
    - If a field contains a comma, double-quote, or newline it MUST be quoted.
    - Double-quotes inside a quoted field are escaped by doubling them.
    """
    encoded_fields: list[str] = []
    for f in fields:
        needs_quoting = "," in f or '"' in f or "\n" in f or "\r" in f
        if needs_quoting:
            escaped = f.replace('"', '""')
            encoded_fields.append(f'"{escaped}"')
        else:
            encoded_fields.append(f)
    return ",".join(encoded_fields)


def csv_decode_row(line: str) -> list[str]:
    """Decode a single CSV line into a list of string fields.

    Implements a small state machine:
    - FIELD_START: beginning of a new field
    - IN_UNQUOTED: reading an unquoted field
    - IN_QUOTED: reading inside a quoted field
    - AFTER_QUOTE: just saw a quote inside a quoted field (could be escaped or end)
    """
    FIELD_START = 0
    IN_UNQUOTED = 1
    IN_QUOTED = 2
    AFTER_QUOTE = 3

    fields: list[str] = []
    current: list[str] = []
    state = FIELD_START

    for ch in line:
        if state == FIELD_START:
            if ch == '"':
                state = IN_QUOTED
            elif ch == ",":
                fields.append("")
                # state stays FIELD_START
            else:
                current.append(ch)
                state = IN_UNQUOTED

        elif state == IN_UNQUOTED:
            if ch == ",":
                fields.append("".join(current))
                current = []
                state = FIELD_START
            else:
                current.append(ch)

        elif state == IN_QUOTED:
            if ch == '"':
                state = AFTER_QUOTE
            else:
                current.append(ch)

        elif state == AFTER_QUOTE:
            if ch == '"':
                # Escaped double-quote
                current.append('"')
                state = IN_QUOTED
            elif ch == ",":
                fields.append("".join(current))
                current = []
                state = FIELD_START
            else:
                # End of quoted field, but unexpected char (be lenient)
                current.append(ch)
                state = IN_UNQUOTED

    # Final field
    fields.append("".join(current))
    return fields


# ---------------------------------------------------------------------------
# High-level: Order <-> CSV
# ---------------------------------------------------------------------------

# Column order for the flattened CSV.  One row per OrderItem.
HEADER = [
    "order_id",
    "platform_transaction_id",
    "customer_id",
    "customer_name",
    "customer_email",
    "customer_phone",
    "customer_address",
    "restaurant_id",
    "status",
    "payment_method",
    "driver_id",
    "delivery_notes",
    "promo_code",
    "tip_cents",
    "created_at",
    "updated_at",
    "estimated_delivery_minutes",
    # Per-item fields
    "item_menu_id",
    "item_name",
    "item_price_cents",
    "item_description",
    "item_category",
    "item_is_vegetarian",
    "item_quantity",
    "item_special_instructions",
]


def csv_encode_order(order: Order) -> str:
    """Flatten an Order into CSV rows (one row per OrderItem, header included).

    Information intentionally lost:
    - allergens list (variable-length, can't fit in fixed columns)
    - thumbnail_png (binary data)
    - metadata dict (variable keys)
    - customer location (nested GeoPoint)
    """
    rows: list[str] = [csv_encode_row(HEADER)]

    for oi in order.items:
        mi = oi.menu_item
        row = [
            order.id,
            str(order.platform_transaction_id),
            order.customer.id,
            order.customer.name,
            order.customer.email,
            order.customer.phone,
            order.customer.address,
            order.restaurant_id,
            order.status.value,
            order.payment_method.value,
            order.driver_id or "",
            order.delivery_notes or "",
            order.promo_code or "",
            str(order.tip_cents),
            str(order.created_at),
            str(order.updated_at),
            str(order.estimated_delivery_minutes) if order.estimated_delivery_minutes is not None else "",
            mi.id,
            mi.name,
            str(mi.price_cents),
            mi.description,
            mi.category,
            str(mi.is_vegetarian),
            str(oi.quantity),
            oi.special_instructions,
        ]
        rows.append(csv_encode_row(row))

    return "\r\n".join(rows) + "\r\n"


def csv_decode_order(csv_text: str) -> dict:
    """Parse CSV back into a dict-of-lists structure.

    Returns a dict with the header names as keys and lists of values.
    This is the best we can do: the nested structure is gone.
    """
    lines = csv_text.strip().split("\r\n")
    if not lines:
        return {}

    # Handle lines that could also be split on just \n
    if len(lines) == 1:
        lines = csv_text.strip().split("\n")

    header = csv_decode_row(lines[0])
    records: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = csv_decode_row(line)
        record = {}
        for i, col in enumerate(header):
            record[col] = values[i] if i < len(values) else ""
        records.append(record)

    return {"header": header, "rows": records}


# ---------------------------------------------------------------------------
# Round-trip fidelity check
# ---------------------------------------------------------------------------


def check_roundtrip(order: Order) -> list[str]:
    """Encode -> decode -> compare. Return list of discrepancies."""
    csv_text = csv_encode_order(order)
    decoded = csv_decode_order(csv_text)
    issues: list[str] = []

    if not decoded.get("rows"):
        issues.append("No rows decoded")
        return issues

    first = decoded["rows"][0]

    # Check basic fields
    if first.get("order_id") != order.id:
        issues.append(f"order_id: {first.get('order_id')!r} != {order.id!r}")
    if first.get("customer_name") != order.customer.name:
        issues.append(f"customer_name: {first.get('customer_name')!r} != {order.customer.name!r}")

    # Structural losses
    issues.append(
        f"LOST: allergens — each menu item had an allergens list, "
        f"e.g. {order.items[0].menu_item.allergens!r}"
    )
    issues.append(
        f"LOST: thumbnail_png — {len(order.items[0].menu_item.thumbnail_png)} bytes of binary data per item"
    )
    issues.append(
        f"LOST: metadata dict — {dict(order.metadata)}"
    )
    issues.append(
        f"LOST: customer.location — GeoPoint({order.customer.location})"
        if order.customer.location
        else "LOST: customer.location — None"
    )
    issues.append(
        f"LOST: nesting — the {len(order.items)} OrderItems are flattened; "
        f"order-level fields are duplicated {len(order.items)} times"
    )
    issues.append(
        "AMBIGUOUS: all values are strings — tip_cents '500' could be "
        "int 500, float 500.0, or string '500'"
    )

    return issues


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("  CH01 — CSV From Scratch (no stdlib csv module)")
    print("=" * 70)

    # --- Low-level demo ---
    print("\n--- Low-level: csv_encode_row / csv_decode_row ---")
    fields = ["hello", "world, with comma", 'has "quotes"', "line\nbreak"]
    encoded = csv_encode_row(fields)
    print(f"  Fields:   {fields}")
    print(f"  Encoded:  {encoded}")
    decoded = csv_decode_row(encoded)
    print(f"  Decoded:  {decoded}")
    assert fields == decoded, f"Round-trip mismatch: {fields} != {decoded}"
    print("  Round-trip: OK")

    # --- Order encode ---
    print("\n--- Encode a typical FoodDash Order ---")
    order = make_typical_order()
    csv_text = csv_encode_order(order)
    print(f"  Order ID:          {order.id}")
    print(f"  Items:             {len(order.items)}")
    print(f"  CSV size:          {len(csv_text.encode('utf-8')):,} bytes")
    print(f"  CSV rows:          {len(csv_text.strip().splitlines())} (1 header + {len(order.items)} data)")
    print()
    print("  First 500 chars of CSV output:")
    print("  " + "-" * 60)
    for line in csv_text[:500].splitlines():
        print(f"    {line}")
    print("  " + "-" * 60)

    # --- Round-trip check ---
    print("\n--- Round-trip fidelity check ---")
    issues = check_roundtrip(order)
    for issue in issues:
        print(f"  {'[OK]' if not issue.startswith('LOST') and not issue.startswith('AMBIGUOUS') else '[!!]'} {issue}")

    print(f"\n  Total issues: {len(issues)}")
    print()


if __name__ == "__main__":
    main()
