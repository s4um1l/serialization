# Exercises: Compression (Ch08) + Schema Evolution (Ch09-Ch10) + Choosing a Format

---

## Exercise 1 [Beginner] -- Predict Compression Ratio

For each data pattern, predict whether zstd compression will achieve high (>3x), moderate (1.5-3x), or low (<1.5x) compression:

1. A JSON array of 1000 identical orders
2. Random binary data (e.g., `/dev/urandom`)
3. A CSV file with 10,000 rows and 5 columns, mostly integers
4. A Protobuf message containing a 1 MB PNG image
5. A MsgPack array of 1000 unique strings (customer names)

<details><summary>Solution</summary>

1. **High (>10x)**. Identical orders mean massive repetition. The compressor's dictionary window will reference the first order for all subsequent ones. JSON's verbosity (repeated key names) makes this even more compressible.

2. **Low (~1.0x)**. Random data is incompressible by definition (maximum entropy). The compressed output may even be slightly larger than the input due to framing overhead.

3. **High (3-5x)**. CSV has repeated column headers (if present), repeated delimiter patterns, and integer text representations that are highly regular. Integers like "1700000000" share a common prefix.

4. **Low (~1.0x)**. PNG is already compressed (deflate internally). Compressing compressed data yields negligible savings. This is why you should NOT compress payloads that already contain compressed binary data.

5. **Moderate (1.5-2x)**. Unique strings have some compressibility (common prefixes, letter frequency patterns) but much less than repeated data. MsgPack's binary format is already more compact than JSON, giving compression less to work with.

**Key insight**: Compression works best on **redundant** data. Binary formats (Protobuf, MsgPack) are already somewhat compressed (no redundant key names, compact encoding), so they benefit less from additional compression than JSON.

</details>

---

## Exercise 2 [Beginner] -- Compression Algorithm Trade-offs

Match each compression algorithm to its primary strength:

| Algorithm | Best for |
|-----------|----------|
| zstd | ? |
| lz4 | ? |
| gzip/deflate | ? |
| snappy | ? |
| brotli | ? |

Options: (A) Maximum speed, (B) Best ratio/speed balance, (C) Maximum compatibility, (D) Web content, (E) Google's internal systems

<details><summary>Solution</summary>

| Algorithm | Best for | Why |
|-----------|----------|-----|
| zstd | **(B) Best ratio/speed balance** | Tunable compression levels 1-22. Level 3 matches gzip ratio at 5x speed. Supports dictionary training. |
| lz4 | **(A) Maximum speed** | Decompression at >4 GB/s. Compression ratio is lower but latency is minimal. Ideal for IPC and caching. |
| gzip/deflate | **(C) Maximum compatibility** | Supported everywhere (HTTP, ZIP, PNG, Avro). Not the fastest or smallest, but universally available. |
| snappy | **(E) Google's internal systems** | Designed for Google's internal data processing. Similar to lz4 in philosophy (speed > ratio). Used in Bigtable, MapReduce. |
| brotli | **(D) Web content** | Designed for HTTP compression. Better ratio than gzip for text/HTML. Supported by all modern browsers. |

For FoodDash at 1M messages/second:
- **lz4** for inter-service RPC (lowest latency overhead)
- **zstd** for Kafka message storage (best ratio without killing throughput)
- **gzip** for HTTP APIs to external consumers (universal support)

</details>

---

## Exercise 3 [Intermediate] -- Compression + Serialization Interaction

You're benchmarking JSON vs Protobuf for FoodDash orders. Before compression, Protobuf is 60% smaller. After zstd compression:

- JSON: 800 bytes -> 180 bytes (77.5% reduction)
- Protobuf: 320 bytes -> 200 bytes (37.5% reduction)

1. Why does JSON compress better than Protobuf?
2. After compression, JSON is only 10% larger than Protobuf. Does this mean JSON is "good enough"?
3. What metric matters more than compressed size for inter-service communication?

<details><summary>Solution</summary>

1. **JSON compresses better because it has more redundancy.** JSON repeats field names ("platform_transaction_id", "restaurant_id") in every message, uses text digits ("1700000000"), and has structural characters ({, }, ", :, ,). These repetitive patterns are exactly what compression algorithms exploit. Protobuf already eliminated this redundancy with field numbers and binary encoding, leaving less for compression to find.

2. **No, JSON is NOT "good enough".** Compressed size is only one factor:
   - **CPU cost**: Compression/decompression adds CPU overhead. JSON requires parse + compress (two steps). Protobuf can skip compression entirely for similar wire size.
   - **Latency**: JSON parse + zstd compress takes more wall time than Protobuf encode alone.
   - **Memory**: JSON parsing allocates more intermediate objects.

3. **Total latency matters most**: serialize + compress + transmit + decompress + deserialize. At 1M messages/second:
   - JSON + zstd: ~30 us serialize + ~5 us compress + ~2 us transmit + ~3 us decompress + ~15 us deserialize = **~55 us**
   - Protobuf (uncompressed): ~8 us serialize + ~3 us transmit + ~5 us deserialize = **~16 us**
   - Protobuf wins by 3.4x on total latency despite similar wire sizes after compression.

</details>

---

## Exercise 4 [Intermediate] -- Schema Migration Planning

FoodDash needs to make these changes to the Order schema. For each change, classify it as backward-compatible, forward-compatible, both, or breaking. Explain how to execute it safely.

1. Add optional field `delivery_fee_cents: int` with default 0
2. Remove the `promo_code` field
3. Rename `tip_cents` to `gratuity_cents`
4. Change `estimated_delivery_minutes` from `int` to `float`
5. Add a new enum value `RETURNED` to `OrderStatus`
6. Make the optional `driver_id` field required

<details><summary>Solution</summary>

| Change | Protobuf | Avro | Classification |
|--------|----------|------|----------------|
| **1. Add optional field** | Safe. Old readers skip unknown field number. | Safe if default provided. Schema resolution fills default. | Both (backward + forward) |
| **2. Remove field** | Safe if field number is `reserved`. Old data's field is skipped. | Safe. Schema resolution skips writer's field if reader doesn't want it. | Both (with `reserved`) |
| **3. Rename field** | Safe in Protobuf (field number unchanged). | **BREAKING in Avro** (matches by name, not position). | Protobuf: safe. Avro: breaking. |
| **4. int to float** | **BREAKING.** Wire type changes from VARINT(0) to 32-BIT(5). Old decoders read wrong bytes. | **Possible if promoted**: `int` -> `float` is a valid Avro promotion. | Protobuf: breaking. Avro: forward-compatible. |
| **5. New enum value** | Safe in proto3 (unknown enum values preserved as int). | Safe if reader schema includes the new symbol. Old readers with old schema get an error. | Forward-compatible only |
| **6. Make field required** | Proto3 has no required fields. In proto2: **BREAKING.** | Avro: remove the `["null", "string"]` union, keep only `"string"`. **BREAKING** if existing data has nulls. | Breaking |

**Safe migration pattern for breaking changes:**
1. Add the new field alongside the old one
2. Deploy writers to populate both old and new fields
3. Deploy readers to prefer the new field, fall back to old
4. After all consumers are updated, stop writing the old field
5. Mark the old field as `reserved` / deprecated

</details>

---

## Exercise 5 [Intermediate] -- Compression Dictionary Training

Zstd supports **dictionary compression**: train a dictionary on sample data, then use it to compress individual messages.

1. Why is dictionary compression especially effective for small messages (<1 KB)?
2. How would you train a dictionary for FoodDash Order messages?
3. What happens if the data distribution changes after training?
4. How do you distribute the dictionary to all services?

<details><summary>Solution</summary>

1. **Small message problem**: Standard compression builds its context (dictionary/window) from the data being compressed. For a 500-byte message, the compressor has very little context to find patterns. A pre-trained dictionary gives the compressor a "head start" -- it already knows common patterns (field names, enum values, common strings). For small messages, this can improve compression ratio by 2-5x.

2. **Training process**:
   ```python
   import zstandard as zstd

   # Collect ~1000 sample Order messages (representative mix)
   samples = [encode_order(order) for order in sample_orders]

   # Train dictionary (typically 32KB-112KB)
   dictionary = zstd.train_dictionary(112_000, samples)

   # Use for compression
   cctx = zstd.ZstdCompressor(dict_data=dictionary)
   compressed = cctx.compress(message)

   # Use for decompression
   dctx = zstd.ZstdDecompressor(dict_data=dictionary)
   original = dctx.decompress(compressed)
   ```
   The training algorithm finds common byte sequences across all samples and builds an optimal dictionary.

3. **Distribution drift**: If the data distribution changes significantly (new fields, different value distributions), the dictionary becomes less effective but doesn't break. Compression still works, just with worse ratios. Re-train periodically (e.g., weekly) and version your dictionaries.

4. **Dictionary distribution**:
   - Store dictionaries in a central config service (like a schema registry)
   - Each dictionary gets a unique ID
   - Messages include the dictionary ID in a header
   - Services cache dictionaries locally
   - Deploy new dictionary alongside old one; switch once all services have it

</details>

---

## Exercise 6 [Intermediate] -- The "Which Format?" Decision Tree

A new FoodDash team asks you: "Which serialization format should we use?" Walk through the decision for each scenario:

1. **Public REST API** consumed by mobile apps and third-party developers
2. **Internal event stream** on Kafka with 500K events/second
3. **Game state sync** for a real-time multiplayer feature (60 updates/second)
4. **Batch data export** for the data science team
5. **Config file** for service configuration
6. **Log aggregation** pipeline processing 10 GB/hour

<details><summary>Solution</summary>

1. **Public REST API -> JSON**
   - Universal client support (every language has JSON)
   - Human-readable for debugging with curl/Postman
   - Schema description via OpenAPI/JSON Schema
   - Optional: add gzip/brotli HTTP compression

2. **Internal Kafka events -> Avro + Schema Registry**
   - Schema evolution with compatibility guarantees
   - Confluent Schema Registry integration is mature
   - Smaller than JSON (no repeated field names)
   - Reader/writer schema resolution handles version differences

3. **Game state sync -> FlatBuffers or Cap'n Proto**
   - Zero-copy: read only the fields that changed
   - Sub-microsecond access latency
   - FlatBuffers for broader language support
   - Cap'n Proto if you need the RPC framework

4. **Batch data export -> Parquet or Avro container files**
   - Columnar (Parquet) for analytical queries
   - Self-describing: schema embedded in file
   - Splittable for parallel processing
   - Built-in compression per column/block

5. **Config file -> JSON, YAML, or TOML**
   - Must be human-readable and editable
   - Version-controlled in git
   - TOML for simple configs, YAML for complex hierarchies
   - Never use a binary format for config

6. **Log aggregation -> MsgPack or Protobuf + lz4**
   - High throughput demands compact encoding
   - lz4 compression for speed (decompression at >4 GB/s)
   - MsgPack if schema-free flexibility is needed
   - Protobuf if you want type safety and schema evolution

</details>

---

## Exercise 7 [Advanced] -- Cost Analysis: Serialization Tax

FoodDash processes 1 million orders/second. Each Order is ~800 bytes as JSON.

Calculate the annual infrastructure cost difference between JSON and Protobuf:

Assumptions:
- Protobuf is 60% smaller (320 bytes)
- Cloud networking: $0.01/GB egress
- CPU: $0.05/vCPU-hour
- JSON parse: 15 us/message, Protobuf: 5 us/message
- Each message crosses 3 network hops

<details><summary>Solution</summary>

**Network costs:**
- JSON: 800 bytes x 1M/s x 3 hops = 2.4 GB/s = 207 TB/day = **$2,074/day**
- Protobuf: 320 bytes x 1M/s x 3 hops = 0.96 GB/s = 83 TB/day = **$830/day**
- **Network savings: $1,244/day = $454,060/year**

**CPU costs (serialization + deserialization):**
- JSON: 15 us x 1M/s = 15 seconds of CPU per second = **15 vCPUs** dedicated to parsing
  - Each hop: encode + decode = 2 x 15 = 30 vCPUs, times 3 hops = 90 vCPUs
  - 90 vCPUs x $0.05/hr x 8,760 hrs = **$39,420/year**
- Protobuf: 5 us x 1M/s = 5 seconds of CPU per second = **5 vCPUs**
  - 3 hops x 2 x 5 = 30 vCPUs
  - 30 vCPUs x $0.05/hr x 8,760 hrs = **$13,140/year**
- **CPU savings: $26,280/year**

**Total annual savings: $454,060 + $26,280 = $480,340/year**

At this scale, the serialization format choice is worth nearly half a million dollars per year. And this ignores the latency improvement, which may enable better user experience and higher conversion rates.

</details>

---

## Exercise 8 [Advanced] -- Schema Evolution Strategy Document

Design a complete schema evolution strategy for FoodDash. Your document should cover:

1. Compatibility rules (what changes are allowed?)
2. Field numbering/naming conventions
3. Deprecation process (how to remove a field safely)
4. Testing requirements (how to verify compatibility before deploy)
5. Rollback plan (what if a breaking change slips through?)

<details><summary>Solution</summary>

**1. Compatibility Rules:**
- All changes must be **backward-compatible** (new reader, old writer) AND **forward-compatible** (old reader, new writer)
- Allowed changes: add optional fields with defaults, add new enum values, promote int->long
- Prohibited: remove fields without deprecation, reuse field numbers, change field types incompatibly, rename Avro fields

**2. Field Numbering Conventions:**
- Reserve field numbers 1-15 for the most frequently accessed fields (single-byte tag in protobuf)
- Leave gaps (e.g., 1, 2, 3, 5, 8, 10) to allow inserting related fields later
- Document every field number, even unused ones: `reserved 4, 6, 7;`
- Use consistent field number ranges: 1-20 for core fields, 21-50 for extended, 51+ for experimental

**3. Deprecation Process (6-week cycle):**
- Week 1: Add `[deprecated = true]` to field. Add replacement field.
- Week 2: Deploy writers to populate both old and new fields.
- Week 3: Deploy readers to use new field, fallback to old.
- Week 4: Monitor: ensure no consumer reads the deprecated field.
- Week 5: Stop populating deprecated field.
- Week 6: Add to `reserved` list. Never reuse the field number.

**4. Testing Requirements:**
- CI pipeline runs schema compatibility check against the last N versions
- Integration tests encode with old schema, decode with new (and vice versa)
- Canary deployment: new schema deployed to 1% of traffic first
- Schema registry rejects incompatible schemas at registration time

**5. Rollback Plan:**
- Every schema change is a separate, revertible commit
- Services must handle receiving messages with both old and new schema for 24 hours
- Schema registry supports rollback (re-register old version as latest)
- If data was written with new schema and must be read by rolled-back service: the forward-compatibility guarantee ensures this works

</details>

---

## Exercise 9 [Advanced] -- Compression Benchmark Design

Design a fair benchmark to compare zstd, lz4, and gzip for FoodDash messages. Describe:

1. What data to use (and why synthetic data is dangerous)
2. What metrics to measure
3. How to handle warm-up and measurement noise
4. What visualization to produce

<details><summary>Solution</summary>

**1. Data Selection:**
- Use **real production message samples** (anonymized), not synthetic data. Synthetic data has unrealistic entropy patterns that bias compression ratios.
- Include a representative mix: small orders (1 item), typical orders (3 items), large orders (20 items), orders with binary thumbnails, orders with CJK text.
- Minimum 10,000 messages for statistical significance.
- Test both individual message compression and batch compression (1000 messages concatenated).

**2. Metrics:**
- **Compression ratio**: compressed_size / original_size
- **Compression throughput**: MB/s of input data
- **Decompression throughput**: MB/s of output data
- **Total latency**: compress + transmit + decompress (for a target network speed)
- **Memory usage**: peak RSS during compression/decompression
- Measure at multiple compression levels (zstd 1-22, gzip 1-9)

**3. Warm-up and Noise:**
- 100 warm-up iterations (fills CPU caches, JIT if applicable)
- 10,000 timed iterations minimum
- Report median and p99, not mean (avoids GC/scheduling outlier skew)
- Disable GC during timed section
- Pin to a single CPU core to avoid migration noise
- Run 3 separate trials; report if variance > 5%

**4. Visualization:**
- Pareto chart: X = compression throughput (MB/s), Y = compression ratio. Each point = (algorithm, level). The Pareto frontier shows the optimal trade-offs.
- Latency CDF: for each algorithm, plot the cumulative distribution of per-message latencies.
- Bar chart: total cost (CPU + bandwidth) per year at different message rates.

</details>

---

## Exercise 10 [Advanced] -- Format Migration: JSON to Protobuf

FoodDash's Order service currently uses JSON. You need to migrate to Protobuf without downtime. Design the migration plan.

Constraints:
- 20 consuming services
- Cannot require all services to deploy simultaneously
- Must be rollback-safe at every step
- Zero message loss

<details><summary>Solution</summary>

**Phase 1: Dual-Write (Week 1-2)**
- Modify the Order service to write **both JSON and Protobuf** to separate Kafka topics
- JSON topic: `orders.json` (existing)
- Protobuf topic: `orders.proto` (new)
- Verify Protobuf messages are correct by comparing with JSON (shadow validation)

**Phase 2: Consumer Migration (Week 3-6)**
- Each consuming service migrates independently:
  1. Add Protobuf deserialization code alongside existing JSON code
  2. Read from both topics, compare results (shadow mode)
  3. Switch primary source to Protobuf topic
  4. After 1 week of stability, remove JSON consumer
- Teams self-service: provide a migration guide + library helpers
- Track migration progress on a dashboard

**Phase 3: Stop Dual-Write (Week 7-8)**
- After all 20 consumers have migrated to Protobuf:
  1. Stop writing to `orders.json` topic
  2. Keep the topic alive for 2 weeks (retention) as safety net
  3. Remove JSON serialization code from the Order service

**Rollback plan at each phase:**
- Phase 1: Stop writing to Protobuf topic. Zero impact on consumers.
- Phase 2: Any consumer can switch back to JSON topic instantly. No coordination needed.
- Phase 3: Re-enable JSON dual-write. Consumers that haven't deleted JSON code can switch back.

**Zero message loss guarantee:**
- Kafka consumer groups track offsets independently per topic
- Dual-write ensures both topics have the same data
- Consumer offset management is independent of the format change

**Timeline**: 8 weeks total. Could be 4 weeks if teams prioritize migration.

</details>
