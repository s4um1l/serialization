"""Benchmarking harness — consistent measurements across all chapters.

Usage:
    from shared.bench import benchmark

    result = benchmark(
        name="json",
        encode_fn=lambda: json.dumps(data).encode(),
        decode_fn=lambda payload: json.loads(payload),
        iterations=10_000,
    )
    result.print_report()
"""

from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from dataclasses import dataclass, field


@dataclass
class BenchmarkResult:
    name: str
    iterations: int
    payload_size_bytes: int
    encode_times_ns: list[float] = field(repr=False)
    decode_times_ns: list[float] = field(repr=False)
    encode_peak_memory_bytes: int = 0
    decode_peak_memory_bytes: int = 0
    roundtrip_ok: bool = True

    @property
    def encode_median_ns(self) -> float:
        return statistics.median(self.encode_times_ns)

    @property
    def decode_median_ns(self) -> float:
        return statistics.median(self.decode_times_ns)

    @property
    def encode_p99_ns(self) -> float:
        return self.encode_times_ns[int(len(self.encode_times_ns) * 0.99)]

    @property
    def decode_p99_ns(self) -> float:
        return self.decode_times_ns[int(len(self.decode_times_ns) * 0.99)]

    def print_report(self) -> None:
        print(f"\n{'=' * 60}")
        print(f"  {self.name.upper()}")
        print(f"{'=' * 60}")
        print(f"  Payload size:       {self.payload_size_bytes:>10,} bytes")
        print(f"  Encode (median):    {self.encode_median_ns / 1000:>10,.1f} µs")
        print(f"  Encode (p99):       {self.encode_p99_ns / 1000:>10,.1f} µs")
        print(f"  Decode (median):    {self.decode_median_ns / 1000:>10,.1f} µs")
        print(f"  Decode (p99):       {self.decode_p99_ns / 1000:>10,.1f} µs")
        print(f"  Encode peak mem:    {self.encode_peak_memory_bytes:>10,} bytes")
        print(f"  Decode peak mem:    {self.decode_peak_memory_bytes:>10,} bytes")
        print(f"  Roundtrip OK:       {self.roundtrip_ok}")
        print(f"  Iterations:         {self.iterations:>10,}")
        print(f"{'=' * 60}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "payload_size_bytes": self.payload_size_bytes,
            "encode_median_us": self.encode_median_ns / 1000,
            "encode_p99_us": self.encode_p99_ns / 1000,
            "decode_median_us": self.decode_median_ns / 1000,
            "decode_p99_us": self.decode_p99_ns / 1000,
            "encode_peak_memory_bytes": self.encode_peak_memory_bytes,
            "decode_peak_memory_bytes": self.decode_peak_memory_bytes,
            "roundtrip_ok": self.roundtrip_ok,
            "iterations": self.iterations,
        }


def benchmark(
    name: str,
    encode_fn: callable,
    decode_fn: callable,
    *,
    iterations: int = 10_000,
    warmup: int = 100,
    check_roundtrip: callable | None = None,
) -> BenchmarkResult:
    """Run encode/decode benchmark.

    Args:
        name: Format name (e.g. "json", "protobuf").
        encode_fn: Callable that returns encoded bytes. Called with no args.
        decode_fn: Callable that takes encoded bytes and returns decoded object.
        iterations: Number of timed iterations.
        warmup: Number of warmup iterations (not timed).
        check_roundtrip: Optional callable(decoded) -> bool to verify fidelity.
    """
    # Warmup
    for _ in range(warmup):
        payload = encode_fn()
        decode_fn(payload)

    # Measure payload size
    payload = encode_fn()
    payload_size = len(payload)

    # Measure encode times
    gc.disable()
    encode_times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        encode_fn()
        end = time.perf_counter_ns()
        encode_times.append(end - start)

    # Measure decode times
    decode_times = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        decode_fn(payload)
        end = time.perf_counter_ns()
        decode_times.append(end - start)
    gc.enable()

    encode_times.sort()
    decode_times.sort()

    # Measure peak memory for encode
    tracemalloc.start()
    encode_fn()
    _, encode_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Measure peak memory for decode
    tracemalloc.start()
    decode_fn(payload)
    _, decode_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Check roundtrip fidelity
    roundtrip_ok = True
    if check_roundtrip is not None:
        decoded = decode_fn(payload)
        roundtrip_ok = check_roundtrip(decoded)

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        payload_size_bytes=payload_size,
        encode_times_ns=encode_times,
        decode_times_ns=decode_times,
        encode_peak_memory_bytes=encode_peak,
        decode_peak_memory_bytes=decode_peak,
        roundtrip_ok=roundtrip_ok,
    )


def compare(*results: BenchmarkResult) -> None:
    """Print a comparison table of multiple benchmark results."""
    if not results:
        return

    # Header
    name_width = max(len(r.name) for r in results) + 2
    print(f"\n{'Format':<{name_width}} {'Size':>10} {'Enc µs':>10} {'Dec µs':>10} {'Enc mem':>10} {'Dec mem':>10} {'RT':>4}")
    print("─" * (name_width + 58))

    # Find best values for highlighting
    min_size = min(r.payload_size_bytes for r in results)
    min_enc = min(r.encode_median_ns for r in results)
    min_dec = min(r.decode_median_ns for r in results)

    for r in results:
        size_marker = " ★" if r.payload_size_bytes == min_size else ""
        enc_marker = " ★" if r.encode_median_ns == min_enc else ""
        dec_marker = " ★" if r.decode_median_ns == min_dec else ""
        rt = "✓" if r.roundtrip_ok else "✗"

        print(
            f"{r.name:<{name_width}} "
            f"{r.payload_size_bytes:>8,} B{size_marker:>1} "
            f"{r.encode_median_ns / 1000:>8,.1f}{enc_marker:>1} "
            f"{r.decode_median_ns / 1000:>8,.1f}{dec_marker:>1} "
            f"{r.encode_peak_memory_bytes:>8,} B "
            f"{r.decode_peak_memory_bytes:>8,} B "
            f"{rt:>4}"
        )

    print()
