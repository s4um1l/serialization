# Chapter 02 — JSON: The Lingua Franca of Web APIs

## The Scene

The CSV postmortem is still warm on the wiki when the API team proposes the obvious fix: JSON. Every engineer on FoodDash already knows the syntax. Every language ships a JSON library in its standard distribution. The Python services call `json.dumps()`, the JavaScript frontend calls `JSON.parse()`, and the mobile team barely notices the migration. No more flattening nested menu items into comma-separated rows. No more arguing about whether `"true"` means the boolean or the string. No more character encoding roulette.

The first month is bliss. The order service emits clean, nested JSON. The kitchen display service parses it without edge-case code. The mobile app renders real-time order tracking from the same stream. The new driver assignment service, written in Go, consumes the same messages with `encoding/json`. The team ships three new microservices in three weeks, each speaking JSON over HTTP, and nobody writes a single line of parsing code by hand.

Then the traffic grows. FoodDash signs a national restaurant chain, and daily order volume triples in two weeks. The monitoring dashboard begins to glow. JSON serialization is now consuming 15 percent of CPU on the order service. The garbage collector runs every few seconds, chasing transient string allocations from `json.dumps()`. Memory usage on the notification service spikes during dinner rush because a batch of 10,000 order updates balloons into a 48 MB JSON array where 40 percent of the bytes are just the same field names repeated ten thousand times.

Then the incident.

The billing service reconciles a high-value catering order: platform transaction ID `9007199254740993`, a 17-digit number that fits comfortably in a 64-bit integer. The reconciliation fails. The frontend dashboard shows the transaction as `9007199254740992`. One digit off. Nine hundred billion dollars' worth of trust, undermined by a single bit.

The postmortem reads:

> **Root cause:** JSON numbers are IEEE 754 doubles. JavaScript's `Number` type cannot represent integers above 2^53 exactly. The platform_transaction_id `9007199254740993` (which is 2^53 + 1) was silently rounded to `9007199254740992` when the JavaScript frontend parsed the JSON response. No error was raised. The billing reconciliation then failed because the IDs did not match.

JSON solved CSV's problems beautifully. But it introduced an entirely new class of failures: precision loss, bandwidth waste, and the complete absence of a schema contract. This chapter dissects exactly how JSON works at the byte level, demonstrates each failure mode with running code, and builds the case for something better.

---

## How It Works: The JSON Format

JSON (JavaScript Object Notation) is defined by [RFC 8259](https://datatracker.ietf.org/doc/html/rfc8259), published in December 2017. The specification is remarkably short: roughly 16 pages. That brevity is both its greatest strength and the source of its most dangerous ambiguities.

### The Six Data Types

JSON supports exactly six data types:

1. **String** -- A sequence of Unicode characters enclosed in double quotes. Supports escape sequences: `\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`, `\t`, and `\uXXXX` for arbitrary Unicode code points. The encoding is UTF-8 (RFC 8259 requires this).

2. **Number** -- A decimal number that may have a fractional part and an exponent. There is no distinction between integer and floating-point. The specification says implementations may impose limits on range and precision, but does not mandate any. In practice, most implementations use IEEE 754 double-precision floating-point, which means integers above 2^53 lose precision silently.

3. **Object** -- An unordered collection of key-value pairs enclosed in curly braces. Keys must be strings. Values can be any JSON type, including nested objects. The specification does not prohibit duplicate keys but says behavior is "unpredictable" if they appear.

4. **Array** -- An ordered sequence of values enclosed in square brackets. Elements can be any JSON type, and types can be mixed within a single array.

5. **Boolean** -- Either `true` or `false` (lowercase, no quotes).

6. **Null** -- The literal `null`, representing the absence of a value.

That is the complete type system. Notice what is missing:

- No integer type (everything is a number)
- No binary data type (you must base64-encode and transmit as a string)
- No date/time type (you must choose a string representation: ISO 8601, Unix timestamp, or something custom)
- No distinction between absent and null (a missing key and a key with value `null` may or may not mean the same thing, depending on who wrote the code)

### Self-Describing Format

Every JSON message carries its own structure. Field names travel with every single message. If you send 10,000 orders, the string `"platform_transaction_id"` appears 10,000 times. This is what "self-describing" means: any consumer can inspect the payload and understand its structure without external metadata.

This is simultaneously JSON's greatest usability feature and its most expensive performance characteristic.

### The Wire Format

JSON is a text format. A JSON object is a sequence of UTF-8 bytes that a human can read in a text editor. There is no binary header, no type prefix byte, no length prefix. The parser must scan every character to determine structure. To find the value of the last field in an object, you must parse every character from the opening brace to reach it. There is no random access.

---

## From Scratch: Building a JSON Encoder

The file `json_from_scratch.py` builds a complete JSON encoder and decoder without using Python's `json` module. This is educational: it demonstrates that JSON encoding is fundamentally string concatenation with escape rules.

### The Encoder

The encoder is a recursive function `json_encode(obj) -> str`. It examines the type of its input and dispatches accordingly:

```
json_encode(obj):
    if obj is None:     return "null"
    if obj is bool:     return "true" or "false"
    if obj is int:      return str(obj)
    if obj is float:    return repr(obj)      # handles precision
    if obj is str:      return escape_and_quote(obj)
    if obj is bytes:    return base64_encode(obj)
    if obj is list:     return "[" + join(map(json_encode, obj)) + "]"
    if obj is dict:     return "{" + join(key:value pairs) + "}"
```

The critical detail is in string encoding. Every string must be scanned character by character to escape special characters:

- `"` becomes `\"`
- `\` becomes `\\`
- Newline becomes `\n`
- Tab becomes `\t`
- Control characters (code points below 0x20) become `\uXXXX`
- Everything else passes through unchanged

This character-by-character scanning is why JSON encoding is CPU-intensive. For a typical FoodDash order with hundreds of string characters across field names and values, the encoder touches every single character and builds a new string.

### The Decoder: Recursive Descent Parsing

The decoder uses the classic recursive descent approach. It maintains a position cursor into the input string and processes characters one at a time:

1. Skip whitespace
2. Peek at the next character
3. Branch:
   - `"` means parse a string (scan until unescaped `"`, process escape sequences)
   - `{` means parse an object (parse key-value pairs until `}`)
   - `[` means parse an array (parse values until `]`)
   - `t` means parse `true`
   - `f` means parse `false`
   - `n` means parse `null`
   - Digit or `-` means parse a number

This is inherently sequential. The parser cannot skip ahead, cannot process fields in parallel, and cannot determine the type of a value without first examining its bytes. Every character in the payload is visited at least once. For a 2 KB order, that means 2,048 character comparisons, branch decisions, and string allocations just to parse a single message.

### Byte-Level Anatomy

When we encode a typical FoodDash order and analyze the resulting bytes, the breakdown is revealing:

- **Structural characters** (`{}[]:,`): roughly 8-12% of the payload. These are the syntactic scaffolding that makes JSON human-readable.
- **Quote characters** (`"`): roughly 15-20%. Every string requires two quotes, every field name requires two quotes. A single key-value pair like `"status": "placed"` uses four quote characters for sixteen data characters.
- **Data bytes**: the actual field names and values, roughly 60-70%.
- **Whitespace**: zero in compact JSON, up to 30% in pretty-printed.

The structural overhead (braces, brackets, colons, commas, quotes) typically accounts for 25-35% of a compact JSON payload. That means roughly one in three bytes carries no data.

---

## The Pain Points

The code in `pain_points.py` demonstrates five specific failure modes. Each one has caused real production incidents.

### 1. Float Precision

JSON has a single number type. When you write `0.1` in JSON, the parser reads the characters `0`, `.`, `1` and converts them to the nearest IEEE 754 double-precision floating-point value. That value is not exactly 0.1. It is `0.1000000000000000055511151231257827021181583404541015625`.

This means:

```python
>>> 0.1 + 0.2
0.30000000000000004
>>> 0.1 + 0.2 == 0.3
False
```

This survives JSON round-tripping. If a service encodes `0.1 + 0.2` into JSON and another service parses it, the result is still `0.30000000000000004`, not `0.3`.

For FoodDash, the real danger is money. If a service stores a price as `19.99` (a float), then computes `19.99 * 100` to get cents, the result is `1998.9999999999998`, not `1999`. Truncating to int gives `1998`. The customer is undercharged by one cent. Multiply by a million orders a day, and you have a significant revenue leak.

The solution is to use integer cents everywhere: `price_cents: 1999`. Integers below 2^53 are exact in JSON. But JSON provides no way to enforce this convention. A new engineer can add a `price` field as a float, and JSON will happily encode and decode it without complaint.

### 2. Large Integer Precision (The 2^53 Boundary)

IEEE 754 double-precision floating-point uses 52 bits for the significand (plus one implicit bit), giving 53 bits of integer precision. This means integers up to 2^53 (9,007,199,254,740,992) can be represented exactly. One more, and precision is lost:

```
2^53 - 1 = 9007199254740991  ->  exact
2^53     = 9007199254740992  ->  exact
2^53 + 1 = 9007199254740993  ->  rounds to 9007199254740992
```

The FoodDash platform generates transaction IDs using a distributed ID service (similar to Twitter's Snowflake). These IDs are 64-bit integers. As the platform scales, IDs eventually cross the 2^53 boundary. Python handles this fine because Python integers have arbitrary precision. But the JavaScript frontend, the React Native mobile app, and any service using a JSON parser that maps numbers to IEEE 754 doubles will silently truncate the ID.

The recommended workaround is to encode large integers as strings in JSON: `"platform_transaction_id": "9007199254740993"`. But this means the receiving service must know to parse that string back to an integer, which requires out-of-band knowledge that JSON does not provide.

### 3. Binary Data Overhead (base64 Bloat)

JSON is a text format. It has no binary data type. To transmit binary data (images, protobuf payloads, encrypted tokens), you must encode the bytes as text. The standard approach is base64 encoding.

base64 works by taking every 3 bytes of input and encoding them as 4 ASCII characters (using the alphabet `A-Za-z0-9+/`). This means:

- 3 bytes of binary become 4 bytes of text: **33% inflation**
- Plus 2 bytes for the surrounding JSON quotes
- Plus any prefix marker you add (FoodDash uses `$base64:`)

For a large FoodDash order with 20 menu item thumbnails (each a small PNG), the binary data can be several kilobytes. After base64 encoding, it grows by a third. In a batch of 1000 orders, that overhead adds up to megabytes of wasted bandwidth.

A binary serialization format could transmit those same bytes with zero overhead: a length prefix followed by the raw bytes.

### 4. Repeated Field Names

When FoodDash encodes a batch of 1000 orders as a JSON array, every single order carries its own complete set of field names. The string `"platform_transaction_id"` (24 characters plus quotes and colon = 27 bytes) appears 1000 times, consuming 27,000 bytes for a single field name.

Across all fields in a typical order (approximately 30-40 unique field names when you include nested objects), the field-name overhead in a batch of 1000 orders can reach 35-45% of the total payload. Nearly half the bytes on the wire are just repeating the same strings over and over.

A schema-based format like Protocol Buffers assigns each field a numeric tag (1-2 bytes) instead of a string name. That same batch of 1000 orders would use 1-2 bytes per field per order instead of 10-30 bytes. The savings compound with batch size.

### 5. No Schema Enforcement

JSON is "self-describing" but not "self-validating." Any valid JSON document is accepted by any JSON parser, regardless of whether it makes semantic sense. You can:

- Misspell field names: `"statsu"` instead of `"status"` parses fine
- Use wrong types: `"price_cents": "free"` parses fine
- Omit required fields: an order with no items parses fine
- Add unexpected fields: an order with a `"nuclear_launch_codes"` field parses fine

The parser cannot distinguish between a valid order and garbage. Validation must happen in application code, after parsing. This means every service must implement its own validation logic, and inconsistencies between services are inevitable.

JSON Schema exists as a separate specification that can validate JSON documents against a declared schema. But it is not part of JSON itself, not enforced by the parser, and not universally adopted. It adds complexity without the tight integration of a format that carries its schema in the payload.

---

## Systems Constraints

### Encode Speed

JSON encoding is fundamentally string concatenation. The encoder must:

1. Visit every node in the object tree
2. Convert each value to its string representation
3. Escape all string characters
4. Add structural characters (braces, brackets, colons, commas, quotes)
5. Concatenate everything into a single string

In Python's standard library, this is implemented in pure Python with a C accelerator for string escaping. Libraries like orjson (written in Rust) achieve 3-10x speedups by avoiding intermediate string allocations and using SIMD instructions for escape scanning.

For a typical FoodDash order (~2 KB JSON), Python's `json.dumps()` takes roughly 50-150 microseconds. orjson reduces this to 10-30 microseconds. At 100,000 messages per second, the difference is 5-15 seconds of CPU time per second saved -- which is the difference between needing 3 servers and needing 1.

### Decode Speed

JSON decoding is slower than encoding because the parser must:

1. Scan every character to determine structure
2. Process escape sequences in strings
3. Parse number strings into numeric values
4. Allocate objects, arrays, and strings
5. Build the complete object tree in memory

There is no random access. To read a single field from a 2 KB JSON object, you must parse the entire object. There is no way to seek to a specific field without scanning every character before it.

### Wire Size

JSON payloads are large compared to binary alternatives:

- Field names as text strings (vs. 1-2 byte numeric tags)
- Numbers as decimal text (vs. fixed-width binary: `1700000000.0` is 14 bytes in JSON, 8 bytes as a double, 4 bytes as a float)
- Binary data as base64 (33% inflation vs. raw bytes)
- Structural characters (braces, brackets, colons, commas, quotes): 25-35% overhead
- No compression by default

A typical FoodDash order is ~2 KB in JSON. The same data in Protocol Buffers is ~400-600 bytes. In MessagePack, ~900-1200 bytes.

### Memory

Parsing JSON requires building the complete object tree in memory. There is no streaming parse that yields individual fields (you can stream JSON tokens, but reassembling them into objects requires application logic). For a 48 MB batch of 10,000 orders, the parser allocates at least 48 MB of strings and objects, plus overhead for the Python dict and list structures.

### Benchmark: JSON stdlib vs orjson

The `json_stdlib.py` module benchmarks both implementations on a typical FoodDash order. On a modern machine, you will typically see:

| Implementation | Encode (median) | Decode (median) | Payload size |
|----------------|-----------------|-----------------|-------------|
| json (stdlib)  | 50-150 us       | 30-80 us        | ~2 KB       |
| orjson (Rust)  | 10-30 us        | 8-20 us         | ~2 KB       |

The speedup is real but does not fix the fundamental problems: the payload is still large, field names are still repeated, and large integers still lose precision.

---

## Production Depth

### REST APIs

JSON is the default wire format for HTTP APIs. The combination of HTTP + JSON is so dominant that many developers treat them as synonymous. When a service exposes a REST API, the request and response bodies are almost always JSON.

The `Content-Type: application/json` header signals JSON encoding. Most HTTP frameworks (Flask, Express, Spring Boot, Gin) have built-in JSON serialization and deserialization. The developer writes Python dicts or Java POJOs, and the framework converts them to JSON automatically.

This deep integration is why JSON is so hard to displace. Every tool in the web ecosystem speaks JSON: browsers, API gateways, load balancers, logging systems, monitoring dashboards.

### Browser Compatibility

Every modern browser ships `JSON.parse()` and `JSON.stringify()` as built-in functions. They are among the most performance-optimized functions in the JavaScript engine. No import, no library, no setup. This is why JSON dominates client-server communication: the browser already speaks it.

The irony is that JavaScript's `Number` type (IEEE 754 double) is also the source of JSON's most dangerous precision bug.

### JSON Schema

[JSON Schema](https://json-schema.org/) is a separate specification (draft 2020-12 is the latest) that describes the expected structure of a JSON document. You define a schema as a JSON document itself:

```json
{
  "type": "object",
  "required": ["id", "status", "customer"],
  "properties": {
    "id": {"type": "string"},
    "status": {"type": "string", "enum": ["placed", "confirmed", "delivered"]},
    "customer": {"$ref": "#/$defs/Customer"}
  }
}
```

JSON Schema adds validation but not enforcement. The JSON parser does not check the schema; a separate validation step is required. This means schema validation is optional, often inconsistent across services, and adds latency to every request.

### NDJSON (Newline-Delimited JSON)

Standard JSON arrays require the entire array to be in memory before parsing can complete. NDJSON (also called JSON Lines) is a convention where each line is a complete JSON object:

```
{"id": "ord00001", "status": "placed"}
{"id": "ord00002", "status": "confirmed"}
{"id": "ord00003", "status": "delivered"}
```

This enables streaming: each line can be parsed independently as it arrives. FoodDash uses NDJSON for log shipping and real-time event streams. It is not a separate format but a convention on top of JSON.

### JSON in Databases

PostgreSQL's `JSONB` type stores JSON in a decomposed binary format that supports indexing and efficient querying. Despite the name, JSONB is not JSON on the wire; it is an internal storage format.

MongoDB uses BSON (Binary JSON), which is a binary encoding of a JSON-like data model. BSON adds types that JSON lacks: 64-bit integers, dates, binary data, ObjectId. But BSON is specific to MongoDB and not used as a general interchange format.

These adaptations demonstrate a pattern: JSON's data model is useful, but its text encoding is not efficient enough for storage or high-throughput communication. Every system that needs performance takes JSON's model and re-encodes it in binary.

---

## Trade-offs Table

| Property | JSON |
|---|---|
| Human-readable | Yes -- any text editor can display it |
| Nesting | Yes -- objects and arrays nest arbitrarily |
| Types | Partial -- string, number, boolean, null, object, array. No int vs float, no binary, no date |
| Schema | No -- self-describing but not self-validating. JSON Schema exists as a separate layer |
| Binary data | No native support -- must base64-encode (33% overhead) |
| Wire size | Large -- repeated field names, text-encoded numbers, structural overhead |
| Encode speed | Moderate -- string building, escape scanning (orjson 3-10x faster than stdlib) |
| Decode speed | Slow -- character-by-character scanning, no random access, full parse required |
| Schema evolution | Flexible but unsafe -- add fields freely, but no contract enforcement |
| Language support | Universal -- every language has a JSON library |
| Tooling | Excellent -- browser devtools, curl, jq, every API tool |

---

## The Bridge

JSON solved CSV's problems. We have nesting: orders contain items that contain menu items, three levels deep, no flattening required. We have types: strings are strings, numbers are numbers, booleans are booleans, null is null. We have a defined encoding: UTF-8, specified by RFC 8259, no more character set ambiguity.

But we hit new walls.

Forty percent of our bytes are repeated field names. The string `"platform_transaction_id"` appears in every single order message, ten thousand times in a batch, consuming bandwidth and memory for information that both the sender and receiver already know.

Binary data is inflated by 33 percent. Every thumbnail, every encrypted payment token, every protobuf sub-message that we carry as a nested payload must be base64-encoded into text, inflating 3 bytes into 4 characters.

Large integers lose precision. Transaction IDs above 2^53 are silently rounded when parsed by JavaScript, causing reconciliation failures that are invisible until someone audits the numbers.

And parsing means scanning every character. To find the `status` field in an order, the parser must read every byte from the opening brace, through the customer object, through the items array, one character at a time. There is no index, no offset table, no way to jump to the field you need.

What if we kept JSON's data model -- maps, arrays, strings, numbers, booleans, null -- but encoded it in binary? A type prefix byte instead of syntax characters. Binary strings with a length prefix instead of escaped text delimited by quotes. Native binary data support: just a length prefix and the raw bytes, no base64 inflation. Numeric tags instead of string field names. Integer types distinct from float types.

That is MessagePack.
