# Exercises: Synthesis Capstone (Ch11)

---

## Exercise 1 [Beginner] -- Format Selection Quick-Fire

For each scenario, name the best serialization format and give a one-sentence justification:

1. Browser-to-server API for a food ordering app
2. Real-time GPS position updates from 10,000 delivery drivers
3. Storing 5 years of historical order data for analytics
4. Service-to-service RPC between Python and Go services
5. Human-editable configuration for kitchen display software
6. Streaming order events to a machine learning training pipeline

<details><summary>Solution</summary>

1. **JSON** -- Universal browser support; human-readable for debugging; every HTTP client library handles it natively.
2. **Cap'n Proto or FlatBuffers** -- Zero-copy decode means minimal latency for high-frequency position updates; selective field access reads only lat/long.
3. **Parquet (columnar)** -- Column-oriented compression is ideal for analytical queries; supports predicate pushdown; self-describing with embedded schema.
4. **Protobuf + gRPC** -- Strong cross-language support (both Python and Go have mature gRPC libraries); schema enforcement catches integration bugs at compile time.
5. **TOML or YAML** -- Must be readable and editable by kitchen staff or operators without developer tools.
6. **Avro + Schema Registry** -- Schema evolution handles the fact that the order schema changes faster than ML pipelines are retrained; Kafka-native integration.

</details>

---

## Exercise 2 [Beginner] -- Interpret These Benchmark Results

A team ran an encode/decode benchmark and got these results:

| Format | Payload (B) | Encode (us) | Decode (us) | Enc Mem (B) | Dec Mem (B) |
|--------|------------|-------------|-------------|-------------|-------------|
| JSON | 847 | 18.2 | 14.5 | 12,400 | 28,800 |
| MsgPack | 612 | 8.1 | 6.3 | 4,200 | 18,600 |
| Protobuf | 341 | 5.4 | 7.2 | 2,100 | 9,400 |
| Avro | 298 | 6.8 | 8.1 | 1,800 | 11,200 |
| FlatBuffers | 428 | 3.9 | 0.4 | 1,500 | 320 |
| Cap'n Proto | 464 | 2.1 | 0.3 | 800 | 280 |

Answer:
1. Why is FlatBuffers' decode so much faster than encode?
2. Why is Avro smaller than Protobuf but slower to decode?
3. Why do JSON and MsgPack use the most decode memory?
4. Which format would you pick for a read-heavy cache layer? Why?

<details><summary>Solution</summary>

1. **FlatBuffers decode is just pointer arithmetic.** There is no parsing, no object construction, no memory allocation. "Decoding" means reading the root offset and following pointers. Encoding is slower because it involves building the vtable, computing offsets, and writing fields back-to-front.

2. **Avro has no field tags, so it's smaller but slower.** Without tags, Avro must decode every field sequentially in schema order (can't skip ahead). Protobuf's tags allow skipping fields but add 1-2 bytes per field. Avro trades decode flexibility for wire size.

3. **JSON and MsgPack build full Python object trees.** Decoding creates a dict with nested dicts, lists, and strings for every field. Each Python object has ~50-100 bytes of overhead. An order with 30+ nested objects means 30+ Python allocations. Binary schema formats decode into fewer, more compact structures.

4. **FlatBuffers or Cap'n Proto for a read-heavy cache.** The cache stores encoded bytes and reads are selective (typically checking status, reading one or two fields). With FlatBuffers: store the raw buffer, read any field in 0.4 us with 320 bytes of allocation. With JSON: every cache read costs 14.5 us and 28.8 KB of allocation. At 100K reads/second, FlatBuffers saves 1.4 seconds of CPU and 2.8 GB of allocation per second.

</details>

---

## Exercise 3 [Intermediate] -- FoodDash System Design: New Notification Service

FoodDash is adding a real-time notification service with these requirements:
- Push notifications to customer mobile apps (iOS/Android)
- Order status updates (placed, confirmed, preparing, ready, picked up, delivered)
- Driver location updates (every 5 seconds per active driver)
- Estimated delivery time updates
- Must handle 50,000 concurrent delivery tracking sessions
- 99th percentile latency < 100ms from event to push notification

Design the serialization strategy. Specify the format for each communication channel and justify your choice.

<details><summary>Solution</summary>

**Architecture:**

```
Order Service --> [Kafka: Avro] --> Notification Service --> [WebSocket: MsgPack] --> Mobile App
Driver GPS    --> [gRPC: Protobuf] --> Notification Service
```

**Channel 1: Order Service -> Notification Service (Kafka)**
- **Format: Avro with Schema Registry**
- Why: Order status events evolve frequently (new statuses, new fields). Avro's schema resolution handles version mismatches. Kafka + Avro is a proven pattern.
- Message size: ~300 bytes per status update

**Channel 2: Driver GPS -> Notification Service (gRPC)**
- **Format: Protobuf via gRPC streaming**
- Why: High-frequency updates (every 5 seconds x 10,000 active drivers = 2,000 messages/second). gRPC bidirectional streaming keeps connections alive. Protobuf is compact for the simple {lat, long, timestamp, driver_id} payload (~30 bytes).

**Channel 3: Notification Service -> Mobile App (WebSocket)**
- **Format: MsgPack**
- Why: Mobile apps need a compact binary format over WebSocket. MsgPack has native libraries for both iOS (Swift) and Android (Kotlin). It's schema-free, which simplifies client updates (no need to ship new schemas with app updates). Typical push payload: ~100-200 bytes.
- Alternative: Could use Protobuf, but MsgPack avoids the need to distribute .proto files to mobile clients.

**Latency budget (100ms total):**
- Kafka consume + process: ~20ms
- Notification logic: ~5ms
- WebSocket push: ~30ms
- Network to device: ~40ms
- Buffer: ~5ms

**50,000 concurrent sessions:**
- Each WebSocket consumes ~2 KB of memory (connection state + send buffer)
- Total: ~100 MB for connections
- MsgPack encode per push: ~2 us x 50,000 = 0.1 seconds of CPU per batch push -> fits on 1 core

</details>

---

## Exercise 4 [Intermediate] -- Debug This: Mystery Wire Bytes

A FoodDash engineer reports that orders are arriving corrupted. The raw bytes of a problematic message are:

```
7b 22 69 64 22 3a 22 6f 72 64 30 30 31 22 2c 22
74 6f 74 61 6c 22 3a 39 30 30 37 31 39 39 32 35
34 37 34 30 39 39 33 7d
```

1. What format is this?
2. Decode the message.
3. What's the bug?
4. How would you fix it?

<details><summary>Solution</summary>

1. **JSON** -- the bytes start with `7b` = `{` and end with `7d` = `}`.

2. Decoded: `{"id":"ord001","total":9007199254740993}`

3. **The bug**: The value `9007199254740993` is 2^53 + 1. If any JavaScript consumer parses this JSON, `JSON.parse()` silently rounds it to `9007199254740992` (2^53). The order total is wrong by 1, causing financial reconciliation to fail.

4. **Fix options (pick one):**
   - **Immediate**: Serialize the large integer as a string: `{"total": "9007199254740993"}`
   - **Better**: Switch to a binary format (Protobuf/MsgPack) that natively supports 64-bit integers
   - **If keeping JSON**: Add a validation check that rejects integers > 2^53 and requires them to be sent as strings
   - **Client-side**: Use a JSON parsing library that supports BigInt (e.g., `json-bigint` in JavaScript)

This is a real-world bug that has caused financial losses in production systems. The FoodDash `platform_transaction_id` is specifically designed to trigger this (see `make_large_order()` in `shared/sample_data.py`).

</details>

---

## Exercise 5 [Intermediate] -- Serialization Format Audit

Review FoodDash's current architecture and identify serialization-related risks:

- Frontend (React) <-> API Gateway: JSON over HTTPS
- API Gateway <-> Order Service: JSON over HTTP/1.1
- Order Service <-> Kitchen Display: WebSocket with JSON
- Order Service <-> Payment Service: gRPC with Protobuf
- Order Service <-> Kafka: JSON (no schema registry)
- Kafka <-> Analytics: JSON consumed by Spark

For each channel, rate the risk (low/medium/high) and suggest improvements.

<details><summary>Solution</summary>

| Channel | Risk | Issue | Improvement |
|---------|------|-------|-------------|
| Frontend <-> API Gateway | **Low** | JSON is correct for browser APIs | Add response compression (brotli). Add JSON Schema validation. |
| API Gateway <-> Order Service | **Medium** | JSON over HTTP/1.1 is slow for internal traffic | Switch to gRPC/Protobuf or at least HTTP/2 + MsgPack. JSON parsing adds unnecessary latency on the hot path. |
| Order Service <-> Kitchen Display | **Low** | JSON over WebSocket is fine for low-volume display updates | Consider MsgPack for smaller payloads if bandwidth matters. |
| Order Service <-> Payment Service | **Low** | gRPC + Protobuf is ideal for this channel | Ensure proto files are versioned in a shared repo. Add field-level validation. |
| Order Service <-> Kafka | **HIGH** | JSON with no schema registry means: no compatibility checks, no schema evolution safety, JSON precision bugs | Switch to Avro + Schema Registry. This is the highest-priority fix. |
| Kafka <-> Analytics | **Medium** | JSON in Spark is slow (text parsing at scale) | If switching Kafka to Avro, Analytics gets Avro for free. Alternatively, use Spark's native Avro reader or convert to Parquet on landing. |

**Priority order**: Fix the Kafka channel first (highest risk, most data), then optimize the API Gateway internal path (highest traffic).

</details>

---

## Exercise 6 [Advanced] -- Design a Multi-Format Gateway

FoodDash needs an API gateway that accepts requests in JSON, MsgPack, or Protobuf and forwards them to backend services in the appropriate format.

Design the gateway's content negotiation and transcoding layer:

1. How does the client specify the request format?
2. How does the client specify the desired response format?
3. How does the gateway transcode between formats efficiently?
4. What are the edge cases and failure modes?

<details><summary>Solution</summary>

**1. Request Format (Content-Type header):**
```
Content-Type: application/json
Content-Type: application/msgpack
Content-Type: application/x-protobuf; proto=fooddash.Order
```

**2. Response Format (Accept header):**
```
Accept: application/json            # default for browsers
Accept: application/msgpack          # for mobile apps
Accept: application/x-protobuf      # for internal services
```

**3. Transcoding Architecture:**
```
Request -> Deserialize (based on Content-Type)
        -> Canonical internal representation (Python dict or Pydantic model)
        -> Validate (schema check, field constraints)
        -> Serialize for backend (based on backend's expected format)
        -> Forward to backend
        -> Deserialize backend response
        -> Serialize for client (based on Accept header)
        -> Response
```

**Efficient implementation:**
- Cache compiled Protobuf descriptors and Avro schemas
- Use a zero-copy path when request and backend format match (passthrough)
- For JSON->Protobuf: use `google.protobuf.json_format` (handles field name <-> number mapping)
- For JSON<->MsgPack: transcode via dict (both are schema-free)
- Pool serialization buffers to reduce allocation

**4. Edge Cases and Failure Modes:**

| Edge Case | Handling |
|-----------|----------|
| Unsupported Content-Type | Return 415 Unsupported Media Type |
| Unsupported Accept | Return 406 Not Acceptable, or default to JSON |
| Protobuf unknown fields | Preserve and forward (don't drop) |
| JSON precision loss (int64) | When transcoding Protobuf int64 to JSON, use string representation |
| Binary fields (bytes) | JSON: base64-encode. MsgPack: native binary. Protobuf: native bytes. |
| Null/missing fields | JSON: absent key or `null`. MsgPack: `nil`. Protobuf: default value (indistinguishable from absent). |
| Schema version mismatch | Return 422 with error describing the mismatch |
| Request too large | Enforce per-format size limits (JSON is ~2.5x larger than Protobuf for the same data) |

</details>

---

## Exercise 7 [Advanced] -- Estimate Annual Infrastructure Cost

FoodDash processes:
- 1M order events/second through Kafka
- 100K API requests/second to the gateway
- 10K driver GPS updates/second
- 50K push notifications/second

For each channel, estimate the annual cost difference between using JSON everywhere vs. the optimal format choice. Show your math.

Assumptions:
- Average JSON message: 800 bytes (orders), 200 bytes (API), 100 bytes (GPS), 150 bytes (push)
- Binary format savings: 60% for orders, 50% for API, 70% for GPS, 40% for push
- Cloud networking: $0.01/GB
- CPU for JSON parse: 15 us/msg; binary: 5 us/msg
- vCPU cost: $0.05/hour

<details><summary>Solution</summary>

**Channel 1: Kafka Order Events (1M/s)**
- JSON: 800 B x 1M/s = 800 MB/s = 69.1 TB/day
- Avro: 320 B x 1M/s = 320 MB/s = 27.6 TB/day
- Network savings: 41.5 TB/day x 365 x $0.01/GB = **$151,475/year**
- CPU savings: (15-5) us x 1M x 2 (encode+decode) = 20 vCPUs saved
- 20 vCPUs x $0.05/hr x 8,760 hrs = **$8,760/year**
- **Subtotal: $160,235/year**

**Channel 2: API Gateway (100K/s)**
- JSON: 200 B x 100K/s = 20 MB/s = 1.73 TB/day
- Protobuf: 100 B x 100K/s = 10 MB/s = 0.86 TB/day
- Network savings: 0.87 TB/day x 365 x $0.01/GB = **$3,176/year**
- CPU savings: 10 us x 100K x 2 = 2 vCPUs -> **$876/year**
- **Subtotal: $4,052/year**

**Channel 3: Driver GPS (10K/s)**
- JSON: 100 B x 10K/s = 1 MB/s = 86 GB/day
- Cap'n Proto: 30 B x 10K/s = 0.3 MB/s = 26 GB/day
- Network savings: 60 GB/day x 365 x $0.01/GB = **$219/year**
- CPU savings: negligible at this rate
- **Subtotal: $219/year**

**Channel 4: Push Notifications (50K/s)**
- JSON: 150 B x 50K/s = 7.5 MB/s = 648 GB/day
- MsgPack: 90 B x 50K/s = 4.5 MB/s = 389 GB/day
- Network savings: 259 GB/day x 365 x $0.01/GB = **$945/year**
- CPU savings: 10 us x 50K x 2 = 1 vCPU -> **$438/year**
- **Subtotal: $1,383/year**

**GRAND TOTAL: $165,889/year**

The Kafka channel dominates (97% of savings) because it has the highest volume. Optimizing the Kafka format should be the first priority. The GPS and push channels have low ROI for format changes -- JSON might be acceptable there.

</details>

---

## Exercise 8 [Advanced] -- FoodDash Adds a New Service: Menu Sync

FoodDash is building a Menu Sync service that:
- Restaurants update their menus via a web dashboard (writes: 100/hour)
- Menu data is synced to 10,000 restaurant tablets (reads: 1M/hour)
- Each menu has 50-200 items, each with a name, description, price, thumbnail image (5-50 KB), allergen list, and availability flag
- Tablets display the menu and must update within 30 seconds of a change
- Tablets have limited bandwidth (cellular connection, 1 Mbps)
- Must work offline (cache the full menu)

Design the serialization and sync strategy.

<details><summary>Solution</summary>

**Architecture:**
```
Restaurant Dashboard -> [REST API: JSON] -> Menu Service
Menu Service -> [gRPC streaming: Protobuf delta] -> Sync Gateway
Sync Gateway -> [WebSocket: FlatBuffers] -> Tablet App
```

**Format choices and justification:**

**1. Dashboard -> Menu Service: JSON**
- Low volume (100 writes/hour). Human-debuggable.
- JSON for restaurant operators using the web UI.

**2. Menu Service -> Sync Gateway: Protobuf delta updates**
- When a menu changes, compute the diff (changed items only).
- Send only the delta as a Protobuf message: `{restaurant_id, changed_items[], deleted_item_ids[]}`.
- Full menu Protobuf for initial sync; deltas for updates.
- gRPC server streaming: Sync Gateway subscribes to changes.

**3. Sync Gateway -> Tablet: FlatBuffers**
- **Why FlatBuffers**: Tablets need selective access (render one menu category at a time). FlatBuffers enables reading only the visible items without parsing the full menu.
- **Thumbnail images**: Stored separately from structured data. Reference by URL/hash in the FlatBuffer, download images via HTTP with CDN caching. Never embed large binary blobs in the serialized menu.
- **Delta updates over WebSocket**: Send FlatBuffers with only changed items. Tablet patches its local cache.

**4. Offline cache on tablet: FlatBuffers file**
- Store the full menu as a FlatBuffer file on disk.
- On reconnection: send last-known version timestamp, receive delta.
- FlatBuffers can be memory-mapped: the OS loads only the pages you read.

**Bandwidth optimization for cellular:**
- Full menu (200 items, no thumbnails): ~50 KB as FlatBuffer. With zstd: ~15 KB.
- Delta update (1 changed item): ~200 bytes.
- Thumbnail download: use progressive JPEG, serve via CDN with cache headers.
- Total bandwidth per tablet per day: ~500 KB (well within 1 Mbps).

**30-second update SLA:**
- Menu Service publishes change to gRPC stream: ~100ms
- Sync Gateway pushes to WebSocket: ~200ms
- Network to tablet: ~500ms
- Total: <1 second. Well within the 30-second requirement.

</details>

---

## Exercise 9 [Advanced] -- Benchmark Analysis: What Went Wrong?

A junior engineer presents these benchmark results and concludes "we should use Cap'n Proto everywhere":

| Format | Encode (us) | Decode (us) | Size (B) |
|--------|------------|-------------|----------|
| JSON | 45.2 | 38.1 | 2,847 |
| Protobuf | 12.3 | 15.8 | 498 |
| Cap'n Proto | 1.2 | 0.3 | 512 |

Identify at least 5 problems with this benchmark and/or the conclusion.

<details><summary>Solution</summary>

1. **Missing error bars / statistical information.** Single-value results don't show variance. Were these median, mean, or single-run? Without p50/p99/stddev, the numbers are meaningless. One GC pause could skew results.

2. **Likely comparing different schemas.** Cap'n Proto and FlatBuffers from-scratch implementations typically encode a simplified subset of fields (e.g., 8 fields). JSON and Protobuf encode the full Order (15+ fields with nested objects). Comparing 8-field Cap'n Proto with 15-field JSON is apples to oranges.

3. **Decode measures different things.** JSON/Protobuf decode builds a complete Python dict with all fields. Cap'n Proto "decode" might just be reading the root pointer (zero-copy). To be fair, measure "access all fields" for Cap'n Proto, which requires reading every field.

4. **Ignoring the full picture.** Cap'n Proto's encode is fast because it's writing values at offsets (no transformation). But the ORDER of operations matters: the data must already be in the right structure. If you count the time to prepare the data (convert from Pydantic model to Cap'n Proto builder calls), Cap'n Proto's advantage shrinks.

5. **"Use everywhere" ignores ecosystem costs.** Cap'n Proto has limited language support (~5 languages vs Protobuf's 10+). If FoodDash has services in Python, Go, Java, and TypeScript, Cap'n Proto would require custom implementations for some languages. The engineering cost dwarfs the microseconds saved.

6. **Ignoring payload size context.** Cap'n Proto (512 B) is larger than Protobuf (498 B) due to word alignment padding. For high-throughput Kafka streams, this means more network cost. The 0.3 us decode advantage doesn't help if the bottleneck is network bandwidth.

7. **No warm-up mentioned.** The first iterations include Python import overhead, JIT compilation, memory allocation. Without explicit warm-up, cold-start effects pollute the results.

</details>

---

## Exercise 10 [Advanced] -- Complete System Design: FoodDash v2

FoodDash is redesigning from scratch. You are the serialization architect. Design the complete serialization strategy for a system with:

- 20 microservices (Python, Go, TypeScript, Rust)
- 3 external APIs (mobile app, restaurant dashboard, delivery partner API)
- 1 event streaming platform (Kafka, 2M events/second)
- 1 real-time tracking system (50K concurrent sessions)
- 1 analytics data lake
- Global deployment (US, EU, APAC) with data residency requirements

Deliverables:
1. Format choice for each communication channel (with justification)
2. Schema management strategy
3. Data residency approach
4. Cost estimate (order of magnitude)
5. Migration plan from v1

<details><summary>Solution</summary>

**1. Format Choices:**

| Channel | Format | Why |
|---------|--------|-----|
| External APIs (mobile, dashboard, partner) | JSON over HTTPS/2 + brotli | Universal. OpenAPI spec for documentation. brotli for 20-30% smaller than gzip. |
| Service-to-service sync RPC | Protobuf + gRPC | Strong multi-language support (Python, Go, TypeScript, Rust all have gRPC). Schema enforcement. HTTP/2 multiplexing. |
| Kafka event streaming | Avro + Confluent Schema Registry | Schema evolution with compatibility guarantees. Smallest wire size for events. Schema Registry prevents breaking changes. |
| Real-time tracking (WebSocket) | FlatBuffers | Zero-copy selective reads for GPS coordinates. Clients only parse the fields they display. Rust backend can serve FlatBuffers without allocation. |
| Analytics data lake | Parquet (converted from Avro on landing) | Columnar format for analytical queries. Predicate pushdown. Compression per column. |
| Service config | TOML files in git | Human-editable. Version-controlled. No binary format needed. |

**2. Schema Management:**

- **Central schema repository**: `schemas/` directory in a monorepo (or dedicated repo)
- **Schema Registry**: Confluent Schema Registry for Kafka/Avro schemas
- **Proto Registry**: Buf.build for Protobuf schemas with breaking change detection
- **CI pipeline**: Every PR that modifies schemas runs compatibility checks
- **Versioning**: Semantic versioning for API schemas. Monotonic IDs for Kafka schemas.
- **Code generation**: Automated codegen for Go (protoc-gen-go), TypeScript (protoc-gen-ts), Rust (prost), Python (betterproto)

**3. Data Residency:**

- Each region (US, EU, APAC) runs independent Kafka clusters
- Avro schemas are identical across regions (replicated via Schema Registry)
- Orders contain a `region` field; routing layer ensures data stays in-region
- Cross-region analytics: anonymized Parquet exports only (no PII crosses borders)
- Serialization format is the same globally; data residency is a routing/storage concern, not a serialization concern

**4. Cost Estimate (annual):**

- Kafka bandwidth savings (Avro vs JSON at 2M/s): ~$300K/year
- gRPC vs REST for internal traffic: ~$50K/year (CPU savings)
- FlatBuffers for tracking: ~$10K/year (memory savings on tracking servers)
- Schema Registry infrastructure: ~$20K/year
- Engineering cost for initial migration: ~$200K (one-time, 4 engineers x 3 months)
- **Net annual savings after year 1: ~$340K/year**

**5. Migration Plan (16 weeks):**

- Weeks 1-2: Deploy Schema Registry. Register all existing schemas.
- Weeks 3-4: Add Avro producers alongside JSON on Kafka. Shadow validation.
- Weeks 5-8: Migrate Kafka consumers to Avro (self-service, team by team).
- Weeks 9-10: Deploy gRPC alongside REST for internal services.
- Weeks 11-14: Migrate internal callers to gRPC (highest-traffic first).
- Weeks 15-16: Deploy FlatBuffers for tracking service. Remove old JSON paths.

Each step is independently rollback-safe. No big-bang cutover.

</details>

---

## Exercise 11 [Advanced] -- The Serialization Interview

You're interviewing a candidate for a senior backend role. Design 5 interview questions about serialization, ranging from foundational to system design. Include the ideal answer and what you're evaluating.

<details><summary>Solution</summary>

**Q1 (Foundational):** "What happens when you call `JSON.parse('{"id": 9007199254740993}')` in JavaScript?"

**Ideal answer:** The value is silently rounded to 9007199254740992 because JavaScript Numbers are IEEE 754 doubles with 53 bits of mantissa. Any integer > 2^53 loses precision. Fix: send as string or use BigInt-aware parser.

**Evaluating:** Understanding of number representation, awareness of cross-language serialization pitfalls, practical debugging instinct.

---

**Q2 (Depth):** "Explain the difference between Protobuf and Avro's wire format. Why is Avro smaller?"

**Ideal answer:** Protobuf prefixes each field with a tag (field_number + wire_type). Avro has no tags; fields are encoded in schema order and the reader must have the schema. Avro is smaller because it saves 1-2 bytes per field (no tags), but it can't skip unknown fields or decode without the schema.

**Evaluating:** Understanding of binary format trade-offs, ability to reason about wire-level details, awareness that "smaller" has costs.

---

**Q3 (Trade-offs):** "When would you choose FlatBuffers over Protobuf?"

**Ideal answer:** When you need zero-copy reads (no deserialization step), selective field access (read 2 of 50 fields), or minimal memory allocation (embedded systems, high-frequency data). FlatBuffers trades wire size and encoding complexity for zero-allocation reads. Not worth it for simple request/response RPC where you read all fields anyway.

**Evaluating:** Ability to reason about trade-offs, understanding of when complexity is justified, practical engineering judgment.

---

**Q4 (System Design):** "You're designing a system that processes 1M events/second from Kafka. How do you choose the serialization format?"

**Ideal answer:** Should cover: Avro + Schema Registry for evolution safety, compressed wire size matters at this throughput (calculate bandwidth), producer/consumer language support, schema compatibility strategy (backward + forward), monitoring for serialization errors, dictionary compression for small messages.

**Evaluating:** System thinking, ability to consider multiple dimensions (performance, evolution, operations), knowledge of the Kafka ecosystem.

---

**Q5 (Debugging):** "A service is receiving corrupted data intermittently. The Protobuf decoder throws 'unexpected wire type' errors on about 0.1% of messages. What could cause this?"

**Ideal answer:** Possible causes: (1) Schema version mismatch (producer uses a newer schema that changed a field's type), (2) Message framing error (reading past the end of one message into the next), (3) Network corruption (unlikely with TCP, but possible with UDP), (4) Producer bug where a non-Protobuf message (e.g., JSON) is accidentally sent to the Protobuf topic, (5) Compression/decompression failure corrupting bytes. Debugging: log the raw bytes of failing messages, check producer schema version, compare with expected schema.

**Evaluating:** Debugging methodology, breadth of failure mode knowledge, ability to systematically narrow down causes.

</details>
