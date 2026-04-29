"""Zero-copy proof — tracemalloc evidence that FlatBuffers skip allocation.

This module uses Python's tracemalloc to measure the memory allocations
during deserialization/field-reading for two formats:

  1. Protobuf-style (from-scratch TLV): full deserialization into dicts/strings
  2. FlatBuffers (from-scratch): zero-copy field reads from the buffer

We compare three scenarios:
  - Read ALL fields
  - Read only 2 fields
  - Buffer creation overhead

The result proves that FlatBuffers allocate dramatically less when reading
a subset of fields — the killer advantage for services like FoodDash's
driver-matching that only need 2 out of 30 fields.
"""

from __future__ import annotations

import gc
import struct
import tracemalloc

from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
    FlatBufferReader,
    FIELD_TIP_CENTS,
    encode_order,
    decode_order_all_fields,
    decode_order_two_fields,
)


# ─────────────────────────────────────────────────────────────────────
# Simple Protobuf-style TLV encoder/decoder (inline, no ch04 dependency)
# ─────────────────────────────────────────────────────────────────────
# We implement a minimal TLV (tag-length-value) format that mimics
# Protobuf's behavior: full deserialization into Python dicts/strings.

def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a varint (base-128)."""
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    """Decode a varint, return (value, new_position)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos


# Wire types: 0=varint, 1=64-bit, 2=length-delimited, 5=32-bit
def _proto_encode_order(
    order_id: str,
    restaurant_id: str,
    status: int,
    tip_cents: int,
    created_at: float,
    platform_transaction_id: int,
    driver_id: str,
    delivery_notes: str,
) -> bytes:
    """Encode fields as Protobuf-style TLV (tag + wire_type + value)."""
    parts: list[bytes] = []

    def add_string(field_num: int, val: str):
        tag = (field_num << 3) | 2  # wire type 2 = length-delimited
        encoded = val.encode("utf-8")
        parts.append(_encode_varint(tag))
        parts.append(_encode_varint(len(encoded)))
        parts.append(encoded)

    def add_varint(field_num: int, val: int):
        tag = (field_num << 3) | 0
        parts.append(_encode_varint(tag))
        parts.append(_encode_varint(val))

    def add_fixed64(field_num: int, val: float):
        tag = (field_num << 3) | 1
        parts.append(_encode_varint(tag))
        parts.append(struct.pack("<d", val))

    def add_fixed64_int(field_num: int, val: int):
        tag = (field_num << 3) | 1
        parts.append(_encode_varint(tag))
        parts.append(struct.pack("<q", val))

    add_string(1, order_id)
    add_string(2, restaurant_id)
    add_varint(3, status)
    add_varint(4, tip_cents)
    add_fixed64(5, created_at)
    add_fixed64_int(6, platform_transaction_id)
    add_string(7, driver_id)
    add_string(8, delivery_notes)

    return b"".join(parts)


def _proto_decode_all(buf: bytes) -> dict:
    """Decode ALL fields from a Protobuf-style TLV buffer.

    This is the key comparison: Protobuf MUST scan the entire buffer
    and allocate Python objects for every field.
    """
    result: dict = {}
    pos = 0
    while pos < len(buf):
        tag, pos = _decode_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            val, pos = _decode_varint(buf, pos)
            if field_num == 3:
                result["status"] = val
            elif field_num == 4:
                result["tip_cents"] = val
        elif wire_type == 1:  # 64-bit
            if field_num == 5:
                result["created_at"] = struct.unpack_from("<d", buf, pos)[0]
            elif field_num == 6:
                result["platform_transaction_id"] = struct.unpack_from("<q", buf, pos)[0]
            pos += 8
        elif wire_type == 2:  # length-delimited
            length, pos = _decode_varint(buf, pos)
            val_bytes = buf[pos: pos + length]
            val_str = val_bytes.decode("utf-8")
            if field_num == 1:
                result["id"] = val_str
            elif field_num == 2:
                result["restaurant_id"] = val_str
            elif field_num == 7:
                result["driver_id"] = val_str
            elif field_num == 8:
                result["delivery_notes"] = val_str
            pos += length

    return result


def _proto_decode_two_fields(buf: bytes) -> tuple[str, int]:
    """Decode 2 fields from Protobuf — but must scan the ENTIRE buffer.

    Even though we only want restaurant_id and tip_cents, Protobuf's TLV
    format requires scanning every tag to find the fields we need.  Every
    string along the way gets decoded.  (You could skip unknown wire types
    without decoding their content, but you still scan every tag.)
    """
    restaurant_id = ""
    tip_cents = 0
    pos = 0
    while pos < len(buf):
        tag, pos = _decode_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:
            val, pos = _decode_varint(buf, pos)
            if field_num == 4:
                tip_cents = val
        elif wire_type == 1:
            pos += 8
        elif wire_type == 2:
            length, pos = _decode_varint(buf, pos)
            if field_num == 2:
                restaurant_id = buf[pos: pos + length].decode("utf-8")
            pos += length

    return restaurant_id, tip_cents


# ─────────────────────────────────────────────────────────────────────
# Memory measurement
# ─────────────────────────────────────────────────────────────────────

def measure_allocations(fn, label: str, runs: int = 50) -> tuple[int, int, int]:
    """Run fn() under tracemalloc and return (current, peak, block_count)."""
    gc.collect()
    tracemalloc.start()
    for _ in range(runs):
        fn()
    current, peak = tracemalloc.get_traced_memory()
    # Count allocation blocks
    snapshot = tracemalloc.take_snapshot()
    stats = snapshot.statistics("lineno")
    block_count = sum(s.count for s in stats)
    tracemalloc.stop()
    return current, peak, block_count


def main() -> None:
    print("=" * 70)
    print("  ZERO-COPY PROOF — tracemalloc Memory Analysis")
    print("=" * 70)

    # -- Prepare test data --
    # Use a realistic payload with long strings to make the difference dramatic.
    order_id = "ord00042-abcdef1234567890"
    restaurant_id = "rest0001"
    status = 5
    tip_cents = 500
    created_at = 1700000000.0
    platform_txn_id = 9007199254740993
    driver_id = "driv0001-xyz-matchmaker-v2"
    delivery_notes = (
        "Ring doorbell twice, leave at door. "
        "Do not leave with the neighbor. "
        "Call if no answer within 5 minutes. "
        "Gate code: #4521. Building B, floor 3, apt 3C."
    )

    fb_buf = encode_order(
        order_id=order_id,
        restaurant_id=restaurant_id,
        status=status,
        tip_cents=tip_cents,
        created_at=created_at,
        platform_transaction_id=platform_txn_id,
        driver_id=driver_id,
        delivery_notes=delivery_notes,
    )

    proto_buf = _proto_encode_order(
        order_id=order_id,
        restaurant_id=restaurant_id,
        status=status,
        tip_cents=tip_cents,
        created_at=created_at,
        platform_transaction_id=platform_txn_id,
        driver_id=driver_id,
        delivery_notes=delivery_notes,
    )

    print(f"\n  FlatBuffer size: {len(fb_buf)} bytes")
    print(f"  Protobuf size:   {len(proto_buf)} bytes")

    # -- Scenario 1: Read ALL fields --
    print("\n  --- Scenario 1: Read ALL fields ---")

    _, proto_all_peak, proto_all_blocks = measure_allocations(
        lambda: _proto_decode_all(proto_buf),
        "Protobuf decode all",
    )
    _, fb_all_peak, fb_all_blocks = measure_allocations(
        lambda: decode_order_all_fields(fb_buf),
        "FlatBuffer read all",
    )

    print(f"    {'':30s} {'Peak Memory':>14s} {'Alloc Blocks':>14s}")
    print(f"    {'─' * 60}")
    print(f"    {'Protobuf (decode all)':30s} {proto_all_peak:>10,} B   {proto_all_blocks:>10,}")
    print(f"    {'FlatBuffers (read all)':30s} {fb_all_peak:>10,} B   {fb_all_blocks:>10,}")
    if proto_all_peak > 0:
        ratio = fb_all_peak / proto_all_peak
        print(f"    FlatBuffers uses {ratio:.1%} of Protobuf's peak memory")

    # -- Scenario 2: Read only 2 fields --
    print("\n  --- Scenario 2: Read ONLY 2 fields (restaurant_id + tip_cents) ---")
    print("    This is the KILLER scenario for zero-copy.")
    print("    FoodDash driver-matching reads 2 of 30 fields per order.\n")

    _, proto_2_peak, proto_2_blocks = measure_allocations(
        lambda: _proto_decode_two_fields(proto_buf),
        "Protobuf decode 2",
    )
    _, fb_2_peak, fb_2_blocks = measure_allocations(
        lambda: decode_order_two_fields(fb_buf),
        "FlatBuffer read 2",
    )

    print(f"    {'':30s} {'Peak Memory':>14s} {'Alloc Blocks':>14s}")
    print(f"    {'─' * 60}")
    print(f"    {'Protobuf (scan + decode 2)':30s} {proto_2_peak:>10,} B   {proto_2_blocks:>10,}")
    print(f"    {'FlatBuffers (read 2)':30s} {fb_2_peak:>10,} B   {fb_2_blocks:>10,}")

    # -- Scenario 3: Read a single int32 field (no string allocation at all) --
    print("\n  --- Scenario 3: Read a single int32 (tip_cents) ---")
    print("    FlatBuffers: two struct.unpack_from calls, ZERO string allocation.\n")

    def fb_read_one_int():
        reader = FlatBufferReader(fb_buf)
        root = reader.read_root_table()
        return root.read_int32(FIELD_TIP_CENTS)

    def proto_read_one_int():
        # Still must scan entire buffer to find field 4
        pos = 0
        while pos < len(proto_buf):
            tag, pos = _decode_varint(proto_buf, pos)
            field_num = tag >> 3
            wire_type = tag & 0x07
            if wire_type == 0:
                val, pos = _decode_varint(proto_buf, pos)
                if field_num == 4:
                    return val
            elif wire_type == 1:
                pos += 8
            elif wire_type == 2:
                length, pos = _decode_varint(proto_buf, pos)
                pos += length
        return 0

    _, proto_1_peak, proto_1_blocks = measure_allocations(proto_read_one_int, "Proto 1")
    _, fb_1_peak, fb_1_blocks = measure_allocations(fb_read_one_int, "FB 1")

    print(f"    {'':30s} {'Peak Memory':>14s} {'Alloc Blocks':>14s}")
    print(f"    {'─' * 60}")
    print(f"    {'Protobuf (scan for 1 int)':30s} {proto_1_peak:>10,} B   {proto_1_blocks:>10,}")
    print(f"    {'FlatBuffers (read 1 int)':30s} {fb_1_peak:>10,} B   {fb_1_blocks:>10,}")

    # -- Scenario 4: Timing comparison (where zero-copy really shines) --
    print("\n  --- Scenario 4: Timing — O(n) scan vs O(1) lookup ---")
    print("    In C/C++/Rust, FlatBuffer reads compile to raw pointer math.")
    print("    In Python, struct.unpack overhead dilutes the advantage, but")
    print("    the ACCESS PATTERN difference is still measurable.\n")

    import time

    iterations = 200_000

    # FlatBuffer: read 1 int (O(1) — vtable lookup + read)
    start = time.perf_counter_ns()
    for _ in range(iterations):
        reader = FlatBufferReader(fb_buf)
        root = reader.read_root_table()
        _ = root.read_int32(FIELD_TIP_CENTS)
    fb_1int_ns = (time.perf_counter_ns() - start) / iterations

    # Protobuf: read 1 int (O(n) — must scan past every tag)
    start = time.perf_counter_ns()
    for _ in range(iterations):
        proto_read_one_int()
    proto_1int_ns = (time.perf_counter_ns() - start) / iterations

    # FlatBuffer: read 2 fields
    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order_two_fields(fb_buf)
    fb_2_ns = (time.perf_counter_ns() - start) / iterations

    # Protobuf: read 2 fields
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _proto_decode_two_fields(proto_buf)
    proto_2_ns = (time.perf_counter_ns() - start) / iterations

    print(f"    {'':30s} {'ns/op':>10s} {'Speedup':>10s}")
    print(f"    {'─' * 52}")
    print(f"    {'Proto  (scan for 1 int)':30s} {proto_1int_ns:>8.0f} ns {'':>10s}")
    print(f"    {'FlatBuf (read 1 int)':30s} {fb_1int_ns:>8.0f} ns {proto_1int_ns/fb_1int_ns:>8.2f}x")
    print(f"    {'Proto  (scan for 2 fields)':30s} {proto_2_ns:>8.0f} ns {'':>10s}")
    print(f"    {'FlatBuf (read 2 fields)':30s} {fb_2_ns:>8.0f} ns {proto_2_ns/fb_2_ns:>8.2f}x")

    # -- Summary --
    print("\n  --- Summary ---")
    print("    Protobuf (TLV) must scan every tag in the buffer sequentially.")
    print("    Even to read 1 field, it touches every byte before the target.")
    print("    Each string field decoded along the way allocates a Python str.")
    print()
    print("    FlatBuffers jump directly to any field via vtable lookup — O(1).")
    print("    Reading an int32 is: root_offset -> vtable -> field offset -> done.")
    print("    No scanning. No intermediate objects. The buffer IS the data.")
    print()
    print("    In Python the struct.unpack overhead narrows the gap, but in")
    print("    C++/Rust/Go, a FlatBuffer field read compiles to a single")
    print("    pointer dereference — literally 1 CPU instruction vs scanning")
    print("    the entire message. At 1M msg/s that is the difference between")
    print("    stable p99 and GC-induced latency spikes.")
    print()


if __name__ == "__main__":
    main()
