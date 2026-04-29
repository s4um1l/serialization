"""Full matrix benchmark: [JSON, MsgPack, Protobuf, Avro] x [none, gzip, zstd, lz4].

For each combination, measure total size, encode+compress time, and
decompress+decode time to find the real-world optimal combination.
"""

from __future__ import annotations

import gzip
import json
import time

import lz4.frame
import zstandard as zstd

from shared.sample_data import make_typical_order

# ---------------------------------------------------------------------------
# Format encoders/decoders (import from previous chapters with fallbacks)
# ---------------------------------------------------------------------------

FORMATS: dict[str, dict] = {}

# -- JSON (stdlib, always available) --
def _json_encode(order) -> bytes:
    return json.dumps(order.model_dump(), default=str).encode("utf-8")

def _json_decode(data: bytes):
    return json.loads(data)

FORMATS["JSON"] = {"encode": _json_encode, "decode": _json_decode}

# -- MsgPack --
try:
    import msgpack

    def _msgpack_encode(order) -> bytes:
        return msgpack.packb(order.model_dump(), default=str)

    def _msgpack_decode(data: bytes):
        return msgpack.unpackb(data, raw=False)

    FORMATS["MsgPack"] = {"encode": _msgpack_encode, "decode": _msgpack_decode}
except ImportError:
    print("[format_plus_compression] WARNING: msgpack not available, skipping MsgPack")

# -- Protobuf (from-scratch, Ch04) --
try:
    from chapters.ch04_protobuf.proto_from_scratch import (
        encode_order as _proto_raw_encode,
        decode_order as _proto_raw_decode,
    )

    def _proto_encode(order) -> bytes:
        d = order.model_dump()
        d["status"] = d["status"].value if hasattr(d["status"], "value") else d["status"]
        d["payment_method"] = d["payment_method"].value if hasattr(d["payment_method"], "value") else d["payment_method"]
        return _proto_raw_encode(d)

    def _proto_decode(data: bytes):
        return _proto_raw_decode(data)

    FORMATS["Protobuf"] = {"encode": _proto_encode, "decode": _proto_decode}
except ImportError:
    print("[format_plus_compression] WARNING: ch04 protobuf encoder not available, skipping Protobuf")

# -- Avro (from-scratch, Ch06) --
try:
    import pathlib
    from chapters.ch06_avro.avro_from_scratch import (
        avro_encode,
        avro_decode,
        order_to_avro_dict,
    )

    _avro_schema_path = pathlib.Path(__file__).parent.parent / "ch06_avro" / "fooddash.avsc"
    with open(_avro_schema_path) as _f:
        _AVRO_SCHEMA = json.load(_f)

    def _avro_encode(order) -> bytes:
        d = order_to_avro_dict(order)
        return avro_encode(_AVRO_SCHEMA, d)

    def _avro_decode(data: bytes):
        val, _ = avro_decode(_AVRO_SCHEMA, data)
        return val

    FORMATS["Avro"] = {"encode": _avro_encode, "decode": _avro_decode}
except Exception as e:
    print(f"[format_plus_compression] WARNING: Avro encoder not available ({e}), skipping Avro")


# ---------------------------------------------------------------------------
# Compressors
# ---------------------------------------------------------------------------

COMPRESSORS: dict[str, dict] = {
    "none": {
        "compress": lambda d: d,
        "decompress": lambda d: d,
    },
    "gzip": {
        "compress": gzip.compress,
        "decompress": gzip.decompress,
    },
    "zstd": {
        "compress": lambda d: zstd.ZstdCompressor().compress(d),
        "decompress": lambda d: zstd.ZstdDecompressor().decompress(d),
    },
    "lz4": {
        "compress": lz4.frame.compress,
        "decompress": lz4.frame.decompress,
    },
}


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2]


def benchmark_matrix(order, iterations: int = 200) -> list[dict]:
    """Run the full format x compressor matrix."""
    results = []

    for fmt_name, fmt in FORMATS.items():
        for comp_name, comp in COMPRESSORS.items():
            encode_fn = fmt["encode"]
            decode_fn = fmt["decode"]
            compress_fn = comp["compress"]
            decompress_fn = comp["decompress"]

            # Warmup
            for _ in range(10):
                encoded = encode_fn(order)
                compressed = compress_fn(encoded)
                decompressed = decompress_fn(compressed)
                decode_fn(decompressed)

            # Measure encode + compress
            enc_times = []
            for _ in range(iterations):
                start = time.perf_counter_ns()
                encoded = encode_fn(order)
                compressed = compress_fn(encoded)
                elapsed = time.perf_counter_ns() - start
                enc_times.append(elapsed)

            # Capture sizes
            encoded = encode_fn(order)
            compressed = compress_fn(encoded)
            serialized_size = len(encoded)
            compressed_size = len(compressed)

            # Measure decompress + decode
            dec_times = []
            for _ in range(iterations):
                start = time.perf_counter_ns()
                decompressed = decompress_fn(compressed)
                decode_fn(decompressed)
                elapsed = time.perf_counter_ns() - start
                dec_times.append(elapsed)

            results.append({
                "format": fmt_name,
                "compressor": comp_name,
                "serialized_bytes": serialized_size,
                "compressed_bytes": compressed_size,
                "ratio": serialized_size / compressed_size if compressed_size > 0 else 0,
                "encode_compress_us": _median(enc_times) / 1000,
                "decompress_decode_us": _median(dec_times) / 1000,
            })

    return results


def print_matrix(results: list[dict]) -> None:
    """Print a formatted matrix table of results."""
    print(f"\n{'=' * 100}")
    print("  FORMAT x COMPRESSION MATRIX  --  Typical FoodDash Order")
    print(f"{'=' * 100}")
    print(
        f"  {'Format+Compressor':<25} {'Serialized':>11} {'Compressed':>11} "
        f"{'Ratio':>7} {'Enc+Comp':>12} {'Dec+Decomp':>12}"
    )
    print(
        f"  {'':<25} {'(bytes)':>11} {'(bytes)':>11} "
        f"{'':>7} {'(us)':>12} {'(us)':>12}"
    )
    print(f"  {'-' * 92}")

    # Group by format
    current_format = None
    for r in results:
        if r["format"] != current_format:
            if current_format is not None:
                print(f"  {'-' * 92}")
            current_format = r["format"]

        label = f"{r['format']}+{r['compressor']}"
        print(
            f"  {label:<25} {r['serialized_bytes']:>11,} {r['compressed_bytes']:>11,} "
            f"{r['ratio']:>7.2f}x {r['encode_compress_us']:>11.1f} {r['decompress_decode_us']:>11.1f}"
        )

    # Find extremes
    min_size = min(r["compressed_bytes"] for r in results)
    fastest_enc = min(r["encode_compress_us"] for r in results)
    fastest_dec = min(r["decompress_decode_us"] for r in results)

    smallest = [r for r in results if r["compressed_bytes"] == min_size][0]
    fast_enc = [r for r in results if r["encode_compress_us"] == fastest_enc][0]
    fast_dec = [r for r in results if r["decompress_decode_us"] == fastest_dec][0]

    print(f"\n  Smallest:     {smallest['format']}+{smallest['compressor']} at {min_size:,} bytes")
    print(f"  Fastest enc:  {fast_enc['format']}+{fast_enc['compressor']} at {fastest_enc:.1f} us")
    print(f"  Fastest dec:  {fast_dec['format']}+{fast_dec['compressor']} at {fastest_dec:.1f} us")


def print_findings(results: list[dict]) -> None:
    """Print key findings from the benchmark."""
    print(f"\n{'=' * 100}")
    print("  KEY FINDINGS")
    print(f"{'=' * 100}")

    # Find JSON+zstd and Protobuf+none for the "surprising result"
    json_zstd = next((r for r in results if r["format"] == "JSON" and r["compressor"] == "zstd"), None)
    proto_none = next((r for r in results if r["format"] == "Protobuf" and r["compressor"] == "none"), None)

    print("""
  1. JSON + zstd can be SURPRISINGLY competitive on size.
     JSON carries redundant field names and quoted values, but compression
     algorithms are specifically designed to eliminate this kind of redundancy.""")
    if json_zstd and proto_none:
        pct = json_zstd["compressed_bytes"] / proto_none["compressed_bytes"] * 100
        print(f"     JSON+zstd = {json_zstd['compressed_bytes']:,} bytes vs Protobuf+none = {proto_none['compressed_bytes']:,} bytes ({pct:.0f}%)")

    print("""
  2. Protobuf + zstd is typically the SMALLEST overall.
     Protobuf's compact binary plus zstd's compression = maximum density.
     But the size advantage over JSON+zstd is smaller than you might expect.""")

    print("""
  3. LZ4 is the FASTEST compressor but has the lowest compression ratio.
     If CPU time matters more than bandwidth, LZ4 is the right choice.
     Common in real-time systems where latency budgets are tight.""")

    print("""
  4. gzip is the SLOWEST but most widely supported.
     Every HTTP client/server, every programming language supports gzip.
     It's the safe default when compatibility matters most.""")

    print("""
  5. The "best" choice depends on what you're optimizing for:
     - Size:          Protobuf + zstd  (minimum bytes on the wire)
     - Speed:         MsgPack + lz4    (fast encode + fast compress)
     - Compatibility: JSON + gzip      (works everywhere)
     - Balance:       Protobuf + lz4   or  MsgPack + zstd
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 100)
    print("  CHAPTER 08 - FORMAT x COMPRESSION MATRIX")
    print("  Benchmarking [JSON, MsgPack, Protobuf, Avro] x [none, gzip, zstd, lz4]")
    print("=" * 100)

    order = make_typical_order()
    results = benchmark_matrix(order)
    print_matrix(results)
    print_findings(results)


if __name__ == "__main__":
    main()
