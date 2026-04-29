# Chapter 08: Compression

## The Scene

FoodDash has come a long way. The team has evolved from CSV to JSON to MsgPack, built from-scratch Protobuf and Avro encoders, explored zero-copy with FlatBuffers and Cap'n Proto. Every chapter has squeezed more performance out of the wire format itself.

But bytes still cost money.

FoodDash processes 1 million messages per second across three data centers. The typical order message -- even in compact Protobuf -- is about 500 bytes. That means:

```
500 bytes x 1,000,000 msg/s = 500 MB/s
500 MB/s x 86,400 s/day = 43.2 TB/day
```

Cross-data-center transfer on AWS costs roughly $0.01 per GB. That's:

```
43,200 GB/day x $0.01/GB = $432/day = $157,680/year
```

Just in bandwidth. Not compute, not storage -- just moving bytes between data centers.

The infrastructure team asks: "We've optimized the format. Can we compress the messages?" The answer is yes, but compression has CPU cost. The question isn't *whether* to compress -- it's *which algorithm*, *at what level*, and *whether the CPU trade-off is worth the bandwidth savings*.

This chapter explores that trade-off.

## How Compression Works

Every compression algorithm boils down to two ideas: **find patterns** and **encode them efficiently**.

### LZ-Family: Pattern Matching

The LZ (Lempel-Ziv) family of algorithms finds repeated byte sequences and replaces later occurrences with back-references to earlier ones.

Consider this JSON fragment:

```json
{"restaurant_id":"rest0001","restaurant_id":"rest0001"}
```

An LZ compressor sees the second `"restaurant_id":"rest0001"` and replaces it with something like "go back 30 bytes, copy 30 bytes." The repeated sequence is stored once; every subsequent occurrence costs just a few bytes for the back-reference.

This is why **text formats compress so well** -- JSON messages are full of repeated field names, quoted strings, and structural characters (`{`, `}`, `:`, `,`) that LZ algorithms exploit ruthlessly.

### Entropy Coding: Shorter Codes for Common Bytes

After LZ matching, most compressors apply **entropy coding** -- assigning shorter bit sequences to more frequent symbols (like Morse code assigns `.` to 'E' because it's the most common letter).

- **Huffman coding**: builds a binary tree where frequent symbols get shorter codes. Classic, well-understood, used in gzip.
- **ANS (Asymmetric Numeral Systems)**: a more modern approach that achieves near-optimal compression with faster encoding. Used in zstd.
- **FSE (Finite State Entropy)**: Yann Collet's implementation of ANS, the entropy coder inside zstd.

### The Algorithms

**gzip** (deflate = LZ77 + Huffman)

The grandfather of compression. Published in 1992. Every HTTP server, every programming language, every operating system supports gzip. The algorithm combines LZ77 pattern matching with Huffman entropy coding. Compression ratio is good but speed is moderate -- the Huffman tree construction and optimal match-finding take time.

```
gzip = LZ77 (sliding window pattern matching) + Huffman (entropy coding)
```

**zstd** (LZ matching + FSE)

Facebook's modern compressor, released in 2016 by Yann Collet (who also created LZ4). Zstd achieves gzip-like ratios at 3-5x the speed, or significantly better ratios at gzip-like speeds (it has 22 compression levels). The key innovations:
- FSE (Finite State Entropy) instead of Huffman -- faster encoding/decoding
- Larger match-finding windows
- **Dictionary support** -- pre-load compression context from training data
- Designed for real-time compression of data streams

```
zstd = LZ matching (large windows) + FSE (fast entropy coding) + optional dictionary
```

**lz4** (fast LZ matching, minimal entropy coding)

Also by Yann Collet (2011). LZ4 sacrifices compression ratio for extreme speed. It uses a simplified LZ matching algorithm and skips most entropy coding entirely. The compressed output is larger than gzip or zstd, but compression and decompression are dramatically faster.

```
lz4 = simplified LZ matching + minimal overhead
```

LZ4 is the right choice when latency matters more than bandwidth: real-time systems, in-memory caches, database page compression.

**snappy** (Google's fast compressor)

Similar philosophy to LZ4 -- optimize for speed, not ratio. Google designed snappy for internal use where they compress enormous volumes of data and decompression speed is critical. Used in Bigtable, MapReduce, and many Google systems. The compression ratio is similar to LZ4.

```
snappy = fast LZ matching + lightweight framing
```

## Compression x Serialization Format Matrix

Here's where it gets interesting. We benchmarked four serialization formats against four compression options (including "none") on a typical FoodDash order:

```
Format+Compressor          Serialized  Compressed  Ratio    Enc+Comp   Dec+Decomp
                              (bytes)     (bytes)              (us)         (us)
----------------------------------------------------------------------------------
JSON+none                      1,916       1,916   1.00x      ~30          ~16
JSON+gzip                      1,916         775   2.47x      ~60          ~19
JSON+zstd                      1,916         795   2.41x      ~30          ~13
JSON+lz4                       1,916       1,125   1.70x      ~20          ~11
----------------------------------------------------------------------------------
MsgPack+none                   1,289       1,289   1.00x       ~9           ~5
MsgPack+gzip                   1,289         775   1.66x      ~30          ~10
MsgPack+zstd                   1,289         760   1.70x      ~15           ~7
MsgPack+lz4                    1,289         989   1.30x       ~9           ~5
----------------------------------------------------------------------------------
Protobuf+none                    715         715   1.00x      ~22          ~22
Protobuf+gzip                    715         540   1.32x      ~33          ~26
Protobuf+zstd                    715         546   1.31x      ~28          ~25
Protobuf+lz4                     715         644   1.11x      ~22          ~23
----------------------------------------------------------------------------------
Avro+none                        671         671   1.00x      ~27          ~22
Avro+gzip                        671         497   1.35x      ~40          ~27
Avro+zstd                        671         500   1.34x      ~35          ~22
Avro+lz4                         671         601   1.12x      ~28          ~23
```

*(Times are approximate and vary by machine. Run the benchmarks yourself for precise numbers.)*

### Why JSON Compresses So Well

JSON at 1,916 bytes compresses to ~775 bytes with gzip or zstd -- a 2.4x reduction. That's because JSON is *full* of redundancy:

- Every field name is repeated in full: `"platform_transaction_id"`, `"special_instructions"`, `"restaurant_id"`
- Every string value is quoted: `"en_route"`, `"credit_card"`, `"mobile_app"`
- Structure characters repeat: `{`, `}`, `[`, `]`, `:`, `,`
- Numbers are ASCII text: `1700000300.0` is 14 bytes instead of 8

Compression algorithms are *specifically designed* to eliminate this kind of byte-level redundancy. JSON is almost the ideal input for LZ-family compressors.

### Why Binary Formats Compress Less

Protobuf at 715 bytes compresses to ~540 bytes with gzip -- only 1.3x. Binary formats have already removed most of the redundancy that compressors exploit:

- Field names are replaced by 1-2 byte tags
- Integers use variable-length encoding (small values = fewer bytes)
- No quoting, no structural punctuation
- Enum values are integers, not strings

There's less redundancy left for the compressor to find. You still get *some* compression (repeated tag patterns, zero-padding in fixed-width fields), but the gains are modest.

### The Surprising Result

JSON + zstd (795 bytes) is competitive with Protobuf uncompressed (715 bytes). This is counterintuitive -- shouldn't the "wasteful" text format be much larger?

The insight: **compression normalizes format overhead**. JSON's redundancy is exactly the kind of pattern that compression eliminates efficiently. Once compressed, the information content of the two formats is similar -- because they're encoding the same data.

This doesn't mean JSON+compression equals Protobuf+compression (it doesn't -- Protobuf+zstd is still smaller). But it means that **if you're going to compress anyway**, the gap between text and binary formats narrows significantly.

### Batch Compression: Where It Really Shines

Single-message compression is modest. Batch compression is dramatic:

```
Payload                    gzip        zstd        lz4
------------------------------------------------------
100 JSON orders (191KB)    3,125 B     1,568 B     5,127 B
  ratio                    61x         122x        37x

100 Proto orders (71KB)    1,934 B     1,347 B     3,152 B
  ratio                    37x         53x         23x
```

100 JSON orders compress from 191 KB to 1.5 KB with zstd -- a **122x** compression ratio. Even Protobuf batches see 53x compression.

Why? Because batch compression gives the algorithm a much larger window of data to find patterns in. When you concatenate 100 orders, the compressor sees that `"platform_transaction_id"` appears 100 times, that `"restaurant_id":"rest0001"` repeats in every message, that the overall structure is identical across messages. It exploits all of this ruthlessly.

This is why **Kafka compresses message batches**, not individual messages. The batch is the unit of compression.

## Dictionary Compression: The Small Message Solution

There's a problem with compressing individual small messages. A typical FoodDash order is 500-2000 bytes. At that size, regular compression gives modest ratios (1.3-2.5x) because there aren't enough repeated patterns *within a single message* for the LZ algorithm to exploit.

But what if the compressor could start with *pre-loaded knowledge* about what FoodDash messages look like?

### How Dictionary Compression Works

1. **Training phase**: Feed 100-1000 representative messages to `zstd.train_dictionary()`. The training algorithm analyzes byte patterns across all messages and builds a "dictionary" -- a compact representation of common patterns.

2. **Compression**: Instead of starting from scratch, the compressor initializes its state from the dictionary. It already "knows" that `"platform_transaction_id"` is a common byte sequence, that JSON structural patterns repeat, that certain byte ranges correspond to enum values.

3. **Decompression**: The decompressor must have the same dictionary. It uses it to reconstruct the original data.

### The Results

```
Metric                          Regular zstd       Dict zstd    Improvement
---------------------------------------------------------------------------
Avg original size (bytes)              1,915           1,915
Avg compressed size (bytes)              793              49         16x
Compression ratio                      2.42x          39.00x
```

Dictionary compression on individual messages achieves **39x compression** -- compared to 2.4x without a dictionary. The dictionary provides the cross-message pattern knowledge that regular compression can only get from batching.

### Training Size: How Much Data Do You Need?

```
Training samples    Dict ratio    Plain ratio    Improvement
------------------------------------------------------------
          10          11.84x         2.42x          4.90x
          50          12.12x         2.42x          5.02x
         100          12.24x         2.42x          5.07x
         250          39.90x         2.42x         16.52x
         500          34.53x         2.42x         14.29x
        1000          39.00x         2.42x         16.15x
```

The dictionary quality improves rapidly with training samples and generally plateaus around 250-500 samples. Beyond that, returns diminish. The dictionary itself is typically 16-64 KB -- a one-time cost that pays for itself after compressing just a few hundred messages.

### Dictionary Distribution

The dictionary must be available to both the compressor and decompressor. In practice:

- **Kafka**: The producer and consumer can share a dictionary via the schema registry. Alternatively, Kafka's built-in batching achieves a similar effect by compressing message batches rather than individual messages.
- **gRPC**: A dictionary can be negotiated during connection setup and reused for the lifetime of the connection.
- **HTTP**: Dictionary compression is emerging. Chrome supports `Content-Encoding: dcz` (dictionary compressed zstd) experimentally, and shared dictionaries via `Use-As-Dictionary` headers are being standardized.

## Systems Constraints

Compression is not free. Every byte compressed and decompressed costs CPU cycles.

### CPU Cost at Scale

Approximate per-message overhead for a typical FoodDash order:

| Algorithm | Compress (us) | Decompress (us) | CPU cores at 1M msg/s |
|-----------|:-------------:|:----------------:|:---------------------:|
| gzip      |     ~15-60    |       ~4-20      |       ~20-80          |
| zstd      |      ~5-30    |       ~3-13      |        ~5-40          |
| lz4       |      ~2-10    |       ~1-5       |        ~2-15          |
| snappy    |      ~2-10    |       ~1-5       |        ~2-15          |

At 1 million messages per second:
- **gzip** might consume 20+ CPU cores just for compression
- **zstd** uses about 5-10 cores
- **lz4** uses about 2-5 cores

These are rough estimates -- actual numbers depend on message size, compression level, hardware, and implementation.

### The Break-Even Calculation

For FoodDash at 1M msg/s with ~500-byte Protobuf messages:

**Without compression:**
```
500 bytes x 1M msg/s = 500 MB/s = 43.2 TB/day
43,200 GB x $0.01/GB = $432/day in bandwidth
```

**With zstd compression (1.3x ratio on individual messages):**
```
385 bytes x 1M msg/s = 385 MB/s = 33.2 TB/day
33,200 GB x $0.01/GB = $332/day in bandwidth
Savings: $100/day
CPU cost: ~5 cores x ~$0.05/core-hour x 24h = $6/day
Net savings: $94/day
```

**With zstd + batching (50x ratio on batches of 100):**
```
10 bytes/msg x 1M msg/s = 10 MB/s = 0.86 TB/day
864 GB x $0.01/GB = $8.64/day in bandwidth
Savings: $423/day
CPU cost: ~5 cores x $0.05/core-hour x 24h = $6/day
Net savings: $417/day = $152,205/year
```

The lesson: **batching + compression pays for itself many times over** at FoodDash's scale.

## Production Depth

Compression isn't an academic exercise. It's built into every layer of the modern stack.

### HTTP: Content-Encoding

Every HTTP response can be compressed. The client sends `Accept-Encoding: gzip, br, zstd` and the server responds with `Content-Encoding: gzip` (or whichever it supports).

- **gzip**: Universally supported. Every browser, every server, every CDN. The safe default.
- **br (Brotli)**: Google's compressor, designed for the web. 15-20% better ratio than gzip at similar speeds. Supported by all modern browsers. Most CDNs use Brotli for static content (HTML, CSS, JS) because it can be pre-compressed at high levels.
- **zstd**: The newest addition. Supported in Chrome 123+, Firefox, and growing server support. Better ratio and speed than gzip. The future default.

### Kafka: Producer-Side Compression

Kafka supports four compression codecs at the producer level:

| Codec  | Ratio | CPU    | Notes |
|--------|:-----:|:------:|-------|
| gzip   | Best  | High   | Safe default, widely supported |
| snappy | Low   | Low    | Google's choice, fast decompression |
| lz4    | Low   | Lowest | Fastest overall, recommended for throughput |
| zstd   | Best  | Medium | Best ratio-to-speed, recommended for most |

The producer compresses each **message batch** (not individual messages). This is crucial -- batch compression gives 10-100x better ratios than per-message compression because the compressor sees cross-message patterns.

Consumers decompress automatically. The compression codec is stored in the batch metadata, so consumers don't need configuration.

### gRPC: Transport Compression

gRPC supports compression at the message level via `grpc-encoding` headers:

- **gzip**: Built-in, always available
- **identity**: No compression (the default)
- Custom codecs can be registered (zstd, snappy, etc.)

gRPC compression is particularly effective for streaming RPCs where many similar messages flow over a single connection.

### CDNs: Brotli for Static Content

CDNs like Cloudflare, Fastly, and AWS CloudFront use Brotli at high compression levels (9-11) for static assets. This is practical because:
- Static files are compressed once, served many times
- High compression levels take seconds but produce significantly smaller output
- A 100 KB JavaScript bundle might compress to 20 KB with gzip but 17 KB with Brotli
- At CDN scale, those 3 KB per request save terabytes of bandwidth per day

### Database Storage: RocksDB and Friends

LSM-tree databases like RocksDB (used by CockroachDB, TiDB, many others) compress SST files on disk:

- **LZ4** for the most recent (hot) data -- fast decompression for frequent reads
- **zstd** for older (cold) data -- better ratio when reads are less frequent
- This tiered approach balances read latency against storage cost

PostgreSQL supports TOAST compression (pglz, and LZ4 since PostgreSQL 14) for large column values. Cassandra compresses SSTables with LZ4 by default.

## Trade-offs Table

| Criterion        | gzip        | zstd        | lz4         | snappy      |
|------------------|:-----------:|:-----------:|:-----------:|:-----------:|
| Compression ratio| Good        | Best        | Moderate    | Moderate    |
| Compress speed   | Slow        | Fast        | Fastest     | Fast        |
| Decompress speed | Moderate    | Fast        | Fastest     | Fast        |
| Dictionary support| No         | Yes         | No          | No          |
| Streaming support| Yes         | Yes         | Yes         | Yes         |
| Ubiquity         | Everywhere  | Growing     | Growing     | Google stack|
| Best for         | Compatibility| General use | Latency-sensitive | Google ecosystem |
| Compression levels| 1-9        | 1-22        | 1-12 (accel)| Fixed       |
| Year introduced  | 1992        | 2016        | 2011        | 2011        |
| Author           | Gailly/Adler| Yann Collet | Yann Collet | Google      |

**When to use what:**

- **gzip**: When you need maximum compatibility. HTTP APIs consumed by unknown clients. Legacy systems. "When in doubt, gzip."
- **zstd**: When you control both ends. Internal microservice communication. Kafka topics. Database storage. The modern default.
- **lz4**: When latency matters more than size. Real-time systems. In-memory caches. Database page compression for hot data.
- **snappy**: When you're in the Google ecosystem or need a proven, battle-tested fast compressor. Bigtable, Hadoop, legacy systems.

## Running the Code

```bash
# Install dependencies
uv sync --extra compression --extra msgpack --extra avro

# Run all demos
uv run python -m chapters.ch08_compression

# Run individual modules
uv run python -m chapters.ch08_compression.compression_basics
uv run python -m chapters.ch08_compression.format_plus_compression
uv run python -m chapters.ch08_compression.dictionary_compression
```

### Files

| File | What It Does |
|------|-------------|
| `compression_basics.py` | Compares gzip/zstd/lz4 on single messages vs batches |
| `format_plus_compression.py` | Full [format x compressor] matrix benchmark |
| `dictionary_compression.py` | Zstd dictionary training and compression demo |
| `visual.html` | Interactive visualizations (open in browser) |

## The Bridge to Chapter 09

Compression works on top of any serialization format, squeezing out bytes by exploiting redundancy. We've now covered the full spectrum of wire format optimization: text formats (JSON, CSV), binary formats (MsgPack, Protobuf, Avro), zero-copy formats (FlatBuffers, Cap'n Proto), and compression (gzip, zstd, lz4).

But there's a deeper question we've been skirting around.

We've compressed the data, chosen the format, defined the schema. What happens when the schema *changes*? FoodDash has been running for two years. The Order schema has evolved seven times. Some services run schema version 3, some run version 7. The order-tracking service was deployed last week with the new `estimated_delivery_window` field. The payment service hasn't been updated in six months and doesn't know that field exists.

We touched on schema evolution in Chapter 04 (Protobuf field numbers and wire compatibility) and Chapter 06 (Avro's reader/writer schema resolution). But schema evolution deserves its own deep dive. What are the exact rules for safe changes? What's the difference between backward compatibility, forward compatibility, and full compatibility? What happens when you break the rules -- not in theory, but at 1 million messages per second?

That's Chapter 9: Schema Evolution.
