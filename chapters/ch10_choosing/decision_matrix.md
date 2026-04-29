# Serialization Format Decision Matrix

## The Definitive Comparison

| Criterion              | CSV | JSON | MsgPack | CBOR | Protobuf | FlatBuffers | Avro | Cap'n Proto |
|------------------------|-----|------|---------|------|----------|-------------|------|-------------|
| Human-readable         | ✓✓  | ✓✓   | ✗       | ✗    | ✗        | ✗           | ✗    | ✗           |
| Wire size              | ○   | ✗    | ○       | ○    | ✓✓       | ✓           | ✓✓   | ✓           |
| Encode speed           | ✓   | ○    | ✓       | ✓    | ✓✓       | ✓           | ✓✓   | ✓✓✓         |
| Decode speed           | ○   | ✗    | ○       | ○    | ✓        | ✓✓✓         | ✓    | ✓✓✓         |
| Schema enforcement     | ✗   | ✗    | ✗       | ✗    | ✓✓       | ✓✓          | ✓✓   | ✓✓          |
| Schema evolution       | ✗   | ○    | ✗       | ✗    | ✓✓       | ✓           | ✓✓✓  | ✓✓          |
| Ecosystem/tooling      | ✓✓  | ✓✓✓  | ✓       | ○    | ✓✓       | ✓           | ✓✓   | ○           |
| Browser compatibility  | ○   | ✓✓✓  | ✗       | ✗    | ○        | ✗           | ✗    | ✗           |
| Streaming support      | ✓   | ○    | ○       | ○    | ✓✓       | ✗           | ✓    | ✓✓          |
| Binary data support    | ✗   | ✗    | ✓✓      | ✓✓   | ✓✓       | ✓✓          | ✓✓   | ✓✓          |

### Legend

- **✓✓✓** = Best in class
- **✓✓** = Strong
- **✓** = Good
- **○** = Adequate / average
- **✗** = Weak / unsupported

## When to Use Each Format

**CSV:** Use for tabular data exports, spreadsheet interchange, or quick-and-dirty data dumps where human readability matters more than structure.

**JSON:** Use at the browser boundary, for public REST APIs, for configuration files, and anywhere human readability and universal tooling are the top priorities.

**MessagePack:** Use as a drop-in binary replacement for JSON when you need smaller payloads without adding schema complexity -- internal caches, session storage, non-critical internal APIs.

**CBOR:** Use when you need an IETF-standardized binary format, particularly in IoT or constrained environments where the RFC matters more than ecosystem size.

**Protobuf:** Use for service-to-service RPC (especially with gRPC), anywhere you need strong schema contracts, and when wire size and encode/decode speed both matter.

**FlatBuffers:** Use for latency-critical hot paths where zero-copy deserialization is essential -- game engines, real-time systems, memory-mapped data access.

**Avro:** Use for data pipelines, Kafka event streaming, and long-lived data stores where schema evolution over months or years is the primary concern.

**Cap'n Proto:** Use for high-performance IPC, zero-copy scenarios where the in-memory layout must match the wire format, and systems where encode speed is the bottleneck.
