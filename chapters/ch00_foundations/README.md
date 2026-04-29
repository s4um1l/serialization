# Chapter 00: Foundations — Why You Can't Just Send Memory

> **Format:** None yet  
> **The wall:** Objects in memory are not portable  
> **The bridge:** We need a language-neutral wire format... starting with CSV

---

## The Scene

It's your first week at FoodDash, a food delivery platform processing one million messages per second across twenty microservices. Your tech lead gives you a straightforward task: the **order-service** (Python) needs to send `Order` objects to the **kitchen-service** (also Python) over a TCP socket.

You look at the `Order` model — a Pydantic class with nested `Customer`, `OrderItem`, and `MenuItem` objects — and think: "Python has `pickle` for this."

```python
import pickle, socket

order = make_typical_order()
payload = pickle.dumps(order)

sock = socket.create_connection(("kitchen-service", 9000))
sock.sendall(len(payload).to_bytes(4, "big") + payload)
```

It works. The kitchen service calls `pickle.loads()`, gets back a perfect `Order` object, and starts preparing the food. You ship it to production. Life is good.

Three months later, the infrastructure team rewrites the kitchen service in Go for performance. The Go service receives bytes on the socket, calls... what, exactly? There is no `pickle.loads()` in Go. Pickle is a Python-specific format that encodes Python-specific type information — class names, module paths, object graphs with Python reference semantics. Go has no idea what to do with it.

Your "working" serialization just became a wall. And the deeper you dig, the more you realize: the problem isn't just pickle. The problem is that **in-memory representations of data are fundamentally non-portable**. Pointers, byte order, alignment, object layouts — everything about how data lives in RAM is specific to a particular language, on a particular architecture, in a particular process.

This chapter is about understanding *why* that's true, so that when we start building wire formats in Chapter 01, you'll understand what problem they solve.

---

## How It Works: Objects in Memory

### What a Python Object Really Is

Every value in CPython — every integer, every string, every `None` — is a C struct allocated on the heap. At minimum, it contains:

- **A type pointer** (8 bytes on 64-bit systems): points to the `PyTypeObject` that defines this value's behavior. When you call `type(x)`, Python follows this pointer.
- **A reference count** (8 bytes): CPython uses reference counting for memory management. Every assignment, function call, or container insertion increments this counter; every deletion or scope exit decrements it. When it hits zero, the object is freed.
- **The actual data**: for an integer, the digits; for a string, the characters; for a list, an array of pointers to other objects.

This means `sys.getsizeof(42)` returns **28 bytes** — not 4. Here's where those 28 bytes go:

| Offset | Size | Content |
|--------|------|---------|
| 0 | 8 | Type pointer (`PyTypeObject*` for `int`) |
| 8 | 8 | Reference count |
| 16 | 4 | Number of "digits" (internal representation) |
| 20 | 4 | Hash cache |
| 24 | 4 | The actual value (42) |

A C `int` is 4 bytes. A Python `int` wrapping the same value is 28 bytes — a **7x overhead** just for the metadata. For floats it's similar: `sys.getsizeof(3.14)` returns 24 bytes vs. C's 8-byte `double`.

### Pointers: The Object Graph

An `Order` doesn't contain its `Customer` inline. It contains a **pointer** — an 8-byte memory address that says "the Customer object lives over there." The `Customer` in turn contains a pointer to its `GeoPoint`, which contains two Python `float` objects (each with their own type pointer and reference count).

Run the `memory_layout.py` demo and you'll see something like:

```
Field                                Address (hex)       Size
order                                0x7f8b8c1a0100        72
order.customer                       0x7f8b8c1a0200        72
order.customer.name                  0x7f8b8c1a0300        55
order.items                          0x7f8b8c1a0400        80
order.items[0].menu_item.name        0x7f8b8c1a0500        61
```

These addresses are **process-local**. They're virtual memory addresses assigned by the operating system to *this* process. If you send address `0x7f8b8c1a0200` to another machine, that address points to... whatever happens to live there in the receiving process's address space. Probably nothing. Possibly the middle of a completely unrelated string. Definitely not a `Customer` object.

This is why you can't just `memcpy()` an object graph to another machine. The pointers would be **dangling** — pointing to memory that doesn't contain what they expect.

### The Memory Layout Diagram

Here's how a simplified Order lives in Python's heap vs. how it would need to look as a flat byte sequence on the wire:

```
PYTHON HEAP (scattered)                 WIRE FORMAT (contiguous)
========================                ========================

   Order @ 0x1000                       +------------------+
   +-- type_ptr -> int_type             | id: "ord00001"   |
   +-- refcount: 3                      | price: 1299      |
   +-- id ---------> str @ 0x5000       | status: "placed"  |
   +-- customer ---> Cust @ 0x2000      | customer_name:   |
   +-- items ------> list @ 0x3000      |   "Alice"        |
   +-- status -----> enum @ 0x6000      | latitude:        |
                                        |   40.748817      |
   Customer @ 0x2000                    | ...              |
   +-- type_ptr -> cust_type            +------------------+
   +-- refcount: 1
   +-- name -------> str @ 0x4000
   +-- location ---> GeoPoint @ 0x7000
```

On the left: a graph of heap objects linked by pointers. On the right: a flat, contiguous byte sequence with all the data inline. **Serialization is the process of converting from the left to the right.** Deserialization goes the other way.

---

## Endianness: The First Portability Trap

Even if you could flatten your object into a sequence of bytes (ignoring the pointer problem), you'd hit another wall: **byte order**.

### What Is Endianness?

A 32-bit integer like `1299` (hex `0x00000513`) occupies 4 bytes. But which byte comes first?

- **Big-endian** ("most significant byte first"): `00 00 05 13` — reads left-to-right, like how we write numbers
- **Little-endian** ("least significant byte first"): `13 05 00 00` — reversed

The term comes from *Gulliver's Travels*, where the Lilliputians fought a war over which end of a boiled egg to crack first. It's an apt metaphor: there's no inherently correct choice, but you must agree on one.

### Network Byte Order

RFC 1700 established that network protocols use **big-endian** byte order (called "network byte order"). TCP/IP headers, DNS records, and most wire protocols send the most significant byte first.

But nearly every modern CPU — x86, x86-64, ARM (in its default mode) — is **little-endian** internally. This means that every time a program sends or receives multi-byte integers over a network, it must convert between native byte order and network byte order.

In C, this conversion uses functions like `htonl()` (host-to-network-long) and `ntohl()` (network-to-host-long). In Python, the `struct` module uses format prefixes:

```python
import struct

price_cents = 1299

big_endian    = struct.pack('>I', price_cents)   # b'\x00\x00\x05\x13'
little_endian = struct.pack('<I', price_cents)   # b'\x13\x05\x00\x00'
network_order = struct.pack('!I', price_cents)   # b'\x00\x00\x05\x13' (same as big)
```

### The Endianness Bug

What happens when one service sends big-endian and another reads little-endian?

```python
# Service A sends price_cents=1299 as big-endian
sent = struct.pack('>I', 1299)          # b'\x00\x00\x05\x13'

# Service B reads the same bytes as little-endian
wrong = struct.unpack('<I', sent)[0]    # 319,094,784
```

The customer was charged **$3,190,947.84** instead of $12.99. This isn't hypothetical — endianness bugs have caused real production incidents in financial systems, network protocol implementations, and file format parsers.

### Floating-Point Endianness

Endianness applies to all multi-byte values, including IEEE 754 floating-point numbers. A `double` (64-bit float) representing latitude `40.748817` is:

```
Big-endian:    40 44 5f d9 3c 46 d8 2c
Little-endian: 2c d8 46 3c d9 5f 44 40
```

Read the big-endian bytes as little-endian, and you get `1.16e-92` — your delivery driver ends up in a very different part of the universe.

---

## Alignment: The Second Portability Trap

Even if you agree on endianness, there's another trap: **alignment and padding**.

### Why CPUs Care About Alignment

Modern CPUs access memory through a bus that's typically 4 or 8 bytes wide. When you read a 4-byte integer, it's most efficient if that integer starts at an address divisible by 4 (its "natural alignment"). If the integer straddles a bus boundary (e.g., starting at address 5), the CPU may need two bus transactions instead of one — or on some architectures, it will raise a hardware fault.

To avoid this, C compilers insert **padding bytes** between struct fields to ensure each field starts at its natural alignment. Consider:

```c
struct OrderSummary {
    char   status;       // 1 byte  at offset 0
    // 3 bytes of padding (so price_cents starts at offset 4)
    int    price_cents;  // 4 bytes at offset 4
    double latitude;     // 8 bytes at offset 8
};                       // Total: 16 bytes (not 13)
```

The `status` field is 1 byte, but `price_cents` needs 4-byte alignment, so the compiler inserts 3 bytes of padding. Those padding bytes are wasted space — they contain nothing useful.

### Padding Depends on Field Order

Rearranging fields can change the amount of padding:

```c
// BAD: 24 bytes (lots of padding)      GOOD: 16 bytes (minimal padding)
struct Bad {                             struct Good {
    char   a;   // 1 + 7 padding            double c;  // 8
    double c;   // 8                         int    b;  // 4
    int    b;   // 4 + 4 padding             char   a;  // 1 + 3 padding
};              // = 24 bytes            };              // = 16 bytes
```

Same three fields, same data, but **8 bytes of difference** purely due to ordering. At 1M messages/second, 8 bytes per message is 8 MB/s of wasted bandwidth.

### The Cross-Machine Problem

Different compilers may apply different padding rules:
- GCC on Linux might use one alignment strategy
- MSVC on Windows might use another
- Go's compiler has its own rules entirely
- `#pragma pack(1)` in C eliminates padding but changes the layout

If Machine A serializes a struct with its native padding and Machine B reads those bytes assuming its own padding rules, fields will be read from the wrong offsets. The data won't just be wrong — it will be **silently** wrong, because the bytes are still valid numbers, just not the numbers you intended.

Run the `alignment.py` demo to see this in action:

```
Machine A (x86, aligned):    50 00 00 00 13 05 00 00 2c d8 46 3c d9 5f 44 40
Machine B (big-endian):      50 00 00 00 00 00 05 13 40 44 5f d9 3c 46 d8 2c
Machine C (x86, packed):     50 13 05 00 00 2c d8 46 3c d9 5f 44 40
```

Three different byte sequences for the same three values.

---

## Why memcpy Doesn't Work

Let's stack up all the reasons why "just send the bytes" fails:

### 1. Pointers Are Process-Local

Python objects contain pointers to other objects. Those pointers are virtual memory addresses that only make sense within a single process on a single machine. Send them over a network and they become random numbers.

### 2. Endianness Differs Between Architectures

A 32-bit integer `1299` is `13 05 00 00` on little-endian x86 but `00 00 05 13` on big-endian systems. Without agreement on byte order, every multi-byte value is ambiguous.

### 3. Alignment and Padding Differ Between Compilers

The same logical struct has different physical layouts depending on the compiler, platform, and pragma settings. Fields end up at different offsets.

### 4. Object Layout Differs Between Languages

This is the deepest problem. A Python `int` is a 28-byte heap object. A C `int` is 4 bytes on the stack. A Go `int` is 8 bytes (on 64-bit). A JavaScript number is an IEEE 754 double (8 bytes). They're **completely different representations** of the same logical concept.

Even simple types don't agree. For compound types it's worse: a Python `dict` is a hash table with open addressing; a Go `map` is a hash table with a completely different layout; a C `struct` is a flat sequence of fields with padding. There's no way to send one and have the other "just work."

### The Fundamental Insight

**Serialization is the translation layer between in-memory representation and on-the-wire representation.**

It's the process of:
1. Walking an in-memory object graph
2. Extracting the *logical* data (field names, values, types)
3. Encoding that data into a *portable* byte sequence
4. That any language can decode back into its own native representation

Without serialization, distributed systems are impossible. Every RPC call, every message queue publish, every database write, every HTTP response — all of them serialize data from one representation and deserialize it into another.

---

## The Serialization-Deserialization Round Trip

Every serialization format implements this contract:

```
encode(object) -> bytes     (serialization)
decode(bytes)  -> object    (deserialization)
```

A format is **correct** if the round trip preserves fidelity:

```python
original = make_typical_order()
encoded  = encode(original)
decoded  = decode(encoded)
assert decoded == original   # round-trip fidelity
```

But correctness is just the starting point. We also care about:

| Property | Definition |
|----------|-----------|
| **Portability** | Can any language encode/decode this format? |
| **Compactness** | How many bytes does the encoded form take? |
| **Speed** | How many microseconds to encode/decode? |
| **Fidelity** | Does the round trip produce an identical object? |
| **Schema** | Is the format self-describing, or do you need external metadata? |
| **Readability** | Can a human inspect the encoded bytes and understand them? |
| **Evolvability** | Can you add/remove fields without breaking existing readers? |

These properties **conflict**. A human-readable format (like JSON) is portable and debuggable but large and slow. A binary format (like Protocol Buffers) is compact and fast but not human-readable. A schema-less format is flexible but fragile. Every serialization format makes different trade-offs, and understanding those trade-offs is the subject of this entire book.

---

## Systems Constraints

FoodDash processes **1 million messages per second**. At that scale, serialization costs are not theoretical — they're a line item in your cloud bill.

### CPU Cost

If serialization takes 10 microseconds per message, that's:

```
10 us x 1,000,000 msg/s = 10 seconds of CPU time per second
```

You'd need **10 CPU cores** just for serialization. Cut it to 1 microsecond and you need 1 core. Cut it to 100 nanoseconds and serialization becomes negligible. The difference between a slow format and a fast one is **10x in compute cost**.

### Memory / GC Pressure

Deserialization typically allocates new objects. In garbage-collected languages (Python, Go, Java), every allocation is a future GC pause. At 1M msg/s, even small allocations add up:

```
100 bytes/msg x 1,000,000 msg/s = 100 MB/s of allocation
```

That's enough to trigger major GC pauses every few seconds, causing latency spikes that your p99 SLAs can't tolerate. Formats that enable **zero-copy deserialization** (reading fields directly from the wire buffer without allocating new objects) can eliminate this entirely. We'll explore these in later chapters (FlatBuffers, Cap'n Proto).

### Wire Size

Every byte you put on the wire costs bandwidth and adds latency:

```
500 bytes/msg x 1,000,000 msg/s = 500 MB/s = 4 Gbps
```

On a 10 Gbps network link, you're using 40% of your bandwidth just for order messages. Halve the payload size and you halve the bandwidth cost. For cloud-to-cloud traffic billed per GB, this directly impacts your infrastructure bill.

### Latency

Serialization and deserialization are on the critical path of every RPC. If you're making 5 serial RPC calls to process an order (validate payment, check inventory, assign driver, estimate time, send notification), serialization overhead multiplies:

```
5 RPCs x 2 (encode + decode) x 10 us = 100 us of pure serialization overhead
```

That's 100 microseconds you can never get back, regardless of how fast your business logic is.

These constraints drive the entire progression from human-readable text formats (simple but slow) to schema-driven binary formats (complex but fast).

---

## Production Depth: How Real Systems Handle This

Before we build our own wire formats, let's look at how existing systems have tried to solve the serialization problem — and where they fall short.

### Python's pickle

`pickle` can serialize almost any Python object, including custom classes, closures, and even code objects. This power comes at a steep cost:

- **Python-only**: There's no pickle decoder for Go, Java, Rust, or JavaScript. Your data is trapped in the Python ecosystem.
- **Insecure**: `pickle.loads()` can execute arbitrary code. A malicious payload can run `os.system("rm -rf /")` on the deserializing machine. The Python docs literally warn: "Never unpickle data received from an untrusted or unauthenticated source."
- **Version-dependent**: Pickle has 6 protocol versions (0-5). Objects pickled with one version may not unpickle with another. Python version upgrades can break stored pickled data.
- **Not human-readable**: The output is an opaque byte stream. Debugging requires specialized tools.

Pickle is fine for temporary local caching (shelve, multiprocessing). It's disqualified for any inter-service communication.

### Java Serialization

Java's built-in `Serializable` interface has similar problems:

- **Java-only**: The format encodes Java class hierarchy, field types, and serialVersionUID.
- **Class evolution**: Adding or removing fields can break deserialization unless you manually manage `serialVersionUID` and write custom `readObject`/`writeObject` methods.
- **Security**: Like pickle, Java deserialization has led to critical vulnerabilities (Apache Commons Collections, Spring Framework, WebLogic). The Java team has been trying to deprecate it since Java 9.
- **Performance**: Java serialization is consistently one of the slowest serialization mechanisms, because it uses reflection and writes full class metadata.

### Go's encoding/gob

Go's `gob` package takes a more principled approach:

- **Schema-aware**: It encodes type information once and then sends compact field data.
- **Self-describing**: The decoder doesn't need a separate schema file.
- **Efficient for Go**: It leverages Go's reflection and type system.

But it's still **Go-only**. A Python service can't decode gob without reimplementing the entire format. And gob's type information is Go-specific (e.g., it knows about Go slices, maps, and interfaces).

### The Lesson

Language-specific serialization is a dead end for distributed systems. As soon as your architecture includes services in more than one language — which happens at virtually every company that grows beyond a single team — you need a format that's defined independently of any language.

That's what we'll build, step by step, starting in the next chapter.

---

## Trade-offs Table

Before we move on, let's score the "just send memory" approach against the properties we care about:

| Property | "Just send memory" | Notes |
|----------|:-------------------:|-------|
| **Portable** | No | Language-specific object layout |
| **Compact** | No | Python objects are 7-16x larger than C equivalents |
| **Fast** | No | Pointer chasing destroys cache locality |
| **Schema** | No | Implicit in code, not in the data |
| **Readable** | No | Raw bytes with embedded pointers |
| **Evolvable** | No | Any struct change breaks all readers |
| **Secure** | No | Pickle/Java deserialization = arbitrary code execution |

Zero out of seven. We can do better.

---

## The Bridge

We've established that in-memory representations are non-portable. Pointers are process-local. Byte order varies across architectures. Alignment and padding vary across compilers. Object layouts vary across languages. You cannot send memory.

We need a **wire format** — a defined byte layout that both sender and receiver agree on, independent of their programming language or CPU architecture.

What's the simplest possible wire format? One where:
- Every value is written as **human-readable text** (no endianness issues)
- Fields are separated by a **delimiter** (no alignment issues)
- Any language with string parsing can read it (maximum portability)

That format is **CSV** (comma-separated values) — and it's where Chapter 01 begins.

It won't be fast. It won't be compact. It won't handle nested objects gracefully. But it will be *portable*, and that's the one property we absolutely cannot compromise on.

Let's go build it.

---

## Running the Demos

```bash
# Run all Chapter 00 demos
uv run python -m chapters.ch00_foundations

# Run individual modules
uv run python -m chapters.ch00_foundations.memory_layout
uv run python -m chapters.ch00_foundations.endianness
uv run python -m chapters.ch00_foundations.alignment
```

## Files in This Chapter

| File | Purpose |
|------|---------|
| `memory_layout.py` | Python object sizes, heap scatter, raw memory peek, pickle demo |
| `endianness.py` | Big vs little endian, network byte order, the endianness bug |
| `alignment.py` | C struct padding, field order, cross-machine incompatibility |
| `visual.html` | Interactive visualization of memory layout vs wire format |
| `__main__.py` | Entry point that runs all demos |
