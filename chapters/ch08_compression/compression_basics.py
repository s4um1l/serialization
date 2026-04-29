"""Compression algorithms applied to serialized data.

Compares gzip, zstd, lz4, and (optionally) snappy on both single messages
and batches of messages, demonstrating that small messages compress poorly
while batches compress dramatically better.
"""

from __future__ import annotations

import gzip
import json
import time

import lz4.frame
import zstandard as zstd

# Optional: snappy
try:
    import snappy  # type: ignore[import-untyped]

    HAS_SNAPPY = True
except ImportError:
    HAS_SNAPPY = False

from shared.sample_data import make_typical_order, make_batch_orders

# ---------------------------------------------------------------------------
# Protobuf from-scratch encoder (Ch04)
# ---------------------------------------------------------------------------
try:
    from chapters.ch04_protobuf.proto_from_scratch import encode_order as proto_encode
except ImportError:
    proto_encode = None  # type: ignore[assignment]
    print("[compression_basics] WARNING: ch04 protobuf encoder not available, skipping protobuf tests")


# ---------------------------------------------------------------------------
# Compressor registry
# ---------------------------------------------------------------------------

def _gzip_compress(data: bytes) -> bytes:
    return gzip.compress(data)


def _gzip_decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def _zstd_compress(data: bytes) -> bytes:
    cctx = zstd.ZstdCompressor()
    return cctx.compress(data)


def _zstd_decompress(data: bytes) -> bytes:
    dctx = zstd.ZstdDecompressor()
    return dctx.decompress(data)


def _lz4_compress(data: bytes) -> bytes:
    return lz4.frame.compress(data)


def _lz4_decompress(data: bytes) -> bytes:
    return lz4.frame.decompress(data)


COMPRESSORS: dict[str, tuple[callable, callable]] = {
    "gzip": (_gzip_compress, _gzip_decompress),
    "zstd": (_zstd_compress, _zstd_decompress),
    "lz4": (_lz4_compress, _lz4_decompress),
}

if HAS_SNAPPY:
    COMPRESSORS["snappy"] = (snappy.compress, snappy.uncompress)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_ns(fn, *args) -> tuple:
    """Return (result, elapsed_ns)."""
    start = time.perf_counter_ns()
    result = fn(*args)
    elapsed = time.perf_counter_ns() - start
    return result, elapsed


def _order_to_json_bytes(order) -> bytes:
    return json.dumps(order.model_dump(), default=str).encode("utf-8")


def _order_to_proto_bytes(order) -> bytes:
    d = order.model_dump()
    # proto encoder expects string enum values
    d["status"] = d["status"].value if hasattr(d["status"], "value") else d["status"]
    d["payment_method"] = d["payment_method"].value if hasattr(d["payment_method"], "value") else d["payment_method"]
    return proto_encode(d)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def benchmark_compression(label: str, data: bytes, iterations: int = 100) -> list[dict]:
    """Compress/decompress data with each algorithm, return results."""
    results = []
    for name, (compress_fn, decompress_fn) in COMPRESSORS.items():
        # Warmup
        for _ in range(5):
            compressed = compress_fn(data)
            decompress_fn(compressed)

        # Time compression
        compress_times = []
        for _ in range(iterations):
            _, elapsed = _time_ns(compress_fn, data)
            compress_times.append(elapsed)
        compressed = compress_fn(data)

        # Time decompression
        decompress_times = []
        for _ in range(iterations):
            _, elapsed = _time_ns(decompress_fn, compressed)
            decompress_times.append(elapsed)

        compress_times.sort()
        decompress_times.sort()
        median_c = compress_times[len(compress_times) // 2]
        median_d = decompress_times[len(decompress_times) // 2]

        results.append({
            "compressor": name,
            "original_bytes": len(data),
            "compressed_bytes": len(compressed),
            "ratio": len(data) / len(compressed) if len(compressed) > 0 else float("inf"),
            "compress_us": median_c / 1000,
            "decompress_us": median_d / 1000,
        })
    return results


def print_results(label: str, results: list[dict]) -> None:
    """Pretty-print a benchmark results table."""
    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"{'=' * 78}")
    print(
        f"  {'Compressor':<10} {'Original':>10} {'Compressed':>12} "
        f"{'Ratio':>7} {'Compress':>12} {'Decompress':>12}"
    )
    print(
        f"  {'':<10} {'(bytes)':>10} {'(bytes)':>12} "
        f"{'':>7} {'(us)':>12} {'(us)':>12}"
    )
    print(f"  {'-' * 70}")
    for r in results:
        print(
            f"  {r['compressor']:<10} {r['original_bytes']:>10,} {r['compressed_bytes']:>12,} "
            f"{r['ratio']:>7.2f}x {r['compress_us']:>11.1f} {r['decompress_us']:>11.1f}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 78)
    print("  CHAPTER 08 - COMPRESSION BASICS")
    print("  Comparing gzip, zstd, lz4" + (", snappy" if HAS_SNAPPY else "") + " on serialized FoodDash orders")
    print("=" * 78)

    order = make_typical_order()

    # Prepare payloads
    single_json = _order_to_json_bytes(order)
    print(f"\n  Single JSON order:     {len(single_json):>8,} bytes")

    has_proto = proto_encode is not None
    if has_proto:
        single_proto = _order_to_proto_bytes(order)
        print(f"  Single Protobuf order: {len(single_proto):>8,} bytes")

    # Batch: 100 orders
    batch_orders = make_batch_orders(100)
    batch_json = b"".join(_order_to_json_bytes(o) for o in batch_orders)
    print(f"  Batch JSON (x100):    {len(batch_json):>8,} bytes")

    if has_proto:
        batch_proto = b"".join(_order_to_proto_bytes(o) for o in batch_orders)
        print(f"  Batch Protobuf (x100):{len(batch_proto):>8,} bytes")

    # --- Benchmark each payload ---
    payloads = [
        ("Single JSON order (~1.7KB)", single_json),
    ]
    if has_proto:
        payloads.append(("Single Protobuf order (~700B)", single_proto))
    payloads.append(("Batch of 100 JSON orders (~170KB)", batch_json))
    if has_proto:
        payloads.append(("Batch of 100 Protobuf orders (~70KB)", batch_proto))

    all_results = {}
    for label, data in payloads:
        results = benchmark_compression(label, data)
        print_results(label, results)
        all_results[label] = results

    # --- Key insight ---
    print("\n" + "=" * 78)
    print("  KEY INSIGHT")
    print("=" * 78)
    print("""
  Small messages compress poorly -- there are not enough repeated patterns
  within a single ~500-1700 byte message for LZ-family algorithms to exploit.

  Batch compression is dramatically better:
  - 100 JSON orders share the same field names, enum values, and structure
  - The compressor finds these cross-message patterns and eliminates them
  - JSON batches often see 5-10x compression ratios
  - Protobuf batches still benefit (3-5x) even though the format is already compact

  This is why systems like Kafka batch messages before compressing: the batch
  gives the compressor enough data to work with.
""")


if __name__ == "__main__":
    main()
