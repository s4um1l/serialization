"""CBOR (Concise Binary Object Representation) — the IETF alternative.

RFC 8949. Similar to MessagePack but with semantic tags:
- Tag 0: datetime as ISO 8601 string
- Tag 1: datetime as epoch timestamp
- Tag 2/3: big positive/negative integers
- Tag 4: decimal fractions
- Native binary data, just like MsgPack

Designed for constrained environments (IoT), more standardized than MsgPack,
but less adoption in web services.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

import cbor2
import msgpack

from shared.bench import benchmark, compare
from shared.sample_data import make_large_order, make_small_order, make_typical_order


def _json_default(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    return str(obj)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prepare(obj: Any) -> Any:
    """Recursively prepare a Pydantic model dump for CBOR encoding."""
    if isinstance(obj, dict):
        return {k: _prepare(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return obj


def prepare_order_dict(order) -> dict:
    return _prepare(order.model_dump())


# ---------------------------------------------------------------------------
# CBOR semantic tags demo
# ---------------------------------------------------------------------------

def demo_tags() -> None:
    """Demonstrate CBOR's semantic tag system — its key advantage over MsgPack."""
    print("--- CBOR semantic tags ---\n")

    # Tag 0: datetime as ISO 8601 string
    now = datetime(2024, 11, 15, 10, 30, 0, tzinfo=timezone.utc)
    tagged_dt = cbor2.CBORTag(0, now.isoformat())
    encoded_tag0 = cbor2.dumps(tagged_dt)
    decoded_tag0 = cbor2.loads(encoded_tag0)
    print("  Tag 0 (datetime string):")
    print(f"    Input:   {now.isoformat()}")
    print(f"    Encoded: {encoded_tag0.hex()} ({len(encoded_tag0)} bytes)")
    print(f"    Decoded: {decoded_tag0}")
    print()

    # Tag 1: datetime as epoch timestamp
    epoch = now.timestamp()
    tagged_epoch = cbor2.CBORTag(1, epoch)
    encoded_tag1 = cbor2.dumps(tagged_epoch)
    decoded_tag1 = cbor2.loads(encoded_tag1)
    print("  Tag 1 (epoch timestamp):")
    print(f"    Input:   {epoch}")
    print(f"    Encoded: {encoded_tag1.hex()} ({len(encoded_tag1)} bytes)")
    print(f"    Decoded: {decoded_tag1}")
    print()

    # Native datetime support (cbor2 auto-tags datetimes)
    auto_encoded = cbor2.dumps(now)
    auto_decoded = cbor2.loads(auto_encoded)
    print("  Auto-tagged datetime:")
    print(f"    Input:   {now}")
    print(f"    Encoded: {auto_encoded.hex()} ({len(auto_encoded)} bytes)")
    print(f"    Decoded: {auto_decoded}")
    print()

    # Big integers (Tag 2/3)
    big_int = 2**53 + 1  # Breaks JSON in JavaScript
    cbor_big = cbor2.dumps(big_int)
    cbor_big_decoded = cbor2.loads(cbor_big)
    print(f"  Big integer (2^53 + 1 = {big_int}):")
    print(f"    Encoded: {cbor_big.hex()} ({len(cbor_big)} bytes)")
    print(f"    Decoded: {cbor_big_decoded}")
    print(f"    Exact:   {cbor_big_decoded == big_int}")
    print()

    # Binary data — same advantage as MsgPack
    thumbnail = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    msg = {"id": "item1", "thumbnail": thumbnail}
    cbor_encoded = cbor2.dumps(msg)
    cbor_decoded = cbor2.loads(cbor_encoded)
    print("  Binary data (72-byte thumbnail):")
    print(f"    Encoded: {len(cbor_encoded)} bytes (raw binary, no base64)")
    print(f"    Intact:  {cbor_decoded['thumbnail'] == thumbnail}")


def demo_comparison() -> None:
    """Compare CBOR vs MsgPack feature-by-feature."""
    print("\n--- CBOR vs MsgPack: feature comparison ---\n")

    features = [
        ("Spec status", "Community spec", "IETF RFC 8949"),
        ("Datetime support", "Extension types (manual)", "Native tags (0, 1)"),
        ("Big integers", "Up to uint64", "Arbitrary precision (tags 2/3)"),
        ("Decimal fractions", "Not supported", "Tag 4"),
        ("Binary data", "bin 8/16/32", "Major type 2 (byte string)"),
        ("String encoding", "str types (UTF-8)", "Major type 3 (text string)"),
        ("Map key types", "Any type", "Any type"),
        ("Extensibility", "Extension types (app-defined)", "Semantic tags (IANA registry)"),
        ("Canonical form", "Not specified", "Deterministic encoding (RFC 8949 s4.2)"),
        ("Primary ecosystem", "Redis, Fluentd, web", "IoT, COSE, WebAuthn"),
    ]

    print(f"  {'Feature':<25} {'MessagePack':<30} {'CBOR':<35}")
    print(f"  {'-'*25} {'-'*30} {'-'*35}")
    for feature, mp, cbor_val in features:
        print(f"  {feature:<25} {mp:<30} {cbor_val:<35}")


def demo_sizes() -> None:
    """Compare payload sizes: JSON vs MsgPack vs CBOR."""
    print("\n--- Payload sizes: JSON vs MsgPack vs CBOR ---\n")

    orders = [
        ("small", make_small_order()),
        ("typical", make_typical_order()),
        ("large", make_large_order()),
    ]

    print(f"  {'Order':<10} {'JSON':>10} {'MsgPack':>10} {'CBOR':>10} {'MP save':>10} {'CBOR save':>10}")
    print(f"  {'-----':<10} {'----':>10} {'-------':>10} {'----':>10} {'-------':>10} {'---------':>10}")

    for label, order in orders:
        order_dict = _prepare(order.model_dump())
        json_dict = _prepare(order.model_dump())

        json_size = len(json.dumps(json_dict, default=_json_default).encode())
        mp_size = len(msgpack.packb(order_dict, use_bin_type=True))
        cbor_size = len(cbor2.dumps(order_dict))

        mp_save = (1 - mp_size / json_size) * 100
        cbor_save = (1 - cbor_size / json_size) * 100

        print(
            f"  {label:<10} {json_size:>8,} B {mp_size:>8,} B {cbor_size:>8,} B"
            f" {mp_save:>8.1f}% {cbor_save:>8.1f}%"
        )


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def run_benchmarks() -> None:
    """Three-way benchmark: JSON vs MsgPack vs CBOR."""
    print("\n--- Benchmarks: JSON vs MsgPack vs CBOR ---\n")

    order = make_typical_order()
    order_dict = _prepare(order.model_dump())
    json_dict = _prepare(order.model_dump())

    json_result = benchmark(
        name="JSON (stdlib)",
        encode_fn=lambda: json.dumps(json_dict, default=_json_default).encode(),
        decode_fn=lambda data: json.loads(data),
        iterations=5_000,
    )

    mp_result = benchmark(
        name="MessagePack",
        encode_fn=lambda: msgpack.packb(order_dict, use_bin_type=True),
        decode_fn=lambda data: msgpack.unpackb(data, raw=False),
        iterations=5_000,
    )

    cbor_result = benchmark(
        name="CBOR",
        encode_fn=lambda: cbor2.dumps(order_dict),
        decode_fn=lambda data: cbor2.loads(data),
        iterations=5_000,
    )

    compare(json_result, mp_result, cbor_result)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    demo_tags()
    demo_comparison()
    demo_sizes()
    run_benchmarks()


if __name__ == "__main__":
    main()
