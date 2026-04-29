"""Appendix B: Length-prefixed protobuf streaming.

Each record on the wire:
    [varint: message_length][protobuf_bytes of that length]

Uses ch04's hand-rolled protobuf encoder for the actual message encoding.

Run:
    uv run python -m appendices.appendix_b_streaming_serialization.proto_streaming
"""

from __future__ import annotations

import time

from shared.sample_data import make_typical_order

# Re-use the from-scratch protobuf encoder/decoder from Chapter 04
from chapters.ch04_protobuf.proto_from_scratch import (
    encode_varint,
    decode_varint,
    encode_string_field,
    encode_varint_field,
    encode_double_field,
    encode_bool_field,
    decode_tag,
    WIRE_VARINT,
    WIRE_64BIT,
    WIRE_LENGTH_DELIMITED,
)


# ---------------------------------------------------------------------------
# Simplified order encoder (flat proto message, no nesting)
# ---------------------------------------------------------------------------

def _encode_simple_order(order_dict: dict) -> bytes:
    """Encode a simplified order as a flat protobuf message.

    Schema (field numbers):
        1: order_id     (string)
        2: restaurant   (string)
        3: total_cents  (uint32 varint)
        4: latitude     (double)
        5: longitude    (double)
        6: is_delivered  (bool)
        7: status       (string)
    """
    parts = []
    parts.append(encode_string_field(1, order_dict.get("order_id", "")))
    parts.append(encode_string_field(2, order_dict.get("restaurant_name", "")))
    parts.append(encode_varint_field(3, order_dict.get("total_cents", 0)))
    lat = order_dict.get("latitude", 0.0)
    lon = order_dict.get("longitude", 0.0)
    if lat:
        parts.append(encode_double_field(4, lat))
    if lon:
        parts.append(encode_double_field(5, lon))
    parts.append(encode_bool_field(6, order_dict.get("is_delivered", False)))
    parts.append(encode_string_field(7, order_dict.get("status", "")))
    return b"".join(parts)


def _decode_simple_order(data: bytes) -> dict:
    """Decode a simplified order from protobuf bytes."""
    result: dict = {
        "order_id": "",
        "restaurant_name": "",
        "total_cents": 0,
        "latitude": 0.0,
        "longitude": 0.0,
        "is_delivered": False,
        "status": "",
    }
    offset = 0
    while offset < len(data):
        field_number, wire_type, offset = decode_tag(data, offset)
        if wire_type == WIRE_VARINT:
            value, offset = decode_varint(data, offset)
            if field_number == 3:
                result["total_cents"] = value
            elif field_number == 6:
                result["is_delivered"] = bool(value)
        elif wire_type == WIRE_64BIT:
            import struct
            value = struct.unpack_from("<d", data, offset)[0]
            offset += 8
            if field_number == 4:
                result["latitude"] = value
            elif field_number == 5:
                result["longitude"] = value
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, offset = decode_varint(data, offset)
            raw = data[offset : offset + length]
            offset += length
            if field_number == 1:
                result["order_id"] = raw.decode("utf-8")
            elif field_number == 2:
                result["restaurant_name"] = raw.decode("utf-8")
            elif field_number == 7:
                result["status"] = raw.decode("utf-8")
        else:
            raise ValueError(f"Unknown wire type {wire_type} at field {field_number}")
    return result


# ---------------------------------------------------------------------------
# Stream encoder / decoder
# ---------------------------------------------------------------------------

def encode_stream(orders: list[dict]) -> bytes:
    """Encode a list of orders as a length-prefixed protobuf stream.

    Wire format: [varint_length][proto_bytes][varint_length][proto_bytes]...
    """
    parts: list[bytes] = []
    for order in orders:
        msg = _encode_simple_order(order)
        parts.append(encode_varint(len(msg)))
        parts.append(msg)
    return b"".join(parts)


def decode_stream(data: bytes) -> list[dict]:
    """Decode a length-prefixed protobuf stream, yielding one dict per record."""
    records: list[dict] = []
    offset = 0
    while offset < len(data):
        msg_len, offset = decode_varint(data, offset)
        msg_bytes = data[offset : offset + msg_len]
        offset += msg_len
        records.append(_decode_simple_order(msg_bytes))
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order_dicts(n: int) -> list[dict]:
    """Generate n simplified order dicts."""
    base = make_typical_order()
    orders = []
    for i in range(n):
        orders.append({
            "order_id": f"order-{i:06d}",
            "restaurant_name": base.restaurant_id,
            "total_cents": base.total_cents + i,
            "latitude": 40.748817,
            "longitude": -73.985428,
            "is_delivered": i % 3 == 0,
            "status": base.status.value,
        })
    return orders


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo() -> None:
    print("=" * 64)
    print("  Length-Prefixed Protobuf Streaming")
    print("=" * 64)

    # Basic encode/decode
    orders = _make_order_dicts(5)
    stream_bytes = encode_stream(orders)

    print(f"\n  Encoded {len(orders)} orders as length-prefixed stream")
    print(f"  Total stream size: {len(stream_bytes)} bytes")
    print(f"  Average per record: {len(stream_bytes) / len(orders):.1f} bytes")

    # Show first record's wire layout
    msg_len, hdr_end = decode_varint(stream_bytes, 0)
    print("\n  First record:")
    print(f"    Length prefix: {msg_len} (varint: {hdr_end} byte(s))")
    first_msg = stream_bytes[hdr_end : hdr_end + msg_len]
    hex_preview = " ".join(f"{b:02X}" for b in first_msg[:32])
    print(f"    Proto bytes (first 32): {hex_preview}...")

    # Decode all
    decoded = decode_stream(stream_bytes)
    print(f"\n  Decoded {len(decoded)} records")
    for i, rec in enumerate(decoded[:3]):
        print(f"    [{i}] id={rec['order_id']}  total={rec['total_cents']}  "
              f"delivered={rec.get('is_delivered', False)}")
    if len(decoded) > 3:
        print(f"    ... and {len(decoded) - 3} more")

    # Verify roundtrip
    print("\n  Roundtrip verification:")
    all_ok = True
    for i, (orig, dec) in enumerate(zip(orders, decoded)):
        for key in orig:
            if orig[key] != dec.get(key):
                print(f"    MISMATCH at record {i}, field '{key}': "
                      f"{orig[key]!r} != {dec.get(key)!r}")
                all_ok = False
    if all_ok:
        print(f"    PASS: all {len(orders)} records match")

    # Benchmark: stream vs single-blob
    print(f"\n{'='*64}")
    print("  Benchmark: Encode + Decode")
    print(f"{'='*64}")

    import json

    for n in [100, 1_000, 10_000]:
        order_dicts = _make_order_dicts(n)

        # Proto stream
        t0 = time.perf_counter_ns()
        proto_bytes = encode_stream(order_dicts)
        proto_enc_us = (time.perf_counter_ns() - t0) / 1000

        t0 = time.perf_counter_ns()
        _decoded = decode_stream(proto_bytes)
        proto_dec_us = (time.perf_counter_ns() - t0) / 1000

        # JSON array for comparison
        t0 = time.perf_counter_ns()
        json_bytes = json.dumps(order_dicts, separators=(",", ":")).encode()
        json_enc_us = (time.perf_counter_ns() - t0) / 1000

        t0 = time.perf_counter_ns()
        _json_decoded = json.loads(json_bytes)
        json_dec_us = (time.perf_counter_ns() - t0) / 1000

        print(f"\n  {n:>6,} orders:")
        print(f"    Proto stream: {len(proto_bytes):>10,} bytes  "
              f"enc {proto_enc_us:>10,.0f} us  dec {proto_dec_us:>10,.0f} us")
        print(f"    JSON array:   {len(json_bytes):>10,} bytes  "
              f"enc {json_enc_us:>10,.0f} us  dec {json_dec_us:>10,.0f} us")
        ratio = len(json_bytes) / max(len(proto_bytes), 1)
        print(f"    Proto is {ratio:.1f}x smaller")


if __name__ == "__main__":
    demo()
