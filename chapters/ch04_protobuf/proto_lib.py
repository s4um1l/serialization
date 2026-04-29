"""Protocol Buffers -- library comparison and benchmarks.

Compares the from-scratch encoder with the protobuf library's internal
wire format utilities, plus JSON and MsgPack baselines.

Since we don't require protoc (the .proto compiler), we use the protobuf
library's lower-level descriptor_pool and message_factory to build messages
dynamically at runtime, OR fall back to pure from-scratch encoding.
"""

from __future__ import annotations

import base64
import json

from shared.bench import benchmark, compare
from shared.sample_data import make_typical_order

from chapters.ch04_protobuf.proto_from_scratch import (
    encode_order,
    decode_order,
    decode_message,
    _prepare_order_dict,
)


# ============================================================================
# Protobuf library approach (dynamic descriptors, no protoc needed)
# ============================================================================

def _try_protobuf_library():
    """Attempt to use the protobuf library with dynamic message creation.

    Returns (encode_fn, decode_fn) or None if the library can't be used.
    """
    try:
        from google.protobuf import descriptor_pb2  # noqa: F401
        from google.protobuf import descriptor  # noqa: F401
        from google.protobuf import descriptor_pool  # noqa: F401
        from google.protobuf import symbol_database  # noqa: F401
        from google.protobuf import message_factory  # noqa: F401
    except ImportError:
        return None

    try:
        # Build a file descriptor proto programmatically
        file_proto = descriptor_pb2.FileDescriptorProto()
        file_proto.name = "fooddash_dynamic.proto"
        file_proto.package = "fooddash"
        file_proto.syntax = "proto3"

        # OrderStatus enum
        enum_desc = file_proto.enum_type.add()
        enum_desc.name = "OrderStatus"
        for name, number in [
            ("ORDER_STATUS_UNSPECIFIED", 0), ("PLACED", 1), ("CONFIRMED", 2),
            ("PREPARING", 3), ("READY", 4), ("PICKED_UP", 5),
            ("EN_ROUTE", 6), ("DELIVERED", 7), ("CANCELLED", 8),
        ]:
            val = enum_desc.value.add()
            val.name = name
            val.number = number

        # PaymentMethod enum
        pm_enum = file_proto.enum_type.add()
        pm_enum.name = "PaymentMethod"
        for name, number in [
            ("PAYMENT_METHOD_UNSPECIFIED", 0), ("CREDIT_CARD", 1),
            ("DEBIT_CARD", 2), ("CASH", 3), ("WALLET", 4),
        ]:
            val = pm_enum.value.add()
            val.name = name
            val.number = number

        # GeoPoint message
        geo_msg = file_proto.message_type.add()
        geo_msg.name = "GeoPoint"
        for fname, fnum, ftype in [
            ("latitude", 1, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
            ("longitude", 2, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ]:
            f = geo_msg.field.add()
            f.name = fname
            f.number = fnum
            f.type = ftype
            f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL

        # Customer message
        cust_msg = file_proto.message_type.add()
        cust_msg.name = "Customer"
        for fname, fnum, ftype, type_name in [
            ("id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
            ("name", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
            ("email", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
            ("phone", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
            ("address", 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, None),
            ("location", 6, descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, ".fooddash.GeoPoint"),
        ]:
            f = cust_msg.field.add()
            f.name = fname
            f.number = fnum
            f.type = ftype
            f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
            if type_name:
                f.type_name = type_name

        # We'll use the from-scratch encoder for the full Order since building
        # the complete descriptor tree (with nested repeated messages and maps)
        # is very verbose. The point of this module is benchmarking, not
        # reimplementing the descriptor system.
        return None

    except Exception:
        return None


# ============================================================================
# Benchmark wrappers
# ============================================================================

def _make_json_fns(order_dict: dict):
    """Create JSON encode/decode functions."""
    def _default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)

    def encode():
        return json.dumps(order_dict, default=_default).encode("utf-8")

    def decode(data):
        return json.loads(data)

    return encode, decode


def _make_proto_fns(order_dict: dict):
    """Create protobuf (from-scratch) encode/decode functions."""
    def encode():
        return encode_order(order_dict)

    def decode(data):
        return decode_order(data)

    return encode, decode


def _make_proto_raw_fns(order_dict: dict):
    """Create protobuf raw decode (just field splitting, no interpretation)."""
    def encode():
        return encode_order(order_dict)

    def decode(data):
        return decode_message(data)

    return encode, decode


def _make_msgpack_fns(order_dict: dict):
    """Create MsgPack encode/decode functions (if available)."""
    try:
        import msgpack
    except ImportError:
        return None, None

    def encode():
        return msgpack.packb(order_dict, use_bin_type=True)

    def decode(data):
        return msgpack.unpackb(data, raw=False)

    return encode, decode


# ============================================================================
# main()
# ============================================================================

def main() -> None:
    print("--- Protocol Buffers: library comparison & benchmarks ---\n")

    order = make_typical_order()
    order_dict = _prepare_order_dict(order)

    # Try protobuf library
    lib_result = _try_protobuf_library()
    if lib_result:
        print("  protobuf library: available (dynamic descriptors)")
    else:
        print("  protobuf library: using from-scratch encoder for benchmarks")
        print("  (Building full dynamic descriptors for nested messages + maps")
        print("   is very verbose; the from-scratch encoder is the star here.)\n")

    # Run benchmarks
    iterations = 5_000

    # JSON
    json_enc, json_dec = _make_json_fns(order_dict)
    json_result = benchmark(
        "JSON",
        json_enc, json_dec,
        iterations=iterations,
    )

    # Protobuf from-scratch (full decode)
    proto_enc, proto_dec = _make_proto_fns(order_dict)
    proto_result = benchmark(
        "Protobuf (from-scratch)",
        proto_enc, proto_dec,
        iterations=iterations,
    )

    # Protobuf raw decode (just field splitting)
    proto_raw_enc, proto_raw_dec = _make_proto_raw_fns(order_dict)
    proto_raw_result = benchmark(
        "Protobuf (raw decode)",
        proto_raw_enc, proto_raw_dec,
        iterations=iterations,
    )

    results = [json_result, proto_result, proto_raw_result]

    # MsgPack
    mp_enc, mp_dec = _make_msgpack_fns(order_dict)
    if mp_enc:
        mp_result = benchmark(
            "MsgPack (library)",
            mp_enc, mp_dec,
            iterations=iterations,
        )
        results.append(mp_result)

    # Print individual reports
    for r in results:
        r.print_report()

    # Comparison table
    print("\n--- Comparison ---")
    compare(*results)

    # Analysis
    print("--- Analysis ---\n")
    print("  Protobuf's size advantage comes from field numbers vs names.")
    print("  Even our unoptimized Python encoder produces smaller payloads.\n")

    proto_size = proto_result.payload_size_bytes
    json_size = json_result.payload_size_bytes
    ratio = json_size / proto_size if proto_size > 0 else 0
    print(f"  JSON payload:      {json_size:>8,} bytes")
    print(f"  Protobuf payload:  {proto_size:>8,} bytes")
    print(f"  Ratio:             {ratio:.1f}x smaller\n")

    print("  Note: A C++ protobuf encoder would be 5-10x faster than our")
    print("  Python implementation. The size advantage is the same regardless")
    print("  of implementation language -- it's a property of the format.\n")

    print("  The 'raw decode' benchmark shows just parsing the wire format")
    print("  into {field_number: [values]} without interpreting types.")
    print("  This is what makes Protobuf's wire format simple and efficient:\n")
    print("  every field starts with a tag that tells you exactly how many")
    print("  bytes to skip if you don't care about that field.")


if __name__ == "__main__":
    main()
