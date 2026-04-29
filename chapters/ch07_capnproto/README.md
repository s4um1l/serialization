# Chapter 07: Cap'n Proto -- The Wire Format IS the Memory Format

## The Scene

FoodDash's real-time pricing engine computes delivery prices for every incoming order. For each request, it factors in distance, demand surge, driver availability, restaurant prep time, and traffic conditions. During peak hours -- Friday dinner, Super Bowl Sunday, New Year's Eve -- the system handles millions of pricing computations per second.

Every one of these computations involves deserializing an order message, running the pricing algorithm, and serializing a response. With Protobuf, each encode takes ~2us and each decode takes ~2us. That's 4us of pure serialization overhead per message. At 1M messages/second, that's 4 seconds of CPU time every second spent on serialization alone -- more than the actual business logic.

FlatBuffers (Chapter 05) solved the decode side: zero-copy reading means decode cost drops to ~0. But encoding still takes ~2us. The builder has to allocate a buffer, write fields back-to-front, build vtables, and finalize the root offset. For a hot pricing path, even 2us of encode overhead per message adds up.

Kenton Varda was the engineer who designed and implemented Protocol Buffers v2 at Google. After years of watching Protobuf's encode/decode overhead consume CPU cycles across Google's data centers, he asked a radical question: **"What if encoding took 0us too? What if the wire format and the in-memory format were the same thing?"**

The answer was Cap'n Proto.

## How It Works: The Wire Format IS the Memory Format

Cap'n Proto's core insight is deceptively simple: if you design the in-memory data layout to be the same as the wire format, then "encoding" is just writing field values to memory, and "decoding" is just reading them. No transformation. No parsing. No intermediate representation.

### 8-Byte Words

Everything in Cap'n Proto is aligned to 8-byte "words." This is the fundamental unit of the format:

```
Word 0: [byte 0] [byte 1] [byte 2] [byte 3] [byte 4] [byte 5] [byte 6] [byte 7]
Word 1: [byte 8] [byte 9] [byte 10] ...
```

Why 8 bytes? Because the largest primitive type (Int64, Float64) is 8 bytes. Word alignment means any field can be read with a single aligned memory access -- no shifting, no masking, no crossing cache line boundaries.

The trade-off: more padding. A single Bool field still occupies space within a word. Cap'n Proto trades wire size for access speed.

### Struct Layout: Data + Pointers

Every struct in Cap'n Proto has two sections:

```
┌─────────────────────────────────────────────────────────────┐
│  DATA SECTION (fixed size, inline scalars)                   │
│  Word 0: [Int64 field] or [Float64 field] or [4x Int16]     │
│  Word 1: [Int32 field + Int16 field + Bool + padding]        │
│  ...                                                         │
├─────────────────────────────────────────────────────────────┤
│  POINTER SECTION (fixed size, references to variable data)   │
│  Ptr 0: [64-bit pointer to text/list/substruct]              │
│  Ptr 1: [64-bit pointer to text/list/substruct]              │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

**Data section**: Contains all scalar fields (integers, floats, bools, enums) packed directly into words. Reading an Int32 at slot 3 is just: `read_int32(struct_start + 3 * 4)`. One memory access. Done.

**Pointer section**: Contains 64-bit pointers to variable-length data (text strings, lists, sub-structs). Each pointer encodes the type, offset, and size of its target.

The sizes of both sections are fixed for a given struct type and encoded in the struct pointer, so readers always know exactly where each field lives.

### Pointer Encoding

Cap'n Proto pointers are 64-bit values with a precise bit layout:

**Struct pointer:**
```
Bits  0-1:  Type = 0 (struct)
Bits  2-31: Signed offset in words from pointer to target struct
Bits 32-47: Data section size in words (uint16)
Bits 48-63: Pointer section size in words (uint16)
```

**List pointer:**
```
Bits  0-1:  Type = 1 (list)
Bits  2-31: Signed offset in words from pointer to list data
Bits 32-34: Element size tag (void/bit/byte/2byte/4byte/8byte/pointer/composite)
Bits 35-63: Element count (29 bits = up to 500M elements)
```

**Far pointer** (for cross-segment references):
```
Bits  0-1:  Type = 2 (far)
Bits  2-31: Offset in words within the target segment
Bits 32-63: Segment ID
```

The pointer itself tells you everything you need to navigate the data. No vtable lookup (unlike FlatBuffers), no tag parsing (unlike Protobuf). One 64-bit read gives you the type, location, and size of any referenced data.

### Text and Data

Text in Cap'n Proto is stored as a list of bytes with a NUL terminator:

```
[List pointer: type=byte, count=len+1] -> [UTF-8 bytes...] [0x00] [padding to word boundary]
```

The NUL terminator means C/C++ code can use the pointer directly as a C string without copying. The word-aligned padding means the next field starts at a clean boundary.

### "Encoding" = Just Memory Writes

Here's what "encoding" an order looks like in Cap'n Proto:

```python
# 1. Allocate a struct (just bump a pointer)
offset = builder.alloc_struct(data_words=4, pointer_words=3)

# 2. Write scalar fields (just memory writes at computed offsets)
builder.write_int64(offset, slot=0, value=9007199254740993)  # txn ID
builder.write_float64(offset, slot=1, value=1700000000.0)     # timestamp
builder.write_int32(offset, slot=4, value=500)                 # tip cents

# 3. Write text (allocate + copy bytes + write pointer)
text_offset = builder.write_text("ord00042")
builder.write_text_pointer(offset, ptr_slot=0, text_offset)
```

There is no "serialize" call. No schema-driven field iteration. No varint encoding. Each field write is a single `struct.pack_into()` call at a pre-computed offset.

### "Decoding" = Just Pointer Arithmetic

```python
reader = CapnpReader(message_bytes)
root = reader.root()

# Reading a field: compute offset, read bytes. That's it.
tip = root.read_int32(slot=4)        # One struct.unpack_from() call
txn = root.read_int64(slot=0)        # One struct.unpack_from() call
name = root.read_text(ptr_slot=0)    # Follow one pointer, read bytes
```

No parsing pass. No object construction. No field-by-field deserialization. The buffer IS the data. You just compute where a field lives and read it.

## Cap'n Proto vs FlatBuffers

Both Cap'n Proto and FlatBuffers are zero-copy serialization formats, but they take different approaches:

| Aspect | FlatBuffers | Cap'n Proto |
|--------|-------------|-------------|
| **Build direction** | Back-to-front | Front-to-back |
| **Field lookup** | VTable indirection (2 reads) | Direct offset computation (1 read) |
| **Alignment** | 4-byte (configurable) | 8-byte (words) |
| **Wire size** | Smaller (less padding) | Larger (word alignment) |
| **Default values** | Omitted from wire (vtable says "absent") | Always present (zero = default) |
| **Schema evolution** | Add fields at end, vtable handles gaps | Add fields at end, data/ptr sections grow |
| **RPC framework** | None (separate gRPC layer needed) | Built-in with promise pipelining |
| **API feel** | Builder pattern (explicit start/end) | Struct-like (feels like writing to an object) |
| **Pointer encoding** | uint32 relative offsets | 64-bit typed pointers |

**FlatBuffers' advantage**: Smaller wire size. The vtable system allows omitting default values entirely. For bandwidth-sensitive scenarios, this matters.

**Cap'n Proto's advantage**: Simpler field access (no vtable indirection), built-in RPC, and the front-to-back build order is more natural. The 64-bit typed pointers carry more information, enabling richer traversal without schema knowledge.

In practice, both achieve the same goal: zero-copy access to serialized data. The choice between them often comes down to ecosystem (FlatBuffers has stronger mobile/game support; Cap'n Proto has the RPC framework) rather than performance.

## Promise Pipelining: The RPC Killer Feature

Cap'n Proto isn't just a serialization format -- it includes an RPC framework with a feature that no other mainstream RPC system offers: **promise pipelining**.

### The Problem

FoodDash's delivery tracking screen needs to:
1. Get the order (to find which driver is assigned)
2. Get the driver's location (using the driver_id from step 1)
3. Get the restaurant's location (to compute ETA)

Step 2 depends on step 1. Step 3 can run in parallel with step 2. In traditional RPC:

```
Client -> Server: getOrder("ord00042")                    [RTT 1]
Client <- Server: { driver_id: "driv0001", ... }
Client -> Server: getDriverLocation("driv0001")           [RTT 2]
Client <- Server: { lat: 40.752, lng: -73.978 }
Client -> Server: getRestaurantLocation("rest0001")       [RTT 3]
Client <- Server: { lat: 40.748, lng: -73.985 }
```

Total: 2-3 round trips (depending on parallelization). At 50ms cross-region RTT, that's 100-150ms of pure network latency before you can even start computing the ETA.

### The Solution: Promise Pipelining

With Cap'n Proto RPC, the client sends the entire dependency chain in a single message:

```python
# All of these are sent in ONE network message:
order_promise = server.getOrder("ord00042")
location_promise = server.getDriverLocation(order_promise.driverId)
restaurant_promise = server.getRestaurantLocation("rest0001")

# Wait for results -- ONE round trip
driver_loc = await location_promise
restaurant_loc = await restaurant_promise
```

The second call references `order_promise.driverId` -- a field on a result that hasn't arrived yet. Cap'n Proto sends this as a promise reference. The server receives all three requests, resolves the dependency chain locally (no network hop between steps 1 and 2), and returns all results.

**Total: 1 round trip. Always.**

### Why Other RPC Systems Can't Do This

- **REST**: Each HTTP request is independent. No way to reference a future response.
- **gRPC**: Streaming helps throughput, but unary calls with dependencies require sequential round trips. Server reflection/batching is application-level, not protocol-level.
- **GraphQL**: Can resolve dependency chains on the server, but you must know the full query shape upfront. Can't pipeline arbitrary method calls with capabilities.

Cap'n Proto's approach is general: any method call can reference any field of any promise, and the server resolves the full DAG. This is a protocol-level feature, not an application-level optimization.

### Impact at Scale

| Scenario | Traditional (3 deps) | Pipelined | Savings |
|----------|---------------------|-----------|---------|
| Same data center (1ms RTT) | 3ms | 1ms | 67% |
| Cross-AZ (5ms RTT) | 15ms | 5ms | 67% |
| Cross-region (50ms RTT) | 150ms | 50ms | 67% |
| Cross-continent (150ms RTT) | 450ms | 150ms | 67% |

The savings are always `(N-1)/N` where N is the chain depth. For a 4-deep chain, it's 75%. For real-time applications like delivery tracking, this is the difference between "snappy" and "sluggish."

## From Scratch: Building a Cap'n Proto Message

Our `capnp_from_scratch.py` implements the core concepts:

### Building a Message

```python
# 1. Create a builder (allocates a segment)
b = CapnpBuilder()

# 2. Allocate the struct (front-to-back, unlike FlatBuffers)
order_offset = b.alloc_struct(data_words=4, pointer_words=3)

# 3. Write scalars directly into the data section
b.write_int64(order_offset, slot=0, value=9007199254740993)
b.write_float64(order_offset, slot=1, value=1700000000.0)
b.write_int32(order_offset, slot=4, value=500)
b.write_uint16(order_offset, slot=10, value=5)  # status enum

# 4. Allocate and write text (after the struct)
id_offset = b.write_text("ord00042")
b.write_text_pointer(order_offset, data_words=4, ptr_slot=0,
                      text_word_offset=id_offset, text_byte_count=9)

# 5. Build the final message (add segment table + root pointer)
message = b.build_message(order_offset, data_words=4, pointer_words=3)
```

### Reading a Message

```python
# 1. Create a reader (parses segment table, finds root pointer)
reader = CapnpReader(message)
root = reader.root()

# 2. Read fields -- each is ONE struct.unpack_from() call
tip = root.read_int32(slot=4)        # -> 500
txn = root.read_int64(slot=0)        # -> 9007199254740993
ts = root.read_float64(slot=1)       # -> 1700000000.0
status = root.read_uint16(slot=10)   # -> 5

# 3. Read text -- follow pointer, read bytes
order_id = root.read_text(ptr_slot=0)  # -> "ord00042"
```

### Word Alignment in Action

Our simplified Order struct uses 4 data words + 3 pointer words = 56 bytes for the struct itself. Here's how the data section is laid out:

```
Word 0 (bytes 0-7):   platform_transaction_id (Int64)
Word 1 (bytes 8-15):  created_at (Float64)
Word 2 (bytes 16-23): tip_cents (Int32, bytes 16-19) + status (UInt16, bytes 20-21) + padding
Word 3 (bytes 24-31): reserved/padding
```

The padding in words 2 and 3 is the cost of word alignment. In Protobuf, these fields would be tightly packed with varints. In Cap'n Proto, we trade 10+ bytes of padding for the ability to read any field with a single aligned memory access.

## Systems Constraints

| Dimension | Cap'n Proto | Notes |
|-----------|-------------|-------|
| **Wire size** | Larger than Protobuf | Word alignment = padding; defaults not omitted |
| **Encode speed** | ~0 (memory writes) | Just write values at offsets |
| **Decode speed** | ~0 (pointer math) | Just read values at offsets |
| **Memory** | Zero-copy | Buffer IS the data |
| **Schema required** | Yes (.capnp files) | Needed for code generation and pointer layout |
| **Schema evolution** | Forward/backward compatible | Add fields at end; old readers ignore new fields |
| **Language support** | C++, Rust, Go, Python, Java, JS | Smaller ecosystem than Protobuf |
| **Human readable** | No | Binary format |
| **RPC built-in** | Yes (with promise pipelining) | Unique among serialization formats |

### The Size Trade-off

Cap'n Proto messages are typically 20-50% larger than Protobuf for the same data:

- **Protobuf**: Varints for integers (small values = fewer bytes), no padding, omit defaults
- **Cap'n Proto**: Fixed-width integers (Int32 always 4 bytes), word-aligned padding, defaults present

For FoodDash at 1M messages/second:
- Protobuf ~300 bytes/msg = 300 MB/s = 25.9 TB/day
- Cap'n Proto ~450 bytes/msg = 450 MB/s = 38.9 TB/day

At $0.01/GB for cross-DC transfer, that's $259/day vs $389/day. The extra $130/day buys you zero encode/decode overhead -- whether that's worth it depends on whether you're CPU-bound or bandwidth-bound.

## Production Depth

### Who Uses Cap'n Proto

**Cloudflare**: Uses Cap'n Proto for internal service communication. Their Workers runtime (running on thousands of edge servers) uses Cap'n Proto for efficient data passing between the V8 isolate and the Rust runtime. The zero-copy property is critical when processing millions of HTTP requests per second.

**Sandstorm.io**: Created by Kenton Varda himself. The entire platform uses Cap'n Proto for all IPC, leveraging the capability-based RPC for security sandboxing.

**Various game engines and real-time systems**: Where microseconds of serialization overhead per frame are unacceptable.

### Adoption Reality

Cap'n Proto has significantly less adoption than Protobuf or even FlatBuffers:

- **Ecosystem**: Fewer language bindings, fewer tools, smaller community
- **Documentation**: Good but sparse compared to Protobuf's extensive guides
- **Cloud integration**: No native support in AWS/GCP/Azure services (unlike Protobuf in gRPC)
- **Library maturity**: pycapnp requires the C++ library installed system-wide; not all features are exposed

### When to Use Cap'n Proto

**Good fit:**
- Latency-critical paths where encode+decode overhead matters
- Systems with promise-pipelineable RPC patterns (chained lookups)
- Internal services where you control both ends
- Systems already using C++ or Rust (best library support)

**Poor fit:**
- Public APIs (clients need the C++ library or a binding)
- Bandwidth-constrained links (larger wire size)
- Polyglot environments with many languages (limited bindings)
- Simple CRUD services where serialization isn't the bottleneck

## Trade-offs Table

| Format | Wire Size | Encode Speed | Decode Speed | Zero-Copy | Schema | Human Readable | RPC |
|--------|-----------|-------------|-------------|-----------|--------|----------------|-----|
| CSV | Large | Fast | Slow (parsing) | No | No | Yes | No |
| JSON | Large | Medium | Slow (parsing) | No | Optional | Yes | REST |
| MessagePack | Medium | Fast | Medium | No | No | No | No |
| CBOR | Medium | Fast | Medium | No | No | No | No |
| Protobuf | Small | Fast | Fast | No | Yes | No | gRPC |
| FlatBuffers | Small-Medium | Medium | ~Zero | Yes (read) | Yes | No | No |
| Avro | Small | Fast | Fast | No | Yes (embedded) | No | No |
| **Cap'n Proto** | **Medium-Large** | **~Zero** | **~Zero** | **Yes (read+write)** | **Yes** | **No** | **Yes (pipelined)** |

Cap'n Proto sits at one extreme of the spectrum: it trades wire size for the absolute minimum serialization overhead. Both encoding AND decoding are effectively free -- just memory operations at word-aligned offsets.

## Running the Code

```bash
# Run all demos
uv run python -m chapters.ch07_capnproto

# Run individual modules
uv run python -c "from chapters.ch07_capnproto.capnp_from_scratch import main; main()"
uv run python -c "from chapters.ch07_capnproto.capnp_demo import main; main()"
uv run python -c "from chapters.ch07_capnproto.rpc_demo import main; main()"

# Optional: install pycapnp for the library demo
# Requires Cap'n Proto C++ library: brew install capnp
# Then: uv pip install pycapnp
```

## The Bridge to Chapter 08

Cap'n Proto eliminates encoding and decoding entirely. The wire format IS the memory format. We have reached the theoretical minimum for serialization speed: 0us encode, 0us decode. There is nowhere left to optimize in the serialization layer itself.

But bandwidth still costs money. At 1M messages/second, even a compact 500-byte Cap'n Proto payload means:

```
500 bytes x 1,000,000 msg/s = 500 MB/s = 43.2 TB/day
```

At $0.01/GB for cross-data-center transfer, that is **$430/day** in bandwidth costs alone. Over a year, that is $157,000 just to move serialized bytes between data centers.

What if we could shrink the payloads further without changing the serialization format? Compression algorithms like **gzip**, **zstd**, **snappy**, and **lz4** can reduce payload sizes by 2-5x. A 500-byte message compressed to 150 bytes would cut bandwidth costs from $430/day to $129/day -- saving $110,000/year.

But compression has a CPU cost. Compressing and decompressing every message adds latency. We just spent seven chapters optimizing serialization to zero overhead -- are we willing to add compression overhead back?

**Is the bandwidth savings worth the CPU cost? That is Chapter 08.**
