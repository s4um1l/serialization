"""Endianness: the first portability trap.

Demonstrates:
- Big-endian vs little-endian byte order for multi-byte integers
- Network byte order (big-endian) vs x86/ARM (little-endian)
- What happens when you misinterpret byte order
- struct.pack/unpack with explicit byte order prefixes
- Encoding GeoPoint latitude in both byte orders
"""

import struct
import sys

from shared.sample_data import BURGER_PALACE


def show_byte_order_basics() -> None:
    """Show the difference between big-endian and little-endian."""
    print("=" * 60)
    print("  ENDIANNESS: BIG vs LITTLE")
    print("=" * 60)
    print()

    value = 1000
    big = struct.pack(">I", value)  # Big-endian unsigned 32-bit int
    little = struct.pack("<I", value)  # Little-endian unsigned 32-bit int

    print(f"  Value: {value} (0x{value:08X})")
    print()
    print(f"  Big-endian    ('>I'):  {big.hex(' ')}")
    print(f"  Little-endian ('<I'):  {little.hex(' ')}")
    print()
    print("  Big-endian:    most significant byte FIRST  (like reading left-to-right)")
    print("  Little-endian: least significant byte FIRST (like x86, ARM)")
    print()

    # Show this machine's byte order
    print(f"  This machine's byte order: {sys.byteorder}")
    print()


def show_network_byte_order() -> None:
    """Show network byte order (big-endian) per RFC 1700."""
    print("=" * 60)
    print("  NETWORK BYTE ORDER (RFC 1700)")
    print("=" * 60)
    print()

    # Network byte order is big-endian, denoted by '!' in struct
    value = 0xDEADBEEF
    network = struct.pack("!I", value)
    big = struct.pack(">I", value)
    little = struct.pack("<I", value)

    print(f"  Value: 0x{value:08X}")
    print()
    print(f"  Network ('!I'):       {network.hex(' ')}")
    print(f"  Big-endian ('>I'):    {big.hex(' ')}")
    print(f"  Little-endian ('<I'): {little.hex(' ')}")
    print()
    print("  Network byte order = big-endian (they are identical).")
    print("  TCP/IP headers, DNS, and most network protocols use big-endian.")
    print("  But x86 and ARM CPUs are little-endian internally.")
    print()


def show_misinterpretation() -> None:
    """Show what happens when you read bytes with the wrong byte order."""
    print("=" * 60)
    print("  THE ENDIANNESS BUG: MISINTERPRETATION")
    print("=" * 60)
    print()

    # Simulate: Service A sends price_cents as big-endian
    price_cents = 1299  # $12.99
    sent_bytes = struct.pack(">I", price_cents)

    print(f"  Service A (Python) sends price_cents = {price_cents}")
    print(f"  Encoded as big-endian:    {sent_bytes.hex(' ')}")
    print()

    # Service B reads as little-endian (wrong!)
    wrong_value = struct.unpack("<I", sent_bytes)[0]
    correct_value = struct.unpack(">I", sent_bytes)[0]

    print(f"  Service B reads as big-endian (correct):    {correct_value}")
    print(f"  Service B reads as little-endian (WRONG):   {wrong_value}")
    print()
    print(f"  The customer was charged ${wrong_value / 100:,.2f} instead of ${price_cents / 100:.2f}!")
    print()

    # Another example with a larger value
    txn_id = 123456789
    sent = struct.pack(">Q", txn_id)  # 64-bit big-endian
    wrong = struct.unpack("<Q", sent)[0]

    print(f"  Transaction ID sent (big-endian):      {txn_id:,}")
    print(f"  Bytes on wire:                         {sent.hex(' ')}")
    print(f"  Read as little-endian:                 {wrong:,}")
    print()
    print("  Without agreeing on byte order, every multi-byte value")
    print("  can be silently misinterpreted. This is not a hypothetical --")
    print("  it's one of the oldest bugs in networked computing.")
    print()


def show_geopoint_encoding() -> None:
    """Encode a GeoPoint's latitude as both big and little endian."""
    print("=" * 60)
    print("  GEOPOINT LATITUDE: ENDIANNESS IN ACTION")
    print("=" * 60)
    print()

    lat = BURGER_PALACE.location.latitude
    lon = BURGER_PALACE.location.longitude

    print(f"  Burger Palace location: ({lat}, {lon})")
    print()

    # Latitude as 64-bit double (IEEE 754)
    big_lat = struct.pack(">d", lat)
    little_lat = struct.pack("<d", lat)

    print(f"  Latitude {lat} as IEEE 754 double:")
    print(f"    Big-endian:    {big_lat.hex(' ')}")
    print(f"    Little-endian: {little_lat.hex(' ')}")
    print()

    # Show misinterpretation for doubles too
    wrong_lat = struct.unpack("<d", big_lat)[0]
    print("  If big-endian bytes are read as little-endian:")
    print(f"    Correct: {lat}")
    print(f"    Wrong:   {wrong_lat}")
    print()

    # Longitude too
    big_lon = struct.pack(">d", lon)
    little_lon = struct.pack("<d", lon)
    print(f"  Longitude {lon} as IEEE 754 double:")
    print(f"    Big-endian:    {big_lon.hex(' ')}")
    print(f"    Little-endian: {little_lon.hex(' ')}")
    print()

    # Show all common integer sizes
    print("  Common integer sizes and their byte representations:")
    print()
    print(f"  {'Type':<12} {'Format':>8} {'Big-endian':<24} {'Little-endian':<24}")
    print(f"  {'-' * 12} {'-' * 8} {'-' * 24} {'-' * 24}")

    for label, fmt_char, val in [
        ("int16", "h", 1299),
        ("uint16", "H", 1299),
        ("int32", "i", 1299),
        ("uint32", "I", 1299),
        ("int64", "q", 123456789),
        ("uint64", "Q", 123456789),
        ("float32", "f", 40.748817),
        ("float64", "d", 40.748817),
    ]:
        big = struct.pack(f">{fmt_char}", val)
        little = struct.pack(f"<{fmt_char}", val)
        print(f"  {label:<12} {fmt_char:>8} {big.hex(' '):<24} {little.hex(' '):<24}")

    print()


def main() -> None:
    show_byte_order_basics()
    show_network_byte_order()
    show_misinterpretation()
    show_geopoint_encoding()


if __name__ == "__main__":
    main()
