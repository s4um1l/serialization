"""Zstd dictionary compression for small messages.

Demonstrates that training a zstd dictionary on representative FoodDash
messages dramatically improves compression of individual small messages --
the technique behind Kafka's efficient compression of small records.
"""

from __future__ import annotations

import json
import time

import zstandard as zstd

from shared.sample_data import make_batch_orders


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_to_json_bytes(order) -> bytes:
    return json.dumps(order.model_dump(), default=str).encode("utf-8")


def _median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2]


# ---------------------------------------------------------------------------
# Dictionary training and comparison
# ---------------------------------------------------------------------------

def train_dictionary(training_data: list[bytes], dict_size: int = 16384) -> zstd.ZstdCompressionDict:
    """Train a zstd dictionary on a list of sample messages."""
    return zstd.train_dictionary(dict_size, training_data)


def compare_with_without_dict(
    messages: list[bytes],
    dictionary: zstd.ZstdCompressionDict,
    iterations: int = 100,
) -> dict:
    """Compare compression of messages with and without a trained dictionary."""
    # Compressors
    cctx_plain = zstd.ZstdCompressor(level=3)
    cctx_dict = zstd.ZstdCompressor(dict_data=dictionary, level=3)
    dctx_plain = zstd.ZstdDecompressor()
    dctx_dict = zstd.ZstdDecompressor(dict_data=dictionary)

    plain_sizes = []
    dict_sizes = []
    plain_compress_times = []
    dict_compress_times = []
    plain_decompress_times = []
    dict_decompress_times = []

    for msg in messages:
        # --- Plain compression ---
        start = time.perf_counter_ns()
        compressed_plain = cctx_plain.compress(msg)
        plain_compress_times.append(time.perf_counter_ns() - start)
        plain_sizes.append(len(compressed_plain))

        start = time.perf_counter_ns()
        dctx_plain.decompress(compressed_plain)
        plain_decompress_times.append(time.perf_counter_ns() - start)

        # --- Dictionary compression ---
        start = time.perf_counter_ns()
        compressed_dict = cctx_dict.compress(msg)
        dict_compress_times.append(time.perf_counter_ns() - start)
        dict_sizes.append(len(compressed_dict))

        start = time.perf_counter_ns()
        dctx_dict.decompress(compressed_dict)
        dict_decompress_times.append(time.perf_counter_ns() - start)

    original_total = sum(len(m) for m in messages)
    plain_total = sum(plain_sizes)
    dict_total = sum(dict_sizes)

    return {
        "num_messages": len(messages),
        "avg_original_bytes": original_total / len(messages),
        "avg_plain_compressed": plain_total / len(messages),
        "avg_dict_compressed": dict_total / len(messages),
        "plain_ratio": original_total / plain_total if plain_total > 0 else 0,
        "dict_ratio": original_total / dict_total if dict_total > 0 else 0,
        "dict_improvement": plain_total / dict_total if dict_total > 0 else 0,
        "plain_compress_us": _median(plain_compress_times) / 1000,
        "dict_compress_us": _median(dict_compress_times) / 1000,
        "plain_decompress_us": _median(plain_decompress_times) / 1000,
        "dict_decompress_us": _median(dict_decompress_times) / 1000,
    }


def training_size_sweep(
    all_training_data: list[bytes],
    test_messages: list[bytes],
    training_counts: list[int] | None = None,
) -> list[dict]:
    """Show how compression improves as dictionary training size increases."""
    if training_counts is None:
        training_counts = [10, 50, 100, 250, 500, 1000]

    results = []
    for n in training_counts:
        if n > len(all_training_data):
            break
        training_subset = all_training_data[:n]
        dictionary = train_dictionary(training_subset)
        comparison = compare_with_without_dict(test_messages, dictionary)
        comparison["training_samples"] = n
        results.append(comparison)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 78)
    print("  CHAPTER 08 - DICTIONARY COMPRESSION")
    print("  Training zstd dictionaries on FoodDash order messages")
    print("=" * 78)

    # Generate training data: 1000 orders encoded as JSON
    print("\n  Generating 1000 training orders + 50 test orders...")
    training_orders = make_batch_orders(1000)
    test_orders = make_batch_orders(50)
    # Offset test order IDs so they don't overlap with training
    for i, o in enumerate(test_orders):
        test_orders[i] = o.model_copy(update={
            "id": f"test_{i:05d}",
            "platform_transaction_id": 999000 + i,
        })

    training_data = [_order_to_json_bytes(o) for o in training_orders]
    test_data = [_order_to_json_bytes(o) for o in test_orders]

    avg_msg_size = sum(len(d) for d in training_data) / len(training_data)
    print(f"  Average message size: {avg_msg_size:.0f} bytes")

    # ------------------------------------------------------------------
    # 1. Basic comparison: with vs without dictionary
    # ------------------------------------------------------------------
    print(f"\n{'=' * 78}")
    print("  COMPARISON: Regular zstd vs Dictionary zstd")
    print(f"{'=' * 78}")

    dictionary = train_dictionary(training_data)
    print(f"  Dictionary size: {len(dictionary.as_bytes()):,} bytes")
    print(f"  Trained on: {len(training_data)} messages\n")

    result = compare_with_without_dict(test_data, dictionary)

    print(f"  {'Metric':<30} {'Regular zstd':>15} {'Dict zstd':>15} {'Improvement':>12}")
    print(f"  {'-' * 72}")
    print(f"  {'Avg original size (bytes)':<30} {result['avg_original_bytes']:>15.0f} {result['avg_original_bytes']:>15.0f} {'':>12}")
    print(f"  {'Avg compressed size (bytes)':<30} {result['avg_plain_compressed']:>15.0f} {result['avg_dict_compressed']:>15.0f} {result['dict_improvement']:>11.2f}x")
    print(f"  {'Compression ratio':<30} {result['plain_ratio']:>15.2f}x {result['dict_ratio']:>15.2f}x {'':>12}")
    print(f"  {'Compress time (us)':<30} {result['plain_compress_us']:>15.1f} {result['dict_compress_us']:>15.1f} {'':>12}")
    print(f"  {'Decompress time (us)':<30} {result['plain_decompress_us']:>15.1f} {result['dict_decompress_us']:>15.1f} {'':>12}")

    # ------------------------------------------------------------------
    # 2. Training size sweep
    # ------------------------------------------------------------------
    print(f"\n{'=' * 78}")
    print("  TRAINING SIZE SWEEP: How many samples do you need?")
    print(f"{'=' * 78}")
    print(f"\n  {'Training':>10} {'Dict ratio':>12} {'Plain ratio':>13} {'Dict improvement':>18}")
    print(f"  {'samples':>10} {'(with dict)':>12} {'(no dict)':>13} {'over plain':>18}")
    print(f"  {'-' * 55}")

    sweep_results = training_size_sweep(training_data, test_data)
    for r in sweep_results:
        print(
            f"  {r['training_samples']:>10} {r['dict_ratio']:>12.2f}x {r['plain_ratio']:>13.2f}x {r['dict_improvement']:>17.2f}x"
        )

    # ------------------------------------------------------------------
    # 3. Key insights
    # ------------------------------------------------------------------
    print(f"\n{'=' * 78}")
    print("  KEY INSIGHTS")
    print(f"{'=' * 78}")
    print("""
  1. REGULAR COMPRESSION on small messages (~1-2KB) gives modest ratios.
     There simply aren't enough repeated patterns within a single message.

  2. DICTIONARY COMPRESSION pre-loads the compressor with patterns learned
     from representative data. The dictionary knows that field names like
     "platform_transaction_id", "restaurant_id", "special_instructions"
     appear in every message -- it compresses them to just a few bits.

  3. Training on 100-500 samples is usually sufficient.
     Beyond that, returns diminish rapidly.

  4. The dictionary must be SHARED between producer and consumer.
     - Kafka: dictionary can be stored in a schema registry
     - gRPC: dictionary can be negotiated at connection setup
     - HTTP: not practical (no standard dictionary negotiation... yet)

  5. This is how Kafka achieves good compression even for small messages:
     - Producer batches N messages together
     - Compresses the batch as a unit (same principle as dictionary)
     - Consumer decompresses the batch and processes individual messages

  6. Dictionary size is typically 16-64KB -- a one-time cost that pays for
     itself after compressing just a few hundred messages.
""")


if __name__ == "__main__":
    main()
