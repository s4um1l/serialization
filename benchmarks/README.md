# Benchmarks

Micro-benchmarks for comparing serialization formats on a single machine.

## Important caveats

- These are **single-machine micro-benchmarks**, not distributed system benchmarks.
- Results depend on your hardware, Python version, and library versions.
- The goal is **relative comparison** between formats, not absolute numbers.
- Run multiple times; expect variance between runs.

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
