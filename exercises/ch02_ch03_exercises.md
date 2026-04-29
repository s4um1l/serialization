# Exercises: JSON (Ch02) + MsgPack (Ch03)

---

## Exercise 1 [Beginner] -- JSON Precision Trap

JavaScript's `Number` type is IEEE 754 double-precision (53 bits of mantissa).

1. What happens to `9007199254740993` (which is 2^53 + 1) when parsed by JavaScript's `JSON.parse()`?
2. What value does JavaScript produce?
3. How does FoodDash's `platform_transaction_id` field expose this bug?
4. Name two strategies to safely transmit 64-bit integers over JSON.

<details><summary>Solution</summary>

1. JavaScript **silently rounds** the value because IEEE 754 double can only represent integers exactly up to 2^53 (9007199254740992).
2. JavaScript produces `9007199254740992` (2^53) -- the closest representable double. The value is silently wrong by 1.
3. FoodDash sets `platform_transaction_id = 9007199254740993` in the large order. If a JavaScript frontend parses this JSON, it silently gets the wrong transaction ID, which could cause financial reconciliation failures.
4. Two strategies:
   - **Send as a string**: `"platform_transaction_id": "9007199254740993"` -- all characters are preserved
   - **Use a binary format**: MsgPack, Protobuf, etc. store 64-bit integers natively with full precision

</details>

---

## Exercise 2 [Beginner] -- JSON Type System Limitations

For each Python value, state whether JSON can represent it exactly. If not, explain what gets lost:

1. `None`
2. `True`
3. `42`
4. `3.14`
5. `b"\x89PNG\r\n\x1a\n"` (bytes)
6. `datetime(2024, 1, 15, 10, 30)`
7. `{1: "one", 2: "two"}` (integer keys)
8. `float("inf")`
9. `(1, 2, 3)` (tuple)
10. `OrderStatus.PLACED` (enum)

<details><summary>Solution</summary>

| # | Value | JSON? | What gets lost |
|---|-------|-------|----------------|
| 1 | `None` | Yes | `null` |
| 2 | `True` | Yes | `true` |
| 3 | `42` | Yes | Number (but JS may lose precision for large ints) |
| 4 | `3.14` | Yes | Number (but text representation may differ) |
| 5 | `b"\x89PNG..."` | **No** | Must base64-encode to string, adding ~33% overhead |
| 6 | `datetime(...)` | **No** | Must convert to ISO string or Unix timestamp |
| 7 | `{1: "one"}` | **No** | Keys must be strings: `{"1": "one"}` |
| 8 | `float("inf")` | **No** | JSON has no infinity/NaN representation |
| 9 | `(1, 2, 3)` | **No** | Becomes array `[1, 2, 3]`, tuple type is lost |
| 10 | Enum | **No** | Must serialize as string value `"placed"` |

JSON supports exactly 6 types: null, boolean, number, string, array, object. Everything else requires a convention.

</details>

---

## Exercise 3 [Intermediate] -- Base64 Overhead Calculation

FoodDash menu items include a `thumbnail_png` field (72 bytes of PNG data).

1. How many bytes does the base64 encoding of 72 bytes produce?
2. What is the overhead percentage?
3. If you have 100 menu items per restaurant and 10,000 restaurants, how much extra storage does base64 cost?
4. How does MsgPack handle this same field?

<details><summary>Solution</summary>

1. Base64 encodes 3 bytes as 4 characters. `ceil(72 / 3) * 4 = 96 bytes`. Plus 2 quote characters in JSON = **98 bytes** total.
2. Overhead: `(96 - 72) / 72 = 33.3%` for base64 encoding alone. Including JSON quotes: `(98 - 72) / 72 = 36.1%`.
3. Extra storage: `100 items * 10,000 restaurants * 24 bytes overhead = 24 MB` of pure base64 overhead. (Plus the quotes: `100 * 10,000 * 26 = 26 MB`.)
4. MsgPack stores bytes natively using a `bin` type: just a length prefix + raw bytes. The 72-byte PNG becomes **74 bytes** in MsgPack (2-byte bin8 header + 72 raw bytes). That's **24 bytes less** than JSON's base64 representation per thumbnail.

At 1M messages/second with binary payloads, base64 overhead in JSON adds up to significant bandwidth and CPU cost (encoding + decoding base64).

</details>

---

## Exercise 4 [Intermediate] -- MsgPack Type Byte Decoding

Decode this MsgPack hex sequence by hand:

```
93 a5 48 65 6c 6c 6f cd 01 f4 c3
```

Identify each type byte and the value it represents.

<details><summary>Solution</summary>

```
93              -> fixarray of length 3 (0x90 | 0x03)
a5              -> fixstr of length 5 (0xa0 | 0x05)
48 65 6c 6c 6f  -> "Hello" (UTF-8 bytes)
cd              -> uint16 follows (2 bytes)
01 f4           -> 500 (big-endian uint16)
c3              -> true (boolean)
```

The decoded value is: `["Hello", 500, True]`

MsgPack type byte ranges:
- `0x00-0x7f`: positive fixint (0-127)
- `0x80-0x8f`: fixmap (length 0-15)
- `0x90-0x9f`: fixarray (length 0-15)
- `0xa0-0xbf`: fixstr (length 0-31)
- `0xc0`: nil
- `0xc2`: false, `0xc3`: true
- `0xcc-0xcf`: uint8/16/32/64
- `0xd0-0xd3`: int8/16/32/64
- `0xe0-0xff`: negative fixint (-32 to -1)

</details>

---

## Exercise 5 [Intermediate] -- Build a Minimal JSON Parser

Implement a function that parses a JSON **string literal** (not a full JSON parser):

```python
def parse_json_string(data: str, pos: int) -> tuple[str, int]:
    """Parse a JSON string starting at data[pos] (which is a quote).
    Return (parsed_string, position_after_closing_quote).
    Must handle: \\", \\n, \\t, \\\\, \\uXXXX
    """
```

Test cases:
- `"hello"` -> `hello`
- `"say \"hi\""` -> `say "hi"`
- `"line1\\nline2"` -> `line1\nline2`
- `"caf\\u00e9"` -> `cafe` (with accent)

<details><summary>Solution</summary>

```python
def parse_json_string(data: str, pos: int) -> tuple[str, int]:
    assert data[pos] == '"'
    pos += 1
    chars = []
    while pos < len(data):
        ch = data[pos]
        if ch == '"':
            return "".join(chars), pos + 1
        elif ch == '\\':
            pos += 1
            esc = data[pos]
            if esc == '"':   chars.append('"')
            elif esc == '\\': chars.append('\\')
            elif esc == '/':  chars.append('/')
            elif esc == 'n':  chars.append('\n')
            elif esc == 't':  chars.append('\t')
            elif esc == 'r':  chars.append('\r')
            elif esc == 'b':  chars.append('\b')
            elif esc == 'f':  chars.append('\f')
            elif esc == 'u':
                hex_str = data[pos+1:pos+5]
                chars.append(chr(int(hex_str, 16)))
                pos += 4
            pos += 1
        else:
            chars.append(ch)
            pos += 1
    raise ValueError("Unterminated string")
```

Key insight: JSON string parsing is surprisingly complex. The `\uXXXX` escape can encode surrogate pairs for characters outside the BMP, requiring two consecutive `\uXXXX` sequences. This is why even "simple" JSON parsing has subtle bugs.

</details>

---

## Exercise 6 [Intermediate] -- MsgPack vs JSON Size Comparison

Calculate the exact byte counts for encoding this Python dict in both JSON and MsgPack:

```python
data = {"status": "delivered", "tip": 500, "paid": True}
```

<details><summary>Solution</summary>

**JSON** (`json.dumps(data)`):
```
{"status": "delivered", "tip": 500, "paid": true}
```
Count: `{` + `"status"` (8) + `: ` + `"delivered"` (11) + `, ` + `"tip"` (5) + `: ` + `500` (3) + `, ` + `"paid"` (6) + `: ` + `true` (4) + `}` = **49 bytes** (may vary slightly by whitespace settings -- `json.dumps` with no indent produces `{"status": "delivered", "tip": 500, "paid": true}` = 49 bytes).

**MsgPack** (`msgpack.packb(data)`):
```
83                          -> fixmap of 3 entries (1 byte)
a6 73 74 61 74 75 73        -> "status" (7 bytes: 1 prefix + 6 chars)
a9 64 65 6c 69 76 65 72 65 64 -> "delivered" (10 bytes: 1 prefix + 9 chars)
a3 74 69 70                 -> "tip" (4 bytes: 1 prefix + 3 chars)
cd 01 f4                    -> 500 as uint16 (3 bytes)
a4 70 61 69 64              -> "paid" (5 bytes: 1 prefix + 4 chars)
c3                          -> true (1 byte)
```
Total: 1 + 7 + 10 + 4 + 3 + 5 + 1 = **31 bytes**

**Savings: 18 bytes (36.7%)** -- from eliminating colons, commas, braces, spaces, and using single-byte type prefixes instead of multi-character keywords.

</details>

---

## Exercise 7 [Intermediate] -- JSON Duplicate Key Trap

What does `json.loads('{"a": 1, "a": 2}')` return in Python? What does the JSON RFC say about this? Why is this a security concern?

<details><summary>Solution</summary>

1. Python's `json.loads` returns `{"a": 2}` -- the **last value wins**.
2. RFC 8259 says object keys **SHOULD** be unique but doesn't require it. Different implementations handle duplicates differently:
   - Python: last value wins
   - Some parsers: first value wins
   - Some parsers: reject as error
3. **Security concern**: An attacker can craft a JSON payload like:
   ```json
   {"admin": false, "admin": true}
   ```
   If a validation layer sees `"admin": false` (first wins) but the application uses `"admin": true` (last wins), the attacker bypasses authorization. This is a real class of vulnerabilities (see "JSON interoperability vulnerabilities").

MsgPack has the same issue -- the map format allows duplicate keys. Schema-based formats like Protobuf avoid this because fields are identified by number, and duplicate field numbers use well-defined merge rules.

</details>

---

## Exercise 8 [Advanced] -- MsgPack Timestamp Extension

MsgPack has a Timestamp extension type (type -1) with three formats:

- **Timestamp 32**: 4 bytes, stores seconds in uint32 (range: 0 to 2^32-1)
- **Timestamp 64**: 8 bytes, stores nanoseconds in 30 bits + seconds in 34 bits
- **Timestamp 96**: 12 bytes, stores nanoseconds in uint32 + seconds in int64

For Unix timestamp `1700000000.123456789`:

1. Can Timestamp 32 represent this? What precision is lost?
2. Encode this as Timestamp 64 by hand. Show the bit layout.
3. What is the maximum date representable by Timestamp 32? When does it overflow?

<details><summary>Solution</summary>

1. **Timestamp 32**: stores `1700000000` as uint32. It fits (< 2^32). But **all nanosecond precision is lost** -- only whole seconds. The `.123456789` is discarded.

2. **Timestamp 64** layout (8 bytes, big-endian):
   - Bits 0-29: nanoseconds adjustment = `123456789` = `0x075BCD15`
   - Bits 30-63: seconds = `1700000000` = `0x6553F100`
   ```
   nanosec (30 bits): 0x075BCD15 -> binary: 00 0111 0101 1011 1100 1101 0001 0101
   seconds (34 bits): 0x6553F100 -> binary: 01 1001 0101 0101 0011 1111 0001 0000 0000 00

   Combined 64 bits:
   [00 0111 0101 1011 1100 1101 0001 01][01 01 1001 0101 0101 0011 1111 0001 0000 0000 00]
   ```
   Result bytes: `1D 6F 34 55 95 54 FC 40`

3. **Timestamp 32 overflow**: max value = 2^32 - 1 = `4294967295` seconds after epoch = **February 7, 2106 at 06:28:15 UTC**. Timestamp 64 extends to 2514 (34-bit seconds field).

</details>

---

## Exercise 9 [Advanced] -- JSON Streaming Parser Design

You receive a 500 MB JSON file containing an array of orders. You cannot load it all into memory.

1. Why does `json.loads(open("huge.json").read())` fail for large files?
2. Design a streaming approach using `ijson` or a custom state machine.
3. How does MsgPack handle this differently? (Hint: think about the `Unpacker` API.)
4. What does this tell you about JSON's suitability for streaming?

<details><summary>Solution</summary>

1. `json.loads` requires loading the **entire string** into memory, then building the **entire parsed object**. For 500 MB of JSON, you need ~500 MB for the string + ~1-2 GB for the parsed Python objects = 1.5-2.5 GB total RAM.

2. Streaming approach:
   ```python
   # Using ijson (SAX-like JSON parsing)
   import ijson

   with open("huge.json", "rb") as f:
       for order in ijson.items(f, "item"):
           process_order(order)  # one order at a time
   ```
   This works because `ijson` is an event-driven parser that doesn't build the full tree.

3. MsgPack's `Unpacker` is naturally streaming:
   ```python
   import msgpack
   unpacker = msgpack.Unpacker(raw=False)
   with open("huge.msgpack", "rb") as f:
       for chunk in iter(lambda: f.read(4096), b""):
           unpacker.feed(chunk)
           for obj in unpacker:
               process_order(obj)
   ```
   MsgPack objects are self-delimiting (length-prefixed), so the parser knows exactly when one object ends and the next begins without scanning for delimiters.

4. JSON was designed for human readability, not streaming. Its nested delimiters (`{}`, `[]`) require the parser to maintain a stack. MsgPack's length-prefixed design makes streaming natural.

</details>

---

## Exercise 10 [Advanced] -- Custom JSON Encoder Performance

Write a specialized JSON encoder that is faster than `json.dumps()` for FoodDash Order objects by exploiting knowledge of the schema.

Constraints:
- You know the exact fields and types at compile time
- No need to handle arbitrary Python objects
- Must produce valid JSON

<details><summary>Solution</summary>

```python
import base64

def fast_encode_order(order_dict: dict) -> bytes:
    """Hand-rolled JSON encoder exploiting schema knowledge.

    Instead of generic type inspection per value, we hard-code
    the field order and types. String escaping is still needed
    but we skip isinstance() checks.
    """
    parts = [b'{"id":"', order_dict["id"].encode(), b'"']
    parts.append(b',"platform_transaction_id":')
    parts.append(str(order_dict["platform_transaction_id"]).encode())
    parts.append(b',"restaurant_id":"')
    parts.append(order_dict["restaurant_id"].encode())
    parts.append(b'"')
    parts.append(b',"status":"')
    parts.append(order_dict["status"].encode() if isinstance(order_dict["status"], str) else str(order_dict["status"]).encode())
    parts.append(b'"')
    parts.append(b',"tip_cents":')
    parts.append(str(order_dict["tip_cents"]).encode())
    parts.append(b',"created_at":')
    parts.append(str(order_dict["created_at"]).encode())
    parts.append(b'}')
    return b"".join(parts)
```

This approach is ~2-4x faster than `json.dumps()` for known schemas because it avoids:
- Generic type dispatch (`isinstance()` chains)
- Dictionary iteration for field discovery
- General-purpose string escaping (if you know your strings don't contain special characters)

This is exactly the approach that `orjson` and `simdjson` use internally (though in C/Rust): schema-aware code generation beats generic serialization.

</details>

---

## Exercise 11 [Advanced] -- MsgPack Extension Types

Design a MsgPack extension type for FoodDash's `GeoPoint` (latitude + longitude).

1. Choose an extension type ID (0-127).
2. Define the binary layout of the extension data.
3. Implement `encode_geopoint()` and `decode_geopoint()`.
4. How many bytes does your extension use vs. a MsgPack map with two named keys?

<details><summary>Solution</summary>

```python
import struct
import msgpack

GEOPOINT_TYPE = 42  # extension type ID

def encode_geopoint(lat: float, lon: float) -> msgpack.ExtType:
    """Pack two float64s into a 16-byte extension."""
    data = struct.pack("<dd", lat, lon)
    return msgpack.ExtType(GEOPOINT_TYPE, data)

def decode_geopoint(ext: msgpack.ExtType) -> tuple[float, float]:
    """Unpack a GeoPoint extension."""
    assert ext.code == GEOPOINT_TYPE
    lat, lon = struct.unpack("<dd", ext.data)
    return lat, lon

# Usage with ext_hook:
def ext_hook(code, data):
    if code == GEOPOINT_TYPE:
        return decode_geopoint(msgpack.ExtType(code, data))
    return msgpack.ExtType(code, data)

# Size comparison:
# Extension: 1 (ext header) + 1 (type) + 16 (data) = 18 bytes
# Map: 1 (fixmap) + 8+8 (key "latitude") + 8 (float) + 9+8 (key "longitude") + 8 (float) = ~50 bytes
# Savings: 32 bytes per GeoPoint (64% smaller)
```

Extension types are MsgPack's escape hatch for domain-specific types. They provide type safety and compactness that generic maps cannot match.

</details>
