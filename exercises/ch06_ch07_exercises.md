# Exercises: Avro (Ch06) + Cap'n Proto (Ch07)

---

## Exercise 1 [Beginner] -- Avro vs Protobuf: What's on the Wire?

Encode the record `{name: "Alice", age: 30}` in both Avro and Protobuf. List the exact bytes for each.

Avro schema:
```json
{"type": "record", "name": "Person", "fields": [
  {"name": "name", "type": "string"},
  {"name": "age", "type": "int"}
]}
```

Protobuf schema:
```protobuf
message Person { string name = 1; int32 age = 2; }
```

<details><summary>Solution</summary>

**Avro** (fields in schema order, NO tags):
```
0a                  -> string length 5 (zigzag of 5 = 10 = 0x0A)
41 6c 69 63 65      -> "Alice"
3c                  -> int 30 (zigzag of 30 = 60 = 0x3C)
```
Total: **7 bytes**

**Protobuf** (field tag + value):
```
0a                  -> tag: field 1, wire type 2 (length-delimited)
05                  -> length: 5
41 6c 69 63 65      -> "Alice"
10                  -> tag: field 2, wire type 0 (varint)
1e                  -> value: 30
```
Total: **9 bytes**

**Difference**: Avro saves 2 bytes (the two field tags). This savings grows linearly with the number of fields. For FoodDash's 15-field Order with nested items, Avro saves ~30-40 tag bytes.

**Trade-off**: Avro requires both reader and writer to have the schema. Protobuf can skip unknown fields without the schema because tags are self-describing.

</details>

---

## Exercise 2 [Beginner] -- Avro Zigzag for Everything

Unlike Protobuf (which has both unsigned and signed variants), Avro uses zigzag encoding for ALL integers.

For each value, compute the zigzag-encoded varint bytes:
1. `0`
2. `1`
3. `-1`
4. `127`
5. `500`
6. `1700000000` (a Unix timestamp)

<details><summary>Solution</summary>

| Value | Zigzag | Varint bytes |
|-------|--------|-------------|
| 0 | 0 | `00` (1 byte) |
| 1 | 2 | `02` (1 byte) |
| -1 | 1 | `01` (1 byte) |
| 127 | 254 | `fe 01` (2 bytes) |
| 500 | 1000 | `e8 07` (2 bytes) |
| 1700000000 | 3400000000 | `80 b8 e0 ab 19` (5 bytes) |

Note that `127` takes 2 bytes in Avro's zigzag but only 1 byte in Protobuf's unsigned varint. For always-positive values like timestamps and IDs, Avro's mandatory zigzag adds ~1 extra byte per field. This is a design trade-off: Avro chose simplicity (one integer encoding) over optimality.

</details>

---

## Exercise 3 [Intermediate] -- Avro Schema Resolution

Avro's killer feature is **schema resolution**: the writer's schema can differ from the reader's schema, and the runtime resolves differences automatically.

Given writer schema:
```json
{"type": "record", "name": "Order", "fields": [
  {"name": "id", "type": "string"},
  {"name": "total", "type": "int"},
  {"name": "status", "type": "string"}
]}
```

And reader schema:
```json
{"type": "record", "name": "Order", "fields": [
  {"name": "id", "type": "string"},
  {"name": "total", "type": "int"},
  {"name": "status", "type": "string"},
  {"name": "priority", "type": "int", "default": 0}
]}
```

1. What happens when data written with the writer schema is read with the reader schema?
2. What if the reader schema **removes** the `status` field?
3. What if the writer changes `total` from `int` to `long`?

<details><summary>Solution</summary>

1. **New field with default**: The `priority` field doesn't exist in the written data. Avro fills it with the default value `0`. This is safe and backward-compatible.

2. **Removed field**: The `status` field exists in the written data but the reader doesn't want it. Avro skips those bytes during reading (it uses the writer's schema to know how many bytes to skip). This is safe and forward-compatible.

3. **Type promotion (int to long)**: Avro supports a set of type promotions: `int` -> `long`, `int` -> `float`, `int` -> `double`, `long` -> `float`, `long` -> `double`, `float` -> `double`. Since `int` -> `long` is a supported promotion, the reader can read `int` data as `long`. However, `long` -> `int` is NOT supported (potential data loss).

The key insight: Avro performs schema resolution at the **binary level** without re-serializing. The reader walks both schemas in parallel, consuming bytes from the writer's layout while producing values in the reader's layout.

</details>

---

## Exercise 4 [Intermediate] -- Design a Schema Registry

FoodDash has 20 microservices communicating via Avro. Each service may use a different schema version.

Design a schema registry that:
1. Stores versioned schemas
2. Supports compatibility checking (backward, forward, full)
3. Integrates with the message wire format

Answer these questions:
- How is the schema ID transmitted with each message?
- What happens when a consumer encounters an unknown schema ID?
- How do you prevent breaking changes from being registered?

<details><summary>Solution</summary>

**Wire format**: Each message is prefixed with: `[magic byte 0x00] [4-byte schema ID (big-endian)] [Avro payload]`. Total overhead: 5 bytes per message.

**Registry API**:
```
POST   /subjects/{name}/versions       -> Register a new schema version
GET    /subjects/{name}/versions/{id}  -> Retrieve schema by version
POST   /compatibility/subjects/{name}  -> Check compatibility
```

**Compatibility checking**:
- **Backward compatible**: New schema can read data written with the old schema. (Add fields with defaults, remove fields.)
- **Forward compatible**: Old schema can read data written with the new schema. (Remove fields, add fields with defaults.)
- **Full compatible**: Both directions work.

**Unknown schema ID flow**:
1. Consumer reads the 4-byte schema ID from the message
2. Looks up schema in local cache (hit rate should be >99.9%)
3. On cache miss: fetch from registry over HTTP
4. Cache the schema (schemas are immutable once registered)
5. Use writer schema + reader schema for Avro resolution

**Preventing breaking changes**: The registry rejects schema registration if compatibility check fails against the latest registered version. Examples of rejected changes:
- Removing a field that has no default value
- Changing a field's type incompatibly (e.g., `string` to `int`)
- Renaming a field (Avro matches by name, not position)

This is exactly how Confluent Schema Registry works with Apache Kafka.

</details>

---

## Exercise 5 [Intermediate] -- Cap'n Proto Pointer Arithmetic

A Cap'n Proto struct pointer has this 64-bit value: `0x0003000200000008`

Decode it:
1. What is the pointer type?
2. What is the offset in words?
3. How many data words does the target struct have?
4. How many pointer words?
5. If this pointer is at byte offset 16 in the buffer, at what byte offset does the target struct begin?

<details><summary>Solution</summary>

`0x0003000200000008` in binary:
```
Bits  0-1:  00 -> pointer type = 0 (STRUCT)
Bits  2-31: 00000000000000000000000000010 -> offset = 2 words
Bits 32-47: 0000000000000010 -> data_words = 2
Bits 48-63: 0000000000000011 -> pointer_words = 3
```

1. **Pointer type**: 0 = struct pointer
2. **Offset**: 2 words (16 bytes) from the end of the pointer
3. **Data words**: 2 (16 bytes of inline scalar data)
4. **Pointer words**: 3 (3 pointers to strings/sub-structs/lists)
5. **Target byte offset**: The pointer is at byte 16. The pointer occupies 8 bytes (one word), so the "end of the pointer" is at byte 24. The target is 2 words (16 bytes) after that: byte **40**.

Formula: `target = pointer_offset + 8 + (offset_words * 8) = 16 + 8 + (2 * 8) = 40`

</details>

---

## Exercise 6 [Intermediate] -- Cap'n Proto Text Encoding

In Cap'n Proto, text (strings) are stored as byte lists with a NUL terminator.

For the string `"Hello"`:
1. How many bytes including the NUL terminator?
2. How many words (8-byte blocks) are needed?
3. How many padding bytes?
4. What does the list pointer look like?

<details><summary>Solution</summary>

1. `"Hello"` = 5 UTF-8 bytes + 1 NUL byte = **6 bytes**
2. `ceil(6 / 8)` = **1 word** (8 bytes)
3. 8 - 6 = **2 padding bytes** (zeros)
4. List pointer (assuming offset = 0 from pointer end):
   ```
   Bits 0-1:   01 (list pointer)
   Bits 2-31:  0 (offset = 0 words)
   Bits 32-34: 010 (element size = BYTE = 2)
   Bits 35-63: 6 (element count = 6, includes NUL)
   ```
   Encoded: `0x0000003000000001`

Memory layout:
```
48 65 6c 6c 6f 00 00 00    "Hello\0" + 2 padding bytes
```

The NUL terminator exists for C interop (you can pass the pointer directly to C functions expecting a `const char*`). The padding ensures word alignment for the next object.

</details>

---

## Exercise 7 [Advanced] -- Compare Wire Bytes: Same Data, Four Formats

Encode this minimal record in Protobuf, FlatBuffers, Avro, and Cap'n Proto:

```
id = "ord001"
tip_cents = 500
```

For each format, list:
1. The exact wire bytes (hex)
2. Total byte count
3. Which bytes are "overhead" (tags, vtables, pointers, padding) vs "data"

<details><summary>Solution</summary>

**Protobuf** (tag + value):
```
0a 06 6f 72 64 30 30 31    field 1 (string) len=6 "ord001"
58 f4 03                    field 11 (varint) 500
```
Total: **11 bytes** (3 overhead, 8 data)

**Avro** (values in schema order, no tags):
```
0c 6f 72 64 30 30 31       string len=6 "ord001"
e8 07                       int 500 (zigzag)
```
Total: **9 bytes** (2 overhead for lengths, 7 data)

**FlatBuffers** (vtable + table + string):
```
Root offset (4) + vtable (8) + soffset (4) + tip_cents (4) + string offset (4) + string: len(4) + "ord001"(6) + null(1) + pad(1)
```
Total: ~**36 bytes** (28 overhead, 8 data)

**Cap'n Proto** (segment table + root pointer + struct + text):
```
Segment table (8) + root pointer (8) + data words 1*8 (tip_cents + padding) + pointer words 1*8 + text: "ord001\0" + padding
```
Total: ~**40 bytes** (32 overhead, 8 data)

| Format | Total | Overhead | Data | Overhead % |
|--------|-------|----------|------|-----------|
| Avro | 9 B | 2 B | 7 B | 22% |
| Protobuf | 11 B | 3 B | 8 B | 27% |
| FlatBuffers | ~36 B | ~28 B | 8 B | 78% |
| Cap'n Proto | ~40 B | ~32 B | 8 B | 80% |

For small messages, parse-based formats (Avro, Protobuf) win on size. Zero-copy formats (FlatBuffers, Cap'n Proto) pay a fixed overhead for their metadata structures but gain zero-allocation reads.

</details>

---

## Exercise 8 [Advanced] -- Avro Union Encoding Edge Cases

Avro unions are encoded as `[type_index varint] [value]`.

Consider the schema: `["null", "string", "int"]`

1. Encode `null`
2. Encode `"hello"`
3. Encode `42`
4. What happens if you try to encode `3.14`?
5. Why does Avro require unions to have at most one type of each kind?

<details><summary>Solution</summary>

1. `null` -> type index 0: `00` (1 byte -- just the index, no payload)
2. `"hello"` -> type index 1 + string: `02 0a 68 65 6c 6c 6f` (7 bytes)
   - `02` = zigzag(1) = index 1
   - `0a` = zigzag(5) = string length 5
   - `68 65 6c 6c 6f` = "hello"
3. `42` -> type index 2 + int: `04 54` (2 bytes)
   - `04` = zigzag(2) = index 2
   - `54` = zigzag(42) = 84
4. `3.14` -> **Error!** The union has no `float` or `double` branch. The encoder cannot find a matching type.
5. Avro requires at most one of each type because union branches are matched by **type**, not by name. If you had `["string", "string"]`, the encoder couldn't determine which branch index to use for a string value. This is a significant limitation -- you can't have a union of two different record types with the same underlying type. (Named types like records are matched by their full name, so `["RecordA", "RecordB"]` is fine.)

</details>

---

## Exercise 9 [Advanced] -- Cap'n Proto: Time-Travel Compatibility

Cap'n Proto's struct layout has fixed data and pointer sections. A new version adds a field.

Version 1:
```
struct Order {
  id @0 :Text;          # pointer 0
  tipCents @1 :Int32;   # data word 0, bytes 0-3
}
# Data: 1 word, Pointers: 1 word
```

Version 2:
```
struct Order {
  id @0 :Text;          # pointer 0
  tipCents @1 :Int32;   # data word 0, bytes 0-3
  status @2 :UInt16;    # data word 0, bytes 4-5
  driverId @3 :Text;    # pointer 1
}
# Data: 1 word, Pointers: 2 words
```

1. Can a V2 reader read V1 data?
2. Can a V1 reader read V2 data?
3. How does the reader know how big the struct is?
4. What happens when V1 reads V2's `driverId` pointer?

<details><summary>Solution</summary>

1. **V2 reads V1**: Yes. The struct pointer encodes data_words=1, pointer_words=1. V2 expects data_words>=1 and pointer_words>=2. For `status` (data word 0, bytes 4-5): those bytes exist and are zero (padding), so status=0 (default). For `driverId` (pointer 1): the pointer section has only 1 word, so pointer 1 is out of range; reader returns null/default. **Safe.**

2. **V1 reads V2**: Yes. The struct pointer says data_words=1, pointer_words=2. V1 only reads tipCents (data word 0, bytes 0-3) and id (pointer 0). It never accesses the extra data or pointer 1. The extra bytes are silently ignored. **Safe.**

3. **Size is in the pointer.** Every struct pointer encodes `data_words` and `pointer_words`. The reader uses these to bounds-check field access. If a field is beyond the declared section size, it returns the default value.

4. **V1 never reads it.** V1's code only accesses pointer slot 0 (id) and data slot 0 (tipCents). Pointer slot 1 (driverId) is never referenced in V1's code, so it's never read. Even if V1 had a bug and tried to read pointer 1, the struct pointer says pointer_words=1, so the bounds check would return null.

This is Cap'n Proto's "time-travel" compatibility: any version of a reader can safely read data from any version of a writer, in either direction, without schema negotiation.

</details>

---

## Exercise 10 [Advanced] -- Schema Format Showdown

You're designing a new microservice for FoodDash. Compare the four schema-based formats for these requirements:

| Requirement | Protobuf | FlatBuffers | Avro | Cap'n Proto |
|---|---|---|---|---|
| Schema evolution (add/remove fields) | | | | |
| Zero-copy reads | | | | |
| Smallest wire size | | | | |
| Selective field access | | | | |
| Schema registry integration | | | | |
| Built-in RPC framework | | | | |
| Language support (# of languages) | | | | |
| Streaming support | | | | |

<details><summary>Solution</summary>

| Requirement | Protobuf | FlatBuffers | Avro | Cap'n Proto |
|---|---|---|---|---|
| Schema evolution | Good. Field numbers ensure compat. No rename tracking. | Good. Vtable handles missing fields. Must not reuse indices. | Best. Schema resolution handles renames, promotions, defaults. | Good. Struct size in pointer. Cannot reorder fields. |
| Zero-copy reads | No. Must parse entire message. | Yes. Vtable + offset arithmetic. | No. Must decode sequentially. | Yes. Direct memory access. |
| Smallest wire size | Small. Varint tags + values. | Large. Vtable + alignment padding. | Smallest. No tags at all. | Large. 8-byte word alignment. |
| Selective field access | Poor. Must scan all tags. | Excellent. O(1) any field via vtable. | Poor. Must decode all preceding fields. | Excellent. O(1) via data slot offset. |
| Schema registry | Manual. No built-in registry. | Manual. | Built-in. Confluent Schema Registry. | Manual. |
| Built-in RPC | gRPC (industry standard). | None (use with gRPC). | None (often used with Kafka). | Cap'n Proto RPC with promise pipelining. |
| Language support | 10+ official languages. | 15+ languages. | 5-10 languages (Java/Python strongest). | ~5 languages (C++/Rust strongest). |
| Streaming | gRPC streaming. Size-prefixed messages. | Not designed for streaming. | Avro container files support streaming. | Segmented messages support streaming. |

**Rules of thumb:**
- High-throughput RPC with broad language needs -> **Protobuf + gRPC**
- Read-heavy with selective access (games, mobile) -> **FlatBuffers**
- Event streaming with schema evolution (Kafka) -> **Avro**
- Ultra-low-latency RPC (C++/Rust systems) -> **Cap'n Proto**

</details>

---

## Exercise 11 [Advanced] -- Avro Container File Format

Avro data files (`.avro`) use a container format with a header:

```
[magic "Obj1"] [file metadata (Avro map)] [sync marker (16 random bytes)]
[block 1: count + size + compressed data + sync marker]
[block 2: ...]
...
```

1. Why does the container include the writer's schema in the metadata?
2. Why is there a 16-byte sync marker between blocks?
3. How does this design enable MapReduce-style parallel processing?
4. What compression codecs are supported in the container header?

<details><summary>Solution</summary>

1. **Self-describing files**: The writer's schema is embedded in the file metadata so any reader can decode the file without external schema information. This is different from the Schema Registry approach (where schemas are stored externally). The file is self-contained: give someone the `.avro` file and they can read it without needing access to your schema registry.

2. **Sync markers enable seeking**: The 16-byte random sync marker appears between data blocks. If a file is corrupted or you want to start reading from the middle, you can scan for the sync marker to find a valid block boundary. This is critical for:
   - Recovery from corruption (skip to next sync marker)
   - Splitting files for parallel processing

3. **MapReduce splitting**: A 100 GB Avro file can be split across 100 map tasks. Each task:
   - Seeks to its assigned byte range
   - Scans forward for the next sync marker
   - Reads complete blocks until the end of its range
   - No coordination needed between tasks
   
   Without sync markers, you'd need an index of block offsets, which doesn't work for streaming writes.

4. **Compression codecs**: The `avro.codec` metadata key specifies:
   - `null` (no compression)
   - `deflate` (zlib/gzip)
   - `snappy` (fast, moderate compression)
   - `zstandard` (best ratio, good speed)
   - `bzip2` (high ratio, slow)
   - `xz` (highest ratio, slowest)
   
   Each block is independently compressed, so random access works (decompress only the block you need).

</details>
