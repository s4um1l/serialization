# Serialization: The Hidden Tax on Every Message

**How data is encoded for storage and transmission — and why the choice of format has massive implications for performance, compatibility, and debuggability.**

Your 20 microservices exchange 1 million messages per second. JSON serialization alone consumes 12 CPU cores. Your infra team says "we need more servers." You say "we need a better format."

This repo takes you from "what is a byte on the wire?" to "why does Kafka use Avro and gRPC use Protobuf?" through a single evolving case study — **FoodDash Wire**, the inter-service communication layer of a food delivery platform.

## Why This Exists

Most serialization tutorials show you the API: `json.dumps()`, `protobuf.SerializeToString()`. But they don't tell you *why* each format was invented, what problem it solves that the previous generation couldn't, or when the "better" format is actually worse.

This repo is different. Each chapter introduces a new format **because the previous one hits a wall** — performance, compatibility, or features. You feel the pain before learning the cure.

## A Note on the Implementations

Every format in this repo is implemented **from scratch in Python** — byte by byte. This is deliberate: the goal is to teach the wire format, not to be a production serialization library.

What this means for benchmarks:
- **Wire size comparisons are valid.** The wire format is the wire format regardless of implementation language.
- **Speed comparisons show Python overhead, not format overhead.** Production C++/Rust Protobuf is 10-100x faster than our from-scratch Python encoder. Don't conclude "Protobuf is slower than JSON" from these numbers.
- **FlatBuffers and Cap'n Proto encode a simplified schema** (5-7 fields) while other formats encode the full Order (15+ fields). Size comparisons for these two are not apples-to-apples.
- **The from-scratch implementations prioritize clarity over performance.** They match the spec enough to produce correct wire bytes, but skip optimizations that production libraries use.

Future work: C++ and Rust implementations to show true production performance characteristics.

## Every Chapter Includes

- **The Scene** — a narrative that makes you *feel* the problem before showing the solution
- **Systems Constraints** — CPU cycles per encode/decode, bytes on wire, memory allocated, schema lookup latency
- **Working Python Code** — encode/decode the same FoodDash Order in every format, with benchmarks
- **From-Scratch Implementation** — build the core encoding manually before using the library
- **Interactive Visuals** — hex dumps, annotated fields, encoding animations, benchmark charts
- **Production Depth** — how Kafka, gRPC, browsers, and game engines use each format
- **Trade-offs Table** — strengths, weaknesses, and the bridge to the next chapter

## The Learning Path

```
Ch00: Foundations ──────── "You can't just send memory"
  │
Ch01: Plain Text / CSV ── "Text is ambiguous and flat"
  │
Ch02: JSON ────────────── "JSON is bloated and slow"
  │
Ch03: MessagePack/CBOR ── "Binary JSON has no contract"
  │
Ch04: Protocol Buffers ── "Parsing still allocates"
  │
Ch05: FlatBuffers ─────── "Zero-copy doesn't solve the data lake"
  │
Ch06: Apache Avro ─────── "Can we eliminate encoding entirely?"
  │
Ch07: Cap'n Proto ─────── "The format is optimized, but bytes cost money"
  │
Ch08: Compression ─────── "Formats evolve, schemas must too"
  │
Ch09: Schema Evolution ── "So which one do we actually use?"
  │
Ch10: Choosing a Format ─ "Show me the numbers"
  │
Ch11: Synthesis ────────── The serialization tax at 1M msg/s
```

Each arrow represents a **wall** — a specific limitation that forces the move to the next format. The quotes describe the pain.

## Quick Start

```bash
# Clone and install core dependencies
git clone <this-repo>
cd serialization
uv sync

# Run any chapter
uv run python -m chapters.ch00_foundations
uv run python -m chapters.ch02_json

# Install extras for specific chapters
uv sync --extra msgpack        # Ch03
uv sync --extra protobuf       # Ch04
uv sync --extra avro           # Ch06
uv sync --extra compression    # Ch08
uv sync --all-extras           # Everything

# Open visuals in your browser
open visuals.html
```

## Prerequisites

- Python 3.12+
- Basic familiarity with Python data structures
- Curiosity about what happens to your data between `send()` and `recv()`

## Project Structure

```
serialization/
├── shared/                  # Domain models, test data, benchmark harness
│   ├── models.py            # FoodDash Order, MenuItem, Customer, etc.
│   ├── sample_data.py       # Deterministic test data factories
│   └── bench.py             # Consistent encode/decode/size/memory measurement
├── chapters/                # One chapter per format
│   ├── ch00_foundations/    → ch11_synthesis/
├── benchmarks/              # Cross-format performance comparisons
├── exercises/               # Per-chapter problem sets with solutions
└── appendices/              # Custom binary formats, streaming serialization
```

## The Case Study: FoodDash Wire

FoodDash is a food delivery platform. 20 microservices communicate over the network: order service, kitchen service, driver matching, billing, notifications, analytics, and more. Every message — every order placed, every status update, every driver location ping — must be **serialized** to bytes before it can be sent, and **deserialized** back to objects on the other end.

At 1 million messages per second, the serialization format is the hidden tax on every single message. A 10µs difference in encode time costs 10 CPU-seconds per second — the equivalent of 10 full CPU cores doing nothing but serialization.

The `Order` model is deliberately designed to stress-test every format:
- **Nested objects** (Order → OrderItem → MenuItem): 3 levels deep
- **Binary data** (thumbnail images): exposes JSON's base64 overhead
- **Large integers** (transaction IDs > 2⁵³): breaks JavaScript's number precision
- **Unicode strings** (Japanese restaurant names, emoji): encoding edge cases
- **Optional fields** (driver, delivery notes): presence/absence encoding
- **Enums** (order status, payment method): serialized differently by every format

## Browse All Visuals

Open [visuals.html](visuals.html) for an interactive index of all chapter visualizations.
