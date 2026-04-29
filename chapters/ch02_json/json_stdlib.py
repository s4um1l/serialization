"""JSON encoding/decoding with the standard library (and orjson if available).

Benchmarks json vs orjson to show how much a C/Rust implementation can
outperform pure-Python string building.
"""

from __future__ import annotations

import base64
import json

from shared.bench import benchmark, compare
from shared.sample_data import make_typical_order


# ---------------------------------------------------------------------------
# Custom encoder that handles bytes -> base64
# ---------------------------------------------------------------------------

class BytesEncoder(json.JSONEncoder):
    """JSON encoder that converts bytes to $base64:... strings."""

    def default(self, o):
        if isinstance(o, bytes):
            return f'$base64:{base64.b64encode(o).decode("ascii")}'
        return super().default(o)


def _bytes_to_base64(obj):
    """Recursively convert bytes values in a dict/list to base64 strings."""
    if isinstance(obj, dict):
        return {k: _bytes_to_base64(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_bytes_to_base64(v) for v in obj]
    if isinstance(obj, bytes):
        return f'$base64:{base64.b64encode(obj).decode("ascii")}'
    return obj


# ---------------------------------------------------------------------------
# Encode / decode helpers
# ---------------------------------------------------------------------------

def json_encode(order_dict: dict) -> bytes:
    """Encode an order dict to JSON bytes using stdlib."""
    return json.dumps(order_dict, cls=BytesEncoder).encode('utf-8')


def json_decode(payload: bytes) -> dict:
    """Decode JSON bytes to a dict using stdlib."""
    return json.loads(payload)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    order = make_typical_order()
    order_dict = order.model_dump()

    # --- stdlib json ---
    print("--- JSON stdlib ---\n")

    payload = json_encode(order_dict)
    print(f"Payload size: {len(payload):,} bytes")
    decoded = json_decode(payload)
    print(f"Round-trip OK: {decoded['id'] == order_dict['id']}")

    json_result = benchmark(
        name="json (stdlib)",
        encode_fn=lambda: json_encode(order_dict),
        decode_fn=json_decode,
        iterations=5_000,
        warmup=200,
    )
    json_result.print_report()

    # --- Try orjson ---
    results = [json_result]

    try:
        import orjson

        print("\n--- orjson (Rust-based) ---\n")

        # orjson handles bytes differently; we pre-convert
        order_dict_b64 = _bytes_to_base64(order_dict)

        def orjson_encode() -> bytes:
            return orjson.dumps(order_dict_b64)

        def orjson_decode(payload: bytes) -> dict:
            return orjson.loads(payload)

        orjson_payload = orjson_encode()
        print(f"Payload size: {len(orjson_payload):,} bytes")

        orjson_result = benchmark(
            name="orjson (Rust)",
            encode_fn=orjson_encode,
            decode_fn=orjson_decode,
            iterations=5_000,
            warmup=200,
        )
        orjson_result.print_report()
        results.append(orjson_result)

        # Show speedup
        enc_speedup = json_result.encode_median_ns / orjson_result.encode_median_ns
        dec_speedup = json_result.decode_median_ns / orjson_result.decode_median_ns
        print(f"orjson encode speedup: {enc_speedup:.1f}x faster")
        print(f"orjson decode speedup: {dec_speedup:.1f}x faster")

    except ImportError:
        print("\norjson not installed. Install with: uv pip install orjson")
        print("Skipping orjson benchmark.\n")

    # --- Comparison table ---
    print("\n--- Comparison ---")
    compare(*results)

    # --- Payload size breakdown ---
    print("--- Payload Size ---\n")
    print(f"JSON payload: {len(payload):,} bytes")
    pretty = json.dumps(order_dict, cls=BytesEncoder, indent=2).encode('utf-8')
    print(f"Pretty-printed: {len(pretty):,} bytes")
    print(f"Pretty overhead: +{len(pretty) - len(payload):,} bytes ({(len(pretty) - len(payload)) / len(payload) * 100:.1f}%)")


if __name__ == "__main__":
    main()
