"""How Python objects live in memory — and why you can't just send them.

Demonstrates:
- sys.getsizeof() overhead on basic Python types
- id() to show that object fields are scattered across the heap
- ctypes to peek at raw bytes at an object's memory address
- Pydantic Order objects contain pointers, not inline data
"""

import ctypes
import sys

from shared.sample_data import make_typical_order


def show_python_object_sizes() -> None:
    """Show how Python wraps every value in a heavyweight object."""
    print("=" * 60)
    print("  PYTHON OBJECT SIZES  (sys.getsizeof)")
    print("=" * 60)
    print()
    specimens = [
        ("int(0)", 0),
        ("int(42)", 42),
        ("int(2**30)", 2**30),
        ("float(3.14)", 3.14),
        ("bool(True)", True),
        ("str('') (empty)", ""),
        ("str('hello')", "hello"),
        ("str('a' * 100)", "a" * 100),
        ("list([])", []),
        ("list([1,2,3])", [1, 2, 3]),
        ("dict({})", {}),
        ("dict({'a':1})", {"a": 1}),
        ("bytes(b'')", b""),
        ("bytes(b'\\x00' * 100)", b"\x00" * 100),
        ("None", None),
    ]

    print(f"  {'Expression':<30} {'Size (bytes)':>15}  Notes")
    print(f"  {'-' * 30} {'-' * 15}  {'-' * 30}")
    for label, obj in specimens:
        size = sys.getsizeof(obj)
        note = ""
        if label == "int(42)":
            note = "<-- a C int is 4 bytes!"
        elif label == "float(3.14)":
            note = "<-- a C double is 8 bytes!"
        elif label == "str('hello')":
            note = "<-- 5 chars, but 54 bytes of overhead"
        print(f"  {label:<30} {size:>15,}  {note}")

    print()
    print("  Key insight: Python objects carry type pointers, reference")
    print("  counts, and other metadata. A Python int(42) is 28 bytes,")
    print("  not 4. You cannot just memcpy these to another process.")
    print()


def show_heap_scatter() -> None:
    """Show that an Order's fields are scattered across the heap."""
    print("=" * 60)
    print("  HEAP SCATTER  (id() addresses)")
    print("=" * 60)
    print()

    order = make_typical_order()

    print("  An Order object and its nested fields live at different")
    print("  heap addresses. These are POINTERS — not inline data.")
    print()

    addresses = [
        ("order", order),
        ("order.id", order.id),
        ("order.customer", order.customer),
        ("order.customer.name", order.customer.name),
        ("order.customer.location", order.customer.location),
        ("order.items", order.items),
        ("order.items[0]", order.items[0]),
        ("order.items[0].menu_item", order.items[0].menu_item),
        ("order.items[0].menu_item.name", order.items[0].menu_item.name),
        ("order.status", order.status),
        ("order.metadata", order.metadata),
    ]

    print(f"  {'Field':<35} {'Address (hex)':>18} {'Size':>8}")
    print(f"  {'-' * 35} {'-' * 18} {'-' * 8}")
    for label, obj in addresses:
        addr = id(obj)
        size = sys.getsizeof(obj)
        print(f"  {label:<35} {hex(addr):>18} {size:>8}")

    # Show address gaps
    addrs = [id(obj) for _, obj in addresses]
    min_addr, max_addr = min(addrs), max(addrs)
    span = max_addr - min_addr
    total_sizes = sum(sys.getsizeof(obj) for _, obj in addresses)

    print()
    print(f"  Address span:  {span:,} bytes ({span / 1024:.1f} KB)")
    print(f"  Total payload: {total_sizes:,} bytes")
    print(f"  Wasted span:   {span - total_sizes:,} bytes (fragmentation)")
    print()
    print("  These pointers are process-local. Sending them to another")
    print("  machine (or even another process) would produce garbage.")
    print()


def peek_raw_bytes() -> None:
    """Use ctypes to look at the raw bytes at an object's memory address."""
    print("=" * 60)
    print("  RAW MEMORY PEEK  (ctypes)")
    print("=" * 60)
    print()

    # Peek at a Python integer
    x = 42
    addr = id(x)
    size = sys.getsizeof(x)

    print(f"  Python int(42) at address {hex(addr)}, size {size} bytes")
    print()
    print("  First 28 bytes of the CPython PyLongObject:")
    print()

    # Read raw bytes from the object's memory
    raw = (ctypes.c_ubyte * size).from_address(addr)
    raw_bytes = bytes(raw)

    # Print hex dump
    for offset in range(0, min(size, 32), 8):
        chunk = raw_bytes[offset : offset + 8]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {offset:04x}:  {hex_str:<24} |{ascii_str}|")

    print()
    print("  Bytes 0-7:   type pointer (PyTypeObject*)")
    print("  Bytes 8-15:  reference count")
    print("  Bytes 16+:   actual integer data")
    print()

    # Now peek at a string
    s = "hello"
    addr_s = id(s)
    size_s = sys.getsizeof(s)

    print(f"  Python str('hello') at address {hex(addr_s)}, size {size_s} bytes")
    print()
    raw_s = (ctypes.c_ubyte * size_s).from_address(addr_s)
    raw_bytes_s = bytes(raw_s)

    for offset in range(0, min(size_s, 64), 8):
        chunk = raw_bytes_s[offset : offset + 8]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {offset:04x}:  {hex_str:<24} |{ascii_str}|")

    print()
    print("  The actual characters 'hello' are buried deep inside the")
    print("  object, surrounded by metadata. This is NOT a wire format.")
    print()


def show_order_is_pointers() -> None:
    """Demonstrate that a Pydantic Order is a graph of pointer references."""
    print("=" * 60)
    print("  ORDER OBJECT = POINTER GRAPH")
    print("=" * 60)
    print()

    order = make_typical_order()

    # Show that the order's __dict__ or model fields are all references
    print("  A Pydantic Order object's fields are all references (pointers):")
    print()

    fields_data = order.model_dump()
    order_size = sys.getsizeof(order)

    print(f"  Order object itself:  {order_size} bytes (just the container)")
    print()

    # Walk the object graph and sum up sizes
    total_reachable = 0

    def walk_size(obj, depth=0) -> int:
        """Recursively estimate total reachable memory."""
        size = sys.getsizeof(obj)
        if isinstance(obj, dict):
            for k, v in obj.items():
                size += sys.getsizeof(k) + walk_size(v, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                size += walk_size(item, depth + 1)
        return size

    total_reachable = walk_size(fields_data)

    print(f"  Total reachable via model_dump(): {total_reachable:,} bytes")
    print("  (traversing every nested dict, list, string, int, ...)")
    print()

    # Compare with pickle
    import pickle

    pickled = pickle.dumps(order)
    print(f"  pickle.dumps(order):  {len(pickled):,} bytes")
    print()
    print("  Pickle works for Python-to-Python... but it encodes Python-")
    print("  specific type information, and is INSECURE (arbitrary code")
    print("  execution on load). When the kitchen service is rewritten")
    print("  in Go, pickle is useless.")
    print()
    print("  We need a PORTABLE byte format.")
    print()


def main() -> None:
    show_python_object_sizes()
    show_heap_scatter()
    peek_raw_bytes()
    show_order_is_pointers()


if __name__ == "__main__":
    main()
