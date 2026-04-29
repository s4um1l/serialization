# Chapter 09: Schema Evolution

## The Scene

FoodDash has been running for two years. The Order schema -- the single most important message in the entire system -- has been through seven versions. Version 1 was a quick prototype: a flat structure with items stored as a comma-separated string. Version 2 split items into a proper list. Version 3 added tip tracking when the company launched its tipping feature. Version 4 introduced driver assignment. Version 5 restructured the payment fields. Version 6 added loyalty points. Version 7 added real-time ETA tracking.

The order service runs v7. The kitchen display service is stuck on v5 -- the team that maintains it was reassigned to a new project six months ago, and nobody has touched it since. The analytics pipeline has data from v1 through v7 sitting in the data lake: two years of orders that need to be queryable together. The payment reconciliation service runs v6 and processes refunds from orders originally placed under v3.

At 1 million messages per second, a schema incompatibility does not produce a polite error dialog. It produces a cascade. The kitchen service receives an order encoded with v7 fields it has never seen. If it crashes, orders pile up. If it silently drops the unknown fields, the kitchen never learns about the customer's allergy note that was added in v6. If it misinterprets a field because a type changed, it bills the wrong amount.

The team needs to answer three questions: What changes are safe? What changes break things? And how does each serialization format handle schema evolution differently?

## The Vocabulary of Schema Evolution

Schema evolution is the practice of changing a message schema while maintaining the ability of existing readers and writers to continue functioning. It sounds simple. In practice, it is the single largest source of production incidents in microservice architectures.

### Forward Compatibility

Forward compatibility means an **old reader** can process data written by a **new writer**. The kitchen service (v5) receives a message from the order service (v7). The message contains fields the kitchen service has never seen: `loyalty_points`, `estimated_eta_seconds`, `driver_rating`. Forward compatibility means the kitchen service does not crash, does not corrupt data, and continues to function correctly with the fields it does understand.

This is the compatibility direction that matters when you deploy producers before consumers. You ship the new order service on Monday, and the kitchen service team will update next sprint. During that gap, the old reader must survive.

### Backward Compatibility

Backward compatibility means a **new reader** can process data written by an **old writer**. The analytics pipeline (v7 reader) ingests historical data written by the original v1 order service two years ago. The v1 data has no tip field, no driver assignment, no loyalty points. Backward compatibility means the analytics pipeline can still read this data, filling in sensible defaults for missing fields.

This is the compatibility direction that matters for historical data, data lakes, log replay, and any situation where old data persists.

### Full Compatibility

Full compatibility means both directions work: old readers handle new data, and new readers handle old data. This is the gold standard for systems where you cannot coordinate deployment order -- where any service might be running any version at any time. In FoodDash's microservice architecture with 20 services, full compatibility is not a luxury. It is a survival requirement.

### The Real World

You rarely control all readers and writers simultaneously. FoodDash has 20 microservices maintained by 8 teams. Deploying a schema change means convincing every team to update their service, test it, and deploy it -- ideally simultaneously. In practice, some services lag by weeks, months, or indefinitely. The kitchen display service on v5 is not a hypothetical. It is the normal state of affairs.

### What "Compatible" Actually Means

"Compatible" does not just mean "does not crash." A system that silently drops a field, misinterprets a type, or returns a zero where a value should exist is not compatible. It is silently corrupt. At 1M msg/s, silent corruption is worse than a crash -- a crash triggers an alert; silent corruption triggers nothing until a customer complaint, a financial discrepancy, or a regulatory audit surfaces it weeks later.

Compatible means: **no crashes AND no silent data corruption.**

## The Rules, Format by Format

### JSON and MessagePack: Self-Describing, No Schema

JSON and MessagePack carry field names in every message. There is no external schema. Every value is tagged with its type. This makes them flexible but undisciplined.

**Add a field:** SAFE. The old reader encounters a key it does not recognize and ignores it -- provided it uses `dict.get()` with defaults rather than direct key access. If the code says `data["loyalty_points"]`, it crashes with a `KeyError`. If it says `data.get("loyalty_points", 0)`, it works perfectly.

**Remove a field:** RISKY. The old reader expects a key that no longer exists. `data["promo_code"]` crashes. `data.get("promo_code")` returns `None`, which may or may not be a valid value in the business logic. If the code does arithmetic on the result, `None` produces a `TypeError` downstream.

**Rename a field:** BREAKS. The old reader looks for `driver_id`. The new writer sends `courier_id`. These are different keys. The old reader sees `driver_id` as missing and `courier_id` as unknown. Both are lost.

**Change a field's type:** SILENT CORRUPTION. The old reader expects `tip_cents` to be an integer. The new writer sends it as a string `"500"`. JSON and MessagePack decode it without error -- the type is whatever the sender put on the wire. The old reader now has a string where it expected an integer. If it does `total = subtotal + tip_cents`, Python raises a `TypeError`. If it does `if tip_cents > 0`, Python compares a string to an integer and may silently produce the wrong result.

**Add an enum value:** PARTIAL. JSON has no enum type -- enums are just strings. The old reader receives `"refunded"` where it expected one of `["placed", "confirmed", ...]`. No crash, but the business logic may have an if/elif chain that does not handle `"refunded"`, leading to silent fallthrough.

**Reorder fields:** SAFE. JSON objects are unordered by specification. Python dicts are ordered by insertion since 3.7, but JSON parsers are not required to preserve order. MessagePack maps are likewise keyed, not positional.

**Strategy:** Always use `.get()` with explicit defaults. Never depend on field order. Never do type-unsafe operations on decoded values. Consider using Pydantic or dataclasses to validate decoded data against expected types.

### Protobuf: Schema-First, Field Tags

Protobuf identifies fields by numeric tags on the wire. Field names exist only in the `.proto` file -- they never appear in the serialized bytes. This fundamental design choice makes protobuf the most evolution-friendly binary format.

**Add a field:** SAFE. The old reader encounters a tag it does not recognize. The wire format encodes the wire type with the tag, so the decoder knows exactly how many bytes to skip -- varint, 4 bytes, 8 bytes, or length-delimited. The unknown field is silently preserved (in most implementations) or discarded, but never causes a crash.

**Remove a field:** SAFE. The new writer simply does not emit the field. The old reader does not find the tag and uses the default value: 0 for integers, empty string for strings, false for bools. Proto3 semantics mean every field already has an implicit default.

**Rename a field:** SAFE. Only the tag number matters on the wire. You can rename `driver_id` to `courier_id` in your `.proto` file, and as long as the field number stays the same, every existing reader continues to work. They will still call it `driver_id` in their code, but the bytes are identical.

**Change wire type:** BREAKS. If you change a field from `int32` (varint, wire type 0) to `string` (length-delimited, wire type 2), the old reader tries to decode a length-delimited value as a varint. The tag encodes the wire type, and a mismatch produces garbage or a decode error.

**Add an enum value:** RISKY. The old reader receives an integer it does not have a name for. Most protobuf implementations store it as the raw integer and expose it as `UNKNOWN(9)`. The value is preserved, but business logic that switches on enum values may not handle it. Proto3's open enum semantics help: unknown values are kept, not rejected.

**Reorder fields:** SAFE. Protobuf fields can appear in any order on the wire. The decoder matches by tag number, not position.

**Critical rules:**
- Never reuse a field number. Once field 7 was `tip_cents`, it must always be `tip_cents` or reserved.
- Use the `reserved` keyword to prevent accidental reuse: `reserved 7; reserved "tip_cents";`
- Never change a field's wire type.

### Avro: Schema-First, Field Names, Resolution

Avro takes a radically different approach. There are **no tags on the wire at all**. Fields are encoded in schema order, and the reader must have the schema to know which bytes are which. But Avro has a powerful feature that protobuf lacks: schema resolution.

With schema resolution (typically via a Schema Registry), the reader knows both the writer's schema and its own schema. It reads the bytes using the writer's schema, then maps field-by-field to the reader's schema by **name**.

**Add a field with a default:** SAFE (both directions). The reader's schema has a field the writer's schema lacks. Resolution fills in the default value. The writer's schema has extra fields the reader ignores.

**Add a field without a default:** BREAKS backward compatibility. If the new reader expects a field that old data does not contain, and there is no default, resolution cannot fill in a value. The decode fails.

**Remove a field with a default:** SAFE. Old readers have the field in their schema with a default. When reading new data that lacks the field, resolution fills in the default.

**Rename a field:** BREAKS. Avro matches fields by name. If the writer calls it `courier_id` and the reader expects `driver_id`, resolution cannot match them. Avro supports aliases as a workaround: you can declare `"aliases": ["driver_id"]` on the `courier_id` field, and resolution will match the old name.

**Reorder fields:** SAFE with resolution. Resolution matches by name, not position. Without resolution (raw positional decode), reordering breaks everything.

**Change type:** Limited support. Avro defines specific type promotions: `int` can be promoted to `long`, `float`, or `double`. `long` can be promoted to `float` or `double`. `float` can be promoted to `double`. All other type changes break.

**Critical dependency:** Avro's evolution story depends entirely on having a Schema Registry. Without it, even adding a field can break readers. With it, Avro's compatibility guarantees are rigorous and enforced.

### FlatBuffers and Cap'n Proto

FlatBuffers and Cap'n Proto follow similar evolution rules to protobuf because they also use numeric field identifiers.

**FlatBuffers:** Fields are identified by slot position in the vtable. Adding fields at the end is safe. Deprecated fields keep their slot (it is never reused) and simply return the default value. Removing a field means marking it deprecated, not actually removing it from the schema.

**Cap'n Proto:** Evolution works by adding fields at the end of a struct. Existing fields cannot be removed or reordered. The struct layout is fixed, and new fields are appended. Old readers simply do not read past their known struct size.

## The Migration Demo

The `migration_demo.py` module simulates FoodDash's schema evolution over three versions:

**v1 (launch):** Basic order with `id`, `customer_id`, `restaurant_id`, `items` as a string, `status`, `total_cents`, `created_at`.

**v2 (three months later):** Added `tip_cents` (default 0) and `driver_id` (optional). Changed `items` from a comma-separated string to a proper list. Kept `total_cents`.

**v3 (six months later):** Added `loyalty_points` (default 0). Removed `total_cents` (now computed from items). Kept all other fields.

The demo encodes with each version and cross-decodes between versions:

| Direction | JSON/MsgPack | Protobuf | Avro (no resolution) |
|-----------|-------------|----------|---------------------|
| v1 -> v2 reader | PARTIAL: items type mismatch (str vs list) | PASS: missing fields default, old field 4 readable | FAIL: items type mismatch crashes decoder |
| v2 -> v3 reader | PASS: new fields default, removed field ignored | PASS: field 6 simply not read | FAIL: positional misalignment |
| v1 -> v3 reader | PARTIAL: items type mismatch persists | PASS: two-version gap works via tags | FAIL: cascading incompatibility |

The key insight: Protobuf handles all three version jumps seamlessly. JSON/MsgPack survive most jumps but cannot handle type changes. Avro requires a Schema Registry for any cross-version reading.

## The Compatibility Matrix

```
Change                     JSON      MsgPack    Protobuf     Avro
-----------------------------------------------------------------
Add field (with default)   PASS      PASS       PASS         PASS*
Add field (no default)     PASS      PASS       PASS         FAIL
Remove field               PARTIAL   PARTIAL    PASS         PASS*
Rename field               FAIL      FAIL       PASS         FAIL
Change type                FAIL      FAIL       FAIL         FAIL**
Add enum value             PARTIAL   PARTIAL    PARTIAL      FAIL
Reorder fields             PASS      PASS       PASS         PASS*
```

`*` Requires Schema Registry for resolution.
`**` Avro supports specific type promotions (int->long, float->double) but all other type changes fail.

## Production Depth

### Confluent Schema Registry

The Schema Registry is a centralized service that stores versioned schemas and enforces compatibility rules. Every Avro (and increasingly Protobuf/JSON Schema) message carries a schema ID in its header. The consumer fetches the writer's schema by ID and uses it for resolution.

**Compatibility modes:**

- **BACKWARD:** New schema can read data from the last version. You can add fields with defaults and remove fields. This is the default mode. Use when consumers upgrade before producers.

- **FORWARD:** Last schema can read data from the new schema. You can remove fields with defaults and add fields. Use when producers upgrade before consumers.

- **FULL:** Both backward and forward compatible with the last version. Only add or remove fields that have defaults.

- **BACKWARD_TRANSITIVE / FORWARD_TRANSITIVE / FULL_TRANSITIVE:** Same rules, but checked against ALL previous versions, not just the last one. FULL_TRANSITIVE is the gold standard for systems with historical data.

- **NONE:** No checking. For development only.

### Protobuf `reserved` Keyword

When you remove a field from a `.proto` file, you must reserve its field number to prevent future reuse:

```protobuf
message Order {
  string id = 1;
  // field 7 was tip_cents, removed in v5
  reserved 7;
  reserved "tip_cents";
  // ...
}
```

Without `reserved`, a future developer might assign field number 7 to a new field with a different type. Old data that still has field 7 as `tip_cents` (an int) would be decoded as the new field (perhaps a string), causing silent corruption.

### Avro Schema Fingerprint

Avro schemas can be uniquely identified by a fingerprint -- a hash (typically CRC-64-AVRO or MD5 or SHA-256) of the schema's canonical form (parsing canonical form or Rabin fingerprint). This allows fast schema matching: instead of transmitting the full schema with every message, the producer sends a 64-bit fingerprint, and the consumer looks up the schema in a cache.

The canonical form normalizes the schema: fields are sorted, whitespace is removed, defaults and docs are stripped. Two logically equivalent schemas produce the same fingerprint.

### JSON Schema

JSON has no built-in schema, but JSON Schema (drafts 04, 06, 07, 2019-09, 2020-12) provides external validation. Key features for schema evolution:

- **`additionalProperties: true`** (the default): allows unknown fields, enabling forward compatibility.
- **`additionalProperties: false`**: rejects unknown fields, breaking forward compatibility but providing strict validation.
- **`$ref`**: schema composition and reuse. A shared `Address.json` schema referenced by `Customer.json` and `Restaurant.json`.
- **Required vs. optional fields**: the `required` array lists mandatory fields. Adding a field to `required` breaks backward compatibility. Adding an optional field is safe.

JSON Schema does not provide automatic resolution like Avro. It is a validation tool, not an encoding format. You validate after decoding, not during.

### The "Never Delete, Only Deprecate" Philosophy

Many organizations adopt a strict rule: never remove a field from a schema. Instead, mark it as deprecated (in protobuf, add `[deprecated = true]`; in Avro, add documentation; in JSON Schema, add `"deprecated": true`). Deprecated fields continue to be serialized and deserialized but are no longer used in business logic.

This maximizes compatibility at the cost of schema bloat. Over years, schemas accumulate dozens of deprecated fields. Some organizations periodically perform "schema compaction" -- creating a new schema version that removes long-deprecated fields, with a coordinated migration of all services.

The philosophy reflects a fundamental truth: in a distributed system, you cannot guarantee that every reader has been updated. Deleting a field is a bet that no reader will ever encounter old data containing that field. In a system with a data lake, that bet always loses.

## Trade-offs Table

| Capability | JSON | MsgPack | Protobuf | Avro |
|---|---|---|---|---|
| Schema enforcement | None (voluntary) | None (voluntary) | Compile-time | Runtime + Registry |
| Field identification | By name | By name | By tag number | By name (resolution) |
| Unknown field handling | Ignored | Ignored | Skipped (preserved) | Resolution required |
| Type safety | None | None | Wire type checked | Schema checked |
| Safe to add fields | Yes | Yes | Yes | Yes (with default) |
| Safe to remove fields | Risky | Risky | Yes | Yes (with default) |
| Safe to rename fields | No | No | Yes | No (use aliases) |
| Safe to change types | No | No | No (wire type) | Limited promotions |
| Requires external tool | No | No | protoc compiler | Schema Registry |
| Evolution philosophy | Liberal | Liberal | Conservative | Strict |

JSON and MessagePack are liberal: anything goes, but nothing is enforced. Protobuf is conservative: the wire format enforces tag-based identification and wire type safety. Avro is strict: the Schema Registry enforces compatibility rules before a new schema can be registered.

## The Bridge

We now understand the rules of schema evolution for every format. We know what is safe and what breaks. We know that JSON gives you freedom without guardrails, Protobuf gives you tag-based resilience, and Avro gives you registry-enforced rigor.

Combined with everything we have learned -- encoding speed, decode speed, wire size, compression, zero-copy access, schema resolution -- we have all the information needed to make an informed choice. But how do you actually decide? What framework do you use when a new service needs a serialization format? When should you pick JSON over Protobuf? When does Avro's registry overhead pay for itself? When do you need zero-copy? That is Chapter 10.
