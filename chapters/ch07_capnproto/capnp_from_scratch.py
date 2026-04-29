"""Cap'n Proto from scratch -- the wire format IS the memory format.

THIS IS THE STAR OF CHAPTER 07.

We implement Cap'n Proto's binary format entirely from scratch to understand:
  1. How data is laid out in 8-byte WORDS (not bytes like FlatBuffers)
  2. How structs have a fixed DATA section (inline scalars) + POINTER section
  3. How "encoding" is just writing values at word-aligned offsets
  4. How "decoding" is just pointer arithmetic -- zero allocation, zero parsing

The Cap'n Proto message layout:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  [segment table: segment count + segment sizes]                     │
  │  [segment 0 data ...]                                               │
  │    struct 0: [data words...] [pointer words...]                     │
  │    text 0:   [list pointer -> NUL-terminated UTF-8 bytes, padded]   │
  │    struct 1: [data words...] [pointer words...]                     │
  │    ...                                                              │
  └──────────────────────────────────────────────────────────────────────┘

Key differences from FlatBuffers:
  - FlatBuffers: build back-to-front, vtable for field lookup, uint32 offsets
  - Cap'n Proto: build front-to-back, fixed struct layout, typed pointers
  - Cap'n Proto: everything is 8-byte word aligned (more padding, simpler math)
  - Cap'n Proto: pointers encode type + offset + size info in a single 64-bit word

Pointer encoding (64 bits):
  Bits 0-1:   Pointer type (0=struct, 1=list, 2=far, 3=other/capability)
  Bits 2-31:  Offset in words from the end of the pointer to the target
  Bits 32-63: Type-specific (struct: data/ptr section sizes; list: element type + count)
"""

from __future__ import annotations

import struct
import time

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────

WORD_SIZE = 8  # Cap'n Proto operates in 8-byte words

# Pointer types (bits 0-1)
PTR_STRUCT = 0
PTR_LIST = 1
PTR_FAR = 2
PTR_OTHER = 3

# List element size tags (bits 32-34 of a list pointer)
LIST_VOID = 0       # 0 bits per element
LIST_BIT = 1        # 1 bit per element
LIST_BYTE = 2       # 1 byte per element
LIST_TWO_BYTES = 3  # 2 bytes per element
LIST_FOUR_BYTES = 4 # 4 bytes per element
LIST_EIGHT_BYTES = 5  # 8 bytes (one word) per element
LIST_POINTER = 6    # one pointer per element
LIST_COMPOSITE = 7  # variable-size structs


# ─────────────────────────────────────────────────────────────────────
# Pointer encoding/decoding helpers
# ─────────────────────────────────────────────────────────────────────

def make_struct_pointer(offset_words: int, data_words: int, pointer_words: int) -> int:
    """Build a struct pointer (64-bit value).

    Layout:
      Bits  0-1:  0 (struct pointer type)
      Bits  2-31: signed offset in words from pointer's end to struct start
      Bits 32-47: data section size in words (uint16)
      Bits 48-63: pointer section size in words (uint16)

    The offset is a SIGNED 30-bit integer stored in bits 2-31.
    """
    # Encode offset as signed 30-bit in bits 2-31
    # offset_words can be negative (for back-references), mask to 30 bits
    offset_masked = offset_words & 0x3FFFFFFF
    lo = PTR_STRUCT | (offset_masked << 2)
    hi = (data_words & 0xFFFF) | ((pointer_words & 0xFFFF) << 16)
    return lo | (hi << 32)


def make_list_pointer(offset_words: int, element_size: int, element_count: int) -> int:
    """Build a list pointer (64-bit value).

    Layout:
      Bits  0-1:  1 (list pointer type)
      Bits  2-31: signed offset in words from pointer's end to list start
      Bits 32-34: element size tag
      Bits 35-63: element count (29 bits)
    """
    offset_masked = offset_words & 0x3FFFFFFF
    lo = PTR_LIST | (offset_masked << 2)
    hi = (element_size & 0x7) | ((element_count & 0x1FFFFFFF) << 3)
    return lo | (hi << 32)


def decode_pointer(raw: int) -> dict:
    """Decode a 64-bit Cap'n Proto pointer into its components."""
    ptr_type = raw & 0x3

    # Extract signed 30-bit offset from bits 2-31
    offset_raw = (raw >> 2) & 0x3FFFFFFF
    if offset_raw >= 0x20000000:  # sign bit set
        offset_raw -= 0x40000000
    offset_words = offset_raw

    if ptr_type == PTR_STRUCT:
        data_words = (raw >> 32) & 0xFFFF
        pointer_words = (raw >> 48) & 0xFFFF
        return {
            "type": "struct",
            "offset_words": offset_words,
            "data_words": data_words,
            "pointer_words": pointer_words,
        }
    elif ptr_type == PTR_LIST:
        element_size = (raw >> 32) & 0x7
        element_count = (raw >> 35) & 0x1FFFFFFF
        return {
            "type": "list",
            "offset_words": offset_words,
            "element_size": element_size,
            "element_count": element_count,
        }
    elif ptr_type == PTR_FAR:
        return {"type": "far", "offset_words": offset_words}
    else:
        return {"type": "other", "raw": raw}


# ─────────────────────────────────────────────────────────────────────
# CapnpBuilder -- builds a Cap'n Proto message segment front-to-back
# ─────────────────────────────────────────────────────────────────────

class CapnpBuilder:
    """Builds a Cap'n Proto message in a single segment.

    Unlike FlatBuffers (which builds back-to-front), Cap'n Proto builds
    front-to-back.  We allocate words sequentially from the start of the
    segment.

    The key insight: there IS no encoding step.  We're just writing values
    at word-aligned offsets in a byte buffer.  The resulting buffer IS the
    wire format AND the in-memory format.
    """

    def __init__(self, initial_words: int = 256):
        self._segment = bytearray(initial_words * WORD_SIZE)
        self._used_words = 0  # how many words have been allocated

    def _ensure_capacity(self, words_needed: int) -> None:
        """Grow the segment if necessary."""
        total_bytes_needed = (self._used_words + words_needed) * WORD_SIZE
        while total_bytes_needed > len(self._segment):
            self._segment.extend(bytearray(len(self._segment)))

    def _alloc_words(self, count: int) -> int:
        """Allocate count words, return the word offset of the first word."""
        self._ensure_capacity(count)
        offset = self._used_words
        self._used_words += count
        return offset

    # -- Struct allocation --

    def alloc_struct(self, data_words: int, pointer_words: int) -> int:
        """Allocate space for a struct and return its word offset.

        A struct is laid out as:
          [data section: data_words * 8 bytes] [pointer section: pointer_words * 8 bytes]

        All scalar fields live inline in the data section.
        All variable-length references (text, lists, sub-structs) go in the pointer section.
        """
        return self._alloc_words(data_words + pointer_words)

    # -- Scalar writes (data section) --

    def write_int32(self, struct_word_offset: int, data_slot: int, value: int) -> None:
        """Write a 32-bit integer at a data slot within a struct.

        data_slot is the 32-bit slot index within the data section.
        Slot 0 = bytes 0-3, slot 1 = bytes 4-7, slot 2 = bytes 8-11, etc.
        """
        byte_offset = struct_word_offset * WORD_SIZE + data_slot * 4
        struct.pack_into("<i", self._segment, byte_offset, value)

    def write_uint16(self, struct_word_offset: int, data_slot: int, value: int) -> None:
        """Write a 16-bit unsigned integer at a data slot within a struct.

        data_slot is the 16-bit slot index within the data section.
        Slot 0 = bytes 0-1, slot 1 = bytes 2-3, etc.
        """
        byte_offset = struct_word_offset * WORD_SIZE + data_slot * 2
        struct.pack_into("<H", self._segment, byte_offset, value)

    def write_int64(self, struct_word_offset: int, data_slot: int, value: int) -> None:
        """Write a 64-bit integer at a data slot within a struct.

        data_slot is the 64-bit slot index (word index) within the data section.
        """
        byte_offset = struct_word_offset * WORD_SIZE + data_slot * 8
        struct.pack_into("<q", self._segment, byte_offset, value)

    def write_float64(self, struct_word_offset: int, data_slot: int, value: float) -> None:
        """Write a 64-bit float at a data slot within a struct.

        data_slot is the 64-bit slot index (word index) within the data section.
        """
        byte_offset = struct_word_offset * WORD_SIZE + data_slot * 8
        struct.pack_into("<d", self._segment, byte_offset, value)

    # -- Text (stored as a byte list with NUL terminator) --

    def write_text(self, text: str) -> int:
        """Write a text value and return its word offset.

        In Cap'n Proto, Text is stored as a list of bytes with a NUL terminator.
        The list pointer encodes element_size=BYTE and element_count=len+1 (for NUL).

        Returns the word offset where the text bytes begin (the list content).
        """
        encoded = text.encode("utf-8")
        byte_len = len(encoded) + 1  # +1 for NUL terminator
        # Round up to whole words
        word_count = (byte_len + WORD_SIZE - 1) // WORD_SIZE
        text_offset = self._alloc_words(word_count)
        byte_start = text_offset * WORD_SIZE
        self._segment[byte_start:byte_start + len(encoded)] = encoded
        self._segment[byte_start + len(encoded)] = 0  # NUL terminator
        return text_offset

    # -- Pointer writes (pointer section) --

    def write_struct_pointer(
        self,
        struct_word_offset: int,
        data_words: int,
        ptr_slot: int,
        target_word_offset: int,
        target_data_words: int,
        target_pointer_words: int,
    ) -> None:
        """Write a struct pointer in the pointer section of a struct.

        ptr_slot: index within the pointer section (0, 1, 2, ...)
        target_word_offset: word offset of the target struct in the segment

        The pointer's offset field = distance in words from (pointer_location + 1 word)
        to the target struct.
        """
        pointer_byte_offset = (struct_word_offset + data_words + ptr_slot) * WORD_SIZE
        pointer_word_pos = struct_word_offset + data_words + ptr_slot
        # Offset = target - (pointer_pos + 1)
        # This is how Cap'n Proto pointers work: offset is from the END of the
        # pointer word to the START of the target.
        offset_words = target_word_offset - (pointer_word_pos + 1)
        ptr_value = make_struct_pointer(offset_words, target_data_words, target_pointer_words)
        struct.pack_into("<Q", self._segment, pointer_byte_offset, ptr_value)

    def write_text_pointer(
        self,
        struct_word_offset: int,
        data_words: int,
        ptr_slot: int,
        text_word_offset: int,
        text_byte_count: int,
    ) -> None:
        """Write a list pointer for text in the pointer section.

        text_byte_count: number of bytes INCLUDING the NUL terminator.
        """
        pointer_byte_offset = (struct_word_offset + data_words + ptr_slot) * WORD_SIZE
        pointer_word_pos = struct_word_offset + data_words + ptr_slot
        offset_words = text_word_offset - (pointer_word_pos + 1)
        ptr_value = make_list_pointer(offset_words, LIST_BYTE, text_byte_count)
        struct.pack_into("<Q", self._segment, pointer_byte_offset, ptr_value)

    # -- Finalize --

    def build_message(self, root_struct_offset: int, root_data_words: int,
                      root_pointer_words: int) -> bytes:
        """Build the final message with segment table and root struct pointer.

        Cap'n Proto message framing:
          [uint32 segment_count - 1]   (0 for single segment)
          [uint32 segment_0_size_words]
          [padding to 8-byte boundary if needed]
          [segment 0 bytes ...]

        The first word of segment 0 is the root struct pointer.
        We allocate a root pointer at the beginning.
        """
        # Build the segment: root pointer + existing data
        # The root pointer points to the root struct
        # The root pointer is at word 0 of the segment.
        # But we already allocated from word 0... We need to shift.
        #
        # Actually, in our simplified builder, we pre-allocate the root pointer
        # as part of the segment. Let's rebuild with the root pointer prepended.

        # Create final segment with root pointer at word 0
        final_segment_words = 1 + self._used_words  # 1 for root pointer
        final_segment = bytearray(final_segment_words * WORD_SIZE)

        # Root pointer: offset from end of root pointer word (word 0) to root struct
        # Root struct is at word (root_struct_offset + 1) in the final segment
        # (because we shifted everything by 1 word)
        offset_from_root_ptr = root_struct_offset  # words from (word 0 + 1) to target
        root_ptr = make_struct_pointer(offset_from_root_ptr, root_data_words, root_pointer_words)
        struct.pack_into("<Q", final_segment, 0, root_ptr)

        # Copy the segment data after the root pointer
        final_segment[WORD_SIZE:WORD_SIZE + self._used_words * WORD_SIZE] = (
            self._segment[:self._used_words * WORD_SIZE]
        )

        # Build message frame: segment table + segment data
        # Single segment: header = [0x00000000 (count-1=0)] [segment_size_words]
        # Header is 8 bytes (already word-aligned for 1 segment)
        header = struct.pack("<II", 0, final_segment_words)
        return header + bytes(final_segment)

    def raw_segment(self) -> bytes:
        """Return just the raw segment bytes (no framing), for inspection."""
        return bytes(self._segment[:self._used_words * WORD_SIZE])


# ─────────────────────────────────────────────────────────────────────
# CapnpReader -- zero-copy reading from a Cap'n Proto message
# ─────────────────────────────────────────────────────────────────────

class StructReader:
    """Zero-copy reader for a Cap'n Proto struct.

    Reading a field is just:
      1. Compute byte offset = struct_start + slot * type_size
      2. Read the bytes at that offset

    No parsing.  No allocation (except Python object wrapping).
    No deserialization step.  The buffer IS the data.
    """

    __slots__ = ("_buf", "_data_start", "_data_words", "_ptr_start", "_ptr_words")

    def __init__(self, buf: bytes | bytearray | memoryview,
                 data_start: int, data_words: int, pointer_words: int):
        self._buf = buf
        self._data_start = data_start
        self._data_words = data_words
        self._ptr_start = data_start + data_words * WORD_SIZE
        self._ptr_words = pointer_words

    def read_int32(self, slot: int) -> int:
        """Read a 32-bit int from data slot.
        One struct.unpack call.  That's it.  Zero-copy."""
        offset = self._data_start + slot * 4
        if offset + 4 > self._data_start + self._data_words * WORD_SIZE:
            return 0  # out of range = default
        return struct.unpack_from("<i", self._buf, offset)[0]

    def read_uint16(self, slot: int) -> int:
        """Read a 16-bit unsigned int from data slot."""
        offset = self._data_start + slot * 2
        if offset + 2 > self._data_start + self._data_words * WORD_SIZE:
            return 0
        return struct.unpack_from("<H", self._buf, offset)[0]

    def read_int64(self, slot: int) -> int:
        """Read a 64-bit int from data slot (word-indexed)."""
        offset = self._data_start + slot * 8
        if offset + 8 > self._data_start + self._data_words * WORD_SIZE:
            return 0
        return struct.unpack_from("<q", self._buf, offset)[0]

    def read_float64(self, slot: int) -> float:
        """Read a 64-bit float from data slot (word-indexed)."""
        offset = self._data_start + slot * 8
        if offset + 8 > self._data_start + self._data_words * WORD_SIZE:
            return 0.0
        return struct.unpack_from("<d", self._buf, offset)[0]

    def read_text(self, ptr_slot: int) -> str | None:
        """Read a text field from the pointer section.

        Steps:
          1. Read the pointer word at ptr_slot
          2. Decode as list pointer to get offset + byte count
          3. Read UTF-8 bytes at that offset (excluding NUL terminator)

        Still just pointer arithmetic.
        """
        ptr_offset = self._ptr_start + ptr_slot * WORD_SIZE
        if ptr_offset + 8 > len(self._buf):
            return None
        raw_ptr = struct.unpack_from("<Q", self._buf, ptr_offset)[0]
        if raw_ptr == 0:
            return None

        info = decode_pointer(raw_ptr)
        if info["type"] != "list":
            return None

        # Target starts at (pointer_word_position + 1 + offset_words) * WORD_SIZE
        # pointer_word_position in words = ptr_offset // WORD_SIZE
        ptr_word_pos = ptr_offset // WORD_SIZE
        target_byte_start = (ptr_word_pos + 1 + info["offset_words"]) * WORD_SIZE
        byte_count = info["element_count"]
        if byte_count > 0:
            byte_count -= 1  # exclude NUL terminator
        raw = self._buf[target_byte_start:target_byte_start + byte_count]
        if isinstance(raw, memoryview):
            raw = bytes(raw)
        return raw.decode("utf-8")

    def read_struct(self, ptr_slot: int) -> StructReader | None:
        """Read a sub-struct from the pointer section."""
        ptr_offset = self._ptr_start + ptr_slot * WORD_SIZE
        if ptr_offset + 8 > len(self._buf):
            return None
        raw_ptr = struct.unpack_from("<Q", self._buf, ptr_offset)[0]
        if raw_ptr == 0:
            return None

        info = decode_pointer(raw_ptr)
        if info["type"] != "struct":
            return None

        ptr_word_pos = ptr_offset // WORD_SIZE
        target_word = ptr_word_pos + 1 + info["offset_words"]
        target_byte = target_word * WORD_SIZE
        return StructReader(
            self._buf, target_byte,
            info["data_words"], info["pointer_words"]
        )


class CapnpReader:
    """Entry point for reading a Cap'n Proto message.

    Usage:
        reader = CapnpReader(message_bytes)
        root = reader.root()
        value = root.read_int32(0)      # just pointer math!
        text = root.read_text(0)        # follow one pointer
    """

    __slots__ = ("_buf", "_segment_start")

    def __init__(self, buf: bytes):
        self._buf = buf
        # Parse segment table
        segment_count_minus_1 = struct.unpack_from("<I", buf, 0)[0]
        # For simplicity, we only support single-segment messages
        assert segment_count_minus_1 == 0, "Only single-segment messages supported"
        _segment_size_words = struct.unpack_from("<I", buf, 4)[0]
        # Header is 8 bytes for single segment (already word-aligned)
        self._segment_start = 8

    def root(self) -> StructReader:
        """Read the root struct pointer and return a StructReader."""
        raw_ptr = struct.unpack_from("<Q", self._buf, self._segment_start)[0]
        info = decode_pointer(raw_ptr)
        assert info["type"] == "struct", f"Root pointer must be struct, got {info['type']}"

        # Root pointer is at word 0 of the segment.
        # Target is at word (0 + 1 + offset_words) relative to segment start.
        root_ptr_word = self._segment_start // WORD_SIZE
        target_word = root_ptr_word + 1 + info["offset_words"]
        target_byte = target_word * WORD_SIZE
        return StructReader(
            self._buf, target_byte,
            info["data_words"], info["pointer_words"]
        )


# ─────────────────────────────────────────────────────────────────────
# Simplified FoodDash Order -- field layout
# ─────────────────────────────────────────────────────────────────────

# Our simplified Order struct layout:
#
# Data section (4 words = 32 bytes):
#   Word 0: [platform_transaction_id: Int64]         -- 64-bit slot 0
#   Word 1: [created_at: Float64]                    -- 64-bit slot 1
#   Word 2: [tip_cents: Int32 (bytes 0-3)] [status: UInt16 (bytes 4-5)] [pad]
#   Word 3: [reserved/padding]
#
# Pointer section (3 words = 24 bytes):
#   Ptr 0: id (Text)
#   Ptr 1: restaurant_id (Text)
#   Ptr 2: driver_id (Text)
#
# Total struct size: 4 data words + 3 pointer words = 7 words = 56 bytes

ORDER_DATA_WORDS = 4
ORDER_PTR_WORDS = 3

# Data slot indices (by type size)
SLOT_PLATFORM_TXN_ID = 0   # 64-bit slot 0 -> word 0
SLOT_CREATED_AT = 1         # 64-bit slot 1 -> word 1
SLOT_TIP_CENTS = 4          # 32-bit slot 4 -> word 2, bytes 0-3
SLOT_STATUS = 8             # 16-bit slot 8 -> word 2, bytes 0-1... actually bytes 16-17
# Let's be precise about our layout:
# 32-bit slot 4 = byte offset 16 = word 2, bytes 0-3
# 16-bit slot 10 = byte offset 20 = word 2, bytes 4-5
SLOT_STATUS_16 = 10         # 16-bit slot 10

# Pointer slot indices
PTR_ID = 0
PTR_RESTAURANT_ID = 1
PTR_DRIVER_ID = 2


def encode_order(
    order_id: str,
    restaurant_id: str,
    status: int,
    tip_cents: int,
    created_at: float,
    platform_transaction_id: int = 0,
    driver_id: str | None = None,
) -> bytes:
    """Encode a simplified Order as a Cap'n Proto message from scratch.

    This shows Cap'n Proto's key insight: "encoding" is just writing values
    at word-aligned offsets.  There's no transformation of the data -- we're
    just laying it out in memory in the Cap'n Proto format.
    """
    b = CapnpBuilder()

    # Step 1: Allocate the Order struct
    # In Cap'n Proto, we allocate the struct first, then fill in fields.
    # Children (text, sub-structs) are allocated AFTER and pointed to.
    order_offset = b.alloc_struct(ORDER_DATA_WORDS, ORDER_PTR_WORDS)

    # Step 2: Write scalar fields into the data section
    # This is just memory writes at computed offsets.  No encoding.
    b.write_int64(order_offset, SLOT_PLATFORM_TXN_ID, platform_transaction_id)
    b.write_float64(order_offset, SLOT_CREATED_AT, created_at)
    b.write_int32(order_offset, SLOT_TIP_CENTS, tip_cents)
    b.write_uint16(order_offset, SLOT_STATUS_16, status)

    # Step 3: Write text fields (allocated after the struct)
    id_text_offset = b.write_text(order_id)
    id_byte_count = len(order_id.encode("utf-8")) + 1
    b.write_text_pointer(order_offset, ORDER_DATA_WORDS, PTR_ID,
                         id_text_offset, id_byte_count)

    rest_text_offset = b.write_text(restaurant_id)
    rest_byte_count = len(restaurant_id.encode("utf-8")) + 1
    b.write_text_pointer(order_offset, ORDER_DATA_WORDS, PTR_RESTAURANT_ID,
                         rest_text_offset, rest_byte_count)

    if driver_id is not None:
        drv_text_offset = b.write_text(driver_id)
        drv_byte_count = len(driver_id.encode("utf-8")) + 1
        b.write_text_pointer(order_offset, ORDER_DATA_WORDS, PTR_DRIVER_ID,
                             drv_text_offset, drv_byte_count)

    # Step 4: Build the message with segment table and root pointer
    return b.build_message(order_offset, ORDER_DATA_WORDS, ORDER_PTR_WORDS)


def decode_order(buf: bytes) -> dict:
    """Decode ALL fields from a Cap'n Proto message.

    Note how "decoding" is just reading values at computed offsets.
    No parsing.  No intermediate representation.  The buffer IS the data.
    """
    reader = CapnpReader(buf)
    root = reader.root()
    return {
        "id": root.read_text(PTR_ID),
        "restaurant_id": root.read_text(PTR_RESTAURANT_ID),
        "status": root.read_uint16(SLOT_STATUS_16),
        "tip_cents": root.read_int32(SLOT_TIP_CENTS),
        "created_at": root.read_float64(SLOT_CREATED_AT),
        "platform_transaction_id": root.read_int64(SLOT_PLATFORM_TXN_ID),
        "driver_id": root.read_text(PTR_DRIVER_ID),
    }


def decode_order_one_field(buf: bytes) -> int:
    """Read ONLY tip_cents -- shows the zero-copy advantage.

    We touch only the root pointer + one int32 read.
    Everything else in the buffer is untouched.
    """
    reader = CapnpReader(buf)
    root = reader.root()
    return root.read_int32(SLOT_TIP_CENTS)


# ─────────────────────────────────────────────────────────────────────
# Wire format annotation
# ─────────────────────────────────────────────────────────────────────

def annotate_wire_bytes(buf: bytes) -> None:
    """Print annotated hex dump of a Cap'n Proto message."""

    print("  Wire bytes (annotated):\n")

    # Segment table
    seg_count = struct.unpack_from("<I", buf, 0)[0] + 1
    seg_size = struct.unpack_from("<I", buf, 4)[0]
    _dump_words(buf, 0, 1, f"Segment table: {seg_count} segment(s), {seg_size} words")

    seg_start = 8

    # Root pointer
    raw_root = struct.unpack_from("<Q", buf, seg_start)[0]
    root_info = decode_pointer(raw_root)
    _dump_words(buf, seg_start, 1,
                f"Root struct pointer: offset={root_info['offset_words']}w, "
                f"data={root_info.get('data_words', '?')}w, "
                f"ptrs={root_info.get('pointer_words', '?')}w")

    # Root struct data section
    data_start = seg_start + WORD_SIZE  # after root pointer
    labels = [
        "platform_transaction_id (Int64)",
        "created_at (Float64)",
        "tip_cents (Int32) + status (UInt16) + padding",
        "reserved/padding",
    ]
    for i in range(ORDER_DATA_WORDS):
        offset = data_start + i * WORD_SIZE
        _dump_words(buf, offset, 1, f"Data[{i}]: {labels[i]}")

    # Pointer section
    ptr_start = data_start + ORDER_DATA_WORDS * WORD_SIZE
    ptr_labels = ["id (Text)", "restaurant_id (Text)", "driver_id (Text)"]
    for i in range(ORDER_PTR_WORDS):
        offset = ptr_start + i * WORD_SIZE
        raw_ptr = struct.unpack_from("<Q", buf, offset)[0]
        if raw_ptr == 0:
            desc = "NULL pointer"
        else:
            info = decode_pointer(raw_ptr)
            if info["type"] == "list":
                desc = f"List ptr: offset={info['offset_words']}w, count={info['element_count']}"
            else:
                desc = f"Struct ptr: {info}"
        _dump_words(buf, offset, 1, f"Ptr[{i}] {ptr_labels[i]}: {desc}")

    # Text content
    text_start = ptr_start + ORDER_PTR_WORDS * WORD_SIZE
    remaining_words = (len(buf) - text_start) // WORD_SIZE
    if remaining_words > 0:
        for i in range(remaining_words):
            offset = text_start + i * WORD_SIZE
            chunk = buf[offset:offset + WORD_SIZE]
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            _dump_words(buf, offset, 1, f"Text data: |{ascii_str}|")


def _dump_words(buf: bytes, offset: int, word_count: int, label: str) -> None:
    """Print word_count 8-byte words with hex and a label."""
    for i in range(word_count):
        pos = offset + i * WORD_SIZE
        chunk = buf[pos:pos + WORD_SIZE]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        prefix = f"    {pos:04x}: "
        if i == 0:
            print(f"{prefix}{hex_str:<24s}  <- {label}")
        else:
            print(f"{prefix}{hex_str}")


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  Cap'n Proto FROM SCRATCH -- The Wire Format IS the Memory Format")
    print("=" * 70)

    # -- Pointer anatomy --
    print("\n  --- Pointer Encoding Anatomy ---\n")

    example_ptr = make_struct_pointer(offset_words=2, data_words=4, pointer_words=3)
    print(f"  Struct pointer: 0x{example_ptr:016x}")
    print(f"    Binary: {example_ptr:064b}")
    print(f"    Bits  0-1  (type):     {example_ptr & 0x3} (0 = struct)")
    print(f"    Bits  2-31 (offset):   {(example_ptr >> 2) & 0x3FFFFFFF} words")
    print(f"    Bits 32-47 (data):     {(example_ptr >> 32) & 0xFFFF} words")
    print(f"    Bits 48-63 (ptrs):     {(example_ptr >> 48) & 0xFFFF} words")
    decoded = decode_pointer(example_ptr)
    print(f"    Decoded: {decoded}")

    example_list_ptr = make_list_pointer(offset_words=1, element_size=LIST_BYTE, element_count=9)
    print(f"\n  List pointer (for text 'ord00042\\0'):  0x{example_list_ptr:016x}")
    decoded_list = decode_pointer(example_list_ptr)
    print(f"    Decoded: {decoded_list}")

    # -- Encode an Order --
    print("\n  --- Encoding a Simplified Order ---\n")
    print("  'Encoding' = just writing values at word-aligned offsets.")
    print("  There is no serialization step.  The buffer IS the wire format.\n")

    buf = encode_order(
        order_id="ord00042",
        restaurant_id="rest0001",
        status=5,           # EnRoute
        tip_cents=500,
        created_at=1700000000.0,
        platform_transaction_id=9007199254740993,  # 2^53+1
        driver_id="driv0001",
    )

    print(f"  Message size: {len(buf)} bytes")
    print(f"  (Segment table: 8 bytes, segment: {len(buf) - 8} bytes)\n")

    annotate_wire_bytes(buf)

    # -- Read ALL fields --
    print("\n  --- Reading ALL fields (zero-copy pointer arithmetic) ---\n")
    all_fields = decode_order(buf)
    for k, v in all_fields.items():
        print(f"    {k}: {v!r}")

    # -- Verify roundtrip --
    print("\n  --- Roundtrip Verification ---\n")
    assert all_fields["id"] == "ord00042"
    assert all_fields["restaurant_id"] == "rest0001"
    assert all_fields["status"] == 5
    assert all_fields["tip_cents"] == 500
    assert all_fields["created_at"] == 1700000000.0
    assert all_fields["platform_transaction_id"] == 9007199254740993
    assert all_fields["driver_id"] == "driv0001"
    print("    All fields roundtrip correctly!")

    # -- Read ONE field (zero-copy advantage) --
    print("\n  --- Selective Read: tip_cents only ---\n")
    tip = decode_order_one_field(buf)
    print(f"    tip_cents = {tip}")
    print("    (Only touched: segment table + root pointer + 4 bytes of data section)")
    print("    (Everything else in the buffer was never read)")

    # -- Timing comparison --
    print("\n  --- Timing: 1 field vs all fields ---\n")
    iterations = 100_000

    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order_one_field(buf)
    one_ns = time.perf_counter_ns() - start

    start = time.perf_counter_ns()
    for _ in range(iterations):
        decode_order(buf)
    all_ns = time.perf_counter_ns() - start

    print(f"    Read 1 field:    {one_ns / iterations:>8.1f} ns/op")
    print(f"    Read all fields: {all_ns / iterations:>8.1f} ns/op")
    if one_ns > 0:
        print(f"    Speedup:         {all_ns / one_ns:.2f}x faster")

    # -- Comparison with FlatBuffers --
    print("\n  --- Cap'n Proto vs FlatBuffers (conceptual) ---\n")
    print("    Both are zero-copy, but different approaches:\n")
    print("    FlatBuffers                     Cap'n Proto")
    print("    ──────────────────────────────── ────────────────────────────────────")
    print("    Build back-to-front             Build front-to-back")
    print("    VTable for field lookup          Fixed struct layout (data+ptr sections)")
    print("    uint32 relative offsets          64-bit typed pointers")
    print("    4-byte alignment                 8-byte (word) alignment")
    print("    Smaller wire size (less padding) Larger wire size (more padding)")
    print("    No built-in RPC                  Built-in RPC with promise pipelining")
    print("    Field lookup: 2 indirections     Field lookup: 1 computation")
    print()


if __name__ == "__main__":
    main()
