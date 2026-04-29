# Appendix B: Streaming Serialization

## Why Streaming Matters

Throughout this book, we serialized complete messages: encode an entire Order, transmit it,
decode it. But what happens when the data is too large to fit in memory, or when latency
matters more than throughput?

**Streaming serialization** lets you process records one at a time, without loading the
entire dataset. This is critical for:

- **Large datasets**: A 50GB analytics export cannot be parsed as a single JSON array. You
  need to process records incrementally, emitting results as you go.
- **Real-time feeds**: A food delivery platform emitting order status updates. Consumers
  need to react to each event immediately, not wait for a batch to complete.
- **Backpressure**: If the consumer is slower than the producer, streaming lets you apply
  flow control at the record level instead of buffering the entire payload.
- **Time-to-first-record (TTFR)**: The interval between receiving the first byte and being
  able to process the first complete record. For a JSON array, TTFR equals the time to
  receive the *entire* response. For a stream, TTFR equals the time to receive just the
  first record.

## NDJSON (Newline-Delimited JSON)

The simplest streaming format: one JSON object per line, separated by `\n`.

```
{"order_id":1,"status":"placed","total_cents":2598}\n
{"order_id":2,"status":"confirmed","total_cents":1899}\n
{"order_id":3,"status":"preparing","total_cents":4297}\n
```

**Advantages:**
- Human readable -- you can `head`, `tail`, `grep`, `wc -l` the file
- Every line is independently parseable (crash recovery: skip corrupted lines)
- Trivial to produce and consume in any language
- Works with Unix pipes: `cat orders.ndjson | jq '.total_cents' | sort -n`

**Disadvantages:**
- Still carries JSON overhead (quoted keys, string escaping)
- No schema -- each line must be self-describing
- Larger than binary alternatives
- Newlines in string values must be escaped (`\n` literal, not byte 0x0A)

**Where you see it in production:**
- Docker container logs (`docker logs --follow`)
- Elasticsearch Bulk API
- BigQuery export/import
- OpenAI API streaming responses

## Length-Prefixed Protobuf Streams

Protobuf messages are not self-delimiting. Given a stream of bytes, you cannot tell where
one message ends and the next begins. The standard solution: prefix each message with its
byte length encoded as a varint.

```
[varint: msg1_length][msg1_bytes][varint: msg2_length][msg2_bytes]...
```

**Advantages:**
- All the benefits of protobuf (compact, fast, typed, schema-evolved)
- Very low framing overhead (1-2 bytes per message for typical sizes)
- Standard pattern supported by every protobuf library (`parseDelimitedFrom` in Java,
  `StreamReader` in C++)

**Disadvantages:**
- Not human readable
- Requires knowing the message schema to parse
- Cannot grep/filter without a protobuf-aware tool

**Where you see it in production:**
- gRPC (HTTP/2 frames contain length-prefixed protobuf)
- TFRecord files (TensorFlow training data)
- Kafka with protobuf serializer

## Avro Container Files (Object Container Format)

Avro takes a different approach: the file embeds the writer's schema in the header, then
stores records in blocks separated by 16-byte sync markers.

```
[header: magic + schema JSON + sync marker]
[block 1: count varint + size varint + encoded records + sync marker]
[block 2: count varint + size varint + encoded records + sync marker]
...
```

**Advantages:**
- Self-describing: the schema travels with the data
- Blocks can be compressed independently (snappy, deflate, zstd per block)
- Sync markers enable splitting: MapReduce/Spark can start reading from any block boundary
- Schema evolution: reader schema can differ from writer schema

**Disadvantages:**
- More complex to implement than NDJSON or length-prefixed protobuf
- Block-level granularity (not single-record) -- TTFR depends on block size
- Overhead of embedded schema (amortized over many records)

**Where you see it in production:**
- Apache Kafka (Confluent Schema Registry + Avro)
- Apache Spark/Hive data lakes
- Hadoop ecosystem (the original use case)

## When to Use Which

| Criterion              | NDJSON       | Length-Prefixed Proto | Avro Container |
|------------------------|--------------|-----------------------|----------------|
| Human readable         | Yes          | No                    | No             |
| Schema required        | No           | Yes (external)        | Yes (embedded) |
| Compression            | External     | External              | Per-block      |
| TTFR                   | Excellent    | Excellent             | Good (block)   |
| Splittable             | Yes (lines)  | No (varint chain)     | Yes (sync)     |
| Size efficiency        | Poor         | Excellent             | Excellent      |
| Ecosystem support      | Universal    | gRPC ecosystem        | Hadoop/Kafka   |
| Crash recovery         | Skip line    | Re-sync hard          | Seek to sync   |

## Running the Code

```bash
# NDJSON streaming with time-to-first-record benchmark
uv run python -m appendices.appendix_b_streaming_serialization.ndjson_streaming

# Length-prefixed protobuf streaming
uv run python -m appendices.appendix_b_streaming_serialization.proto_streaming
```
