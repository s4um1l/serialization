"""FlatBuffers library demo — using the official flatbuffers Python package.

Builds a FoodDash Order using flatbuffers.Builder, reads fields back,
benchmarks encode/decode, and compares with JSON and our from-scratch
implementation.

The key insight: FlatBuffers "decoding" is nearly free because there is
no deserialization step.  You access fields directly from the buffer
via offset lookups.
"""

from __future__ import annotations

import json
import struct
import time

import flatbuffers

from shared.bench import benchmark, compare
from shared.sample_data import make_typical_order

# ─────────────────────────────────────────────────────────────────────
# Encode helpers using the flatbuffers library Builder API
# ─────────────────────────────────────────────────────────────────────
# Without flatc-generated code we use the raw Builder API.
# Every table is: StartObject(num_fields) -> PrependSlot... -> EndObject()
# Every string is: CreateString(value)


def _encode_order_lib(order) -> bytes:
    """Encode a shared.models.Order using the flatbuffers library Builder."""
    builder = flatbuffers.Builder(512)

    # -- Step 1: strings and child objects (must come before the table) --

    # Strings
    id_off = builder.CreateString(order.id)
    rest_off = builder.CreateString(order.restaurant_id)
    driver_off = builder.CreateString(order.driver_id or "")
    notes_off = builder.CreateString(order.delivery_notes or "")
    promo_off = builder.CreateString(order.promo_code or "")

    # Customer sub-table
    cust = order.customer
    cust_id_off = builder.CreateString(cust.id)
    cust_name_off = builder.CreateString(cust.name)
    cust_email_off = builder.CreateString(cust.email)
    cust_phone_off = builder.CreateString(cust.phone)
    cust_addr_off = builder.CreateString(cust.address)

    # Customer table (6 fields: id, name, email, phone, address, location)
    builder.StartObject(6)
    builder.PrependUOffsetTRelativeSlot(0, cust_id_off, 0)
    builder.PrependUOffsetTRelativeSlot(1, cust_name_off, 0)
    builder.PrependUOffsetTRelativeSlot(2, cust_email_off, 0)
    builder.PrependUOffsetTRelativeSlot(3, cust_phone_off, 0)
    builder.PrependUOffsetTRelativeSlot(4, cust_addr_off, 0)
    # location: inline GeoPoint would need a struct, skip for simplicity
    cust_off = builder.EndObject()

    # Items — encode each OrderItem
    item_offsets = []
    for oi in order.items:
        mi = oi.menu_item
        mi_id = builder.CreateString(mi.id)
        mi_name = builder.CreateString(mi.name)
        mi_desc = builder.CreateString(mi.description)
        mi_cat = builder.CreateString(mi.category)

        # MenuItem table (6 fields: id, name, price_cents, desc, cat, is_veg)
        builder.StartObject(6)
        builder.PrependUOffsetTRelativeSlot(0, mi_id, 0)
        builder.PrependUOffsetTRelativeSlot(1, mi_name, 0)
        builder.PrependInt32Slot(2, mi.price_cents, 0)
        builder.PrependUOffsetTRelativeSlot(3, mi_desc, 0)
        builder.PrependUOffsetTRelativeSlot(4, mi_cat, 0)
        builder.PrependBoolSlot(5, mi.is_vegetarian, False)
        mi_off = builder.EndObject()

        instr = builder.CreateString(oi.special_instructions)

        # OrderItem table (3 fields: menu_item, quantity, special_instructions)
        builder.StartObject(3)
        builder.PrependUOffsetTRelativeSlot(0, mi_off, 0)
        builder.PrependInt32Slot(1, oi.quantity, 1)
        builder.PrependUOffsetTRelativeSlot(2, instr, 0)
        item_offsets.append(builder.EndObject())

    # Items vector
    builder.StartVector(4, len(item_offsets), 4)
    for ioff in reversed(item_offsets):
        builder.PrependUOffsetTRelative(ioff)
    items_vec = builder.EndVector()

    # -- Step 2: Order root table --
    # Field indices matching our .fbs:
    #   0:id, 1:platform_transaction_id, 2:customer, 3:restaurant_id,
    #   4:items, 5:status, 6:payment_method, 7:driver_id, 8:delivery_notes,
    #   9:promo_code, 10:tip_cents, 11:created_at, 12:updated_at,
    #   13:estimated_delivery_minutes
    STATUS_MAP = {
        "placed": 0, "confirmed": 1, "preparing": 2, "ready": 3,
        "picked_up": 4, "en_route": 5, "delivered": 6, "cancelled": 7,
    }
    PAY_MAP = {"credit_card": 0, "debit_card": 1, "cash": 2, "wallet": 3}

    builder.StartObject(14)
    builder.PrependUOffsetTRelativeSlot(0, id_off, 0)
    builder.PrependInt64Slot(1, order.platform_transaction_id, 0)
    builder.PrependUOffsetTRelativeSlot(2, cust_off, 0)
    builder.PrependUOffsetTRelativeSlot(3, rest_off, 0)
    builder.PrependUOffsetTRelativeSlot(4, items_vec, 0)
    builder.PrependInt8Slot(5, STATUS_MAP.get(order.status.value, 0), 0)
    builder.PrependInt8Slot(6, PAY_MAP.get(order.payment_method.value, 0), 0)
    builder.PrependUOffsetTRelativeSlot(7, driver_off, 0)
    builder.PrependUOffsetTRelativeSlot(8, notes_off, 0)
    builder.PrependUOffsetTRelativeSlot(9, promo_off, 0)
    builder.PrependInt32Slot(10, order.tip_cents, 0)
    builder.PrependFloat64Slot(11, order.created_at, 0.0)
    builder.PrependFloat64Slot(12, order.updated_at, 0.0)
    builder.PrependInt32Slot(13, order.estimated_delivery_minutes or 0, 0)
    root = builder.EndObject()

    builder.Finish(root)
    return bytes(builder.Output())


def _read_all_fields_lib(buf: bytes) -> dict:
    """Read all top-level scalar fields from a FlatBuffer using raw access.

    Without flatc-generated accessors, we use the flatbuffers.Table class
    for manual vtable lookups — same zero-copy mechanism, just manual.

    The Table.Offset(slot) method takes a vtable byte offset:
      slot = 4 + 2 * field_index
    (4 bytes for vtable header, 2 bytes per field entry.)
    """
    from flatbuffers import table as fb_table
    from flatbuffers import number_types as N

    ba = bytearray(buf)
    root_offset = struct.unpack_from("<I", ba, 0)[0]
    tab = fb_table.Table(ba, root_offset)

    def read_string(field_idx):
        off = tab.Offset(4 + 2 * field_idx)
        if off == 0:
            return None
        pos = tab.Pos + off
        return tab.String(pos).decode("utf-8") if tab.String(pos) else None

    def read_int32(field_idx, default=0):
        return tab.GetSlot(4 + 2 * field_idx, default, N.Int32Flags)

    def read_int64(field_idx, default=0):
        return tab.GetSlot(4 + 2 * field_idx, default, N.Int64Flags)

    def read_float64(field_idx, default=0.0):
        return tab.GetSlot(4 + 2 * field_idx, default, N.Float64Flags)

    def read_byte(field_idx, default=0):
        return tab.GetSlot(4 + 2 * field_idx, default, N.Int8Flags)

    return {
        "id": read_string(0),
        "platform_transaction_id": read_int64(1),
        "restaurant_id": read_string(3),
        "status": read_byte(5),
        "payment_method": read_byte(6),
        "driver_id": read_string(7),
        "delivery_notes": read_string(8),
        "promo_code": read_string(9),
        "tip_cents": read_int32(10),
        "created_at": read_float64(11),
        "updated_at": read_float64(12),
        "estimated_delivery_minutes": read_int32(13),
    }


# ─────────────────────────────────────────────────────────────────────
# JSON helpers for comparison
# ─────────────────────────────────────────────────────────────────────

def _encode_json(order) -> bytes:
    d = order.model_dump()
    d["status"] = d["status"].value if hasattr(d["status"], "value") else d["status"]
    d["payment_method"] = (
        d["payment_method"].value
        if hasattr(d["payment_method"], "value")
        else d["payment_method"]
    )
    # Remove bytes fields (not JSON-serializable as-is)
    for item in d.get("items", []):
        mi = item.get("menu_item", {})
        if "thumbnail_png" in mi:
            mi["thumbnail_png"] = ""
    return json.dumps(d).encode("utf-8")


def _decode_json(payload: bytes):
    return json.loads(payload)


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  FlatBuffers LIBRARY Demo — flatbuffers.Builder")
    print("=" * 70)

    order = make_typical_order()

    # -- Encode --
    fb_buf = _encode_order_lib(order)
    print(f"\n  FlatBuffer size:  {len(fb_buf):>6,} bytes")

    json_buf = _encode_json(order)
    print(f"  JSON size:        {len(json_buf):>6,} bytes")

    # -- Read back --
    print("\n  --- Fields read from FlatBuffer (zero-copy) ---")
    fields = _read_all_fields_lib(fb_buf)
    for k, v in fields.items():
        print(f"    {k}: {v!r}")

    # -- Benchmark --
    print("\n  --- Benchmarks ---")

    fb_result = benchmark(
        name="FlatBuffers (lib)",
        encode_fn=lambda: _encode_order_lib(order),
        decode_fn=lambda payload: _read_all_fields_lib(payload),
        iterations=5_000,
    )

    json_result = benchmark(
        name="JSON",
        encode_fn=lambda: _encode_json(order),
        decode_fn=lambda payload: _decode_json(payload),
        iterations=5_000,
    )

    # from-scratch comparison
    from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
        encode_order,
        decode_order_all_fields,
    )

    scratch_buf = encode_order(
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        status=5,  # en_route
        tip_cents=order.tip_cents,
        created_at=order.created_at,
        platform_transaction_id=order.platform_transaction_id,
        driver_id=order.driver_id,
        delivery_notes=order.delivery_notes,
    )

    scratch_result = benchmark(
        name="FlatBuffers (scratch)",
        encode_fn=lambda: encode_order(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            status=5,
            tip_cents=order.tip_cents,
            created_at=order.created_at,
            platform_transaction_id=order.platform_transaction_id,
            driver_id=order.driver_id,
            delivery_notes=order.delivery_notes,
        ),
        decode_fn=lambda payload: decode_order_all_fields(payload),
        iterations=5_000,
    )

    compare(fb_result, scratch_result, json_result)

    # -- Size comparison --
    print("  --- Size Comparison ---")
    print(f"    FlatBuffers (lib):     {len(fb_buf):>6,} bytes")
    print(f"    FlatBuffers (scratch): {len(scratch_buf):>6,} bytes  (simplified Order)")
    print(f"    JSON:                  {len(json_buf):>6,} bytes")
    ratio = len(fb_buf) / len(json_buf) * 100
    print(f"    FlatBuffer/JSON ratio: {ratio:.0f}%")
    print()

    # -- Demonstrate "decode = ~0" --
    print("  --- FlatBuffers 'decode' is just pointer setup ---")
    iterations = 100_000
    start = time.perf_counter_ns()
    for _ in range(iterations):
        # "Decoding" = creating a TableReader (reads root offset + vtable)
        root_offset = struct.unpack_from("<I", fb_buf, 0)[0]
        _ = struct.unpack_from("<i", fb_buf, root_offset)[0]
    ns = time.perf_counter_ns() - start
    print(f"    Root table setup: {ns / iterations:.1f} ns/op")
    print("    That is the total 'parse' cost. Everything else is per-field lookup.")
    print()


if __name__ == "__main__":
    main()
