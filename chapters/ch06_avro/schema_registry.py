"""Confluent-style Schema Registry simulation.

Demonstrates Avro's killer feature: automatic schema resolution between
writer and reader schemas. This is the pattern used in production Kafka
deployments with the Confluent Schema Registry.

Wire format (Confluent standard):
    [0x00] [4-byte schema ID, big-endian] [Avro payload]

Schema resolution rules:
    - Fields matched by NAME (not position)
    - New fields in reader schema: use default value
    - Fields removed from reader schema: skip in writer data
    - Type changes: error (incompatible)
"""

from __future__ import annotations

import io
import json
import struct
from hashlib import md5

import fastavro

from shared.sample_data import make_typical_order

from chapters.ch06_avro.avro_from_scratch import order_to_avro_dict


# ============================================================================
# Schema Registry
# ============================================================================

class SchemaRegistry:
    """In-memory simulation of a Confluent Schema Registry.

    In production, this would be a REST service (usually at port 8081)
    backed by a Kafka topic (_schemas) for persistence.

    Key operations:
        - register(schema) -> schema_id
        - get(schema_id) -> schema
        - check_compatibility(new_schema, subject) -> bool
    """

    def __init__(self) -> None:
        self._schemas: dict[int, dict] = {}
        self._next_id: int = 1
        self._fingerprints: dict[str, int] = {}  # dedup by content hash

    def register(self, schema: dict) -> int:
        """Register a schema and return its unique ID.

        If the same schema (by content) was already registered, returns
        the existing ID (idempotent).
        """
        # Canonicalize for dedup (handle bytes defaults gracefully)
        def _json_default(obj):
            if isinstance(obj, bytes):
                return obj.hex()
            return str(obj)
        canonical = json.dumps(schema, sort_keys=True, default=_json_default)
        fingerprint = md5(canonical.encode()).hexdigest()

        if fingerprint in self._fingerprints:
            return self._fingerprints[fingerprint]

        schema_id = self._next_id
        self._next_id += 1
        # Parse the schema for fastavro
        parsed = fastavro.parse_schema(schema)
        self._schemas[schema_id] = parsed
        self._fingerprints[fingerprint] = schema_id
        return schema_id

    def get(self, schema_id: int) -> dict:
        """Retrieve a schema by its ID."""
        if schema_id not in self._schemas:
            raise KeyError(f"Schema ID {schema_id} not found")
        return self._schemas[schema_id]

    def list_schemas(self) -> list[tuple[int, str]]:
        """List all registered schemas as (id, name) pairs."""
        result = []
        for sid, schema in self._schemas.items():
            name = schema.get("name", "?")
            ns = schema.get("namespace", "")
            full_name = f"{ns}.{name}" if ns else name
            result.append((sid, full_name))
        return result


# ============================================================================
# Confluent wire format
# ============================================================================

MAGIC_BYTE = 0x00


def encode_with_registry(registry: SchemaRegistry, schema: dict, obj: dict) -> bytes:
    """Encode using the Confluent wire format.

    Wire format: [0x00][4-byte schema ID][Avro schemaless payload]

    The magic byte distinguishes this from raw Avro (which starts with
    'Obj' + 0x01 for container files, or raw data for schemaless).
    """
    schema_id = registry.register(schema)
    parsed = registry.get(schema_id)

    # Encode Avro payload (schemaless)
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, obj)
    payload = buf.getvalue()

    # Wire format: magic + schema_id + payload
    return struct.pack(">bI", MAGIC_BYTE, schema_id) + payload


def decode_with_registry(registry: SchemaRegistry, reader_schema: dict,
                         data: bytes) -> dict:
    """Decode using the Confluent wire format with schema resolution.

    Steps:
        1. Read magic byte (must be 0x00)
        2. Read 4-byte schema ID
        3. Look up writer schema from registry
        4. Decode Avro payload using writer schema + reader schema
        5. fastavro handles schema resolution automatically
    """
    if len(data) < 5:
        raise ValueError("Data too short for Confluent wire format")

    magic, schema_id = struct.unpack(">bI", data[:5])
    if magic != MAGIC_BYTE:
        raise ValueError(f"Invalid magic byte: 0x{magic:02x} (expected 0x00)")

    # Look up writer schema
    writer_schema = registry.get(schema_id)

    # Parse reader schema
    reader_parsed = fastavro.parse_schema(reader_schema)

    # Decode with schema resolution
    buf = io.BytesIO(data[5:])
    return fastavro.schemaless_reader(buf, writer_schema, reader_parsed)


# ============================================================================
# Schema evolution demo schemas
# ============================================================================

def _make_order_v1() -> dict:
    """Order v1: original schema (no tip_cents field)."""
    return {
        "type": "record",
        "name": "Order",
        "namespace": "com.fooddash",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "platform_transaction_id", "type": "long"},
            {"name": "customer", "type": {
                "type": "record",
                "name": "Customer",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "email", "type": ["null", "string"], "default": None},
                    {"name": "phone", "type": ["null", "string"], "default": None},
                    {"name": "address", "type": ["null", "string"], "default": None},
                    {"name": "location", "type": ["null", {
                        "type": "record",
                        "name": "GeoPoint",
                        "fields": [
                            {"name": "latitude", "type": "double"},
                            {"name": "longitude", "type": "double"}
                        ]
                    }], "default": None}
                ]
            }},
            {"name": "restaurant_id", "type": "string"},
            {"name": "items", "type": {"type": "array", "items": {
                "type": "record",
                "name": "OrderItem",
                "fields": [
                    {"name": "menu_item", "type": {
                        "type": "record",
                        "name": "MenuItem",
                        "fields": [
                            {"name": "id", "type": "string"},
                            {"name": "name", "type": "string"},
                            {"name": "price_cents", "type": "int"},
                            {"name": "description", "type": ["null", "string"], "default": None},
                            {"name": "category", "type": ["null", "string"], "default": None},
                            {"name": "is_vegetarian", "type": "boolean", "default": False},
                            {"name": "allergens", "type": {"type": "array", "items": "string"}, "default": []},
                            {"name": "thumbnail_png", "type": "bytes", "default": ""}
                        ]
                    }},
                    {"name": "quantity", "type": "int", "default": 1},
                    {"name": "special_instructions", "type": ["null", "string"], "default": None}
                ]
            }}},
            {"name": "status", "type": {"type": "enum", "name": "OrderStatus",
                "symbols": ["PLACED", "CONFIRMED", "PREPARING", "READY",
                             "PICKED_UP", "EN_ROUTE", "DELIVERED", "CANCELLED"]},
                "default": "PLACED"},
            {"name": "payment_method", "type": {"type": "enum", "name": "PaymentMethod",
                "symbols": ["CREDIT_CARD", "DEBIT_CARD", "CASH", "WALLET"]},
                "default": "CREDIT_CARD"},
            {"name": "driver_id", "type": ["null", "string"], "default": None},
            {"name": "delivery_notes", "type": ["null", "string"], "default": None},
            {"name": "promo_code", "type": ["null", "string"], "default": None},
            # NOTE: no tip_cents field in v1!
            {"name": "created_at", "type": "double"},
            {"name": "updated_at", "type": "double"},
            {"name": "estimated_delivery_minutes", "type": ["null", "int"], "default": None},
            {"name": "metadata", "type": {"type": "map", "values": "string"}, "default": {}}
        ]
    }


def _make_order_v2() -> dict:
    """Order v2: adds tip_cents with default 0."""
    return {
        "type": "record",
        "name": "Order",
        "namespace": "com.fooddash",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "platform_transaction_id", "type": "long"},
            {"name": "customer", "type": {
                "type": "record",
                "name": "Customer",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "email", "type": ["null", "string"], "default": None},
                    {"name": "phone", "type": ["null", "string"], "default": None},
                    {"name": "address", "type": ["null", "string"], "default": None},
                    {"name": "location", "type": ["null", {
                        "type": "record",
                        "name": "GeoPoint",
                        "fields": [
                            {"name": "latitude", "type": "double"},
                            {"name": "longitude", "type": "double"}
                        ]
                    }], "default": None}
                ]
            }},
            {"name": "restaurant_id", "type": "string"},
            {"name": "items", "type": {"type": "array", "items": {
                "type": "record",
                "name": "OrderItem",
                "fields": [
                    {"name": "menu_item", "type": {
                        "type": "record",
                        "name": "MenuItem",
                        "fields": [
                            {"name": "id", "type": "string"},
                            {"name": "name", "type": "string"},
                            {"name": "price_cents", "type": "int"},
                            {"name": "description", "type": ["null", "string"], "default": None},
                            {"name": "category", "type": ["null", "string"], "default": None},
                            {"name": "is_vegetarian", "type": "boolean", "default": False},
                            {"name": "allergens", "type": {"type": "array", "items": "string"}, "default": []},
                            {"name": "thumbnail_png", "type": "bytes", "default": ""}
                        ]
                    }},
                    {"name": "quantity", "type": "int", "default": 1},
                    {"name": "special_instructions", "type": ["null", "string"], "default": None}
                ]
            }}},
            {"name": "status", "type": {"type": "enum", "name": "OrderStatus",
                "symbols": ["PLACED", "CONFIRMED", "PREPARING", "READY",
                             "PICKED_UP", "EN_ROUTE", "DELIVERED", "CANCELLED"]},
                "default": "PLACED"},
            {"name": "payment_method", "type": {"type": "enum", "name": "PaymentMethod",
                "symbols": ["CREDIT_CARD", "DEBIT_CARD", "CASH", "WALLET"]},
                "default": "CREDIT_CARD"},
            {"name": "driver_id", "type": ["null", "string"], "default": None},
            {"name": "delivery_notes", "type": ["null", "string"], "default": None},
            {"name": "promo_code", "type": ["null", "string"], "default": None},
            {"name": "tip_cents", "type": "int", "default": 0},  # NEW in v2
            {"name": "created_at", "type": "double"},
            {"name": "updated_at", "type": "double"},
            {"name": "estimated_delivery_minutes", "type": ["null", "int"], "default": None},
            {"name": "metadata", "type": {"type": "map", "values": "string"}, "default": {}}
        ]
    }


def _make_order_v3() -> dict:
    """Order v3: adds loyalty_points on top of v2."""
    return {
        "type": "record",
        "name": "Order",
        "namespace": "com.fooddash",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "platform_transaction_id", "type": "long"},
            {"name": "customer", "type": {
                "type": "record",
                "name": "Customer",
                "fields": [
                    {"name": "id", "type": "string"},
                    {"name": "name", "type": "string"},
                    {"name": "email", "type": ["null", "string"], "default": None},
                    {"name": "phone", "type": ["null", "string"], "default": None},
                    {"name": "address", "type": ["null", "string"], "default": None},
                    {"name": "location", "type": ["null", {
                        "type": "record",
                        "name": "GeoPoint",
                        "fields": [
                            {"name": "latitude", "type": "double"},
                            {"name": "longitude", "type": "double"}
                        ]
                    }], "default": None}
                ]
            }},
            {"name": "restaurant_id", "type": "string"},
            {"name": "items", "type": {"type": "array", "items": {
                "type": "record",
                "name": "OrderItem",
                "fields": [
                    {"name": "menu_item", "type": {
                        "type": "record",
                        "name": "MenuItem",
                        "fields": [
                            {"name": "id", "type": "string"},
                            {"name": "name", "type": "string"},
                            {"name": "price_cents", "type": "int"},
                            {"name": "description", "type": ["null", "string"], "default": None},
                            {"name": "category", "type": ["null", "string"], "default": None},
                            {"name": "is_vegetarian", "type": "boolean", "default": False},
                            {"name": "allergens", "type": {"type": "array", "items": "string"}, "default": []},
                            {"name": "thumbnail_png", "type": "bytes", "default": ""}
                        ]
                    }},
                    {"name": "quantity", "type": "int", "default": 1},
                    {"name": "special_instructions", "type": ["null", "string"], "default": None}
                ]
            }}},
            {"name": "status", "type": {"type": "enum", "name": "OrderStatus",
                "symbols": ["PLACED", "CONFIRMED", "PREPARING", "READY",
                             "PICKED_UP", "EN_ROUTE", "DELIVERED", "CANCELLED"]},
                "default": "PLACED"},
            {"name": "payment_method", "type": {"type": "enum", "name": "PaymentMethod",
                "symbols": ["CREDIT_CARD", "DEBIT_CARD", "CASH", "WALLET"]},
                "default": "CREDIT_CARD"},
            {"name": "driver_id", "type": ["null", "string"], "default": None},
            {"name": "delivery_notes", "type": ["null", "string"], "default": None},
            {"name": "promo_code", "type": ["null", "string"], "default": None},
            {"name": "tip_cents", "type": "int", "default": 0},
            {"name": "loyalty_points", "type": "int", "default": 0},  # NEW in v3
            {"name": "created_at", "type": "double"},
            {"name": "updated_at", "type": "double"},
            {"name": "estimated_delivery_minutes", "type": ["null", "int"], "default": None},
            {"name": "metadata", "type": {"type": "map", "values": "string"}, "default": {}}
        ]
    }


def _make_v1_order_dict() -> dict:
    """Create an order dict compatible with v1 schema (no tip_cents)."""
    order = make_typical_order()
    d = order_to_avro_dict(order)
    # Remove fields not in v1
    d.pop("tip_cents", None)
    return d


def _make_v3_order_dict() -> dict:
    """Create an order dict compatible with v3 schema (has loyalty_points)."""
    order = make_typical_order()
    d = order_to_avro_dict(order)
    d["loyalty_points"] = 1500  # New field in v3
    return d


# ============================================================================
# main()
# ============================================================================

def main() -> None:
    print("--- Schema Registry & Schema Resolution ---\n")

    registry = SchemaRegistry()

    # ------------------------------------------------------------------
    # 1. Register schemas
    # ------------------------------------------------------------------
    print("=== Registering Schema Versions ===\n")

    v1_schema = _make_order_v1()
    v2_schema = _make_order_v2()
    v3_schema = _make_order_v3()

    v1_id = registry.register(v1_schema)
    v2_id = registry.register(v2_schema)
    v3_id = registry.register(v3_schema)

    print(f"  Order v1 (no tip_cents):          schema_id = {v1_id}")
    print(f"  Order v2 (+ tip_cents):            schema_id = {v2_id}")
    print(f"  Order v3 (+ tip_cents, loyalty):   schema_id = {v3_id}")

    # Idempotent registration
    v1_id_again = registry.register(v1_schema)
    print(f"\n  Re-registering v1: id = {v1_id_again} (same as before = {v1_id == v1_id_again})")

    print("\n  All schemas in registry:")
    for sid, name in registry.list_schemas():
        print(f"    id={sid}: {name}")

    # ------------------------------------------------------------------
    # 2. Wire format demo
    # ------------------------------------------------------------------
    print("\n\n=== Confluent Wire Format ===\n")
    print("  [0x00] [4-byte schema ID] [Avro payload]")
    print("  Total overhead: 5 bytes per message\n")

    v2_order = order_to_avro_dict(make_typical_order())
    wire_bytes = encode_with_registry(registry, v2_schema, v2_order)

    print(f"  Wire message size: {len(wire_bytes):,} bytes")
    print(f"  Magic byte:    0x{wire_bytes[0]:02x}")
    schema_id_from_wire = struct.unpack(">I", wire_bytes[1:5])[0]
    print(f"  Schema ID:     {schema_id_from_wire}")
    print(f"  Avro payload:  {len(wire_bytes) - 5:,} bytes")
    print(f"  Overhead:      5 bytes ({5 / len(wire_bytes) * 100:.2f}%)")

    # Decode
    decoded = decode_with_registry(registry, v2_schema, wire_bytes)
    print(f"\n  Decoded id:       {decoded['id']}")
    print(f"  Decoded tip_cents: {decoded['tip_cents']}")
    print(f"  Roundtrip:        {'OK' if decoded['id'] == v2_order['id'] else 'FAIL'}")

    # ------------------------------------------------------------------
    # 3. Schema resolution: backward compatibility
    # ------------------------------------------------------------------
    print("\n\n=== Schema Resolution Demo ===\n")
    print("  Avro's killer feature: automatic schema resolution.")
    print("  The reader's schema is reconciled with the writer's schema")
    print("  BY FIELD NAME (not by position or field number).\n")

    # --- Scenario 1: Writer v1, Reader v2 (backward compatible) ---
    print("  --- Scenario 1: Writer v1 -> Reader v2 (BACKWARD) ---")
    print("  Writer writes Order v1 (no tip_cents field)")
    print("  Reader reads with Order v2 (has tip_cents, default=0)\n")

    v1_order = _make_v1_order_dict()
    v1_wire = encode_with_registry(registry, v1_schema, v1_order)
    print(f"  Writer (v1) payload: {len(v1_wire):,} bytes")

    # Reader uses v2 schema to read v1 data
    decoded_v2 = decode_with_registry(registry, v2_schema, v1_wire)

    print("  Reader (v2) sees:")
    print(f"    id:         {decoded_v2['id']}")
    print(f"    tip_cents:  {decoded_v2['tip_cents']}  <-- DEFAULT (field didn't exist in v1)")
    print(f"    status:     {decoded_v2['status']}")
    print(f"    items:      {len(decoded_v2['items'])} items")
    print("\n  Result: Reader v2 filled in the default for tip_cents. No crash!")

    # --- Scenario 2: Writer v3, Reader v2 (forward compatible) ---
    print("\n\n  --- Scenario 2: Writer v3 -> Reader v2 (FORWARD) ---")
    print("  Writer writes Order v3 (has tip_cents AND loyalty_points)")
    print("  Reader reads with Order v2 (no loyalty_points field)\n")

    v3_order = _make_v3_order_dict()
    v3_wire = encode_with_registry(registry, v3_schema, v3_order)
    print(f"  Writer (v3) payload: {len(v3_wire):,} bytes")
    print(f"  Writer loyalty_points: {v3_order['loyalty_points']}")

    # Reader uses v2 schema to read v3 data
    decoded_v2_from_v3 = decode_with_registry(registry, v2_schema, v3_wire)

    print("\n  Reader (v2) sees:")
    print(f"    id:              {decoded_v2_from_v3['id']}")
    print(f"    tip_cents:       {decoded_v2_from_v3['tip_cents']}")
    has_loyalty = "loyalty_points" in decoded_v2_from_v3
    print(f"    loyalty_points:  {'PRESENT' if has_loyalty else 'SKIPPED (not in reader schema)'}")
    print(f"    status:          {decoded_v2_from_v3['status']}")
    print("\n  Result: Reader v2 skipped loyalty_points. No crash!")

    # --- Scenario 3: Writer v1, Reader v3 (two versions apart) ---
    print("\n\n  --- Scenario 3: Writer v1 -> Reader v3 (two versions apart) ---")
    print("  Writer writes Order v1 (no tip_cents, no loyalty_points)")
    print("  Reader reads with Order v3 (has both, with defaults)\n")

    decoded_v3_from_v1 = decode_with_registry(registry, v3_schema, v1_wire)

    print("  Reader (v3) sees:")
    print(f"    id:              {decoded_v3_from_v1['id']}")
    print(f"    tip_cents:       {decoded_v3_from_v1['tip_cents']}  <-- DEFAULT")
    print(f"    loyalty_points:  {decoded_v3_from_v1['loyalty_points']}  <-- DEFAULT")
    print("\n  Result: Both new fields got their defaults. Data from 6 months ago still reads!")

    # ------------------------------------------------------------------
    # 4. Summary of resolution rules
    # ------------------------------------------------------------------
    print("\n\n=== Schema Resolution Rules ===\n")
    print("  1. Fields are matched BY NAME (not position or number)")
    print("     -> Field ordering does NOT matter")
    print("     -> This is different from Protobuf (matched by field number)")
    print()
    print("  2. Writer has field, Reader doesn't:")
    print("     -> Field is SKIPPED (forward compatibility)")
    print()
    print("  3. Reader has field, Writer doesn't:")
    print("     -> Default value is used (backward compatibility)")
    print("     -> REQUIRES a default value in the reader schema")
    print()
    print("  4. Both have the field, same type:")
    print("     -> Direct read (normal case)")
    print()
    print("  5. Both have the field, different types:")
    print("     -> ERROR (incompatible change)")
    print("     -> Exception: promotions (int->long, float->double)")
    print()
    print("  Compatibility modes in Confluent Schema Registry:")
    print("    BACKWARD:  new reader can read old data (default)")
    print("    FORWARD:   old reader can read new data")
    print("    FULL:      both backward AND forward")
    print("    NONE:      no compatibility checking")

    # ------------------------------------------------------------------
    # 5. Comparison with Protobuf evolution
    # ------------------------------------------------------------------
    print("\n\n=== Avro vs Protobuf Schema Evolution ===\n")
    print("  Protobuf evolution:")
    print("    - Fields identified by NUMBER")
    print("    - Unknown fields are preserved (but opaque)")
    print("    - No schema embedding in files")
    print("    - Needs the .proto file to decode")
    print()
    print("  Avro evolution:")
    print("    - Fields identified by NAME")
    print("    - Schema embedded in .avro file headers")
    print("    - Writer schema + reader schema = automatic resolution")
    print("    - Schema Registry centralizes versioned schemas")
    print("    - 6-month-old data readable with today's schema")
    print()
    print("  For data pipelines (Kafka, HDFS, S3), Avro wins because:")
    print("    1. The schema IS the data's self-documentation")
    print("    2. No need to track which .proto version wrote which data")
    print("    3. Resolution is automatic, not manual if-field-exists checks")


if __name__ == "__main__":
    main()
