# Exercises: Foundations (Ch00) + CSV (Ch01)

---

## Exercise 1 [Beginner] -- Byte Order Detective

You receive these 4 bytes from a network socket: `00 00 04 D2`

1. What integer do they represent if interpreted as **big-endian** uint32?
2. What integer do they represent if interpreted as **little-endian** uint32?
3. Write a Python one-liner using `struct.unpack` for each.

<details><summary>Solution</summary>

1. Big-endian: `0x000004D2` = **1234**
2. Little-endian: `0xD2040000` = **3,523,215,360**
3. ```python
   import struct
   struct.unpack(">I", b"\x00\x00\x04\xd2")[0]   # 1234
   struct.unpack("<I", b"\x00\x00\x04\xd2")[0]   # 3523215360
   ```

The first byte on the wire is always the leftmost. Big-endian puts the **most significant byte first** (network byte order). Little-endian puts the **least significant byte first** (x86 native order).

</details>

---

## Exercise 2 [Beginner] -- struct.pack Scavenger Hunt

Using `struct.pack`, produce **exactly** these bytes:

1. `\x01\x00` (2 bytes)
2. `\x00\x00\x00\x2a` (4 bytes)
3. `\xff\xff\xff\xff\xff\xff\xff\xff` (8 bytes)

For each, state the format string and the Python value.

<details><summary>Solution</summary>

```python
import struct

# 1. Little-endian unsigned short, value 1
struct.pack("<H", 1)           # b'\x01\x00'

# 2. Big-endian unsigned int, value 42
struct.pack(">I", 42)          # b'\x00\x00\x00\x2a'

# 3. Signed int64, value -1 (all bits set in two's complement)
struct.pack("<q", -1)          # b'\xff\xff\xff\xff\xff\xff\xff\xff'
```

Key insight for (3): -1 in two's complement is all 1-bits regardless of width or endianness. This is why MsgPack/Protobuf use zigzag encoding for signed integers -- naive two's complement makes small negatives into large unsigned values.

</details>

---

## Exercise 3 [Beginner] -- IEEE 754 Precision Trap

```python
import struct
val = 0.1 + 0.2
packed = struct.pack("<d", val)
unpacked = struct.unpack("<d", packed)[0]
```

1. Is `unpacked == 0.3`?
2. Is `unpacked == val`?
3. How many bytes does a double occupy on the wire?

<details><summary>Solution</summary>

1. **No.** `0.1 + 0.2` is `0.30000000000000004` in IEEE 754 double precision. `0.3` is a different bit pattern (`0.2999999999999999888...`).
2. **Yes.** The pack/unpack roundtrip preserves the exact bits.
3. **8 bytes** (64 bits). Every double is exactly 8 bytes on the wire in binary formats, unlike JSON where `0.30000000000000004` takes 20 characters.

This is why FoodDash stores prices in **integer cents** (not float dollars) -- exact representation matters for money.

</details>

---

## Exercise 4 [Intermediate] -- CSV Injection: Break the Parser

Write a single CSV row (one line, 3 fields: name, city, notes) that would produce **incorrect results** with this naive parser:

```python
fields = line.split(",")
```

Come up with at least 3 different ways to break it.

<details><summary>Solution</summary>

**Way 1 -- Comma in a quoted field:**
```
"Smith, Jr.",London,Regular customer
```
Naive split produces 4 fields: `['"Smith', ' Jr."', 'London', 'Regular customer']`

**Way 2 -- Newline inside quotes:**
```
Alice,"New
York",Notes
```
Naive line-by-line reading splits this into two incomplete lines.

**Way 3 -- Escaped quotes (doubled):**
```
Bob,Paris,"He said ""hello"" to me"
```
Naive split gets 3 fields but the third field contains literal `""` instead of `"`.

**Way 4 -- Leading/trailing whitespace ambiguity:**
```
 Alice , London , notes
```
Some parsers trim, some don't. The RFC says spaces are part of the field.

**Way 5 -- Empty quoted field vs empty unquoted field:**
```
"",London,notes
```
Is the first field an empty string or a missing value? CSV doesn't distinguish.

Always use `csv.reader()` in Python, never `split(",")`.

</details>

---

## Exercise 5 [Intermediate] -- Encoding Detection Challenge

You receive a file and need to determine its encoding. The first 20 bytes are:

```
ef bb bf 48 65 6c 6c 6f 2c 20 77 6f 72 6c 64
```

1. What encoding is this file in?
2. What are the first 3 bytes called?
3. What does the text say?
4. Should you include these 3 bytes when sending data between microservices? Why or why not?

<details><summary>Solution</summary>

1. **UTF-8** (with BOM).
2. The first 3 bytes (`EF BB BF`) are the **UTF-8 Byte Order Mark (BOM)**.
3. The text is `Hello, world` (the remaining bytes are ASCII, which is valid UTF-8).
4. **No.** The BOM is unnecessary for UTF-8 (which has no byte-order ambiguity) and causes problems:
   - JSON parsers may reject it (RFC 8259 says JSON text "SHOULD NOT" begin with a BOM)
   - It adds 3 bytes per message -- at 1M messages/second, that's 3 MB/s wasted
   - Many tools misinterpret it as visible characters

   BOMs made sense for UTF-16 (which has genuine byte-order ambiguity), but not for UTF-8.

</details>

---

## Exercise 6 [Intermediate] -- Byte Count Arithmetic

A FoodDash Order has a customer name field containing `"Tanaka Taro"` in Japanese: `"田中太郎"`.

1. How many **characters** is this string?
2. How many **bytes** in UTF-8?
3. How many **bytes** in UTF-16LE?
4. How many **bytes** in UTF-32?
5. If this field appears 1 million times per second, what's the bandwidth difference between UTF-8 and UTF-32?

<details><summary>Solution</summary>

1. **4 characters** (4 CJK ideographs)
2. **12 bytes** in UTF-8 (each CJK character is 3 bytes: `E7 94 B0 E4 B8 AD E5 A4 AA E9 83 8E`)
3. **8 bytes** in UTF-16LE (each CJK character is 2 bytes, all in the BMP)
4. **16 bytes** in UTF-32 (each character is always 4 bytes)
5. UTF-8: 12 bytes x 1M/s = **12 MB/s**; UTF-32: 16 bytes x 1M/s = **16 MB/s**; difference = **4 MB/s** = 345 GB/day. For a mostly-ASCII system, UTF-8 wins bigger (ASCII chars are 1 byte vs 4).

This is why every modern serialization format uses UTF-8 for strings.

</details>

---

## Exercise 7 [Intermediate] -- CSV Schema Evolution Problem

Your service currently writes this CSV:

```
order_id,customer_name,total_cents
ord001,Alice,4599
```

Product wants to add a `tip_cents` column. You have 50 downstream consumers.

1. What happens if you add the column at the end?
2. What happens if you add it between `customer_name` and `total_cents`?
3. How does this compare to adding a field in JSON? In Protobuf?
4. What does this tell you about CSV's suitability for evolving schemas?

<details><summary>Solution</summary>

1. **Adding at the end** works for consumers that parse by index (`fields[0]`, `fields[1]`, `fields[2]`) -- they ignore the extra column. But consumers that expect exactly 3 columns will break.
2. **Adding in the middle** breaks ALL consumers that parse by index. `fields[2]` now returns `tip_cents` instead of `total_cents`.
3. **JSON**: Adding a field is invisible to consumers that don't look for it. No breakage. **Protobuf**: New field number is silently skipped by old decoders. No breakage.
4. CSV has **positional coupling** -- consumers depend on column positions. This makes schema evolution dangerous. JSON and Protobuf use **named/numbered fields**, which decouple producers from consumers.

This is why CSV is acceptable for batch data exports but not for inter-service communication in a system that evolves.

</details>

---

## Exercise 8 [Advanced] -- Build a Minimal struct-Based Wire Format

Design and implement a minimal binary wire format for this message using only `struct.pack`:

```python
message = {
    "order_id": "ord001",       # variable-length string
    "total_cents": 4599,        # uint32
    "is_paid": True,            # boolean
}
```

Requirements:
- No external libraries
- Must handle variable-length strings
- Must be decodable without knowing the field names (self-describing)
- Write both `encode(msg)` and `decode(data)` functions

<details><summary>Solution</summary>

```python
import struct

def encode(msg: dict) -> bytes:
    """Length-prefixed TLV (Type-Length-Value) encoding."""
    parts = []
    for key, value in msg.items():
        # Encode key as length-prefixed UTF-8
        key_bytes = key.encode("utf-8")
        parts.append(struct.pack("<H", len(key_bytes)))
        parts.append(key_bytes)

        if isinstance(value, bool):
            parts.append(b"\x01")  # type tag: bool
            parts.append(struct.pack("<B", int(value)))
        elif isinstance(value, int):
            parts.append(b"\x02")  # type tag: int
            parts.append(struct.pack("<I", value))
        elif isinstance(value, str):
            parts.append(b"\x03")  # type tag: string
            val_bytes = value.encode("utf-8")
            parts.append(struct.pack("<I", len(val_bytes)))
            parts.append(val_bytes)

    return b"".join(parts)


def decode(data: bytes) -> dict:
    result = {}
    offset = 0
    while offset < len(data):
        key_len = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        key = data[offset:offset + key_len].decode("utf-8")
        offset += key_len

        type_tag = data[offset]
        offset += 1

        if type_tag == 1:  # bool
            result[key] = bool(data[offset])
            offset += 1
        elif type_tag == 2:  # int
            result[key] = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        elif type_tag == 3:  # string
            val_len = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            result[key] = data[offset:offset + val_len].decode("utf-8")
            offset += val_len

    return result
```

Key insight: you just reinvented a simplified version of what MsgPack/CBOR do. The type tag is necessary to make the format self-describing. Without it (like Avro), you need an external schema.

</details>

---

## Exercise 9 [Advanced] -- Bit Manipulation: Pack 8 Booleans into 1 Byte

FoodDash menu items have 8 boolean dietary flags. Design a scheme to pack all 8 into a single byte, and implement encode/decode.

```python
flags = {
    "is_vegetarian": True,
    "is_vegan": False,
    "is_gluten_free": True,
    "is_dairy_free": False,
    "is_nut_free": True,
    "is_halal": False,
    "is_kosher": False,
    "is_organic": True,
}
```

<details><summary>Solution</summary>

```python
FLAG_NAMES = [
    "is_vegetarian", "is_vegan", "is_gluten_free", "is_dairy_free",
    "is_nut_free", "is_halal", "is_kosher", "is_organic",
]

def encode_flags(flags: dict) -> int:
    """Pack 8 booleans into a single byte."""
    byte = 0
    for i, name in enumerate(FLAG_NAMES):
        if flags.get(name, False):
            byte |= (1 << i)
    return byte

def decode_flags(byte: int) -> dict:
    """Unpack a byte into 8 named booleans."""
    return {name: bool(byte & (1 << i)) for i, name in enumerate(FLAG_NAMES)}

# Test:
flags = {"is_vegetarian": True, "is_vegan": False, "is_gluten_free": True,
         "is_dairy_free": False, "is_nut_free": True, "is_halal": False,
         "is_kosher": False, "is_organic": True}

packed = encode_flags(flags)  # 0b10010101 = 0x95 = 149
assert packed == 0b10010101
assert decode_flags(packed) == flags
```

At 1M messages/second, this saves 7 bytes per message vs sending 8 separate booleans (7 MB/s saved). This is exactly what FlatBuffers does with boolean fields, and it's related to how Cap'n Proto packs booleans at the bit level within data words.

</details>

---

## Exercise 10 [Advanced] -- CSV vs Binary: Throughput Calculation

A FoodDash service sends 1 million order update messages per second. Each message has 15 fields. Calculate:

1. The overhead of CSV field separators (commas + newline) per message
2. The overhead of quoting every string field (assume 10 of 15 fields are strings)
3. The overhead of representing the integer `1700000000` as text vs a 4-byte uint32
4. Total wasted bytes/second for CSV compared to a binary format

<details><summary>Solution</summary>

1. **Field separators**: 14 commas + 1 newline = **15 bytes** per message
2. **Quoting**: 10 string fields x 2 quote characters each = **20 bytes** per message
3. **Integer representation**: `1700000000` as text = 10 bytes; as uint32 = 4 bytes. **6 bytes** wasted per integer field. With 5 integer fields: **30 bytes** wasted.
4. **Total overhead per message**: 15 + 20 + 30 = **65 bytes**
   - At 1M msg/s: **65 MB/s** = **5.6 TB/day** of pure overhead
   - At $0.05/GB for cloud networking, that's **$280/day** = **$102K/year**

This is a simplified calculation (real-world savings are larger because CSV also repeats field names in headers, has no compression-friendly patterns, etc.), but it illustrates why binary formats matter at scale.

</details>
