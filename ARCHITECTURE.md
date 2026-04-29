# Architecture: FoodDash Wire

## The Big Picture

FoodDash is a food delivery platform where 20 microservices exchange 1 million messages per second. Every arrow below is a serialized message.

```
                          ┌──────────────┐
                          │   Web / App   │
                          │   (Browser)   │
                          └──────┬───────┘
                                 │ JSON (browser-native)
                                 ▼
                          ┌──────────────┐
                          │  API Gateway  │
                          └──┬───┬───┬───┘
               ┌─────────────┘   │   └─────────────┐
               │                 │                  │
               ▼                 ▼                  ▼
        ┌────────────┐   ┌────────────┐     ┌────────────┐
        │   Order    │   │  Restaurant │     │  Customer  │
        │  Service   │   │   Service   │     │  Service   │
        └─────┬──────┘   └─────┬──────┘     └────────────┘
              │                │
    Protobuf  │    Protobuf    │
    (gRPC)    │    (gRPC)      │
              ▼                ▼
        ┌────────────┐   ┌────────────┐
        │  Kitchen   │   │   Driver   │
        │  Service   │   │  Matching  │
        └─────┬──────┘   └─────┬──────┘
              │                │
              │  Avro          │  FlatBuffers (zero-copy
              │  (Kafka)       │   for hot path reads)
              ▼                ▼
        ┌────────────┐   ┌────────────┐
        │  Analytics  │   │  Billing   │
        │  Pipeline   │   │  Service   │
        └────────────┘   └────────────┘
              │
              │  Avro + zstd
              ▼
        ┌────────────┐
        │  Data Lake  │
        │  (S3/HDFS)  │
        └────────────┘
```

## Why Different Formats in Different Places

| Boundary | Format | Why |
|----------|--------|-----|
| Browser ↔ API Gateway | JSON | Browsers speak JSON natively. No build step required. |
| Service ↔ Service (RPC) | Protobuf (gRPC) | Schema-enforced, 5-10x smaller than JSON, streaming support, code generation. |
| Driver Matching hot path | FlatBuffers | Zero-copy: read 2 fields from a message without deserializing all 30. |
| Event stream (Kafka) | Avro | Writer/reader schema resolution. Schema Registry for versioning. |
| Data Lake storage | Avro + zstd | Schema travels with data. zstd compression for cold storage. |

## Constraint Pressure Map

How each format performs under the 5 key serialization constraints:

```
Format          │ Wire Size │ Encode CPU │ Decode CPU │ Schema │ Evolution
────────────────┼───────────┼────────────┼────────────┼────────┼──────────
Plain Text/CSV  │ ●●●○      │ ●○○○       │ ●●○○       │ ○○○○   │ ○○○○
JSON            │ ●●●○      │ ●●○○       │ ●●○○       │ ○○○○   │ ●●○○
MessagePack     │ ●●○○      │ ●○○○       │ ●○○○       │ ○○○○   │ ●○○○
Protobuf        │ ●○○○      │ ●○○○       │ ●○○○       │ ●●●●   │ ●●●○
FlatBuffers     │ ●●○○      │ ●○○○       │ ○○○○       │ ●●●●   │ ●●○○
Avro            │ ●○○○      │ ●○○○       │ ●○○○       │ ●●●●   │ ●●●●
Cap'n Proto     │ ●●○○      │ ○○○○       │ ○○○○       │ ●●●●   │ ●●●○

● = more pressure (worse)    ○ = less pressure (better)
```

## The Serialization Tax

At 1 million messages/second with a typical 500-byte Order:

| Format | Encode CPU | Decode CPU | Bandwidth | Monthly Cost* |
|--------|-----------|-----------|-----------|--------------|
| JSON | ~12 cores | ~10 cores | 43 TB/day | ~$15,000 |
| Protobuf | ~2 cores | ~2 cores | 15 TB/day | ~$5,000 |
| FlatBuffers | ~1 core | ~0.1 core | 18 TB/day | ~$4,500 |
| Avro | ~2 cores | ~2 cores | 12 TB/day | ~$4,000 |

*Estimated: compute + bandwidth at cloud rates. The point isn't the exact numbers — it's the order-of-magnitude difference.*

## How to Read This Repo

**Sequential (recommended):** Start at Ch00, follow the narrative. Each chapter's pain point motivates the next.

**By need:**
- "I want to understand what's on the wire" → Ch00 (Foundations)
- "I'm choosing between JSON and Protobuf" → Ch02, Ch04, Ch10
- "I need schema evolution" → Ch04, Ch06, Ch09
- "I need zero-copy for a hot path" → Ch05, Ch07
- "I'm building a data pipeline" → Ch06, Ch08
- "Show me the benchmarks" → Ch11

**By constraint:**
- Smallest payload → Ch04 (Protobuf), Ch08 (Compression)
- Fastest decode → Ch05 (FlatBuffers), Ch07 (Cap'n Proto)
- Best schema evolution → Ch06 (Avro), Ch09 (Evolution)
- Human readability → Ch02 (JSON)
