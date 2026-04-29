"""Apache Avro -- fastavro library usage and benchmarks.

Demonstrates:
  - fastavro.schemaless_writer / schemaless_reader for single messages
  - fastavro.writer / reader for container files (.avro) with embedded schema
  - Benchmark comparisons: Avro vs Protobuf vs JSON vs MsgPack
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
from pathlib import Path

import fastavro

from shared.bench import benchmark, compare
from shared.sample_data import make_typical_order

from chapters.ch06_avro.avro_from_scratch import (
    avro_encode,
    avro_decode,
    order_to_avro_dict,
)


def _load_schema() -> dict:
    """Load and parse the Avro schema."""
    schema_path = Path(__file__).parent / "fooddash.avsc"
    with open(schema_path) as f:
        schema = json.load(f)
    return fastavro.parse_schema(schema)


# ============================================================================
# Schemaless (single message) encoding/decoding
# ============================================================================

def schemaless_encode(schema: dict, record: dict) -> bytes:
    """Encode a single record without container framing."""
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def schemaless_decode(schema: dict, data: bytes) -> dict:
    """Decode a single record without container framing."""
    buf = io.BytesIO(data)
    return fastavro.schemaless_reader(buf, schema)


# ============================================================================
# Container file (.avro) with embedded schema
# ============================================================================

def write_container_file(schema: dict, records: list[dict], path: str) -> int:
    """Write records to an Avro container file. Returns file size in bytes."""
    with open(path, "wb") as f:
        fastavro.writer(f, schema, records)
    return Path(path).stat().st_size


def read_container_file(path: str) -> tuple[dict, list[dict]]:
    """Read an Avro container file. Returns (writer_schema, records)."""
    with open(path, "rb") as f:
        reader = fastavro.reader(f)
        writer_schema = reader.writer_schema
        records = list(reader)
    return writer_schema, records


# ============================================================================
# Benchmark helpers
# ============================================================================

def _make_avro_fns(schema: dict, order_dict: dict):
    """Create Avro (fastavro) encode/decode functions for benchmarking."""
    def encode():
        return schemaless_encode(schema, order_dict)
    def decode(data):
        return schemaless_decode(schema, data)
    return encode, decode


def _make_avro_scratch_fns(schema_raw: dict, order_dict: dict):
    """Create Avro (from-scratch) encode/decode functions."""
    def encode():
        return avro_encode(schema_raw, order_dict)
    def decode(data):
        return avro_decode(schema_raw, data, 0)[0]
    return encode, decode


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
    """Create Protobuf (from-scratch) encode/decode functions, if available."""
    try:
        from chapters.ch04_protobuf.proto_from_scratch import (
            encode_order, decode_order, _prepare_order_dict,
        )
        proto_dict = _prepare_order_dict(make_typical_order())
        def encode():
            return encode_order(proto_dict)
        def decode(data):
            return decode_order(data)
        return encode, decode
    except ImportError:
        return None, None


def _make_msgpack_fns(order_dict: dict):
    """Create MsgPack encode/decode functions, if available."""
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
    print("--- Apache Avro: fastavro library & benchmarks ---\n")

    schema = _load_schema()

    # Also load raw schema (not parsed) for from-scratch encoder
    schema_path = Path(__file__).parent / "fooddash.avsc"
    with open(schema_path) as f:
        schema_raw = json.load(f)

    order = make_typical_order()
    order_dict = order_to_avro_dict(order)

    # ------------------------------------------------------------------
    # 1. Schemaless encoding (single message)
    # ------------------------------------------------------------------
    print("=== Schemaless Encoding (Single Message) ===\n")

    avro_bytes = schemaless_encode(schema, order_dict)
    print(f"  Encoded size: {len(avro_bytes):,} bytes")

    decoded = schemaless_decode(schema, avro_bytes)
    print(f"  Decoded id: {decoded['id']}")
    print(f"  Decoded customer: {decoded['customer']['name']}")
    print(f"  Decoded status: {decoded['status']}")
    print(f"  Decoded items: {len(decoded['items'])} items")
    print(f"  Roundtrip: {'OK' if decoded['id'] == order_dict['id'] else 'FAIL'}")

    # ------------------------------------------------------------------
    # 2. Container file with embedded schema
    # ------------------------------------------------------------------
    print("\n\n=== Container File (.avro) with Embedded Schema ===\n")
    print("  This is Avro's killer feature for data pipelines:")
    print("  the schema is embedded in the file header.\n")

    with tempfile.NamedTemporaryFile(suffix=".avro", delete=False) as tmp:
        avro_file = tmp.name

    # Write 10 orders
    orders = [order_to_avro_dict(order) for _ in range(10)]
    file_size = write_container_file(schema, orders, avro_file)
    print(f"  Wrote {len(orders)} orders to {Path(avro_file).name}")
    print(f"  File size: {file_size:,} bytes")
    print(f"  Per-record (amortized): {file_size / len(orders):.0f} bytes")
    print(f"  Schemaless per-record: {len(avro_bytes):,} bytes")
    print(f"  Schema overhead (total): {file_size - len(avro_bytes) * len(orders):+,} bytes")

    # Read it back
    writer_schema, read_records = read_container_file(avro_file)
    print(f"\n  Read back {len(read_records)} records")
    print(f"  Writer schema embedded in file: {writer_schema.get('name', '?')} ({writer_schema.get('namespace', '?')})")
    print(f"  Schema has {len(writer_schema.get('fields', []))} top-level fields")

    # Show schema from file header
    print("\n  Fields in embedded schema:")
    for field in writer_schema.get("fields", [])[:8]:
        ftype = field["type"]
        if isinstance(ftype, dict):
            ftype = ftype.get("type", ftype)
        elif isinstance(ftype, list):
            ftype = f"union{ftype}"
        print(f"    {field['name']:<35s} {str(ftype)}")
    print(f"    ... and {len(writer_schema.get('fields', [])) - 8} more fields")

    # Clean up
    Path(avro_file).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # 3. Size comparison across all formats
    # ------------------------------------------------------------------
    print("\n\n=== Size Comparison ===\n")

    sizes = {}

    # Avro (fastavro)
    sizes["Avro (fastavro)"] = len(avro_bytes)

    # Avro (from-scratch)
    scratch_bytes = avro_encode(schema_raw, order_dict)
    sizes["Avro (scratch)"] = len(scratch_bytes)

    # JSON
    def _json_default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)
    json_dict = order.model_dump()
    json_bytes = json.dumps(json_dict, default=_json_default).encode("utf-8")
    sizes["JSON"] = len(json_bytes)

    # MsgPack
    try:
        import msgpack
        mp_bytes = msgpack.packb(order.model_dump(), use_bin_type=True)
        sizes["MsgPack"] = len(mp_bytes)
    except ImportError:
        pass

    # Protobuf
    try:
        from chapters.ch04_protobuf.proto_from_scratch import encode_order, _prepare_order_dict
        proto_dict = _prepare_order_dict(order)
        proto_bytes = encode_order(proto_dict)
        sizes["Protobuf (scratch)"] = len(proto_bytes)
    except ImportError:
        pass

    # Print comparison
    min_size = min(sizes.values())
    print(f"  {'Format':<25s} {'Size':>10s} {'vs smallest':>12s}")
    print(f"  {'------':<25s} {'----':>10s} {'-----------':>12s}")
    for name, size in sorted(sizes.items(), key=lambda x: x[1]):
        ratio = size / min_size
        marker = " (smallest)" if size == min_size else ""
        print(f"  {name:<25s} {size:>8,} B  {ratio:>10.2f}x{marker}")

    # ------------------------------------------------------------------
    # 4. Benchmarks
    # ------------------------------------------------------------------
    print("\n\n=== Benchmarks ===\n")

    iterations = 5_000
    results = []

    # JSON
    json_enc, json_dec = _make_json_fns(order.model_dump())
    results.append(benchmark("JSON", json_enc, json_dec, iterations=iterations))

    # MsgPack
    mp_enc, mp_dec = _make_msgpack_fns(order.model_dump())
    if mp_enc:
        results.append(benchmark("MsgPack", mp_enc, mp_dec, iterations=iterations))

    # Protobuf
    proto_enc, proto_dec = _make_proto_fns(order.model_dump())
    if proto_enc:
        results.append(benchmark("Protobuf (scratch)", proto_enc, proto_dec, iterations=iterations))

    # Avro (fastavro)
    avro_enc, avro_dec = _make_avro_fns(schema, order_dict)
    results.append(benchmark("Avro (fastavro)", avro_enc, avro_dec, iterations=iterations))

    # Avro (from-scratch)
    avro_scratch_enc, avro_scratch_dec = _make_avro_scratch_fns(schema_raw, order_dict)
    results.append(benchmark("Avro (scratch)", avro_scratch_enc, avro_scratch_dec, iterations=iterations))

    # Print individual reports
    for r in results:
        r.print_report()

    # Comparison table
    print("\n--- Comparison ---")
    compare(*results)

    # Analysis
    print("--- Analysis ---\n")
    avro_size = [r for r in results if r.name == "Avro (fastavro)"][0].payload_size_bytes
    json_size = [r for r in results if r.name == "JSON"][0].payload_size_bytes
    print(f"  Avro payload:  {avro_size:>8,} bytes (smallest schema-based format)")
    print(f"  JSON payload:  {json_size:>8,} bytes")
    print(f"  Ratio:         {json_size / avro_size:.1f}x smaller\n")
    print("  Why Avro is the smallest:")
    print("    - No field tags at all (vs Protobuf's 1-2 bytes per field)")
    print("    - No field names on the wire (vs JSON/MsgPack)")
    print("    - Zigzag varints for integers (same as Protobuf)")
    print("    - Binary data is raw bytes (vs JSON's base64)")
    print()
    print("  The trade-off:")
    print("    - Reader MUST have the schema (no self-describing wire format)")
    print("    - Schema resolution adds decode-time overhead")
    print("    - This is why Avro pairs with a Schema Registry")


if __name__ == "__main__":
    main()
