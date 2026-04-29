# Chapter 04 -- Protocol Buffers

> *"We need a contract between services. A schema that says what fields exist, what types they are, and what happens when the schema changes."*

```
uv run python -m chapters.ch04_protobuf
```

---

## The Scene

FoodDash has grown to 20 microservices. The Kitchen Service team ships a release that adds `prep_time_minutes` to the Order payload -- a perfectly reasonable field for estimating delivery times. They test it locally, push to staging, all green.

Within 90 minutes of the production deploy, five services are down.

The **Billing Service** sees the new key in its MsgPack-decoded dict, passes it to a function that expects exactly 12 keys, and crashes with a `TypeError`. The **Analytics Pipeline** has a schema validation step that rejects unknown fields. The **Driver Matching Service** does `order["status"]` but the new field shifted some internal offset in a hand-rolled optimization, producing garbage. Two more services fail their health checks because they log the full order dict and the logging library chokes on the unexpected field.

The postmortem is brutal. Five teams, three time zones, 47 minutes of downtime affecting 180,000 orders. The root cause is clear: **there is no contract between services**. Every team reads the binary blob and hopes for the best. Adding a field is a breaking change because nobody agreed on what fields exist, what types they are, or what happens when the schema evolves.

MessagePack gave FoodDash compact binary encoding. But it's just "binary JSON" -- a schemaless bag of key-value pairs. What FoodDash needs is:

1. **A schema** -- a formal definition of every message's fields and types
2. **Field identity by number, not name** -- so renaming doesn't break anything
3. **Evolution rules** -- add a field without crashing old readers, remove a field without crashing new readers

Enter Protocol Buffers.

---

## How It Works: The Protobuf Wire Format

Protocol Buffers (protobuf) is Google's language-neutral, platform-neutral mechanism for serializing structured data. It has been used internally at Google since 2001 and was open-sourced in 2008. Nearly all inter-service communication at Google uses protobuf.

The key ideas:

### .proto Files: The Schema Definition Language

You define your messages in a `.proto` file:

```protobuf
syntax = "proto3";

message Order {
  string id = 1;
  int64 platform_transaction_id = 2;
  Customer customer = 3;
  string restaurant_id = 4;
  repeated OrderItem items = 5;
  OrderStatus status = 6;
  // ...
}
```

Those numbers (`= 1`, `= 2`, etc.) are **field numbers**, not default values. They are the stable identifiers that appear on the wire. The field *name* (`id`, `restaurant_id`) exists only in the `.proto` file -- it never appears in the serialized bytes.

See `fooddash.proto` for the full FoodDash schema definition.

### Field Numbers: The Stable Identifier

In JSON, every encoded message carries field names as strings:

```json
{"platform_transaction_id": 123456789, "restaurant_id": "rest0001"}
```

That's 26 characters just for the key `"platform_transaction_id"`. In protobuf, the same information is:

```
tag(2, VARINT) + varint(123456789)
```

One byte for the tag, four bytes for the value. Five bytes total vs. 35 bytes in JSON. The field number `2` maps to `platform_transaction_id` via the schema, which both sides have.

This is why field numbers are the *identity* of a field. You can rename `platform_transaction_id` to `txn_id` in your `.proto` file and nothing breaks on the wire -- only the number matters.

### Wire Types

Protobuf uses four wire types to tell the decoder how to read the next value:

| Wire Type | ID | Used For | How Decoder Reads |
|---|---|---|---|
| VARINT | 0 | int32, int64, uint32, uint64, bool, enum | Read bytes until MSB = 0 |
| 64-BIT | 1 | fixed64, sfixed64, double | Read exactly 8 bytes |
| LENGTH_DELIMITED | 2 | string, bytes, embedded messages, repeated | Read varint length, then that many bytes |
| 32-BIT | 5 | fixed32, sfixed32, float | Read exactly 4 bytes |

The wire type is critical for **forward compatibility**: even if a decoder doesn't know a field number, it can read the wire type and skip the right number of bytes.

### Varint Encoding (LEB128)

Protobuf encodes integers using LEB128 (Little-Endian Base 128). Each byte carries 7 bits of data and 1 continuation bit (the MSB):

```
Value: 300
Binary: 100101100

Split into 7-bit groups (from LSB):
  Group 1: 0101100  (low 7 bits)
  Group 2: 0000010  (remaining bits)

Add continuation bits:
  Byte 1: 1_0101100 = 0xAC  (MSB=1: more bytes follow)
  Byte 2: 0_0000010 = 0x02  (MSB=0: last byte)

Result: 0xAC 0x02
```

Key property: small values use fewer bytes.

| Value | Bytes | Varint Size |
|---|---|---|
| 0-127 | `0x00`-`0x7F` | 1 byte |
| 128-16,383 | 2 bytes | 2 bytes |
| 16,384-2,097,151 | 3 bytes | 3 bytes |
| 2^53+1 (JS unsafe) | 8 bytes | 8 bytes |

### Zigzag Encoding: Making Small Negatives Small

A problem: `-1` in two's complement is `0xFFFFFFFFFFFFFFFF` -- that's a 10-byte varint. But `-1` is a *small* number; it should be cheap.

Zigzag encoding maps signed integers to unsigned ones:

```
 0 -> 0
-1 -> 1
 1 -> 2
-2 -> 3
 2 -> 4
```

Formula: `zigzag(n) = (n << 1) ^ (n >> 63)`

Now `-1` encodes as unsigned `1`, which is a 1-byte varint. Used by `sint32`/`sint64` types in protobuf.

### Tag Encoding

Every field on the wire starts with a tag:

```
tag = (field_number << 3) | wire_type
```

The tag is encoded as a varint. Since field numbers 1-15 produce tag values 8-122 (all < 128), they fit in a single byte. Field number 16 produces tag value 128, which needs two bytes.

**This is why protobuf best practice reserves field numbers 1-15 for your most frequently used fields.** In the FoodDash Order schema, we use all 15 single-byte slots for the most common fields (id, customer, status, items, etc.), and the `metadata` map gets the last precious slot at field 15.

### Why Field Numbers 1-15 Are Precious

```
field= 1, wire=2  -> tag_value=  10  -> 1 byte  (0x0A)
field=15, wire=2  -> tag_value= 122  -> 1 byte  (0x7A)
field=16, wire=0  -> tag_value= 128  -> 2 bytes (0x80 0x01)
```

Every field over 15 costs an extra byte per field occurrence. For repeated fields (like `items`), that extra byte is paid once per element.

---

## From Scratch: Building a Protobuf Encoder

The file `proto_from_scratch.py` implements the entire protobuf wire format from first principles. No libraries. Here's what it builds, step by step.

### Varint Encoder/Decoder

```python
def encode_varint(value: int) -> bytes:
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)  # low 7 bits + continuation
        value >>= 7
    parts.append(value & 0x7F)               # last byte, no continuation
    return bytes(parts)

def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset
```

### Field Encoders

Each field type has an encoder that writes `tag + value`:

```python
def encode_string_field(field_number, value):
    raw = value.encode("utf-8")
    return encode_tag(field_number, WIRE_LENGTH_DELIMITED) \
         + encode_varint(len(raw)) \
         + raw

def encode_varint_field(field_number, value):
    if value == 0:
        return b""  # proto3: default values not serialized
    return encode_tag(field_number, WIRE_VARINT) \
         + encode_varint(value)

def encode_double_field(field_number, value):
    if value == 0.0:
        return b""
    return encode_tag(field_number, WIRE_64BIT) \
         + struct.pack("<d", value)
```

Note the proto3 convention: **default values (0, false, empty string) are never serialized**. This saves space and is how the protocol achieves forward/backward compatibility -- missing fields always mean "use the default."

### Full Order Encoding

The `encode_order()` function encodes all 15 fields of a FoodDash Order. For a typical 3-item order:

```
Protobuf (from scratch):    715 bytes
JSON:                     1,661 bytes
Savings:                   57.0%
```

Where does the saving come from?

| Field | JSON bytes | Protobuf bytes | Saving |
|---|---|---|---|
| `id` | 15 | 10 | +5 |
| `platform_transaction_id` | 35 | 5 | +30 |
| `restaurant_id` | 26 | 10 | +16 |
| `status` | 19 | 2 | +17 |
| `tip_cents` | 15 | 3 | +12 |

The biggest wins: long field names (`platform_transaction_id` = 26 chars as a JSON key) become single-byte tags. Enum values become small varints instead of quoted strings. Integers use varints instead of ASCII digits.

### Generic Decoder

The decoder doesn't need to know the schema -- it uses wire types to parse the stream:

```python
def decode_message(data: bytes) -> dict[int, list]:
    fields = {}
    offset = 0
    while offset < len(data):
        field_number, wire_type, offset = decode_tag(data, offset)
        if wire_type == WIRE_VARINT:
            value, offset = decode_varint(data, offset)
        elif wire_type == WIRE_64BIT:
            value = data[offset:offset + 8]; offset += 8
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, offset = decode_varint(data, offset)
            value = data[offset:offset + length]; offset += length
        elif wire_type == WIRE_32BIT:
            value = data[offset:offset + 4]; offset += 4
        fields.setdefault(field_number, []).append(value)
    return fields
```

This returns `{field_number: [raw_values]}`. The caller uses the schema to interpret types (is field 1 a string or embedded message?). But crucially, **unknown fields are parsed and skipped correctly** -- the wire type tells you exactly how many bytes each field occupies.

---

## Schema Evolution: The Killer Feature

The file `schema_evolution.py` demonstrates protobuf's evolution capabilities with six scenarios. This is arguably protobuf's most important feature for production systems.

### Forward Compatibility: Old Reader, New Data

```
v3 writer adds field 20 (priority_score).
v1 reader has never heard of field 20.
Result: v1 reads all its known fields correctly.
        Field 20 is silently skipped.
```

The decoder reads the tag for field 20, sees wire type 0 (VARINT), reads the varint, and moves on. No crash. No data corruption. The self-describing wire format makes this possible.

### Backward Compatibility: New Reader, Old Data

```
v1 writer doesn't include tip_cents (field 11).
v2 reader expects tip_cents.
Result: tip_cents is simply absent.
        Proto3 default (0) kicks in.
```

Missing fields get their default value: 0 for integers, false for bools, empty string for strings. This is why proto3 requires all fields to have sensible defaults.

### The Evolution Rules

**Safe changes:**
- Add new fields (old readers skip unknown fields)
- Stop sending a field (readers get default values)
- Rename fields (only numbers matter on the wire)
- Change `int32` to `int64` (both use varint wire type)

**Breaking changes:**
- Change a field's wire type (`int32` -> `string`)
- Reuse a deleted field number
- Change the meaning of a field number

**Best practice: reserve deleted field numbers:**

```protobuf
message Order {
  reserved 10;
  reserved "promo_code";
  // Prevents anyone from accidentally reusing field 10
}
```

### Why This Matters for FoodDash

Remember the postmortem? Five services crashed because the Kitchen Service added a field. With protobuf:

1. The Kitchen Service adds `prep_time_minutes = 16` to the `.proto` file
2. Old services don't know field 16 -- they skip it silently
3. Services that want the new field update their `.proto` and read it
4. No coordination needed. No downtime. No postmortem.

This is the power of schema evolution. It turns a breaking change into a non-event.

---

## Systems Constraints

### Size Comparison

For a typical FoodDash order (3 items, all common fields set):

| Format | Size | vs. JSON |
|---|---|---|
| JSON | 1,661 bytes | 1.0x |
| MsgPack | ~1,200 bytes | ~0.72x |
| Protobuf | 715 bytes | 0.43x |

Protobuf is roughly 2.3x smaller than JSON. The savings come from:
- Field numbers (1-2 bytes) vs. field names (5-25 bytes)
- Varint integers vs. ASCII digit strings
- No delimiters (no `{`, `}`, `,`, `:`, `"`)
- Default values not serialized
- Binary data is raw (no base64)

### Speed Comparison

Our from-scratch Python encoder is intentionally unoptimized for educational clarity. In production, protobuf's C++ implementation is 5-10x faster than JSON serialization. The Python protobuf library with the C extension is somewhere in between.

The key performance insight isn't speed -- it's what happens during *decode*:

**Protobuf still deserializes the entire message.** When the Driver Matching Service receives an Order and only needs `id` (field 1), `status` (field 6), and `customer.location` (field 3 -> field 6), it still:

1. Allocates an Order object
2. Parses every varint, every string, every embedded message
3. Populates every field in memory
4. The garbage collector must eventually clean up fields 2, 4, 5, 7-15

At millions of orders per second, this "parse everything to read something" pattern creates GC pressure that spikes P99 latency.

### Memory Profile

```
                   Encode Peak    Decode Peak
JSON               ~3,400 B       ~7,900 B
Protobuf (full)    ~3,800 B       ~8,700 B
Protobuf (raw)     ~3,800 B       ~2,200 B
```

The "raw decode" (just splitting into `{field_number: values}` without interpretation) uses much less memory because it doesn't create typed Python objects. But it's still allocating dicts and lists. A truly zero-copy approach wouldn't allocate at all.

---

## Production Depth

### gRPC

gRPC is Google's open-source RPC framework, and protobuf is its default wire format. gRPC uses HTTP/2 for transport, protobuf for serialization, and `.proto` files for service definitions:

```protobuf
service OrderService {
  rpc CreateOrder (CreateOrderRequest) returns (Order);
  rpc GetOrder (GetOrderRequest) returns (Order);
  rpc StreamOrderUpdates (GetOrderRequest) returns (stream OrderUpdate);
}
```

The `protoc` compiler generates client and server stubs in dozens of languages. This is the standard way to build microservice APIs at Google, and increasingly across the industry.

### Proto2 vs Proto3

Proto2 (2008) and proto3 (2016) differ in important ways:

- **Proto2** has `required`, `optional`, and `repeated` labels. The `required` label turned out to be a mistake -- it makes schema evolution impossible for that field.
- **Proto3** drops `required` entirely. All fields are implicitly optional. Default values are well-defined (0, false, "").
- **Proto3** dropped custom default values. The default is always the zero value for the type.
- **Proto3** added map types and improved JSON mapping.

The shift from proto2 to proto3 reflects a decade of experience: **every field should be optional, and every field should have a sensible default.** This is the price of evolution.

### Field Presence in Proto3

Proto3's biggest controversy: you can't distinguish "field was set to 0" from "field was not set." Both look the same on the wire (the field is absent).

Proto3 added `optional` back (as of 3.15) to solve this. An `optional` field has a `has_*` method that distinguishes "explicitly set to 0" from "not set."

For FoodDash, this matters: `tip_cents = 0` might mean "customer chose no tip" or "the order was placed before we added tipping." The wire format can't tell.

### Buf: Modern Protobuf Tooling

[Buf](https://buf.build) provides modern tooling for protobuf workflows:

- **Linting** -- enforce style guidelines (field naming, enum zero values)
- **Breaking change detection** -- CI check that catches wire-incompatible changes
- **Schema registry** -- centralized management of `.proto` files
- **Code generation** -- replace `protoc` with a more reliable build system

For FoodDash's 20 microservices, Buf's breaking change detection would have prevented the postmortem entirely.

### Google Scale

Google uses protobuf for virtually all structured data:
- **48+ billion RPC calls per second** (2023 data) use protobuf
- Bigtable, Spanner, and Pub/Sub all use protobuf internally
- Android and iOS apps communicate with Google backends via protobuf
- `tensorflow.GraphDef` is a protobuf message

The format was designed for Google's scale, and it shows: tiny payloads, fast parsing, and safe schema evolution.

---

## Trade-offs Table

| Dimension | JSON | MsgPack | Protobuf |
|---|---|---|---|
| **Schema** | None | None | `.proto` file (required) |
| **Field identity** | String names | String names | Numeric tags |
| **Type safety** | Runtime | Runtime | Compile-time |
| **Size (typical order)** | 1,661 B | ~1,200 B | 715 B |
| **Human readable** | Yes | No | No |
| **Schema evolution** | Fragile | Fragile | Built-in rules |
| **Unknown fields** | Crash or ignore (app-dependent) | Crash or ignore | Safely skipped |
| **Binary data** | Base64 (33% overhead) | Native | Native |
| **Language support** | Universal | Good (30+ libs) | Excellent (protoc generates code) |
| **Decode model** | Full parse | Full parse | Full parse |
| **Zero-copy** | No | No | No |
| **Tooling** | Ubiquitous | Minimal | gRPC, Buf, protoc plugins |
| **Learning curve** | None | Low | Medium (schema, protoc, field numbers) |

---

## The Bridge

Protobuf solved the schema problem. We have a contract between services. We have evolution rules -- add fields without crashing old readers, remove fields gracefully, rename freely. Field numbers instead of names make payloads 2-3x smaller than JSON.

But there's a cost we didn't expect.

The Driver Matching Service processes millions of decisions per second. For each incoming Order, it needs exactly three things: `order.id`, `order.status`, and `order.customer.location`. That's 3 fields out of 15+ in the Order message, which itself contains nested Customer and OrderItem messages.

With protobuf, when the service calls `Order.ParseFromString(data)`, it:
- Allocates an Order object
- Parses every single field -- all 15 top-level fields
- Recursively parses the Customer message (6 fields)
- Recursively parses every OrderItem (3 fields each), and every MenuItem within (8 fields each)
- Allocates Python objects for every string, every list, every nested message

For a typical order with 3 items, that's ~50 field parses and ~50 object allocations. The service uses 3 of them and throws the rest away. At 2 million orders per second, that's 94 million wasted allocations per second. The garbage collector can't keep up. P99 latency spikes from 2ms to 200ms during GC pauses.

The team profiles the service. The bottleneck isn't the business logic -- it's deserialization. Specifically, it's the memory allocation during deserialization. The actual CPU work of reading varints and tags is fast. But creating Python objects for every field -- strings that will never be read, lists that will never be iterated, nested messages that will never be accessed -- that's what kills them.

What if we didn't have to deserialize at all?

What if we could read `order.status` directly from the serialized buffer -- no parsing, no allocation, no copying? The bytes are right there in memory. Field 6 is a varint at some offset. What if we could jump straight to that offset and read the varint in place?

That's **zero-copy deserialization** -- the buffer IS the object. And it's what FlatBuffers does.

---

## Running the Code

```bash
# Install protobuf dependency
uv sync --extra protobuf

# Run all demos
uv run python -m chapters.ch04_protobuf

# Run individual modules
uv run python -m chapters.ch04_protobuf.proto_from_scratch
uv run python -m chapters.ch04_protobuf.proto_lib
uv run python -m chapters.ch04_protobuf.schema_evolution
```

## Files

| File | Purpose |
|---|---|
| `proto_from_scratch.py` | Full protobuf wire format implementation from scratch |
| `proto_lib.py` | Library comparison and benchmarks |
| `schema_evolution.py` | Six schema evolution scenarios |
| `fooddash.proto` | Reference proto3 schema definition |
| `visual.html` | Interactive varint calculator and wire format explorer |
