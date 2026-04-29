# Chapter 10: Choosing a Format

## The Scene

The FoodDash platform is adding a new service: delivery tracking. This service sits at a critical intersection of the architecture. It receives driver location pings from the mobile driver app -- small payloads, high frequency, sometimes hundreds per second per active driver. It sends ETA updates to the customer-facing web app running in the browser. It publishes delivery events to the Kafka pipeline that feeds the analytics data lake. And it communicates with the driver-matching engine, a latency-sensitive system that needs to process location data as fast as physically possible.

The tech lead calls a meeting. "Which serialization format should we use?"

The room splits immediately. The backend team wants Protobuf -- they already use it for gRPC between services, and they like the strong contracts. The frontend team insists on JSON -- the customer app is a React single-page application, and JSON is native to the browser. The data engineering team advocates for Avro -- the Kafka pipeline already uses it, and schema evolution is critical for long-lived event data. The performance engineer points out that the driver-matching engine needs to decode location pings in microseconds, and argues for FlatBuffers.

Everyone is right. And that is the point. The question "which format should we use?" has no single answer. The correct question is: "which format should we use at each boundary?"

The delivery tracking service will use JSON at the browser boundary (serving the customer app), Protobuf for gRPC calls to other microservices, Avro for events published to Kafka, and FlatBuffers for the real-time location feed to the driver-matching engine. Four formats in one service. This sounds like madness until you realize that each boundary has fundamentally different constraints, and optimizing for one set of constraints at every boundary means being suboptimal everywhere.

This chapter builds the framework for making that decision systematically. Not by opinion, not by hype, not by "Google uses it" -- by understanding what each boundary actually requires and scoring formats against those requirements.

## The Decision Framework

### There Is No "Best" Format

This needs to be stated plainly because it is the most common misconception in serialization discussions. There is no universally best serialization format. Anyone who tells you otherwise is either selling something or has only ever worked on one type of system.

Protobuf is not "better" than JSON. JSON is not "worse" than Avro. CSV is not "obsolete." Each format occupies a different point in a multi-dimensional trade-off space. The right format depends entirely on your constraints.

What makes this confusing is that format comparisons are usually presented as a single dimension -- "binary is faster than text" or "schema-based is safer than schemaless." These statements are true but incomplete. A format that is faster to decode might be slower to encode. A format that is compact on the wire might be impossible to debug. A format with strong schema evolution might have a smaller ecosystem. Every advantage has a cost.

### The Eight Criteria

The decision framework scores formats on eight criteria. These are not arbitrary -- they are the dimensions that matter in practice when choosing a serialization format for a production system.

**1. Human Readability.** Can you open the encoded data in a text editor and understand it? Can you copy it into a bug report? Can you pipe it through `jq` or `grep`? Human readability sounds like a luxury until you are debugging a production incident at 2 AM and need to figure out why a particular message is malformed. JSON and CSV are readable. Everything else requires specialized tooling.

The cost of readability is verbosity. Field names like `"estimated_delivery_minutes"` take 30 bytes in JSON. In Protobuf, the same field is a 1-2 byte tag. At 1 million messages per second, those extra bytes add up to 30 megabytes per second of pure overhead -- just for field names.

**2. Wire Size.** How many bytes does the encoded message consume on the wire? This matters for network bandwidth, storage costs, and latency (smaller messages transmit faster). Wire size varies dramatically across formats. A typical FoodDash order might be 800 bytes in JSON, 400 bytes in Protobuf, and 350 bytes in Avro.

But wire size is not just about the raw byte count. It interacts with compression. JSON compresses well (repetitive field names and whitespace compress beautifully), so the gap narrows when you add gzip or zstd. A 800-byte JSON message might compress to 250 bytes, while a 400-byte Protobuf message might compress to 300 bytes. The text format wins on the compressed wire. This is not always the case, but it illustrates why benchmarking your actual data matters more than consulting generic comparison tables.

**3. Encode Speed.** How fast can you convert an in-memory object to the wire format? This matters on the producer side -- every microsecond of encode time at 1M msg/s adds up to one second of cumulative compute per second. Encode speed is dominated by two factors: whether the format uses reflection (inspecting objects at runtime) or generated code (pre-compiled field access), and how much work the format does per field (type conversion, varint encoding, alignment padding, etc.).

Cap'n Proto wins this category by a wide margin because its encode is essentially a no-op: the in-memory layout is the wire format. Protobuf and Avro are fast because they use generated code. JSON is slow because it must convert every value to a string representation and escape special characters.

**4. Decode Speed.** How fast can you convert wire bytes back to an in-memory object? This matters on the consumer side and is often the bottleneck in request-handling paths. The key distinction is between formats that require full deserialization (parsing every byte into a new object) and formats that support zero-copy access (reading fields directly from the wire buffer).

FlatBuffers and Cap'n Proto achieve zero-copy: they do not deserialize at all. The encoded buffer is the object. You access fields through generated accessor methods that perform pointer arithmetic on the buffer. This is an order of magnitude faster than traditional deserialization for large messages, and it means you only pay the cost of accessing the fields you actually read.

**5. Schema Enforcement.** Does the format guarantee that messages conform to a defined structure? Schema enforcement catches bugs at compile time (type mismatches, missing fields) rather than at runtime (crashes in production). It also serves as living documentation of the contract between services.

CSV, JSON, MessagePack, and CBOR have no schema enforcement. You can put anything on the wire, and the decoder will accept it. Protobuf, FlatBuffers, Avro, and Cap'n Proto require schemas and generate code that enforces them. The trade-off is flexibility versus safety: schemaless formats let you iterate fast; schema-based formats prevent you from breaking things.

**6. Schema Evolution.** How well does the format handle changes to the schema over time? In a microservice architecture with 20 services deployed independently, the schema will change. Fields will be added, deprecated, and occasionally restructured. Schema evolution determines whether these changes are safe (old readers handle new data, new readers handle old data) or catastrophic (services crash, data corrupts).

Avro is the gold standard here. Its reader/writer schema resolution mechanism was designed specifically for long-lived data in pipelines where producers and consumers evolve independently. Protobuf is strong too -- field numbers decouple the wire format from field names, enabling safe addition and deprecation. JSON gets a middling score: self-describing keys help, but the lack of formal evolution rules means "compatible" is whatever the application code happens to tolerate.

**7. Ecosystem and Tooling.** How many libraries, tools, and community resources exist for the format? Can you find a production-quality library in your language? Are there debugging tools, schema registries, code generators, and IDE plugins?

JSON wins this category overwhelmingly. Every programming language, every database, every API tool, every browser, and every text editor understands JSON. Protobuf has a strong ecosystem anchored by gRPC. Avro has deep roots in the Hadoop/Kafka ecosystem. FlatBuffers and Cap'n Proto have smaller but dedicated communities. CBOR and MessagePack have decent library support but less tooling infrastructure.

**8. Browser Compatibility.** Does the format work natively in browser JavaScript? For browser-facing APIs, this is a hard constraint. The browser is the most constrained runtime in the stack: no file system, no native code, limited library support, and the JavaScript type system (no integers, no binary strings, no 64-bit numbers).

JSON is the only format with native browser support. `JSON.parse()` and `JSON.stringify()` are built into every browser engine, optimized at the C++ level, and universally understood. Everything else requires a JavaScript library, a WASM module, or generated code. Protobuf has decent browser support through protobuf.js and grpc-web. The rest range from "possible with effort" to "not really viable."

### How to Weight Criteria

The framework works by assigning weights (1-5) to each criterion based on your use case, then multiplying by each format's raw score. The weights encode your constraints.

A weight of 5 means "this is a hard requirement -- the format must excel here." A weight of 1 means "I don't care much about this." A weight of 0 means "completely irrelevant."

The discipline of assigning explicit weights forces you to articulate what actually matters. Most engineering arguments about serialization formats are actually arguments about unstated priorities. When one engineer says "Protobuf is better" and another says "JSON is better," they are optimizing for different criteria. Making the weights explicit turns a subjective argument into an objective comparison.

## Scenario Analysis

### Scenario 1: Public REST API

**Context:** The FoodDash customer app is a React SPA that fetches order data, restaurant menus, and delivery tracking updates. The API serves browsers on every platform, from the latest Chrome to aging Safari on an iPhone 8.

**Weights:**
- Browser compatibility: 5 (hard requirement -- must work natively in browsers)
- Human readability: 4 (engineers debug API responses in DevTools constantly)
- Ecosystem/tooling: 4 (must integrate with OpenAPI, Postman, curl, every HTTP tool)
- Schema evolution: 2 (API versioning through URL paths, not wire format evolution)
- Wire size: 1 (responses are typically small; gzip handles the rest)
- Encode/decode speed: 1 (API latency is dominated by database queries, not serialization)
- Schema enforcement: 2 (validated at the application layer, not the wire format)

**Result: JSON wins decisively.** Its perfect browser compatibility and ecosystem scores, combined with high weights on those criteria, give it an insurmountable lead. No other format comes close for this use case. This is not because JSON is "better" -- it is because the constraints of browser-facing APIs align perfectly with JSON's strengths.

### Scenario 2: Internal Microservice RPC

**Context:** The order service calls the kitchen service, the payment service, and the notification service. These are internal calls over a private network, never exposed to browsers. There are 20 services, and contracts must be enforced to prevent one team's change from breaking another team's service.

**Weights:**
- Wire size: 5 (at 1M msg/s, every byte matters for bandwidth and latency)
- Schema enforcement: 5 (contracts between teams are non-negotiable)
- Encode speed: 4 (producer throughput matters at scale)
- Decode speed: 4 (consumer throughput matters at scale)
- Schema evolution: 3 (services deploy independently, need safe evolution)
- Ecosystem/tooling: 3 (gRPC integration, code generation, debugging tools)
- Human readability: 1 (internal traffic; use logging/tracing for debugging)
- Browser compatibility: 1 (never touches a browser)

**Result: Protobuf wins.** Its combination of compact wire format, strong schema enforcement, good encode/decode performance, and the gRPC ecosystem make it the clear choice for internal RPC. Cap'n Proto scores well too, but the smaller ecosystem and less mature gRPC-equivalent hold it back in practice.

### Scenario 3: Data Pipeline / Kafka

**Context:** The delivery tracking service publishes events to Kafka: order placed, driver assigned, location updated, order delivered. These events flow into the data lake where they are queried for analytics, ML training, and financial reconciliation. Events from two years ago must remain readable as the schema evolves.

**Weights:**
- Schema evolution: 5 (the defining requirement -- data lives for years)
- Wire size: 5 (billions of events in storage; every byte is multiplied by volume)
- Schema enforcement: 4 (data quality in the lake depends on producer discipline)
- Encode speed: 3 (producers are high-throughput but not microsecond-sensitive)
- Decode speed: 3 (consumers batch-process; throughput matters more than latency)
- Ecosystem/tooling: 3 (Confluent Schema Registry, Kafka Connect, Spark integration)
- Human readability: 1 (data is accessed through query engines, not text editors)
- Browser compatibility: 1 (pipeline data never reaches a browser directly)

**Result: Avro wins.** Its reader/writer schema resolution was designed exactly for this use case. The Confluent Schema Registry provides centralized schema management with compatibility checking. No field tags on the wire means maximum compactness. Protobuf is a solid second choice, but Avro's superior schema evolution and Kafka ecosystem integration give it the edge.

### Scenario 4: Latency-Critical Hot Path

**Context:** The driver-matching engine receives location pings from all active drivers and computes optimal driver assignments. Every microsecond of decode latency delays the assignment. The system processes tens of thousands of location pings per second, and the matching algorithm needs to access only a few fields (driver ID, latitude, longitude) from each ping.

**Weights:**
- Decode speed: 5 (the defining requirement -- zero-copy access is the goal)
- Wire size: 4 (smaller messages mean faster transmission and less cache pressure)
- Encode speed: 4 (drivers send pings at high frequency)
- Schema enforcement: 3 (type safety prevents bugs in the critical path)
- Schema evolution: 2 (the ping schema is small and changes rarely)
- Ecosystem/tooling: 2 (this is a specialized internal component)
- Human readability: 1 (performance trumps debuggability here)
- Browser compatibility: 1 (server-side only)

**Result: FlatBuffers and Cap'n Proto tie for the top.** Both offer zero-copy decoding, which means the matching engine can read driver ID and coordinates directly from the buffer without allocating any objects or copying any data. FlatBuffers has slightly broader adoption, while Cap'n Proto has a slight edge in encode speed. Either is an excellent choice. The key insight is that zero-copy matters here because the consumer reads only a few fields from each message -- if it needed every field, the advantage would be smaller.

### Scenario 5: Quick Data Export

**Context:** The ops team needs to export today's orders for a partner restaurant chain. The partner's team will open the file in Excel. No code, no special tools, just a file that makes sense when you look at it.

**Weights:**
- Human readability: 5 (the file must be self-explanatory to non-engineers)
- Ecosystem/tooling: 5 (must open in Excel, Google Sheets, pandas, any text editor)
- Browser compatibility: 2 (might need to download from a web interface)
- Everything else: 1

**Result: CSV and JSON share the top spot.** For flat tabular data (like a list of orders with columns for ID, customer, total, status), CSV is the best choice -- it opens natively in Excel. For nested or hierarchical data, JSON is better because CSV cannot represent nested structures without flattening. The choice between them depends on the data shape.

## The Real-World Answer: Use Multiple Formats

FoodDash does not pick one format. It uses four:

**JSON** at the browser boundary. The customer app and restaurant dashboard are React SPAs. They consume JSON APIs. This is non-negotiable: JSON.parse() is built into every browser, the DevTools network tab renders JSON beautifully, and the entire frontend toolchain (fetch, axios, React Query) expects JSON.

**Protobuf** for gRPC between services. The order service, kitchen service, payment service, notification service, and 16 other microservices communicate via gRPC with Protobuf messages. The .proto files serve as the contract between teams. Code generation ensures type safety. The compact wire format keeps bandwidth manageable at 1M msg/s.

**Avro** for Kafka events. Every significant state change (order placed, payment processed, delivery completed) is published as an Avro event to Kafka. The Confluent Schema Registry enforces compatibility rules. Two-year-old events in the data lake remain readable because Avro's reader/writer schema resolution handles evolution gracefully.

**FlatBuffers** for the driver-matching hot path. Location pings from drivers are encoded as FlatBuffers. The matching engine reads driver ID and coordinates with zero-copy access -- no deserialization, no object allocation, just pointer arithmetic on the buffer. At 50,000 pings per second, the microseconds saved per ping add up to meaningful compute savings.

**The API gateway** sits at the center, translating between formats. When a browser client requests order status, the gateway calls the order service via gRPC (Protobuf), deserializes the response, and re-serializes it as JSON for the browser. This translation has a cost, but it is paid once per request at the boundary, not on every internal hop.

This is not unusual. Most production systems at scale use multiple serialization formats. Each boundary has different constraints, and trying to use one format everywhere means being suboptimal at every boundary.

## Common Mistakes

### "We'll just use JSON everywhere"

This works at small scale. JSON is universal, debuggable, and every team knows it. The problems emerge as you grow:

At 1M messages per second, JSON's verbosity becomes a bandwidth problem. Field names like `"estimated_delivery_minutes"` consume 30 bytes per message. Multiply by 1M msg/s, and you are spending 30 MB/s on field names alone. String encoding and parsing become a CPU bottleneck. The lack of schema enforcement means teams break each other's services with uncoordinated changes.

The "just use JSON" approach is not wrong -- it is incomplete. JSON is the right choice at some boundaries (browser-facing APIs). It is the wrong choice at others (high-throughput internal RPC, long-lived data pipelines).

### "We should use Protobuf because Google uses it"

Google also has custom hardware, a global private network, and thousands of engineers maintaining serialization infrastructure. "Google uses it" is not a technical argument. Protobuf is excellent for internal RPC with schema contracts, but it is a poor choice for browser-facing APIs (no native support), quick data exports (not human-readable), and data pipelines where schema evolution is the primary concern (Avro is better).

The question is not "what does Google use?" but "what are my constraints?" If your constraints happen to match Google's (many internal services, strong contracts, compact payloads), then Protobuf is likely a good choice. If your constraints are different, the right answer is different.

### "Binary formats are always better"

Binary formats are more compact and faster to encode/decode. That much is true. But "better" depends on what you are optimizing for. Binary formats are worse for debugging (you cannot read the wire data without tools), worse for browser compatibility (no native support), and worse for ad-hoc tooling (no `grep`, `jq`, or text editors).

In many systems, serialization is not the bottleneck. If your service spends 50ms on a database query and 0.5ms on JSON serialization, switching to Protobuf saves 0.3ms -- a 0.6% improvement in total latency. The debugging cost of losing human readability may outweigh the performance gain.

Binary formats are better when serialization IS the bottleneck: high-throughput pipelines, latency-critical hot paths, bandwidth-constrained networks. They are not universally better.

### "We need the fastest format"

Do you? If your service handles 100 requests per second and each request takes 200ms (database, external APIs, business logic), the difference between 10 microseconds (Protobuf) and 50 microseconds (JSON) for serialization is 40 microseconds -- 0.02% of total latency. Optimizing serialization in this context is premature optimization.

The "fastest format" argument makes sense when serialization is a significant fraction of your total processing time. For the FoodDash driver-matching engine processing 50,000 pings per second with a 500-microsecond budget per ping, the difference between zero-copy (1 microsecond) and full deserialization (20 microseconds) is meaningful -- it is 4% of the budget. For a REST API serving restaurant menus at 100 req/s, it is noise.

Measure first. Optimize the actual bottleneck.

## The Decision Flowchart

When you need to choose a serialization format, walk through these questions in order. Each question eliminates options and narrows the field.

**Is the consumer a browser?**
Yes -> JSON. There is no practical alternative for browser-facing APIs. Stop here.
No -> Continue.

**Do you need a schema contract between teams?**
Yes -> Schema-based format (Protobuf, FlatBuffers, Avro, Cap'n Proto). Continue below.
No -> Consider JSON for flexibility, or MessagePack/CBOR if you need smaller payloads without schema overhead.

**Is this a data pipeline or long-lived storage?**
Yes -> Avro. Its reader/writer schema resolution is designed for exactly this case. The Confluent Schema Registry provides centralized evolution management.
No -> Continue.

**Is this RPC between services?**
Yes -> Protobuf. The gRPC ecosystem (load balancing, service mesh integration, streaming, deadlines, interceptors) is unmatched. Protobuf's schema evolution is strong enough for service-to-service communication.
No -> Continue.

**Is decode latency the primary constraint?**
Yes -> FlatBuffers or Cap'n Proto. Zero-copy decoding avoids deserialization entirely. Choose FlatBuffers for broader ecosystem support, Cap'n Proto for slightly better encode performance.
No -> Protobuf is a safe default for schema-based internal communication.

**Is this a quick export or one-off data exchange?**
Flat tabular data -> CSV.
Nested or hierarchical data -> JSON.
Neither -> You have a niche use case; evaluate based on your specific constraints.

## Trade-offs Table

| Format | Best For | Worst For | Hidden Cost |
|--------|----------|-----------|-------------|
| CSV | Tabular exports, spreadsheet interchange | Nested data, binary fields, streaming | No standard for escaping; dialect hell |
| JSON | Browser APIs, debugging, universal interchange | High-throughput internal RPC, large binary data | Field names in every message; no integer >2^53 |
| MessagePack | Drop-in binary JSON replacement | Anything needing schema safety | No schema means no evolution guarantees |
| CBOR | IoT, IETF-standardized binary exchange | Large-scale production services | Smaller ecosystem than alternatives |
| Protobuf | Service-to-service RPC, gRPC | Browser APIs, data lake storage | Code generation step in build pipeline |
| FlatBuffers | Latency-critical zero-copy access | Simple CRUD APIs, streaming data | Complex builder API; no streaming support |
| Avro | Data pipelines, Kafka, long-lived events | Browser APIs, low-latency RPC | Schema resolution overhead per message |
| Cap'n Proto | Ultra-fast encode/decode, zero-copy IPC | Broad ecosystem needs, browser support | Smallest community; fewer production references |

## Running the Code

```bash
uv run python -m chapters.ch10_choosing
```

This runs the decision framework against all five scenarios, printing the weighted scores and recommendations for each. The framework is also importable:

```python
from chapters.ch10_choosing.decision_framework import recommend

# Define your requirements
my_requirements = {
    "wire_size": 5,
    "schema_enforcement": 4,
    "decode_speed": 3,
    "browser_compatibility": 1,
}

# Get ranked recommendations
results = recommend(my_requirements)
for format_name, score, breakdown in results:
    print(f"{format_name}: {score}")
```

## The Visual

Open `visual.html` in a browser for an interactive exploration:

- **Radar chart**: Select 2-3 formats to compare across all 8 criteria. Hover for exact scores and rationale.
- **Decision tree**: Answer yes/no questions interactively to arrive at a recommendation, with explanations at each node.
- **Scenario picker**: Select a use case, see the weights applied, and watch the formats rank themselves.

## The Bridge

We have the framework. We know what to optimize for at each boundary. We can articulate why JSON is right for the browser, Protobuf for RPC, Avro for pipelines, and FlatBuffers for the hot path.

But the CTO is not satisfied with a scoring matrix. "Show me the numbers," she says. "You say Protobuf is more compact -- how much more compact? You say FlatBuffers is faster to decode -- how much faster? You say JSON compresses well -- does it compress better than Protobuf? What does each format cost at our scale -- at 1 million messages per second?"

Opinions are useful for direction. Numbers are necessary for decisions. The scoring framework tells us which formats to consider for each boundary. Benchmarks tell us what each choice actually costs.

That is the synthesis -- Chapter 11.
