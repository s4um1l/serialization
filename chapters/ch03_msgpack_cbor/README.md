# Chapter 03 -- MessagePack / CBOR: Binary JSON

## The Scene

FoodDash hits 100,000 messages per second. The order service, which sits at the center of the platform and touches every transaction, is burning 15% of its CPU budget on `json.dumps` and `json.loads`. The profiler doesn't lie: string scanning, escape handling, base64 encoding of menu item thumbnails -- these are real costs that scale linearly with traffic.

An engineer discovers MessagePack while reading the Redis source code. Redis uses a MessagePack-like format (RESP3) for its client protocol because JSON was too slow for a database that serves millions of operations per second. The pitch is irresistible: "Same data model as JSON -- maps, arrays, strings, numbers, booleans, null -- but encoded in binary. Swap `json.dumps` for `msgpack.packb` and you're done."

They prototype it in an afternoon. The changes are minimal: one import swap, a couple of options flags. The results are immediate:

- **Payloads shrink 30-50%.** No more quoted field names, no more escape sequences, no more base64-encoded thumbnails. A typical order drops from 1,661 bytes to 1,289 bytes. The large order (20 items with thumbnails) drops from 22,477 bytes to 16,290 bytes.
- **Parse time drops 2-3x.** MessagePack doesn't scan characters looking for closing quotes or escape sequences. It reads a type byte, reads a length, and copies that many bytes. No ambiguity, no backtracking.
- **CPU usage drops from 15% to 8%.** The order service gets headroom back. The on-call engineers sleep better.

The win is real. The team rolls MessagePack out to all 20 microservices over the next month.

Three months later, the kitchen service adds `prep_time_minutes` to the Order message. It's a reasonable addition -- the kitchen display needs to show estimated preparation time to cooks. The engineer adds the field, deploys the kitchen service, and goes to lunch.

Five services crash within the hour. The delivery estimator, the billing service, the analytics pipeline, the customer notification service, and the driver dispatch service all throw errors. Some throw `KeyError` because they're iterating over order fields and asserting an exact set of keys. Others don't crash immediately but produce garbage output because they're passing the full order dict to functions that don't expect extra fields.

The root cause is simple: there is no schema. No contract says what fields an Order contains, what types they have, or what happens when a field is added or removed. MessagePack faithfully encodes whatever dict you hand it and faithfully decodes it back. It has no opinion about whether `prep_time_minutes` should be there or not. Every service has to handle every possible shape of the data defensively, and across 20 teams, not everyone does.

Adding a field requires a coordinated deploy across every consumer. Removing a field is even worse -- you have to confirm that no reader anywhere still depends on it, and there's no tooling to check. The format has no evolution story.

MessagePack gave FoodDash binary efficiency. But it didn't give them a contract.

---

## How It Works: The MessagePack Format

MessagePack is JSON's data model encoded in binary. It supports the same types -- maps, arrays, strings, numbers, booleans, null -- but represents them with type-prefix bytes instead of syntax characters.

### The Type Prefix System

Every MessagePack value begins with a single byte that tells the decoder two things: what type of value follows, and how many bytes to read. For small values, the type byte **is** the value itself.

The byte space (0x00 through 0xFF) is divided into ranges:

```
0x00-0x7f  positive fixint    (value IS the byte: 0-127)
0x80-0x8f  fixmap             (map with 0-15 entries)
0x90-0x9f  fixarray           (array with 0-15 elements)
0xa0-0xbf  fixstr             (string with 0-31 bytes)
0xc0       nil
0xc2       false
0xc3       true
0xc4-0xc6  bin 8/16/32        (raw binary data)
0xca-0xcb  float 32/64
0xcc-0xcf  uint 8/16/32/64
0xd0-0xd3  int 8/16/32/64
0xd9-0xdb  str 8/16/32
0xdc-0xdd  array 16/32
0xde-0xdf  map 16/32
0xe0-0xff  negative fixint    (value is byte - 256: -32 to -1)
```

### Compact Integers

The integer 42 in JSON is two bytes: `34 32` (ASCII '4', '2'). In MessagePack, it's one byte: `0x2a` (42 in hex). The type prefix range 0x00-0x7f doubles as the value itself. Any integer from 0 to 127 is a single byte.

Negative integers from -32 to -1 get the same treatment: they occupy the range 0xe0-0xff. The integer -5 is a single byte: `0xfb`.

Larger integers use explicit type prefixes:
- `0xcc` + 1 byte = uint8 (128-255)
- `0xcd` + 2 bytes = uint16 (256-65535)
- `0xce` + 4 bytes = uint32
- `0xcf` + 8 bytes = uint64

This is fundamentally different from JSON, where every number is a variable-length string of ASCII digits that the parser must scan character by character.

### Length-Prefixed Strings

JSON strings are delimited by quotes. The parser must scan every character looking for an unescaped closing quote, handling escape sequences along the way. A 100-character string requires examining every one of those characters.

MessagePack strings are length-prefixed. The string "hello" encodes as:

```
0xa5                  fixstr, length 5 (0xa0 | 0x05)
0x68 0x65 0x6c 0x6c 0x6f  "hello" in UTF-8
```

The decoder reads the type byte, extracts the length (5), reads exactly 5 bytes, and it's done. No scanning, no escape handling, no ambiguity.

For strings longer than 31 bytes, explicit length prefixes are used:
- `0xd9` + 1-byte length (str 8, up to 255 bytes)
- `0xda` + 2-byte length (str 16, up to 65535 bytes)
- `0xdb` + 4-byte length (str 32, up to 4 GB)

### Native Binary Data

This is MessagePack's killer feature over JSON. JSON has no binary type. To send a PNG thumbnail in JSON, you must base64-encode it (33% size overhead), wrap it in quotes, and the receiver must know to base64-decode it. There's no standard way to signal "this string is actually binary data."

MessagePack has dedicated binary types:
- `0xc4` + 1-byte length + raw bytes (bin 8, up to 255 bytes)
- `0xc5` + 2-byte length + raw bytes (bin 16, up to 65535 bytes)
- `0xc6` + 4-byte length + raw bytes (bin 32, up to 4 GB)

A 72-byte PNG thumbnail in MessagePack: 74 bytes (2-byte header + raw data).
The same thumbnail in JSON with base64: 98 bytes (base64 + quotes).

That's 32% overhead eliminated, plus the CPU cost of base64 encode/decode on every message.

### Maps and Arrays

Maps and arrays use the same prefix pattern: a type byte encoding the count, followed by the entries.

```
{"id": "ord00002", "status": "en_route"}
```

In MessagePack:
```
0x82                     fixmap, 2 entries
0xa2 0x69 0x64           fixstr "id"
0xa8 ...8 bytes...       fixstr "ord00002"
0xa6 ...6 bytes...       fixstr "status"
0xa8 ...8 bytes...       fixstr "en_route"
```

### Byte-by-Byte Comparison with JSON

Consider the JSON object `{"a": 1}`:

**JSON (10 bytes):**
```
{ " a " : 1 }
7b 22 61 22 3a 31 7d
```
Plus whitespace if pretty-printed. Each character serves a syntactic purpose: braces delimit the map, quotes delimit strings, colons separate keys from values, commas separate entries.

**MessagePack (4 bytes):**
```
81 a1 61 01
```
- `0x81`: fixmap with 1 entry
- `0xa1 0x61`: fixstr "a" (1 byte length + 1 byte data)
- `0x01`: positive fixint 1

60% smaller. No syntax characters, no quotes, no colons, no commas. Every byte carries data or metadata, nothing is wasted on human readability.

---

## CBOR: The IETF Alternative

CBOR (Concise Binary Object Representation, RFC 8949) is conceptually similar to MessagePack but was designed by the IETF for constrained environments like IoT devices and embedded systems. It was standardized in 2013 (originally RFC 7049) and updated in 2020.

### Semantic Tags

CBOR's distinguishing feature is its **semantic tag** system. Tags are integer prefixes that give meaning to the following value:

- **Tag 0**: A text string containing a date/time in ISO 8601 format (e.g., "2024-11-15T10:30:00Z")
- **Tag 1**: A number representing seconds since the Unix epoch (1970-01-01T00:00:00Z)
- **Tag 2**: A byte string containing a positive bignum (arbitrary precision)
- **Tag 3**: A byte string containing a negative bignum
- **Tag 4**: An array `[exponent, mantissa]` representing a decimal fraction

MessagePack has "extension types" that serve a similar purpose, but they're application-defined and not standardized. CBOR tags come from an IANA registry, meaning there's a global agreement on what tag 0 means.

In practice, this matters for:
- **Datetime handling**: CBOR can natively represent timestamps with semantic meaning. MessagePack treats them as plain numbers or strings.
- **Big integers**: CBOR can encode integers of arbitrary size. MessagePack is limited to 64-bit integers.
- **Decimal fractions**: Important for financial data where floating-point approximation is unacceptable.

### CBOR vs MessagePack

| Feature | MessagePack | CBOR |
|---------|------------|------|
| Spec status | Community spec | IETF RFC 8949 |
| Datetime support | Extension types (manual) | Native tags (0, 1) |
| Big integers | Up to uint64 | Arbitrary precision |
| Decimal fractions | Not supported | Tag 4 |
| Binary data | bin 8/16/32 | Major type 2 |
| Canonical form | Not specified | Deterministic encoding |
| Primary ecosystem | Redis, Fluentd, web services | IoT, COSE, WebAuthn |

In payload size, they're nearly identical -- a typical FoodDash order is 1,289 bytes in MessagePack and 1,290 bytes in CBOR. The encoding strategies are similar enough that the wire size is effectively the same.

CBOR tends to be slower in Python benchmarks (the `cbor2` library is pure Python, while `msgpack` has a C extension), but this is an implementation detail, not a format limitation.

Neither format has won the "standard binary JSON" war. MessagePack has more adoption in web services (Redis, Fluentd, SignalR). CBOR has more adoption in security and IoT (COSE/JOSE, WebAuthn, CoAP).

---

## From Scratch: Building a MessagePack Encoder

The `msgpack_from_scratch.py` module implements a complete MessagePack encoder and decoder in pure Python, with no dependencies. The format is simple enough to implement in an afternoon.

The `msgpack_encode(obj)` function dispatches on Python type: `None` emits `0xc0`, booleans emit `0xc2`/`0xc3`, integers cascade through fixint/uint8/uint16/uint32/uint64, strings are length-prefixed UTF-8, bytes use the bin types, and dicts/lists use the map/array types. Note that `bool` must be checked before `int` since Python's `bool` is a subclass of `int`.

The integer cascade picks the smallest representation: 42 is 1 byte (fixint), 300 is 3 bytes (uint16), 123456789 is 5 bytes (uint32). JSON would use 2, 3, and 9 bytes respectively.

The speed advantage comes from **deterministic parsing**. A JSON parser scans each string character-by-character checking for escapes and closing quotes. A MessagePack decoder reads the type byte, extracts the length, and copies exactly that many bytes. No scanning, no escape handling -- one `memcpy` per string.

Our from-scratch encoder produces byte-identical output to the `msgpack` library for a typical FoodDash order (1,289 bytes), confirming the format is precisely specified.

---

## The Pain Points

MessagePack and CBOR solve the performance problem. They don't solve the contract problem.

### 1. Still Self-Describing

Every MessagePack message carries its own field names. In 1,000 typical FoodDash orders:

- **Total payload**: 1,289,000 bytes
- **Field name bytes**: 625,000 bytes
- **Field name share**: 48.5%

Nearly half the bytes are field names like `"platform_transaction_id"` (23 bytes), `"special_instructions"` (20 bytes), and `"estimated_delivery_minutes"` (26 bytes). These names are identical in every single message.

At 1M messages/second, that's roughly 596 MB/s of bandwidth spent transmitting the same field names over and over. A schema-based format like Protocol Buffers uses numeric tags (1-2 bytes) instead of string names (5-25 bytes), reducing field identifier overhead by 90%.

### 2. No Schema

When the kitchen service adds `prep_time_minutes`, MessagePack doesn't crash -- the new field is just another map entry. But there's no contract telling other services what fields exist, what types they have, which are required vs optional, or what default to use for missing fields. Every consumer must use `order.get("prep_time_minutes", None)` defensively. Across 20 teams, this convention is impossible to enforce.

### 3. No Schema Evolution Contract

**Adding a field**: old readers crash if strict (`dict["key"]`) or silently ignore if defensive (`dict.get()`). **Removing a field**: old readers get `KeyError` with no fallback.

Protocol Buffers solves this with stable numeric tags, default values for missing fields, unknown-tag skipping, and a rule to never reuse field numbers. MessagePack provides none of these guarantees.

### 4. Not Human-Readable

A JSON payload can be read with `cat`. A MessagePack payload is a wall of hex bytes that requires a hex viewer and the spec to interpret. You can't `grep` for a field name or `diff` two messages visually. At 3 AM during a production incident, this matters.

### 5. Field Name Cost at Scale

A typical FoodDash order contains 59 field name occurrences (34 unique names). The total field name overhead per message is 625 bytes -- including the MessagePack header byte for each string.

At FoodDash's scale of 1M messages/second:

| Metric | String Names (MsgPack) | Numeric Tags (Protobuf) |
|--------|----------------------|------------------------|
| Per-message field ID cost | 625 bytes | ~59 bytes |
| Bandwidth at 1M msg/s | ~596 MB/s | ~56 MB/s |
| Annual network cost | ~18 PB | ~1.7 PB |

That's an order-of-magnitude difference just from changing how fields are identified.

---

## Systems Constraints

### Size

MessagePack payloads are 22-31% smaller than JSON for FoodDash orders:

| Order Size | JSON | MsgPack | CBOR | MsgPack Savings |
|-----------|------|---------|------|----------------|
| Small (1 item) | 653 B | 453 B | 453 B | 30.6% |
| Typical (3 items) | 1,661 B | 1,289 B | 1,290 B | 22.4% |
| Large (20 items) | 22,477 B | 16,290 B | 16,290 B | 27.5% |

The savings come from:
- No quotes around strings (saves 2 bytes per string)
- No colons or commas (saves 1 byte per field and per array element)
- Compact integer encoding (42 is 1 byte instead of 2)
- Length prefixes instead of delimiters
- Native binary data (no base64 overhead for thumbnails)

### Encode/Decode Speed

MessagePack is 2-3x faster than JSON thanks to length prefixes (no character scanning), raw UTF-8 (no escape handling), type byte dispatch (no character-by-character inference), and fixed-width numbers. CBOR performance depends on implementation -- Python's `cbor2` is pure Python and slower, but native implementations match MsgPack.

### Memory

Both formats require full deserialization into Python dicts/lists, just like JSON (~3-8 KB per order). Schema-based formats like FlatBuffers can avoid this with zero-copy access.

### Benchmark Summary

Typical FoodDash order (3 items, driver assigned, metadata):

| Format | Payload Size | Encode (median) | Decode (median) |
|--------|-------------|-----------------|-----------------|
| JSON (stdlib) | 1,661 B | ~7 us | ~5 us |
| MessagePack | 1,289 B | ~3 us | ~3 us |
| CBOR | 1,290 B | ~8 us | ~6 us |

MessagePack is the clear winner on raw performance in Python, thanks to its C extension. CBOR is comparable to JSON in speed but offers the same size benefits as MessagePack.

---

## Production Depth

**Redis** uses RESP (Redis Serialization Protocol), which evolved from text (RESP2) to binary (RESP3) with the same type-prefix design as MessagePack. Redis chose a custom format for historical reasons, but the encoding strategy is identical.

**Fluentd / Fluent Bit** uses MessagePack as its internal log format. Every event is a MsgPack array of `[timestamp, record]`. At millions of log lines per second, the 2-3x speed advantage translates directly into lower infrastructure CPU.

**IoT and CBOR**: CBOR was designed for constrained devices. It's used in CoAP (HTTP for IoT), COSE (used by WebAuthn for authenticator attestation), and EDHOC (lightweight key exchange). The IETF chose CBOR over MsgPack for these standards because of its formal RFC, deterministic encoding, and semantic tags.

**SignalR** (Microsoft's real-time web framework) offers MessagePack as an alternative to JSON, reducing per-client bandwidth by 30-50%.

Neither MsgPack nor CBOR has won the "standard binary JSON" war. Web services lean MsgPack; standards bodies lean CBOR. Most APIs still use JSON because the tooling ecosystem is unbeatable. The real competitor is schema-based formats like Protocol Buffers.

---

## Trade-offs Table

| Dimension | JSON | MessagePack | CBOR |
|-----------|------|-------------|------|
| **Spec status** | ECMA-404 / RFC 8259 | Community spec | IETF RFC 8949 |
| **Data model** | map, array, string, number, bool, null | Same as JSON + binary | Same as JSON + binary + tags |
| **Schema** | None (JSON Schema is external) | None | None |
| **Schema evolution** | None | None | None |
| **Human readable** | Yes | No | No |
| **Binary data** | Base64 workaround | Native (bin types) | Native (byte strings) |
| **Integer precision** | Limited by IEEE 754 double | Up to uint64/int64 | Arbitrary (bignum tags) |
| **Datetime** | String convention | No standard | Tags 0 and 1 |
| **Payload size** | Baseline | 22-31% smaller | 22-31% smaller |
| **Encode speed** | Baseline | 2-3x faster | ~1x (Python impl) |
| **Decode speed** | Baseline | 2-3x faster | ~1x (Python impl) |
| **Streaming** | Possible but manual | Yes (natural) | Yes (indefinite-length) |
| **Tooling** | Excellent (browsers, curl, jq) | Moderate | Limited |
| **Adoption** | Universal | High (Redis, Fluentd) | Growing (IoT, WebAuthn) |

---

## The Bridge

MessagePack gave FoodDash binary efficiency: 30-50% smaller payloads, 2-3x faster parsing, and native binary data support. The CPU overhead of serialization dropped from 15% to 8%. The thumbnails stopped being base64-encoded. The wire protocol got leaner.

But three months in, FoodDash discovered a deeper problem. With 20 microservices, adding a single field to the Order message -- `prep_time_minutes`, an innocent integer -- crashed 5 services. The errors were predictable in retrospect: `KeyError`, `AssertionError`, unexpected field in strict validation. The fix required a coordinated deploy across all 20 services, which meant a change freeze, a deploy window, and a rollback plan.

The fundamental issue: MessagePack has no contract. There's no schema that says "these fields exist, these types are expected, these fields are optional." And there's no evolution story -- no way to say "this field was added in v2, old readers should ignore it" or "this field was removed in v3, use this default instead."

FoodDash needs a schema-first format where:

1. **The schema is defined in a file and shared between services.** Everyone agrees on what an Order looks like. The schema is checked into version control and reviewed like code.

2. **Fields have numeric tags instead of string names.** Instead of transmitting `"platform_transaction_id"` (23 bytes) in every message, transmit tag number 2 (1 byte). This saves bandwidth AND provides stable identifiers that survive field renames.

3. **Unknown tags are skipped instead of crashing.** When the kitchen service adds `prep_time_minutes` as tag 15, old services that don't know about tag 15 simply skip over it. No crash, no coordinated deploy, no change freeze.

4. **The schema enforces evolution rules.** You can add fields (with default values). You can deprecate fields (stop writing them). You can never reuse a tag number. The tooling catches violations at compile time, not at 3 AM in production.

That format is Protocol Buffers.
