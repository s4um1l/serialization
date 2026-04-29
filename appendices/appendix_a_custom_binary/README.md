# Appendix A: Designing Your Own TLV Binary Format

## When to Build Custom vs. Use Existing

After studying JSON, MessagePack, Protocol Buffers, FlatBuffers, Avro, and Cap'n Proto,
you might wonder: *when would I actually design my own binary format?*

**Build custom when:**
- You have extreme performance constraints (embedded systems, kernel bypass networking)
- The data shape is fixed and well-understood (sensor telemetry, game state snapshots)
- You need sub-microsecond parsing with zero allocations
- Existing formats carry overhead you cannot afford (schema metadata, field tags, type markers)
- You control both producer and consumer (internal microservice protocol)

**Use existing when:**
- Multiple teams or languages need to interoperate
- The schema evolves over time (protobuf and Avro handle this gracefully)
- You need ecosystem tooling (schema registries, code generators, debugging tools)
- Correctness matters more than the last 10% of performance

The sweet spot for custom formats is narrow. But understanding *how* to build one gives you
deep intuition for what every other format is doing under the hood.

## TLV: Type-Length-Value

TLV is the simplest practical binary encoding pattern. Nearly every binary protocol uses
some variant of it:

```
+------+----------+--------+-----------------+
| Type | Field ID | Length | Value            |
| 1B   | 1B       | 2B LE  | `Length` bytes   |
+------+----------+--------+-----------------+
```

**Type byte** identifies how to interpret the value:
- `0x01` = uint32 (4 bytes, little-endian)
- `0x02` = UTF-8 string
- `0x03` = raw bytes
- `0x04` = nested TLV message (recursive)
- `0x05` = float64 (8 bytes, IEEE 754 little-endian)
- `0x06` = bool (1 byte: 0x00 or 0x01)

**Field ID** is an application-defined tag (0-255) that identifies which field this is
within the message. Similar to protobuf field numbers.

**Length** is a 2-byte little-endian unsigned integer giving the byte length of the value.
Maximum value size: 65,535 bytes. For larger payloads, you would switch to a 4-byte
length prefix or use chunked encoding.

## Worked Example: Encoding a Simplified FoodDash Order

Let's encode a minimal order with three fields:

| Field ID | Type   | Name          | Example Value     |
|----------|--------|---------------|-------------------|
| 1        | uint32 | order_id      | 42                |
| 2        | string | restaurant    | "Burger Palace"   |
| 3        | uint32 | total_cents   | 2598              |

### Step 1: Encode order_id = 42

```
Type:     0x01 (uint32)
Field ID: 0x01
Length:   0x04 0x00 (4 bytes, little-endian)
Value:    0x2A 0x00 0x00 0x00 (42 as uint32 LE)
```

Wire bytes: `01 01 04 00 2A 00 00 00` (8 bytes)

### Step 2: Encode restaurant = "Burger Palace"

```
Type:     0x02 (string)
Field ID: 0x02
Length:   0x0D 0x00 (13 bytes)
Value:    42 75 72 67 65 72 20 50 61 6C 61 63 65
```

Wire bytes: `02 02 0D 00 42 75 72 67 65 72 20 50 61 6C 61 63 65` (17 bytes)

### Step 3: Encode total_cents = 2598

```
Type:     0x01 (uint32)
Field ID: 0x03
Length:   0x04 0x00
Value:    0x26 0x0A 0x00 0x00 (2598 as uint32 LE)
```

Wire bytes: `01 03 04 00 26 0A 00 00` (8 bytes)

### Total message: 33 bytes

Compare with JSON `{"order_id":42,"restaurant":"Burger Palace","total_cents":2598}` at 62
bytes. Our TLV encoding is 47% smaller, and parsing requires zero string comparisons.

## Pitfalls

### 1. Endianness

Always document and enforce byte order. Little-endian is the modern standard (x86, ARM in
LE mode, protobuf, FlatBuffers all use LE). If your format ever crosses architectures,
inconsistent endianness will corrupt every multi-byte value silently.

Our format uses little-endian throughout, matching the host byte order on x86/ARM.

### 2. Versioning

The biggest weakness of custom formats is schema evolution. What happens when you need to
add a `delivery_notes` field?

**Strategy:** Use field IDs, not positions. A decoder should skip unknown field IDs rather
than failing. This is exactly what protobuf does -- our TLV format supports this naturally
because each field carries its own ID. Old decoders ignore new field IDs; new decoders
treat missing fields as defaults.

**Anti-pattern:** Fixed-offset structs where field N is at byte offset O. Adding a field
shifts everything. This is fast to parse but brutal to evolve.

### 3. Alignment

CPUs read memory fastest when values are naturally aligned (uint32 at 4-byte boundaries,
float64 at 8-byte boundaries). Our simple TLV format does NOT guarantee alignment -- the
value section starts wherever the previous field ended.

For maximum performance, you could:
- Pad values to alignment boundaries (wastes space)
- Copy values into aligned temporaries at decode time (what we do)
- Use a format like FlatBuffers that guarantees alignment in the buffer

### 4. String Encoding

Always use UTF-8. Always store the byte length, not the character count. A string like
"Börgér" is 8 bytes in UTF-8 but 6 characters. If you store character count, the decoder
will read the wrong number of bytes.

### 5. Nested Messages

Our `0x04` type code handles nesting: the value bytes are themselves a TLV-encoded message.
This is exactly how protobuf handles embedded messages (wire type 2, length-delimited).
The recursive structure means you can represent arbitrarily complex data, but deep nesting
costs a length-prefix overhead at each level.

## Running the Code

```bash
uv run python -m appendices.appendix_a_custom_binary.custom_format
```

This will encode a sample order, print the hex dump with color-coded regions, decode it
back, and verify the roundtrip.
