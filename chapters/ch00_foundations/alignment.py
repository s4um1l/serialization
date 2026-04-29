"""Alignment and padding: the second portability trap.

Demonstrates:
- C struct padding and alignment rules
- Packed vs aligned struct layouts using Python's struct module
- Why memcpy of a struct between machines can fail
- The difference between Python's object layout and C's struct layout
- The conclusion: we need a portable, self-describing byte format
"""

import struct
import sys


def show_c_struct_padding() -> None:
    """Simulate a C struct and show the padding bytes."""
    print("=" * 60)
    print("  C STRUCT ALIGNMENT AND PADDING")
    print("=" * 60)
    print()
    print("  Consider this C struct for an order summary:")
    print()
    print("    struct OrderSummary {")
    print("        char   status;       // 1 byte  (offset 0)")
    print("        int    price_cents;   // 4 bytes (offset 4, after 3 padding)")
    print("        double latitude;      // 8 bytes (offset 8)")
    print("    };")
    print()

    # Aligned layout (what a C compiler actually does)
    # 'x' in struct format = padding byte
    aligned = struct.pack("=Bxxxi d", ord("P"), 1299, 40.748817)

    # Packed layout (no padding, __attribute__((packed)) in GCC)
    packed = struct.pack("=Bid", ord("P"), 1299, 40.748817)

    print(f"  Aligned (with padding): {len(aligned)} bytes")
    print(f"    Hex: {aligned.hex(' ')}")
    print()

    # Annotate the aligned bytes
    print("    Byte-by-byte breakdown:")
    print(f"      [0]     {aligned[0]:02x}             status = 'P' (0x50)")
    print(f"      [1-3]   {aligned[1]:02x} {aligned[2]:02x} {aligned[3]:02x}          PADDING (3 bytes)")
    print(f"      [4-7]   {aligned[4:8].hex(' ')}    price_cents = 1299")
    print(f"      [8-15]  {aligned[8:16].hex(' ')}  latitude = 40.748817")
    print()

    print(f"  Packed (no padding):    {len(packed)} bytes")
    print(f"    Hex: {packed.hex(' ')}")
    print()
    print("    Byte-by-byte breakdown:")
    print(f"      [0]     {packed[0]:02x}             status = 'P' (0x50)")
    print(f"      [1-4]   {packed[1:5].hex(' ')}    price_cents = 1299")
    print(f"      [5-12]  {packed[5:13].hex(' ')}  latitude = 40.748817")
    print()

    print(f"  Size difference: {len(aligned) - len(packed)} bytes of padding")
    print(f"  At 1M messages/sec, that's {(len(aligned) - len(packed)) * 1_000_000 / 1024 / 1024:.1f} MB/sec wasted on padding alone.")
    print()


def show_field_order_matters() -> None:
    """Show that reordering fields changes padding."""
    print("=" * 60)
    print("  FIELD ORDER AFFECTS PADDING")
    print("=" * 60)
    print()
    print("  struct Bad {          struct Good {")
    print("    char   a;  // 1      double c;  // 8")
    print("    double c;  // 8      int    b;  // 4")
    print("    int    b;  // 4      char   a;  // 1")
    print("  };                   };")
    print()

    # Bad ordering: char, double, int -> lots of padding
    # char(1) + 7 padding + double(8) + int(4) + 4 padding = 24
    bad = struct.pack("=Bxxxxxxxdi xxxx", ord("A"), 3.14, 42)
    # Good ordering: double, int, char -> minimal padding
    # double(8) + int(4) + char(1) + 3 padding = 16
    good = struct.pack("=diB xxx", 3.14, 42, ord("A"))

    print(f"  Bad ordering:  {len(bad):>2} bytes  (hex: {bad.hex(' ')})")
    print(f"  Good ordering: {len(good):>2} bytes  (hex: {good.hex(' ')})")
    print()
    print(f"  Same data, different field order: {len(bad) - len(good)} bytes wasted.")
    print("  A C compiler may add different padding than a Go compiler,")
    print("  even on the same architecture.")
    print()


def show_cross_architecture_problem() -> None:
    """Demonstrate why memcpy of a struct between machines fails."""
    print("=" * 60)
    print("  WHY MEMCPY FAILS ACROSS MACHINES")
    print("=" * 60)
    print()

    status = ord("P")
    price_cents = 1299
    latitude = 40.748817

    # Machine A: little-endian, 4-byte aligned
    machine_a = struct.pack("<Bxxxi d", status, price_cents, latitude)

    # Machine B: big-endian, 4-byte aligned (e.g., old SPARC or network device)
    machine_b = struct.pack(">Bxxxi d", status, price_cents, latitude)

    # Machine C: little-endian, packed (e.g., embedded device with #pragma pack(1))
    machine_c = struct.pack("<Bid", status, price_cents, latitude)

    print("  Same data: status='P', price_cents=1299, latitude=40.748817")
    print()
    print(f"  Machine A (x86, aligned):        {machine_a.hex(' ')}")
    print(f"  Machine B (big-endian, aligned):  {machine_b.hex(' ')}")
    print(f"  Machine C (x86, packed):          {machine_c.hex(' ')}")
    print()

    # Try to read Machine A's bytes on Machine B
    print("  What happens if Machine B reads Machine A's bytes?")
    print()

    # Machine B expects big-endian at offset 4
    price_from_a_on_b = struct.unpack(">i", machine_a[4:8])[0]
    lat_from_a_on_b = struct.unpack(">d", machine_a[8:16])[0]
    print(f"    price_cents: expected 1299, got {price_from_a_on_b}")
    print(f"    latitude:    expected 40.748817, got {lat_from_a_on_b}")
    print()

    # Machine A tries to read Machine C's bytes (different padding)
    print("  What happens if Machine A reads Machine C's packed bytes")
    print("  assuming aligned layout?")
    print()

    # Machine A expects price_cents at offset 4, but in packed it's at offset 1
    price_from_c_on_a = struct.unpack("<i", machine_c[4:8])[0]
    print(f"    price_cents: expected 1299, got {price_from_c_on_a}")
    print("    (reading from wrong offset due to different padding)")
    print()
    print("  Three sources of incompatibility:")
    print("    1. Endianness: byte order within multi-byte values")
    print("    2. Alignment:  padding between fields")
    print("    3. Layout:     field order and packing rules")
    print()


def show_python_vs_c_layout() -> None:
    """Show that Python's object layout is nothing like C's struct layout."""
    print("=" * 60)
    print("  PYTHON LAYOUT vs C LAYOUT")
    print("=" * 60)
    print()

    # C struct: tightly packed data
    c_struct = struct.pack("<Bxxxi d", ord("P"), 1299, 40.748817)

    # Python: each value is its own object with overhead
    status_py = sys.getsizeof(ord("P"))
    price_py = sys.getsizeof(1299)
    lat_py = sys.getsizeof(40.748817)
    dict_overhead = sys.getsizeof({"status": None, "price_cents": None, "latitude": None})

    print(f"  C struct layout:                {len(c_struct):>6} bytes total")
    print(f"    char status:                  {1:>6} byte")
    print(f"    padding:                      {3:>6} bytes")
    print(f"    int price_cents:              {4:>6} bytes")
    print(f"    double latitude:              {8:>6} bytes")
    print()
    print("  Python object layout:")
    print(f"    int(80) for status:           {status_py:>6} bytes")
    print(f"    int(1299) for price_cents:    {price_py:>6} bytes")
    print(f"    float(40.748817) for latitude: {lat_py:>6} bytes")
    print(f"    dict for field names:         {dict_overhead:>6} bytes")
    print(f"    Total (approx):               {status_py + price_py + lat_py + dict_overhead:>6} bytes")
    print()
    print(f"  Ratio: Python uses ~{(status_py + price_py + lat_py + dict_overhead) / len(c_struct):.0f}x more memory than C")
    print("  for the same three fields.")
    print()
    print("  Even within a single language, the in-memory representation")
    print("  is completely unsuitable as a wire format.")
    print()


def show_the_conclusion() -> None:
    """The conclusion: we need a portable, self-describing byte format."""
    print("=" * 60)
    print("  CONCLUSION: WE NEED A WIRE FORMAT")
    print("=" * 60)
    print()
    print("  Sending raw memory fails because:")
    print()
    print("    1. POINTERS are process-local (Python objects are pointer graphs)")
    print("    2. ENDIANNESS differs between architectures")
    print("    3. ALIGNMENT/PADDING differs between compilers")
    print("    4. OBJECT LAYOUT differs between languages")
    print()
    print("  We need a format that is:")
    print()
    print("    - Portable:       any language, any architecture")
    print("    - Self-describing: reader knows how to parse without external info")
    print("    - Compact:        minimal overhead")
    print("    - Fast:           encode/decode in microseconds")
    print()
    print("  That's SERIALIZATION: the translation layer between in-memory")
    print("  and on-the-wire. And the simplest possible format? A text-based")
    print("  one where fields are human-readable, separated by delimiters.")
    print()
    print("  That's CSV -- and it's where Chapter 01 begins.")
    print()


def main() -> None:
    show_c_struct_padding()
    show_field_order_matters()
    show_cross_architecture_problem()
    show_python_vs_c_layout()
    show_the_conclusion()


if __name__ == "__main__":
    main()
