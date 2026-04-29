# Benchmarks

Micro-benchmarks for comparing serialization formats on a single machine.

## Important caveats

- These are **single-machine micro-benchmarks**, not distributed system benchmarks.
- Results depend on your hardware, Python version, and library versions.
- The goal is **relative comparison** between formats, not absolute numbers.
- Run multiple times; expect variance between runs.

### About the implementations

Protobuf, FlatBuffers, Avro, and Cap'n Proto are all **from-scratch Python implementations** written to teach the wire format. They are not production-grade:

- **Speed numbers are misleading for these formats.** Production C++/Rust protobuf is 10-100x faster than our Python encoder. Our from-scratch Protobuf may appear slower than json stdlib — that's a Python implementation artifact, not a format property.
- **Wire size numbers are valid.** The bytes on the wire are the same regardless of implementation language.
- **FlatBuffers and Cap'n Proto encode a simplified schema** (5-7 fields) vs the full Order (15+ fields) for other formats. Their size numbers are not directly comparable.

JSON and MessagePack use production libraries (`json`/`orjson` and `msgpack`), so their speed numbers are more representative.

## How to run

```bash
# Encode/decode speed comparison across all formats
uv run python -m benchmarks.encode_decode

# Wire payload size comparison
uv run python -m benchmarks.payload_size

# Memory allocation measurement (tracemalloc-based)
uv run python -m benchmarks.memory_allocation
```

## What each benchmark measures

| Benchmark | Metric |
|---|---|
| `encode_decode` | Encode and decode speed (median, p99) for a typical order |
| `payload_size` | Wire size in bytes for small, typical, and large orders |
| `memory_allocation` | Peak memory allocated during encode and decode |
