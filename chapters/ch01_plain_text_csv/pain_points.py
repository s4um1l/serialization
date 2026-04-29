"""Demonstrates the specific pain points of CSV as a wire format.

Each function shows a concrete failure mode with visible output.
"""

from __future__ import annotations

from shared.sample_data import make_typical_order

from . import csv_from_scratch


# ---------------------------------------------------------------------------
# 1. Delimiter in data
# ---------------------------------------------------------------------------


def demo_delimiter_collision() -> None:
    """A menu item description containing a comma breaks naive splitting."""
    print("-" * 60)
    print("PAIN POINT 1: Delimiter in Data")
    print("-" * 60)

    description = "Two 4oz patties, American cheese, pickles, onion, secret sauce"
    fields = ["menu0001", "Classic Smash Burger", "1299", description, "main"]

    # Naive approach: just join with commas
    naive = ",".join(fields)
    print(f"\n  Original fields ({len(fields)} fields):")
    for i, f in enumerate(fields):
        print(f"    [{i}] {f!r}")

    print("\n  Naive comma-join:")
    print(f"    {naive!r}")

    # Naive split
    naive_split = naive.split(",")
    print(f"\n  Naive split result ({len(naive_split)} fields -- WRONG, expected {len(fields)}):")
    for i, f in enumerate(naive_split):
        print(f"    [{i}] {f!r}")

    # Proper RFC 4180 encoding
    proper = csv_from_scratch.csv_encode_row(fields)
    print("\n  Proper CSV (RFC 4180 quoting):")
    print(f"    {proper!r}")

    proper_decoded = csv_from_scratch.csv_decode_row(proper)
    print(f"\n  Proper decode ({len(proper_decoded)} fields -- CORRECT):")
    for i, f in enumerate(proper_decoded):
        print(f"    [{i}] {f!r}")

    # Hex analysis of the problem area
    print("\n  Hex analysis of the description field in naive output:")
    desc_bytes = description.encode("utf-8")
    hex_parts = []
    for b in desc_bytes:
        ch = chr(b) if 32 <= b < 127 else "."
        marker = " <<< COMMA (0x2C) -- delimiter collision!" if b == 0x2C else ""
        hex_parts.append(f"    0x{b:02X} {ch}{marker}")
    # Show just around the commas
    for i, part in enumerate(hex_parts):
        if "COMMA" in part or (i > 0 and "COMMA" in hex_parts[i - 1]) or (i < len(hex_parts) - 1 and "COMMA" in hex_parts[i + 1]):
            print(part)

    print()


# ---------------------------------------------------------------------------
# 2. Encoding mismatch
# ---------------------------------------------------------------------------


def demo_encoding_mismatch() -> None:
    """UTF-8 data read as Latin-1 produces mojibake."""
    print("-" * 60)
    print("PAIN POINT 2: Encoding Mismatch (UTF-8 vs Latin-1)")
    print("-" * 60)

    restaurant_name = "Borgér Palace \U0001f354"  # Unicode + emoji
    fields = ["rest0001", restaurant_name, "40.748817", "-73.985428"]
    csv_line = csv_from_scratch.csv_encode_row(fields)

    # Write as UTF-8
    utf8_bytes = csv_line.encode("utf-8")
    print(f"\n  Original:      {restaurant_name!r}")
    print(f"  UTF-8 bytes:   {utf8_bytes!r}")
    print(f"  UTF-8 length:  {len(utf8_bytes)} bytes")

    # Read back as Latin-1 (ISO 8859-1) -- what happens in Japan's Excel
    try:
        latin1_text = utf8_bytes.decode("latin-1")
        print("\n  Decoded as Latin-1 (MOJIBAKE):")
        print(f"    {latin1_text!r}")
    except Exception as e:
        print(f"\n  Latin-1 decode error: {e}")

    # Read back as Shift-JIS -- what the Tokyo team might use
    try:
        shiftjis_text = utf8_bytes.decode("shift_jis", errors="replace")
        print("\n  Decoded as Shift-JIS (MOJIBAKE):")
        print(f"    {shiftjis_text!r}")
    except Exception as e:
        print(f"\n  Shift-JIS decode error: {e}")

    # Byte-level comparison
    print("\n  Byte-level view of restaurant name in UTF-8:")
    name_bytes = restaurant_name.encode("utf-8")
    for i, b in enumerate(name_bytes):
        decoded_latin1 = bytes([b]).decode("latin-1")
        print(f"    byte {i:2d}: 0x{b:02X}  UTF-8 -> correct    Latin-1 -> {decoded_latin1!r}")

    print("\n  CSV has NO encoding field. The file is just bytes.")
    print("  The reader GUESSES the encoding. Different guesses = different text.")
    print()


# ---------------------------------------------------------------------------
# 3. No nesting
# ---------------------------------------------------------------------------


def demo_no_nesting() -> None:
    """Show the information loss when flattening Order -> OrderItem -> MenuItem."""
    print("-" * 60)
    print("PAIN POINT 3: No Nesting (Flat Only)")
    print("-" * 60)

    order = make_typical_order()

    print("\n  Original Order structure:")
    print(f"    Order #{order.id}")
    print(f"      customer: {order.customer.name} ({order.customer.id})")
    print(f"      items ({len(order.items)}):")
    for i, oi in enumerate(order.items):
        print(f"        [{i}] {oi.quantity}x {oi.menu_item.name} @ {oi.menu_item.price_cents}c")
        if oi.special_instructions:
            print(f"            note: {oi.special_instructions!r}")
        print(f"            allergens: {oi.menu_item.allergens}")
    print(f"      metadata: {dict(order.metadata)}")

    # Flatten to CSV
    csv_text = csv_from_scratch.csv_encode_order(order)
    decoded = csv_from_scratch.csv_decode_order(csv_text)

    print(f"\n  Flattened CSV ({len(decoded['rows'])} rows):")
    print("    Each row repeats ALL order-level fields.")
    print("    Here's what the finance team sees in Excel:")
    print()

    rows = decoded["rows"]
    for i, row in enumerate(rows):
        print(f"    Row {i}: order_id={row['order_id']}, "
              f"customer={row['customer_name']}, "
              f"item={row['item_name']}, qty={row['item_quantity']}")

    # Show the duplication waste
    order_fields = ["order_id", "customer_id", "customer_name", "customer_email",
                    "customer_phone", "customer_address", "restaurant_id", "status",
                    "payment_method", "driver_id", "delivery_notes"]
    print("\n  Duplication waste:")
    print(f"    {len(order_fields)} order-level fields x {len(rows)} rows = "
          f"{len(order_fields) * len(rows)} cells")
    print(f"    Only {len(order_fields)} of those cells carry unique information.")
    print(f"    The other {len(order_fields) * (len(rows) - 1)} cells are redundant copies.")

    # What we lost
    print("\n  Information LOST in flattening:")
    print("    - allergens list (variable-length per item)")
    print(f"    - thumbnail_png (binary data, {len(order.items[0].menu_item.thumbnail_png)} bytes per item)")
    print(f"    - metadata dict ({len(order.metadata)} key-value pairs)")
    print("    - customer.location (nested GeoPoint)")
    print("    - The STRUCTURE itself: 'which items belong to this order?'")
    print("      A reader must group rows by order_id to reconstruct nesting.")
    print()


# ---------------------------------------------------------------------------
# 4. Type ambiguity
# ---------------------------------------------------------------------------


def demo_type_ambiguity() -> None:
    """Show that CSV cannot distinguish between types."""
    print("-" * 60)
    print("PAIN POINT 4: Type Ambiguity")
    print("-" * 60)

    # These are all different in Python
    values = [
        ("string '42'", "42", str),
        ("integer 42", 42, int),
        ("float 42.0", 42.0, float),
        ("boolean True", True, bool),
        ("None", None, type(None)),
        ("string 'True'", "True", str),
        ("string ''", "", str),
        ("string '0'", "0", str),
        ("integer 0", 0, int),
        ("boolean False", False, bool),
    ]

    print("\n  In-memory Python values:")
    for label, val, typ in values:
        print(f"    {label:<20s}  type={typ.__name__:<10s}  repr={val!r}")

    # Encode them all as CSV
    csv_fields = [str(v) if v is not None else "" for _, v, _ in values]
    csv_line = csv_from_scratch.csv_encode_row(csv_fields)
    print("\n  As a CSV row:")
    print(f"    {csv_line}")

    # Decode
    decoded = csv_from_scratch.csv_decode_row(csv_line)
    print("\n  Decoded from CSV (everything is a string now):")
    for i, (label, original, typ) in enumerate(values):
        decoded_val = decoded[i]
        match = decoded_val == str(original) if original is not None else decoded_val == ""
        problem = ""
        if typ is not str and typ is not type(None):
            problem = " <-- type information LOST"
        print(f"    {label:<20s}  csv={decoded_val!r:<10s}  matches_str={match}{problem}")

    print("\n  The reader has NO way to know:")
    print("    - Is '42' a number or a string?")
    print("    - Is 'True' a boolean or a string?")
    print("    - Is '' an empty string or null/None?")
    print("    - Is '42.0' a float or an integer or a string?")
    print("    Every consumer must hardcode type coercions per column.")
    print()


# ---------------------------------------------------------------------------
# 5. No schema
# ---------------------------------------------------------------------------


def demo_no_schema() -> None:
    """Show that adding a column breaks existing readers."""
    print("-" * 60)
    print("PAIN POINT 5: No Schema / Schema Evolution")
    print("-" * 60)

    # V1 schema: 4 columns
    header_v1 = ["order_id", "customer_name", "item_name", "price_cents"]
    row_v1 = csv_from_scratch.csv_encode_row(["ord001", "Alice", "Burger", "1299"])

    print("\n  V1 CSV (4 columns):")
    print(f"    Header: {csv_from_scratch.csv_encode_row(header_v1)}")
    print(f"    Data:   {row_v1}")

    # V2: add a column in the middle
    header_v2 = ["order_id", "customer_name", "customer_email", "item_name", "price_cents"]
    row_v2 = csv_from_scratch.csv_encode_row(["ord001", "Alice", "alice@ex.com", "Burger", "1299"])

    print("\n  V2 CSV (5 columns -- added customer_email at position 2):")
    print(f"    Header: {csv_from_scratch.csv_encode_row(header_v2)}")
    print(f"    Data:   {row_v2}")

    # V1 reader tries to read V2 data
    v2_fields = csv_from_scratch.csv_decode_row(row_v2)
    print("\n  V1 reader parsing V2 data (expects column 2 = item_name):")
    for i, col_name in enumerate(header_v1):
        if i < len(v2_fields):
            expected = csv_from_scratch.csv_decode_row(row_v1)[i]
            got = v2_fields[i]
            match = "OK" if expected == got else f"WRONG (expected {expected!r})"
            print(f"    column[{i}] ({col_name}): {got!r} -- {match}")
        else:
            print(f"    column[{i}] ({col_name}): MISSING")

    print("\n  Without a schema, the column index IS the schema.")
    print("  Insert a column -> every downstream reader breaks silently.")
    print("  There is no field name -> column mapping in the data itself.")
    print("  (Headers help, but they are optional and readers often skip them.)")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("  CH01 — CSV Pain Points")
    print("=" * 70)
    print()

    demo_delimiter_collision()
    demo_encoding_mismatch()
    demo_no_nesting()
    demo_type_ambiguity()
    demo_no_schema()

    print("=" * 70)
    print("  SUMMARY: CSV hits four walls for FoodDash")
    print("=" * 70)
    print("""
  1. DELIMITER COLLISION — commas in data break naive parsers
  2. ENCODING MISMATCH   — no defined encoding; UTF-8 vs Latin-1 vs Shift-JIS
  3. NO NESTING          — Order -> OrderItem -> MenuItem cannot be represented
  4. TYPE AMBIGUITY      — '42' could be int, float, string, or boolean
  5. NO SCHEMA           — column order is implicit; adding columns breaks readers

  We need a format that:
    - Supports nesting (Order contains Items)
    - Distinguishes types (number vs string vs boolean)
    - Mandates UTF-8 encoding
    - Doesn't use in-band delimiters

  That format is JSON. See Chapter 02.
""")


if __name__ == "__main__":
    main()
