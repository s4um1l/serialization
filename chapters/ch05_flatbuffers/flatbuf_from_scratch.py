"""FlatBuffers from scratch — zero-copy buffer layout by hand.

THIS IS THE STAR OF CHAPTER 05.

We implement the FlatBuffers binary format entirely from scratch to understand:
  1. How the buffer is built BACK-TO-FRONT
  2. How vtables map field indices to data offsets
  3. How reading is just pointer arithmetic — zero allocation, zero parsing

The FlatBuffer binary layout (simplified):
  ┌──────────────────────────────────────────────────────────────────┐
  │  [root offset (uint32)]                                         │
  │  [... vtable bytes ...]                                         │
  │  [... table data: soffset32 to vtable + inline field data ...]  │
  │  [... strings/vectors (written first, appear at end) ...]       │
  └──────────────────────────────────────────────────────────────────┘

  The buffer is built back-to-front: strings first, then table data, then
  vtables, then the root offset. In the final buffer, the root offset is
  at position 0.

Key insight: FlatBuffers stores data so that reading a field is just:
  1. Read soffset32 at table start -> locate vtable
  2. Read uint16 at vtable[field_index] -> get offset within table
  3. Read value at table + offset -> done. No parsing. No allocation.
"""

from __future__ import annotations

import struct
import time


# ─────────────────────────────────────────────────────────────────────
# FlatBufferBuilder — builds a buffer back-to-front
# ─────────────────────────────────────────────────────────────────────

class FlatBufferBuilder:
    """Builds a FlatBuffer by prepending data into a growable byte array.

    FlatBuffers are constructed back-to-front because:
    - Child objects (strings, sub-tables) must exist before their parents
    - Offsets always point forward in the buffer (toward higher addresses)
    - The root table is the LAST thing written (lowest address)

    Coordinate system:
      _buf is a pre-allocated bytearray.  _head points to the first used byte.
      Data is written by decrementing _head. The "offset" of any written object
      is (len(_buf) - _head_at_time_of_write), i.e. distance from the END of
      the buffer.  In the final output the end-of-buffer has the highest
      address, so the offset IS the buffer position measured from byte 0.

      After finish(), output() returns _buf[_head:].
    """

    def __init__(self, initial_size: int = 1024):
        self._buf = bytearray(initial_size)
        self._head: int = initial_size  # cursor, moves toward 0
        self._current_vtable: list[int] = []  # per-field: abs offset or 0
        self._table_start: int = 0  # _head when start_table was called
        self._finished = False

    # -- internal helpers --------------------------------------------------

    def _grow(self, needed: int) -> None:
        while self._head < needed:
            old_size = len(self._buf)
            new_size = old_size * 2
            new_buf = bytearray(new_size)
            delta = new_size - old_size
            new_buf[delta:] = self._buf
            self._buf = new_buf
            self._head += delta
            self._table_start += delta

    def _pad(self, align: int) -> None:
        """Align the write cursor so the NEXT write starts at a multiple."""
        # total bytes used so far from end of buffer
        used = len(self._buf) - self._head
        overshoot = used % align
        if overshoot:
            pad = align - overshoot
            self._grow(pad)
            self._head -= pad  # zeros by default

    def _place_byte(self, val: int) -> None:
        self._grow(1)
        self._head -= 1
        self._buf[self._head] = val & 0xFF

    def _place_uint16(self, val: int) -> None:
        self._pad(2)
        self._grow(2)
        self._head -= 2
        struct.pack_into("<H", self._buf, self._head, val)

    def _place_int32(self, val: int) -> None:
        self._pad(4)
        self._grow(4)
        self._head -= 4
        struct.pack_into("<i", self._buf, self._head, val)

    def _place_uint32(self, val: int) -> None:
        self._pad(4)
        self._grow(4)
        self._head -= 4
        struct.pack_into("<I", self._buf, self._head, val)

    def _place_int64(self, val: int) -> None:
        self._pad(8)
        self._grow(8)
        self._head -= 8
        struct.pack_into("<q", self._buf, self._head, val)

    def _place_float64(self, val: float) -> None:
        self._pad(8)
        self._grow(8)
        self._head -= 8
        struct.pack_into("<d", self._buf, self._head, val)

    def _current_offset(self) -> int:
        """Offset of the last written byte, measured from end of buffer."""
        return len(self._buf) - self._head

    # -- String creation ---------------------------------------------------

    def create_string(self, s: str) -> int:
        """Write a string and return its offset.

        FlatBuffer string layout (in memory order):
          [uint32 byte_length] [UTF-8 bytes ...] [0x00 null] [padding]

        We write it back-to-front: null first, then string bytes, then length.
        The returned offset points to the length prefix.
        """
        encoded = s.encode("utf-8")
        byte_len = len(encoded)

        # Pad to 4-byte alignment BEFORE writing the string content,
        # so that the length prefix will end up aligned.
        # Total string region = 4 (len) + byte_len + 1 (null).
        # We need the START of this region (the uint32) to be 4-byte aligned.
        self._pad(4)

        # null terminator
        self._grow(1)
        self._head -= 1
        self._buf[self._head] = 0

        # string bytes
        self._grow(byte_len)
        self._head -= byte_len
        self._buf[self._head: self._head + byte_len] = encoded

        # uint32 length prefix — no alignment padding here, it must be
        # immediately before the string bytes
        self._grow(4)
        self._head -= 4
        struct.pack_into("<I", self._buf, self._head, byte_len)

        return self._current_offset()

    # -- Table construction ------------------------------------------------

    def start_table(self, num_fields: int) -> None:
        """Begin building a new table with num_fields field slots."""
        self._current_vtable = [0] * num_fields
        self._table_start = self._current_offset()

    def add_field_byte(self, field_index: int, value: int, default: int = 0) -> None:
        if value == default:
            return
        self._place_byte(value)
        self._current_vtable[field_index] = self._current_offset()

    def add_field_int32(self, field_index: int, value: int, default: int = 0) -> None:
        if value == default:
            return
        self._place_int32(value)
        self._current_vtable[field_index] = self._current_offset()

    def add_field_int64(self, field_index: int, value: int, default: int = 0) -> None:
        if value == default:
            return
        self._place_int64(value)
        self._current_vtable[field_index] = self._current_offset()

    def add_field_float64(self, field_index: int, value: float, default: float = 0.0) -> None:
        if value == default:
            return
        self._place_float64(value)
        self._current_vtable[field_index] = self._current_offset()

    def add_field_offset(self, field_index: int, off: int) -> None:
        """Add an offset field pointing to a previously written string/table.

        In FlatBuffers, offset fields store a uint32 *relative* offset:
          value_at_field_pos = target_buf_pos - field_buf_pos

        During building we record absolute offsets and fix up later.
        Actually — we write a placeholder and record the info to patch.
        For simplicity, we write the relative offset now.
        """
        if off == 0:
            return
        # The target (string/table) is at buf_pos = (len(buf) - off)
        # We're about to write a uint32 at a new position.
        # After writing, the field will be at buf_pos = (len(buf) - new_offset).
        # relative = target_buf_pos - field_buf_pos
        #          = (len(buf) - off) - (len(buf) - new_offset)
        #          = new_offset - off
        # But we haven't written yet!  We need to pre-compute.
        # After _place_uint32, _head decreases by 4 (plus maybe padding).
        # Let's just write a placeholder and patch it.

        # Simpler approach: compute where the field will land, then the relative.
        # _pad(4) first, then the field buf position = self._head - 4.
        self._pad(4)
        self._grow(4)
        self._head -= 4
        field_buf_pos = self._head
        target_buf_pos = len(self._buf) - off
        rel = target_buf_pos - field_buf_pos
        struct.pack_into("<I", self._buf, field_buf_pos, rel)

        self._current_vtable[field_index] = self._current_offset()

    def end_table(self) -> int:
        """Finish the table: write the soffset32 and vtable.

        Table data so far sits between _table_start and _current_offset.
        We prepend the soffset32 (int32) that points from the table to its
        vtable, then prepend the vtable itself.

        vtable layout (in memory order, lowest address first):
          [uint16 vtable_byte_size]
          [uint16 table_data_byte_size]  (includes the soffset32)
          [uint16 field_0_offset]  — offset of field 0 from table start, 0=absent
          [uint16 field_1_offset]
          ...

        The soffset32 at the table start = signed offset from table to vtable.
          vtable_buf_pos = table_buf_pos + soffset32
          (positive means vtable is at a higher address, i.e., before table
           in our back-to-front building order.)

        Actually in FlatBuffers: soffset = vtable_pos - table_pos
        (signed, can be negative if vtable is before table in address space,
         but in practice vtable is written after table data, so vtable has a
         lower address and soffset is negative.)

        Wait — let me be precise.  In the FINAL buffer (after output()):
          table starts at some address T.
          bytes T..T+3 are soffset32.
          vtable is at address V.
          soffset32 = T - V  (yes, T - V, so V = T - soffset32).

        When reading: vtable_pos = table_pos - soffset32.  If soffset is
        positive, vtable is at a lower address than the table.
        """
        # Write soffset32 placeholder
        self._place_int32(0)
        table_end_offset = self._current_offset()  # offset from buf end
        # table_buf_pos (in final buf) = len(output) - table_end_offset
        # Actually in the output slice, position = (buf_len - head) - ...
        # Let's think in terms of the output buffer.
        # output = self._buf[self._head:]
        # output_len = buf_len - self._head
        # An object at absolute offset X from buf-end is at output position
        # output_len - X = (buf_len - head) - X.

        # The table's soffset32 is the last thing we wrote (used for vtable patching below)

        # Compute table data size: from soffset32 to _table_start
        table_data_size = table_end_offset - self._table_start + 4
        # Wait, _table_start was recorded BEFORE any field data.
        # Fields were written AFTER start_table, growing the offset.
        # Then soffset32 was written, growing further.
        # table_data_size = soffset32 size + field data bytes
        #                 = table_end_offset - _table_start
        # Actually table_end_offset includes the soffset, _table_start is
        # where field data begins (the "bottom" of the table).
        # In the final buffer, table goes from the soffset position (lowest
        # addr) to _table_start position (highest addr).
        table_data_size = table_end_offset - self._table_start

        # Compute vtable field entries: offset of each field within the table
        # Table spans from table_end_offset (low addr end, where soffset is)
        # to _table_start (high addr end).
        # Field at absolute offset F is at table-relative position:
        #   table_end_offset - F  (distance from the soffset32)
        vt_entries = []
        for abs_off in self._current_vtable:
            if abs_off == 0:
                vt_entries.append(0)
            else:
                vt_entries.append(table_end_offset - abs_off)

        vt_byte_size = 4 + 2 * len(vt_entries)

        # Write vtable back-to-front
        for entry in reversed(vt_entries):
            self._place_uint16(entry)
        self._place_uint16(table_data_size)
        self._place_uint16(vt_byte_size)

        # Now patch soffset32: soffset = vtable_out_pos - table_out_pos
        # In output coordinates:
        #   vtable is at output_len - vtable_offset
        #   table  is at output_len - table_end_offset
        # Wait — we need to express in terms of the output buffer that will
        # be produced by output().  output = buf[head:].
        # output_len = buf_len - head_now ... but head changed since we wrote
        # the table!  We need the positions in the FINAL output.
        #
        # Better: use buf positions directly.
        # vtable buf pos = self._head (it was just written, so _head is at its start)
        vtable_buf_pos = self._head
        # table soffset buf pos = len(buf) - table_end_offset
        table_buf_pos = len(self._buf) - table_end_offset

        # soffset32 stored at table_buf_pos, value = table_buf_pos - vtable_buf_pos
        # Reader does: vtable_pos = table_pos - soffset
        # So: soffset = table_pos - vtable_pos
        soffset = table_buf_pos - vtable_buf_pos
        struct.pack_into("<i", self._buf, table_buf_pos, soffset)

        self._current_vtable = []
        return table_end_offset

    def finish(self, root_table_offset: int) -> None:
        """Prepend the root offset (uint32) — first 4 bytes of the buffer.

        The value is the byte position of the root table in the final buffer.
        """
        # root table is at buf position (len(buf) - root_table_offset)
        # In the final output (buf[head:]), that becomes:
        #   (len(buf) - root_table_offset) - head_after_this_write
        # We don't know head_after yet, so do it in two steps.
        self._pad(4)
        self._grow(4)
        self._head -= 4
        # In the output, root table will be at position:
        #   (len(buf) - root_table_offset) - self._head
        root_out_pos = (len(self._buf) - root_table_offset) - self._head
        struct.pack_into("<I", self._buf, self._head, root_out_pos)
        self._finished = True

    def output(self) -> bytes:
        """Return the finished FlatBuffer as bytes."""
        assert self._finished, "Call finish() before output()"
        return bytes(self._buf[self._head:])


# ─────────────────────────────────────────────────────────────────────
# FlatBufferReader — zero-copy field access
# ─────────────────────────────────────────────────────────────────────

class TableReader:
    """Reads fields from a FlatBuffer table with zero-copy access.

    To read field N:
      1. vtable_pos = table_pos - soffset32_at(table_pos)
      2. field_offset = vtable[4 + 2*N]  (uint16, 0 means absent)
      3. value is at table_pos + field_offset

    This is just pointer arithmetic — no parsing, no object allocation.
    (Strings do allocate a Python str, but we skip fields we don't need.)
    """

    __slots__ = ("_buf", "_table_pos", "_vtable_pos", "_vtable_size")

    def __init__(self, buf: bytes | bytearray | memoryview, table_pos: int):
        self._buf = buf
        self._table_pos = table_pos

        soffset = struct.unpack_from("<i", self._buf, self._table_pos)[0]
        self._vtable_pos = self._table_pos - soffset
        self._vtable_size = struct.unpack_from("<H", self._buf, self._vtable_pos)[0]

    def _field_offset(self, field_index: int) -> int:
        """Vtable lookup: returns offset of field within table, or 0."""
        entry_pos = self._vtable_pos + 4 + 2 * field_index
        if entry_pos >= self._vtable_pos + self._vtable_size:
            return 0
        return struct.unpack_from("<H", self._buf, entry_pos)[0]

    def read_byte(self, field_index: int, default: int = 0) -> int:
        """Read a byte field — one vtable lookup + one byte read."""
        off = self._field_offset(field_index)
        if off == 0:
            return default
        return self._buf[self._table_pos + off]

    def read_int32(self, field_index: int, default: int = 0) -> int:
        """Read a 32-bit int — one vtable lookup + 4 byte read."""
        off = self._field_offset(field_index)
        if off == 0:
            return default
        return struct.unpack_from("<i", self._buf, self._table_pos + off)[0]

    def read_int64(self, field_index: int, default: int = 0) -> int:
        """Read a 64-bit int."""
        off = self._field_offset(field_index)
        if off == 0:
            return default
        return struct.unpack_from("<q", self._buf, self._table_pos + off)[0]

    def read_float64(self, field_index: int, default: float = 0.0) -> float:
        """Read a 64-bit float."""
        off = self._field_offset(field_index)
        if off == 0:
            return default
        return struct.unpack_from("<d", self._buf, self._table_pos + off)[0]

    def read_string(self, field_index: int) -> str | None:
        """Read a string field.

        At the field position there's a uint32 relative offset to the string.
        The string itself: [uint32 byte_length] [UTF-8 bytes] [null].

        Note: Python will allocate a str object.  The zero-copy win is that
        fields you DON'T read cost zero CPU and zero memory.
        """
        off = self._field_offset(field_index)
        if off == 0:
            return None
        field_pos = self._table_pos + off
        # Relative offset to the string
        rel = struct.unpack_from("<I", self._buf, field_pos)[0]
        str_pos = field_pos + rel
        str_len = struct.unpack_from("<I", self._buf, str_pos)[0]
        raw = self._buf[str_pos + 4: str_pos + 4 + str_len]
        if isinstance(raw, memoryview):
            raw = bytes(raw)
        return raw.decode("utf-8")

    def read_table(self, field_index: int) -> TableReader | None:
        """Read a sub-table field."""
        off = self._field_offset(field_index)
        if off == 0:
            return None
        field_pos = self._table_pos + off
        rel = struct.unpack_from("<I", self._buf, field_pos)[0]
        return TableReader(self._buf, field_pos + rel)


class FlatBufferReader:
    """Entry point for reading a FlatBuffer.

    Usage:
        reader = FlatBufferReader(buffer_bytes)
        root = reader.read_root_table()
        name = root.read_string(0)       # only reads field 0
        # Fields you skip cost ZERO.
    """

    __slots__ = ("_buf",)

    def __init__(self, buf: bytes):
        self._buf = buf

    def read_root_table(self) -> TableReader:
        root_offset = struct.unpack_from("<I", self._buf, 0)[0]
        return TableReader(self._buf, root_offset)


# ─────────────────────────────────────────────────────────────────────
# Simplified FoodDash Order — field indices
# ─────────────────────────────────────────────────────────────────────

FIELD_ID = 0
FIELD_RESTAURANT_ID = 1
FIELD_STATUS = 2
FIELD_TIP_CENTS = 3
FIELD_CREATED_AT = 4
FIELD_PLATFORM_TXN_ID = 5
FIELD_DRIVER_ID = 6
FIELD_DELIVERY_NOTES = 7
NUM_FIELDS = 8


def encode_order(
    order_id: str,
    restaurant_id: str,
    status: int,
    tip_cents: int,
    created_at: float,
    platform_transaction_id: int = 0,
    driver_id: str | None = None,
    delivery_notes: str | None = None,
) -> bytes:
    """Encode a simplified Order as a FlatBuffer from scratch."""
    b = FlatBufferBuilder()

    # Step 1: Create strings FIRST (children before parents)
    notes_off = b.create_string(delivery_notes) if delivery_notes else 0
    driver_off = b.create_string(driver_id) if driver_id else 0
    rest_off = b.create_string(restaurant_id)
    id_off = b.create_string(order_id)

    # Step 2: Build the Order table
    b.start_table(NUM_FIELDS)

    # Largest-alignment fields first for tighter packing
    b.add_field_float64(FIELD_CREATED_AT, created_at)
    b.add_field_int64(FIELD_PLATFORM_TXN_ID, platform_transaction_id)
    b.add_field_int32(FIELD_TIP_CENTS, tip_cents)
    b.add_field_byte(FIELD_STATUS, status)

    # Offset fields (strings)
    b.add_field_offset(FIELD_DELIVERY_NOTES, notes_off)
    b.add_field_offset(FIELD_DRIVER_ID, driver_off)
    b.add_field_offset(FIELD_RESTAURANT_ID, rest_off)
    b.add_field_offset(FIELD_ID, id_off)

    order_off = b.end_table()

    # Step 3: Finish — prepend root offset
    b.finish(order_off)

    return b.output()


def decode_order_all_fields(buf: bytes) -> dict:
    """Decode ALL fields from a FlatBuffer."""
    reader = FlatBufferReader(buf)
    root = reader.read_root_table()
    return {
        "id": root.read_string(FIELD_ID),
        "restaurant_id": root.read_string(FIELD_RESTAURANT_ID),
        "status": root.read_byte(FIELD_STATUS),
        "tip_cents": root.read_int32(FIELD_TIP_CENTS),
        "created_at": root.read_float64(FIELD_CREATED_AT),
        "platform_transaction_id": root.read_int64(FIELD_PLATFORM_TXN_ID),
        "driver_id": root.read_string(FIELD_DRIVER_ID),
        "delivery_notes": root.read_string(FIELD_DELIVERY_NOTES),
    }


def decode_order_two_fields(buf: bytes) -> tuple[str | None, int]:
    """Read ONLY restaurant_id and tip_cents.

    With Protobuf you'd parse the entire message to read 2 fields.
    With FlatBuffers we touch ONLY the bytes for these 2 fields.
    """
    reader = FlatBufferReader(buf)
    root = reader.read_root_table()
    restaurant_id = root.read_string(FIELD_RESTAURANT_ID)
    tip_cents = root.read_int32(FIELD_TIP_CENTS)
    return restaurant_id, tip_cents


# ─────────────────────────────────────────────────────────────────────
# main — demonstration
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  FlatBuffers FROM SCRATCH — Zero-Copy Buffer Layout")
    print("=" * 70)

    # -- Encode --
    buf = encode_order(
        order_id="ord00042",
        restaurant_id="rest0001",
        status=5,           # EnRoute
        tip_cents=500,
        created_at=1700000000.0,
        platform_transaction_id=9007199254740993,  # 2^53+1
        driver_id="driv0001",
        delivery_notes="Ring doorbell twice",
    )

    print(f"\n  Buffer size: {len(buf)} bytes")
    print("  Hex dump:")
    for i in range(0, len(buf), 16):
        chunk = buf[i: i + 16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"    {i:04x}: {hex_str:<48s} |{ascii_str}|")

    # -- Read ALL fields --
    print("\n  --- Read ALL fields (zero-copy per-field access) ---")
    all_fields = decode_order_all_fields(buf)
    for k, v in all_fields.items():
        print(f"    {k}: {v!r}")

    # -- Read ONLY 2 fields (the killer feature) --
    print("\n  --- Read ONLY 2 fields (zero-copy advantage) ---")
    restaurant_id, tip_cents = decode_order_two_fields(buf)
    print(f"    restaurant_id: {restaurant_id!r}")
    print(f"    tip_cents:     {tip_cents}")

    # -- Timing comparison --
    print("\n  --- Timing: 2 fields vs all fields ---")
    iterations = 100_000

    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order_two_fields(buf)
    two_ns = time.perf_counter_ns() - start

    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order_all_fields(buf)
    all_ns = time.perf_counter_ns() - start

    print(f"    Read 2 fields:   {two_ns / iterations:>8.1f} ns/op")
    print(f"    Read all fields: {all_ns / iterations:>8.1f} ns/op")
    print(f"    Speedup:         {all_ns / two_ns:.2f}x faster")

    # -- Buffer layout walkthrough --
    print("\n  --- Buffer Layout Walkthrough ---")
    root_off = struct.unpack_from("<I", buf, 0)[0]
    print(f"    Bytes 0..3:  root offset = {root_off}")

    table_pos = root_off
    soffset = struct.unpack_from("<i", buf, table_pos)[0]
    vtable_pos = table_pos - soffset
    print(f"    Bytes {table_pos}..{table_pos+3}: soffset32 = {soffset}")
    print(f"    vtable at byte {vtable_pos}")

    vt_size = struct.unpack_from("<H", buf, vtable_pos)[0]
    tbl_size = struct.unpack_from("<H", buf, vtable_pos + 2)[0]
    print(f"    vtable size = {vt_size} bytes, table data size = {tbl_size} bytes")

    field_names = [
        "id", "restaurant_id", "status", "tip_cents",
        "created_at", "platform_txn_id", "driver_id", "delivery_notes",
    ]
    print("\n    vtable field map:")
    for i in range(NUM_FIELDS):
        entry_pos = vtable_pos + 4 + 2 * i
        if entry_pos < vtable_pos + vt_size:
            off = struct.unpack_from("<H", buf, entry_pos)[0]
            label = f"offset {off}" if off != 0 else "ABSENT (default)"
            print(f"      [{i}] {field_names[i]:20s} -> {label}")

    print()


if __name__ == "__main__":
    main()
