# Glossary

Quick-reference for serialization terminology used throughout this repo.

---

## Core Concepts

**Serialization (marshalling, encoding)**
Converting an in-memory object into a sequence of bytes suitable for storage or transmission.

**Deserialization (unmarshalling, decoding, parsing)**
Converting a sequence of bytes back into an in-memory object.

**Wire format**
The byte-level encoding of data as it appears on the network or on disk. "What the bytes look like."

**In-memory representation**
How the runtime (Python, Go, JVM) stores an object — heap pointers, vtables, reference counts, padding. Not portable.

**Round trip**
Serialize → transmit/store → deserialize. A format has *round-trip fidelity* if the deserialized object is identical to the original.

**Payload**
The serialized bytes. "The message on the wire."

---

## Binary Encoding

**Endianness (byte order)**
The order in which bytes of a multi-byte value are stored. *Big-endian* (most significant byte first) is network byte order. *Little-endian* (least significant byte first) is used by x86/ARM.

**Alignment / padding**
Inserting unused bytes so that fields start at memory addresses that are multiples of their size. Required by many CPUs for efficient access.

**Varint (variable-length integer)**
An encoding where small integers use fewer bytes. Used by Protocol Buffers (LEB128) and Avro (zigzag).

**LEB128 (Little-Endian Base 128)**
Varint encoding where each byte uses 7 bits for data and 1 bit to signal continuation. Used by Protobuf.

**Zigzag encoding**
Maps signed integers to unsigned integers so that small negative numbers also use few bytes: 0→0, -1→1, 1→2, -2→3, 2→4. Used by Protobuf and Avro for signed fields.

**TLV (Type-Length-Value)**
A generic encoding pattern: a tag byte identifies the type, a length byte says how many bytes follow, then the value. Many binary formats are variations of TLV.

---

## Schema Concepts

**Schema**
A formal definition of the structure: field names, types, required/optional. Exists as a file (.proto, .avsc, .fbs, .capnp) or in a registry.

**Schema evolution**
Changing the schema over time — adding fields, removing fields, changing types — without breaking existing readers or writers.

**Forward compatibility**
Old code can read data written by new code. "I don't know about the new field, but I won't crash."

**Backward compatibility**
New code can read data written by old code. "The old data doesn't have the new field, but I have a default."

**Full compatibility**
Both forward and backward compatible. The gold standard.

**Field tag (field number)**
A numeric identifier for a field, used instead of the field name on the wire. Protobuf, FlatBuffers, and Cap'n Proto use field tags. Changing the tag breaks compatibility.

**Schema Registry**
A centralized service that stores versioned schemas. Writers register their schema and embed the schema ID in each message. Readers look up the schema by ID. Used by Confluent Schema Registry with Avro/Kafka.

**Writer's schema / Reader's schema**
In Avro, the schema used to encode the data (writer's) and the schema the reader expects (reader's). Avro resolves differences automatically at read time.

---

## Format Categories

**Self-describing format**
The encoded data includes enough information to decode it without external schema: field names, type indicators. JSON, MessagePack, CBOR are self-describing.

**Schema-dependent format**
The encoded data only makes sense with the schema. Without it, the bytes are meaningless. Protobuf, FlatBuffers, Avro, Cap'n Proto.

**Text format**
Human-readable encoding using printable characters. CSV, JSON, XML, YAML.

**Binary format**
Compact encoding using the full byte range (0x00–0xFF). MessagePack, CBOR, Protobuf, FlatBuffers, Avro, Cap'n Proto.

---

## Performance Concepts

**Zero-copy deserialization**
Reading fields directly from the serialized buffer without allocating new objects or copying data. FlatBuffers and Cap'n Proto support this.

**Parsing overhead**
CPU time spent converting bytes into objects. Text formats (JSON) require character-by-character scanning. Binary formats use offset-based access.

**Base64**
Encoding binary data as printable ASCII characters. Uses 4 characters per 3 bytes of binary data — a 33% size overhead. Required when embedding binary data in JSON.

**Serialization tax**
The total CPU, memory, and bandwidth cost of serialization across all messages. At 1M msg/s, even microsecond differences matter.

---

## Compression

**Lossless compression**
Reducing payload size without losing information. All algorithms in this repo are lossless.

**gzip (zlib/deflate)**
Widely supported, good compression ratio, moderate speed. The default for HTTP Content-Encoding.

**zstd (Zstandard)**
Facebook's compressor. Better ratio than gzip at similar or faster speed. Supports dictionary compression. Used by Kafka, Linux kernel.

**Snappy**
Google's compressor. Moderate ratio, very fast. Used by Bigtable, LevelDB.

**LZ4**
Extremely fast compression and decompression. Lower ratio than zstd. Used when speed matters more than size.

**Dictionary compression**
Training a compression dictionary on representative data, then using it to compress individual small messages more effectively. Critical for compressing small messages (< 1KB) which are too short for regular compression to find patterns.

---

## Production Systems

**gRPC**
Google's RPC framework. Uses Protobuf for serialization and HTTP/2 for transport. Generates client/server code from .proto files.

**Apache Kafka**
Distributed event streaming platform. Commonly uses Avro + Schema Registry for message serialization.

**Apache Avro**
Created for Hadoop. Schema resolution (writer ↔ reader) makes it ideal for data pipelines where data outlives the code that wrote it.

**Protocol Buffers (Protobuf)**
Google's schema-first binary format. The most widely used binary serialization format. Used by gRPC, Google's internal systems, and many open-source projects.

**FlatBuffers**
Google's zero-copy format. Created for game development (Android games). Also used by TensorFlow Lite for ML model serialization.

**Cap'n Proto**
Created by Kenton Varda (Protobuf v2 author). The wire format IS the memory format — no encoding/decoding step. Includes an RPC framework with promise pipelining.
