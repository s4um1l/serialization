# Exercises: Protobuf (Ch04) + FlatBuffers (Ch05)

---

## Exercise 1 [Beginner] -- Varint Encoding by Hand

Encode the integer **300** as an LEB128 varint (the encoding Protobuf uses).

Show your work step by step:
1. Convert 300 to binary.
2. Split into 7-bit groups (least significant first).
3. Set the continuation bit (MSB) on all but the last group.
4. Write the final bytes in hex.

<details><summary>Solution</summary>

1. `300` in binary: `100101100` (9 bits)
2. Split into 7-bit groups (LSB first):
   - Group 1 (bits 0-6): `0101100` = 0x2C
   - Group 2 (bits 7-8): `0000010` = 0x02
3. Set continuation bits:
   - Group 1: `1 0101100` = 0xAC (continuation bit = 1, more bytes follow)
   - Group 2: `0 0000010` = 0x02 (continuation bit = 0, last byte)
4. Final bytes: **`0xAC 0x02`**

Verification: `(0xAC & 0x7F) | ((0x02 & 0x7F) << 7) = 44 | (2 << 7) = 44 + 256 = 300`

</details>

---

## Exercise 2 [Beginner] -- Protobuf Tag Decoding

You see byte `0x1A` at the start of a protobuf field. What does it mean?

1. Convert `0x1A` to decimal.
2. Extract the wire type (bits 0-2).
3. Extract the field number (bits 3+).
4. What kind of value follows this tag?

<details><summary>Solution</summary>

1. `0x1A` = 26 decimal
2. Wire type: `26 & 0x07` = `26 & 7` = **2** (LENGTH_DELIMITED)
3. Field number: `26 >> 3` = **3**
4. A **length-delimited** value follows: the next bytes are a varint length, then that many bytes of data. This could be a string, bytes, embedded message, or packed repeated field. The proto schema tells you which.

In the FoodDash Order schema, field 3 is `customer` (an embedded message). So after this tag, we'll find a varint with the byte length of the Customer message, followed by the Customer's protobuf bytes.

</details>

---

## Exercise 3 [Beginner] -- Zigzag Encoding

Protobuf uses zigzag encoding for `sint32`/`sint64` fields.

Map each value to its zigzag-encoded unsigned equivalent:
1. `0`
2. `-1`
3. `1`
4. `-2`
5. `2147483647` (INT32_MAX)
6. `-2147483648` (INT32_MIN)

Formula: `zigzag(n) = (n << 1) ^ (n >> 63)`

<details><summary>Solution</summary>

| Signed | Zigzag | Varint bytes |
|--------|--------|-------------|
| 0 | 0 | 1 byte (0x00) |
| -1 | 1 | 1 byte (0x01) |
| 1 | 2 | 1 byte (0x02) |
| -2 | 3 | 1 byte (0x03) |
| 2147483647 | 4294967294 | 5 bytes |
| -2147483648 | 4294967295 | 5 bytes |

Without zigzag, `-1` would be `0xFFFFFFFFFFFFFFFF` in two's complement, requiring a **10-byte** varint. With zigzag, it's just `1`, a **1-byte** varint.

This is why Protobuf has both `int32` (no zigzag, good for always-positive values) and `sint32` (zigzag, good for values that can be negative).

</details>

---

## Exercise 4 [Intermediate] -- Proto Design Review

Find at least 4 problems with this `.proto` definition:

```protobuf
syntax = "proto3";

message Order {
  string id = 0;
  int32 total_cents = 1;
  string customer_name = 2;
  float price = 3;
  string status = 16;
  repeated string items = 5;
  map<int32, string> metadata = 6;
  int64 created_at = 7;
  string large_integer_id = 8;
}
```

<details><summary>Solution</summary>

1. **Field number 0 is invalid.** Protobuf field numbers must be 1 or higher. Field 0 is reserved.

2. **Field number 16 wastes bytes.** Field numbers 1-15 encode as a single-byte tag. `status` (likely the most frequently accessed field) is at field 16, which requires a 2-byte tag. Move it to a low field number.

3. **`float price` for money is dangerous.** IEEE 754 single-precision float has only ~7 decimal digits of precision. Use `int32 price_cents` or `int64 price_micros` for monetary values.

4. **`string status` for an enum.** Status values like "delivered" are better represented as a protobuf `enum`, which encodes as a single varint instead of a length-prefixed string. Saves bytes and provides type safety.

5. **`map<int32, string>` for metadata.** Integer keys are unusual for metadata. If these are string key-value pairs, use `map<string, string>`.

6. **Missing field number 4.** The field numbers skip from 3 to 5. While not an error, it suggests a field was deleted. You should add a `reserved 4;` declaration to prevent accidental reuse.

7. **`string large_integer_id` is a workaround.** If this is a 64-bit integer that needs to survive JSON round-trips, consider using `int64` in protobuf and only converting to string at the JSON boundary.

</details>

---

## Exercise 5 [Intermediate] -- Protobuf Default Value Trap

In proto3, what gets sent on the wire for each of these field values?

```protobuf
message Example {
  int32 count = 1;       // value: 0
  string name = 2;       // value: ""
  bool active = 3;       // value: false
  float score = 4;       // value: 0.0
  repeated int32 ids = 5; // value: []
}
```

<details><summary>Solution</summary>

**None of them are sent on the wire.** In proto3, default values (0, "", false, 0.0, empty list) are not serialized. The entire message encodes as **0 bytes**.

This has two important implications:

1. **You cannot distinguish "field was set to 0" from "field was not set."** This is a major design difference from proto2, which had explicit `has_field()` semantics. In proto3, if you need to distinguish "absent" from "zero", use wrapper types like `google.protobuf.Int32Value` or optional field declarations.

2. **Default values are "free."** A message with mostly-default fields is tiny. This is why protobuf excels at sparse updates: sending `{status: 7}` on a 15-field message only encodes 2 bytes (tag + varint).

</details>

---

## Exercise 6 [Intermediate] -- FlatBuffers Buffer Size Calculation

Given this FlatBuffers schema (simplified):

```
table Order {
  id: string;           // offset field
  tip_cents: int;       // 4 bytes inline
  created_at: double;   // 8 bytes inline
  status: byte;         // 1 byte inline
}
```

Calculate the minimum buffer size, accounting for:
1. Root offset (uint32)
2. VTable: vtable_size (uint16) + table_size (uint16) + 4 field entries (uint16 each)
3. Table: soffset32 + inline data (with alignment padding)
4. String "ord00042": uint32 length + 8 chars + null terminator + padding

<details><summary>Solution</summary>

**VTable** (lowest addresses after root offset):
- vtable_size: 2 bytes
- table_data_size: 2 bytes
- 4 field entries: 4 x 2 = 8 bytes
- VTable total: **12 bytes**

**Table data** (after vtable):
- soffset32 (to vtable): 4 bytes
- created_at (double, 8-byte aligned): 8 bytes
- tip_cents (int32): 4 bytes
- status (byte): 1 byte
- Padding to 4-byte alignment: 3 bytes
- String offset (uint32): 4 bytes
- Table total: **24 bytes**

**String "ord00042"**:
- uint32 length: 4 bytes
- 8 UTF-8 characters: 8 bytes
- Null terminator: 1 byte
- Padding to 4-byte alignment: 3 bytes
- String total: **16 bytes**

**Root offset**: 4 bytes

**Grand total**: 4 + 12 + 24 + 16 = **56 bytes**

For comparison, JSON `{"id":"ord00042","tip_cents":500,"created_at":1700000000.0,"status":5}` is ~70 bytes. FlatBuffers is smaller AND supports zero-copy reads.

</details>

---

## Exercise 7 [Intermediate] -- FlatBuffers Zero-Copy Advantage

A FoodDash routing service receives an Order message and only needs the `restaurant_id` field to make a routing decision.

1. With JSON, how many bytes must be parsed to extract `restaurant_id`?
2. With Protobuf, how many bytes must be parsed?
3. With FlatBuffers, how many bytes must be read?
4. At 1M messages/second, estimate the CPU time saved by FlatBuffers.

<details><summary>Solution</summary>

1. **JSON**: You must parse the **entire message** to find the `restaurant_id` key. For a typical order (~800 bytes), you parse all 800 bytes, build all Python objects, then extract one field. **~800 bytes parsed.**

2. **Protobuf**: You must scan field tags sequentially until you find `restaurant_id` (field 4). If it's near the beginning, you might parse ~50-100 bytes. But the decoder typically allocates the full message object. **~50-800 bytes parsed, full allocation.**

3. **FlatBuffers**: Read the root offset (4 bytes) -> follow to table -> read soffset32 (4 bytes) -> vtable lookup for field index (2 bytes) -> follow string offset (4 bytes) -> read string length + data. **~22 bytes read.** No allocation except the Python string.

4. **Savings estimate**: JSON parsing ~800 bytes takes ~10-20 us. FlatBuffers reading one field takes ~0.1-0.5 us. Savings: ~15 us/message x 1M/s = **~15 seconds of CPU per second** -- you'd need 15+ cores just for JSON parsing. FlatBuffers needs a fraction of one core.

</details>

---

## Exercise 8 [Advanced] -- Protobuf Wire Format Dissection

Given this protobuf message hex dump, decode every field:

```
0a 08 6f 72 64 30 30 30 30 32 10 95 9a ef 3a 1a 15 0a 08 63 75 73 74 30 30 30 31 12 05 41 6c 69 63 65
```

Show the field number, wire type, and decoded value for each field.

<details><summary>Solution</summary>

```
0a -> tag: field 1, wire type 2 (length-delimited)
08 -> length: 8 bytes
6f 72 64 30 30 30 30 32 -> "ord00002"

10 -> tag: field 2, wire type 0 (varint)
95 9a ef 3a -> varint: 0x95 & 0x7F = 0x15
                       0x9a & 0x7F = 0x1A << 7
                       0xef & 0x7F = 0x6F << 14
                       0x3a & 0x7F = 0x3A << 21
             = 21 | (26 << 7) | (111 << 14) | (58 << 21)
             = 21 + 3328 + 1818624 + 121634816
             = 123456789

1a -> tag: field 3, wire type 2 (length-delimited)
15 -> length: 21 bytes (embedded Customer message)
  0a -> tag: field 1, wire type 2 (length-delimited)
  08 -> length: 8
  63 75 73 74 30 30 30 31 -> "cust0001"
  12 -> tag: field 2, wire type 2 (length-delimited)
  05 -> length: 5
  41 6c 69 63 65 -> "Alice"
```

**Decoded**: Order with id="ord00002", platform_transaction_id=123456789, customer={id="cust0001", name="Alice"}

</details>

---

## Exercise 9 [Advanced] -- FlatBuffers vs Protobuf: Table Evolution

Both Protobuf and FlatBuffers support schema evolution, but in different ways.

For each scenario, explain what happens in both formats:

1. Adding a new field at the end
2. Removing a field
3. Renaming a field
4. Changing a field's type from int32 to int64

<details><summary>Solution</summary>

| Scenario | Protobuf | FlatBuffers |
|----------|----------|-------------|
| **Add field** | Safe. Old decoder skips unknown field numbers. New decoder uses default for missing fields. | Safe. Old vtable is shorter, so new field's vtable slot doesn't exist; reader returns default. |
| **Remove field** | Safe if you `reserved` the field number. Old data with the field is silently skipped. Never reuse the field number. | Safe if you don't reuse the field index. Old data still has the vtable entry; new reader ignores it. |
| **Rename field** | Safe. Field numbers are the wire identity, not names. Renaming in `.proto` is transparent. | Safe. Field indices are the wire identity. The name is only in the schema file. |
| **Change int32 to int64** | **DANGEROUS.** Wire type changes from VARINT(0) to VARINT(0) (same wire type), but the decoder must know the width. If an old int32 value is read as int64, it works. But int64 values > 2^31 read as int32 will overflow. | **DANGEROUS.** The vtable entry now points to 4 bytes instead of 8. Old buffers have 4 bytes of data but the new reader expects 8, reading garbage. |

The key difference: Protobuf is **parse-and-reconstruct** (field numbers + wire types make it self-describing enough), while FlatBuffers is **memory-layout-dependent** (the vtable offsets must match the expected sizes).

</details>

---

## Exercise 10 [Advanced] -- Implement Packed Repeated Fields

Protobuf's "packed" encoding stores repeated numeric fields as a single length-delimited blob instead of repeating the tag.

Implement `encode_packed_varint_field()` and `decode_packed_varint_field()`:

```python
def encode_packed_varint_field(field_number: int, values: list[int]) -> bytes:
    """Encode a packed repeated varint field."""
    ...

def decode_packed_varint_field(data: bytes) -> list[int]:
    """Decode the values from a packed varint blob."""
    ...
```

Test with values `[1, 2, 300, 0, 127, 128]`.

<details><summary>Solution</summary>

```python
from chapters.ch04_protobuf.proto_from_scratch import (
    encode_tag, encode_varint, decode_varint,
    WIRE_LENGTH_DELIMITED,
)

def encode_packed_varint_field(field_number: int, values: list[int]) -> bytes:
    """Packed encoding: tag + length + varint1 + varint2 + ..."""
    if not values:
        return b""
    # Encode all varints
    payload = b"".join(encode_varint(v) for v in values)
    # One tag + one length prefix for all values
    return (
        encode_tag(field_number, WIRE_LENGTH_DELIMITED)
        + encode_varint(len(payload))
        + payload
    )

def decode_packed_varint_field(data: bytes) -> list[int]:
    """Decode packed varints from a length-delimited blob."""
    values = []
    offset = 0
    while offset < len(data):
        val, offset = decode_varint(data, offset)
        values.append(val)
    return values

# Test:
values = [1, 2, 300, 0, 127, 128]
encoded = encode_packed_varint_field(5, values)
# Skip tag + length to get the packed data
_, off = decode_varint(encoded, 0)  # skip tag
length, off = decode_varint(encoded, off)
packed_data = encoded[off:off + length]
decoded = decode_packed_varint_field(packed_data)
assert decoded == values

# Size comparison:
# Non-packed: 6 values * (1 tag + 1-2 value) = ~12 bytes
# Packed: 1 tag + 1 length + 8 value bytes = ~10 bytes
# The savings grow with more values.
```

Packed encoding saves one tag byte per repeated element. For an array of 100 integers, that's ~100 bytes saved. Proto3 uses packed by default for repeated numeric fields.

</details>

---

## Exercise 11 [Advanced] -- FlatBuffers: Implement a Vector

FlatBuffers vectors are stored as: `[uint32 element_count] [element_0] [element_1] ...`

Extend the `FlatBufferBuilder` to support `create_int32_vector`:

```python
def create_int32_vector(self, values: list[int]) -> int:
    """Write a vector of int32 values and return its offset."""
    ...
```

Then implement a reader that accesses elements by index without copying the entire vector.

<details><summary>Solution</summary>

```python
import struct

class FlatBufferBuilder:
    # ... existing methods ...

    def create_int32_vector(self, values: list[int]) -> int:
        """Write a vector of int32 values back-to-front.

        Layout: [uint32 count] [int32 elem0] [int32 elem1] ...
        Written back-to-front: elements first, then count.
        """
        # Write elements in reverse order (back-to-front building)
        for val in reversed(values):
            self._place_int32(val)

        # Write element count
        self._place_uint32(len(values))

        return self._current_offset()


class VectorReader:
    """Zero-copy reader for a FlatBuffer int32 vector."""

    def __init__(self, buf, vector_pos):
        self._buf = buf
        self._pos = vector_pos
        self._count = struct.unpack_from("<I", buf, vector_pos)[0]

    def __len__(self):
        return self._count

    def __getitem__(self, index):
        """Read element at index -- just one struct.unpack call."""
        if index < 0 or index >= self._count:
            raise IndexError(f"Index {index} out of range [0, {self._count})")
        offset = self._pos + 4 + index * 4
        return struct.unpack_from("<i", self._buf, offset)[0]
```

The key insight: `vector[i]` is a single pointer-arithmetic computation + 4-byte read. No iteration, no allocation, no copying of the other N-1 elements.

</details>
