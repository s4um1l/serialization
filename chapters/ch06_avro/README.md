# Chapter 06 -- Apache Avro: Schema-Driven Encoding with Automatic Resolution

```
uv run python -m chapters.ch06_avro
```

---

## The Scene

FoodDash has grown. Millions of orders per day flow through Apache Kafka into a data lake -- S3 buckets and HDFS clusters holding months of historical data. The analytics team runs nightly batch jobs over this data to compute metrics: average delivery time by neighborhood, peak ordering hours, revenue per restaurant.

Six months ago, the Order schema was at v3. Today it is at v7. The analytics team upgrades their pipeline to use v7 and kicks off a backfill over the historical data. It crashes immediately.

The problem: the data written six months ago was serialized with Protobuf using the v3 `.proto` file. The pipeline is trying to read it with the v7 `.proto` file. New fields like `loyalty_points` and `surge_pricing_cents` do not exist in the old data. Worse, the v3 `.proto` file was never checked into version control. It is gone. The team has no idea which fields existed in v3, which were added in v4, and which were renamed in v5.

Protobuf is schema-driven, but the schema is **external** to the data. You need the `.proto` file to decode, and you need to know which `.proto` version produced each file. For a data pipeline where files accumulate over months, this is a real operational problem.

Apache Avro takes a different approach: **the writer's schema is embedded in the data file header**. When a reader opens the file, it reads the writer's schema, compares it with its own (the reader's) schema, and automatically resolves the differences. New fields in the reader's schema get their default values. Fields that existed in the writer's schema but not the reader's are skipped. No crash, no data loss, no need to track `.proto` versions.

This is why Avro became the standard for Kafka event streaming and Hadoop data lakes: the schema travels with the data.

---

## How It Works: Avro Encoding

Avro's binary encoding is simpler than Protobuf in one critical way: **there are no field tags on the wire**. Fields are encoded in the order they appear in the schema, one after another, with no separators, no tags, no framing.

### The Core Encoding Rules

**Integers (int and long):** Zigzag-encoded variable-length integers, identical to Protobuf's `sint32`/`sint64`. The value 0 encodes as `0x00`, 1 as `0x02`, -1 as `0x01`, 300 as `0xd8 0x04`. Unlike Protobuf, Avro *always* uses zigzag -- there is no unsigned variant.

**Strings:** A zigzag varint length prefix followed by UTF-8 bytes. No null terminator. The string `"hello"` encodes as `0x0a 0x68 0x65 0x6c 0x6c 0x6f` (length 5 as zigzag varint = `0x0a`, then five UTF-8 bytes).

**Bytes:** Identical to strings but with raw bytes instead of UTF-8. This means binary data like PNG thumbnails go on the wire without base64 encoding.

**Booleans:** A single byte -- `0x00` for false, `0x01` for true.

**Doubles:** 8 bytes, little-endian IEEE 754. Same as Protobuf.

**Enums:** A zigzag varint index into the schema's symbol list. If the schema defines `["PLACED", "CONFIRMED", "PREPARING", ...]`, then `PLACED` encodes as `0x00`, `CONFIRMED` as `0x02`, etc.

**Unions:** A zigzag varint type index followed by the value. For `["null", "string"]`, null encodes as `0x00` (just the index, since null has zero bytes), and a string encodes as `0x02` (index 1) followed by the string bytes.

**Arrays:** A series of blocks. Each block starts with a zigzag varint count (number of items in the block), followed by that many encoded items. A count of 0 terminates the array. The array `[1, 2, 3]` with `int` items encodes as: `0x06` (count=3) `0x02 0x04 0x06` (zigzag-encoded 1, 2, 3) `0x00` (terminator).

**Maps:** Same block structure as arrays, but each entry is a string key followed by a value.

**Records:** This is where the magic happens. A record is just each field encoded in schema order, concatenated together. **No tags, no field numbers, no framing.** The reader must have the schema to know where one field ends and the next begins.

### Comparison With Protobuf

Consider encoding a simple point with x=42, y=-7, label="origin":

```
Protobuf (15 bytes):
  [08] [54]                    -- tag(field=1, varint) + zigzag(42)
  [10] [0d]                    -- tag(field=2, varint) + zigzag(-7)
  [1a] [06] [6f 72 69 67 69 6e] -- tag(field=3, len-del) + len(6) + "origin"

Avro (9 bytes):
  [54]                         -- zigzag(42)
  [0d]                         -- zigzag(-7)
  [0c] [6f 72 69 67 69 6e]    -- len(6) + "origin"
```

Protobuf needs 6 extra bytes for the three field tags. On a deeply nested message like our FoodDash Order with ~60 fields, the tag overhead adds up: Avro's typical Order encoding is 671 bytes vs Protobuf's 715 bytes -- a 6% reduction that comes entirely from eliminating field tags.

The trade-off is real: Protobuf's field tags make the wire format self-describing enough to skip unknown fields during decoding. Avro's wire format is opaque without the schema. This is acceptable when the schema is always available (embedded in a file header, or looked up from a Schema Registry), but it means you cannot inspect raw Avro bytes without the schema.

---

## Schema Resolution: The Killer Feature

Schema resolution is what makes Avro the dominant format for long-lived data. When a reader decodes Avro data, it does not simply use its own schema -- it reconciles its schema (the "reader schema") with the schema that was used to write the data (the "writer schema").

### Resolution Rules

1. **Fields are matched by NAME**, not by position and not by number. This is fundamentally different from Protobuf, where fields are identified by their field number. In Avro, the field `tip_cents` in the writer schema matches `tip_cents` in the reader schema regardless of where each appears in the field list.

2. **Writer has a field, reader does not:** The field's data is **skipped** during decoding. This provides forward compatibility: an old reader can process data from a new writer without crashing.

3. **Reader has a field, writer does not:** The field's **default value** is used. This provides backward compatibility: a new reader can process data from an old writer. The field must have a default value in the reader schema -- otherwise it is an error.

4. **Both have the field, same type:** Direct read. The normal case.

5. **Both have the field, different types:** An error, unless the types are promotable (int to long, float to double).

### Worked Example

FoodDash evolves its Order schema through three versions:

- **v1:** The original schema. No `tip_cents` field.
- **v2:** Adds `tip_cents` with default `0`.
- **v3:** Adds `loyalty_points` with default `0`.

**Scenario 1: Writer v1, Reader v2 (backward compatible)**

A message written with v1 contains no `tip_cents` data. When a v2 reader decodes it, the resolution engine sees that `tip_cents` exists in the reader schema but not the writer schema. It fills in the default value of 0. No crash, no data loss.

**Scenario 2: Writer v3, Reader v2 (forward compatible)**

A message written with v3 contains `loyalty_points = 1500`. When a v2 reader decodes it, the resolution engine sees that `loyalty_points` exists in the writer schema but not the reader schema. It skips those bytes during decoding. The v2 reader never sees the field. No crash.

**Scenario 3: Writer v1, Reader v3 (two versions apart)**

A message written with v1 is read by a v3 reader. Both `tip_cents` and `loyalty_points` are missing from the writer data. Both get their defaults (0). The reader processes the message as if those fields were always zero.

This works across any number of schema versions, as long as every new field has a default value. In practice, Avro schemas in production Kafka deployments can span 50+ versions without breaking readers.

### Schema Ordering Does Not Matter

Because fields match by name, the order of fields in the schema is irrelevant for resolution. If the writer schema has fields `[a, b, c]` and the reader schema has fields `[c, a, b]`, resolution still works: `a` matches `a`, `b` matches `b`, `c` matches `c`. The data is decoded in the writer's field order, then mapped to the reader's field names.

---

## The Schema Registry Pattern

In a Kafka-based architecture, messages are small and numerous. Embedding the full schema in every message would be wasteful -- a typical Avro schema for our Order is ~2KB of JSON, while the encoded message is ~670 bytes. The solution is the **Schema Registry**: a central service that stores versioned schemas and assigns each one a numeric ID.

### Confluent Wire Format

The de facto standard (from Confluent) adds exactly 5 bytes of overhead per message:

```
[0x00] [schema_id: 4 bytes, big-endian] [Avro payload]
```

- **Magic byte (0x00):** Distinguishes this format from raw Avro container files (which start with `Obj\x01`).
- **Schema ID:** A 32-bit integer that uniquely identifies the writer's schema in the registry.
- **Payload:** The Avro-encoded message (schemaless -- no file header).

### The Flow

1. **Producer writes:** Serializes the message, registers the schema with the registry (idempotent -- same schema returns the same ID), prepends the 5-byte header.
2. **Kafka stores:** The topic holds messages with the 5-byte header. Kafka does not interpret the contents.
3. **Consumer reads:** Strips the 5-byte header, extracts the schema ID, fetches the writer's schema from the registry, resolves it against the consumer's reader schema, and decodes the payload.

### Compatibility Modes

The Schema Registry enforces compatibility rules when new schema versions are registered:

- **BACKWARD (default):** New reader schema can read data written with the previous schema. In practice: you can add fields with defaults, but you cannot remove fields without defaults.
- **FORWARD:** Old reader schema can read data written with the new schema. In practice: you can remove fields, but you cannot add required fields.
- **FULL:** Both backward and forward compatible. The safest mode.
- **NONE:** No compatibility checking. Use with caution.

In large Kafka deployments, the Schema Registry can hold 100,000+ schema versions across thousands of subjects. Each subject typically corresponds to a Kafka topic.

---

## Systems Constraints

### Payload Size

Avro produces the smallest payloads of any schema-based format we have studied:

| Format | Typical Order | vs Avro |
|--------|-------------|---------|
| JSON | ~1,661 B | 2.5x larger |
| MsgPack | ~1,000 B | 1.5x larger |
| Protobuf | ~715 B | 1.07x larger |
| **Avro** | **~671 B** | **baseline** |

The size advantage over Protobuf comes entirely from eliminating field tags. Over millions of messages, this adds up to significant bandwidth and storage savings.

### Encode/Decode Speed

Avro's encoding speed is comparable to Protobuf: both walk the schema and write field values sequentially. fastavro (a C-accelerated Python library) achieves ~14 microseconds per encode for a typical Order, similar to our from-scratch Protobuf encoder.

Decoding is where schema resolution adds overhead. When the writer and reader schemas differ, the decoder must map fields between schemas. With fastavro, decoding a typical Order takes ~10 microseconds. For identical schemas, it is faster; for highly divergent schemas, it is slower.

### Memory Usage

Like Protobuf and unlike FlatBuffers, Avro requires full deserialization. The decoded result is a Python dict (or equivalent in other languages). There is no zero-copy access to individual fields. This is the main trade-off compared to FlatBuffers.

### Benchmark Summary

| Format | Size | Encode (median) | Decode (median) |
|--------|------|-----------------|-----------------|
| JSON | 1,661 B | ~6.5 us | ~5.0 us |
| Protobuf (scratch) | 715 B | ~16 us | ~22 us |
| Avro (fastavro) | 671 B | ~14 us | ~10 us |
| Avro (scratch) | 671 B | ~22 us | ~22 us |

JSON's speed advantage is due to Python's built-in C JSON implementation. The Avro and Protobuf "scratch" implementations are pure Python. fastavro's C extensions make it competitive with the JSON module despite producing payloads 60% smaller.

---

## Production Depth

### Apache Kafka + Avro + Schema Registry

This is **the** standard combination for event streaming in large organizations. Companies like LinkedIn (where Avro was created), Netflix, Uber, and Airbnb use this stack to process billions of events per day.

The pattern works because Kafka topics are long-lived: data may sit in a topic for days or weeks (or indefinitely with compacted topics). Producers and consumers are deployed independently, potentially running different schema versions at the same time. The Schema Registry ensures that any consumer can decode any message, regardless of when it was produced and which schema version was used.

### Apache Hadoop / Spark

Avro is a native file format in the Hadoop ecosystem. HDFS stores `.avro` files with embedded schemas. Apache Spark can read and write Avro files natively. Because the schema is in the file header, Spark can read data written years ago without any external schema management -- the file is self-contained.

### Confluent Schema Registry at Scale

Production deployments of the Confluent Schema Registry handle:

- **100K+ schema versions** across thousands of subjects
- **Millions of lookups per second** (schema IDs are cached on the client side)
- **Sub-millisecond latency** for schema lookups (after initial cache warmup)
- **High availability** through Kafka-backed storage (the schemas themselves are stored in a compacted Kafka topic)

### Avro vs Protobuf for Kafka

Both Avro and Protobuf work with Kafka. Confluent provides serializers for both. The key differences:

- **Schema resolution:** Avro resolves writer/reader schemas automatically. Protobuf requires the consumer to handle missing fields manually (or rely on default values being acceptable).
- **Schema embedding:** Avro container files embed the schema. Protobuf files do not -- you need the `.proto` file separately.
- **Schema Registry support:** Both are supported. Avro has deeper integration because it was designed for this use case.
- **Speed:** Protobuf is generally faster in compiled languages (C++, Go, Java). In Python, fastavro is comparable to the protobuf library.
- **Ecosystem:** Avro is the default in the Hadoop/Spark/Kafka ecosystem. Protobuf is the default in the gRPC/microservices ecosystem.

---

## Trade-offs Table

| Dimension | JSON | MsgPack | CBOR | Protobuf | FlatBuffers | **Avro** |
|-----------|------|---------|------|----------|-------------|----------|
| **Schema** | None | None | None (or CDDL) | `.proto` file | `.fbs` file | `.avsc` JSON |
| **Schema on wire** | No | No | No | No | No | **Yes** (file header) |
| **Schema resolution** | N/A | N/A | N/A | Manual | Manual | **Automatic** |
| **Field identification** | Names | Names | Names | Numbers | Offsets | **Schema order** |
| **Field tags on wire** | Names | Names | Names | 1-2 B/field | vtable | **None** |
| **Payload size** | Largest | Medium | Medium | Small | Medium+vtable | **Smallest** |
| **Zero-copy decode** | No | No | No | No | **Yes** | No |
| **Human readable** | **Yes** | No | No | No | No | No |
| **Binary data** | Base64 | Native | Native | Native | Native | **Native** |
| **Primary ecosystem** | Web | Caching | IoT | gRPC | Games | **Kafka/Hadoop** |
| **Schema evolution** | N/A | N/A | N/A | Good | Good | **Best** |
| **Decode without schema** | **Yes** | **Yes** | **Yes** | Partial | No | **No** |
| **Typical encode speed** | Fast (C impl) | Fast | Medium | Medium | Slow (builder) | Medium |
| **Typical decode speed** | Fast (C impl) | Fast | Medium | Medium | **Instant** (zero-copy) | Medium |

Key takeaway: Avro wins on schema evolution and payload size, but loses on decode flexibility (requires the schema) and decode speed (no zero-copy). It is purpose-built for data pipelines where schemas are managed centrally and data is long-lived.

---

## The Bridge

Avro solved the data pipeline problem: the schema travels with the data, and reader/writer schemas are resolved automatically. Six months of historical data? No problem -- the file header contains the writer's schema, and the reader's schema fills in the gaps.

But step back and look at what we have been doing across these chapters. We started with text (JSON), moved to binary (MsgPack), added schemas (Protobuf), eliminated deserialization (FlatBuffers), and now eliminated field tags (Avro). Each step made the payload smaller or the parsing faster.

Yet every format so far has a fundamental step: you write data into some wire format, and you read it back out. Even FlatBuffers, which avoids deserialization, still requires a "builder" step to construct the buffer. Avro requires schema-driven encoding. Protobuf requires varint encoding. There is always an encoding step.

What if we eliminated that step entirely? What if the in-memory representation of your data **was** the wire format? No serialization at all. No deserialization at all. You write a struct into memory, and you send those bytes directly. The receiver reads the bytes directly as a struct. Zero encoding, zero decoding.

Kenton Varda, the author of Protocol Buffers v2 at Google, asked exactly this question when he left Google and created Cap'n Proto. The result is a format where the memory layout IS the wire format -- but with the schema evolution guarantees of Protobuf.

In Chapter 07, we will see how Cap'n Proto achieves this, and what it gives up in return.
