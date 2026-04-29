"""MessagePack with the msgpack library — production-grade encoding.

Demonstrates:
- msgpack.packb() / msgpack.unpackb() with use_bin_type=True
- Native binary data handling (no base64!)
- Enum handling (convert to string values)
- Benchmarks vs JSON stdlib
- Payload size comparisons across order sizes
"""

from __future__ import annotations

import base64
import json
from typing import Any

import msgpack

from shared.bench import benchmark, compare
from shared.sample_data import make_large_order, make_small_order, make_typical_order


def _json_default(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def prepare_order_dict(order) -> dict:
    """Convert a Pydantic Order to a dict suitable for msgpack encoding.

    - Enum values are converted to their string .value
    - bytes fields are kept as-is (msgpack handles them natively!)
    - Nested structures are recursively processed
    """
    return _prepare(order.model_dump())


def _prepare(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _prepare(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return obj


def encode_order(order_dict: dict) -> bytes:
    """Encode a prepared order dict to msgpack bytes."""
    return msgpack.packb(order_dict, use_bin_type=True)


def decode_order(data: bytes) -> dict:
    """Decode msgpack bytes back to a dict."""
    return msgpack.unpackb(data, raw=False)


# ---------------------------------------------------------------------------
# Demos
# ---------------------------------------------------------------------------

def demo_basics() -> None:
    """Show basic msgpack encoding and the binary data advantage."""
    print("--- msgpack library basics ---\n")

    # Simple roundtrip
    data = {"name": "Alice", "age": 30, "active": True, "scores": [95, 87, 92]}
    packed = msgpack.packb(data, use_bin_type=True)
    unpacked = msgpack.unpackb(packed, raw=False)
    print(f"  Original:  {data}")
    print(f"  Packed:    {len(packed)} bytes")
    print(f"  Unpacked:  {unpacked}")
    print(f"  Roundtrip: {'PASS' if data == unpacked else 'FAIL'}")

    # Binary data — the killer feature over JSON
    print("\n--- Native binary data (no base64!) ---\n")
    thumbnail = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    msg_with_binary = {"id": "item1", "thumbnail": thumbnail}

    mp_packed = msgpack.packb(msg_with_binary, use_bin_type=True)
    mp_unpacked = msgpack.unpackb(mp_packed, raw=False)

    print("  108-byte PNG thumbnail in a message:")
    print(f"    msgpack payload:  {len(mp_packed)} bytes (binary is stored raw)")
    print(f"    Thumbnail intact: {mp_unpacked['thumbnail'] == thumbnail}")

    # Compare with JSON approach
    import base64
    json_msg = {"id": "item1", "thumbnail": base64.b64encode(thumbnail).decode()}
    json_packed = json.dumps(json_msg).encode()
    print(f"    JSON payload:     {len(json_packed)} bytes (base64 + quotes + escapes)")
    print(f"    msgpack saves:    {len(json_packed) - len(mp_packed)} bytes ({(1 - len(mp_packed)/len(json_packed))*100:.0f}%)")


def demo_order_encoding() -> None:
    """Encode FoodDash orders and compare sizes with JSON."""
    print("\n--- Order encoding: msgpack vs JSON ---\n")

    orders = [
        ("small", make_small_order()),
        ("typical", make_typical_order()),
        ("large", make_large_order()),
    ]

    print(f"  {'Order':<10} {'JSON':>10} {'MsgPack':>10} {'Savings':>10}")
    print(f"  {'-----':<10} {'----':>10} {'-------':>10} {'-------':>10}")

    for label, order in orders:
        order_dict = prepare_order_dict(order)

        mp_bytes = encode_order(order_dict)
        json_bytes = json.dumps(
            order.model_dump(), default=_json_default
        ).encode()

        savings = (1 - len(mp_bytes) / len(json_bytes)) * 100
        print(
            f"  {label:<10} {len(json_bytes):>8,} B {len(mp_bytes):>8,} B {savings:>8.1f}%"
        )

        # Verify roundtrip
        decoded = decode_order(mp_bytes)
        assert decoded["id"] == order_dict["id"]


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def run_benchmarks() -> None:
    """Benchmark msgpack vs JSON on a typical FoodDash order."""
    print("\n--- Benchmarks: msgpack vs JSON ---\n")

    order = make_typical_order()
    order_dict = prepare_order_dict(order)
    json_dict = _prepare(order.model_dump())

    # JSON benchmark
    json_result = benchmark(
        name="JSON (stdlib)",
        encode_fn=lambda: json.dumps(json_dict, default=_json_default).encode(),
        decode_fn=lambda data: json.loads(data),
        iterations=5_000,
    )

    # msgpack benchmark
    mp_result = benchmark(
        name="MessagePack",
        encode_fn=lambda: msgpack.packb(order_dict, use_bin_type=True),
        decode_fn=lambda data: msgpack.unpackb(data, raw=False),
        iterations=5_000,
    )

    compare(json_result, mp_result)

    return json_result, mp_result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    demo_basics()
    demo_order_encoding()
    run_benchmarks()


if __name__ == "__main__":
    main()
