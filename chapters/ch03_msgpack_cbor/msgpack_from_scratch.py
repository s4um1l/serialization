"""MessagePack encoder/decoder — built from scratch, no libraries.

Implements the core MessagePack specification:
https://github.com/msgpack/msgpack/blob/master/spec.md

This shows what JSON-to-binary really means: every value gets a type prefix
byte that tells the decoder exactly what comes next (and for small values,
the type byte IS the value).
"""

from __future__ import annotations

import json
import struct
from typing import Any

from shared.sample_data import make_typical_order


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def msgpack_encode(obj: Any) -> bytes:
    """Recursively encode a Python object into MessagePack bytes."""
    if obj is None:
        return b"\xc0"

    if isinstance(obj, bool):
        # Must check bool before int (bool is a subclass of int in Python)
        return b"\xc3" if obj else b"\xc2"

    if isinstance(obj, int):
        return _encode_int(obj)

    if isinstance(obj, float):
        return _encode_float(obj)

    if isinstance(obj, str):
        return _encode_str(obj)

    if isinstance(obj, bytes):
        return _encode_bin(obj)

    if isinstance(obj, (list, tuple)):
        return _encode_array(obj)

    if isinstance(obj, dict):
        return _encode_map(obj)

    raise TypeError(f"Cannot msgpack-encode type {type(obj).__name__}")


def _encode_int(n: int) -> bytes:
    """Encode an integer using the smallest possible representation."""
    if 0 <= n <= 127:
        # positive fixint: single byte, value IS the byte
        return bytes([n])
    if -32 <= n < 0:
        # negative fixint: single byte, 0xe0 + (n & 0x1f)
        return bytes([n & 0xff])
    if 0 <= n <= 0xFF:
        return b"\xcc" + bytes([n])  # uint 8
    if 0 <= n <= 0xFFFF:
        return b"\xcd" + struct.pack(">H", n)  # uint 16
    if 0 <= n <= 0xFFFFFFFF:
        return b"\xce" + struct.pack(">I", n)  # uint 32
    if 0 <= n <= 0xFFFFFFFFFFFFFFFF:
        return b"\xcf" + struct.pack(">Q", n)  # uint 64
    if -128 <= n < 0:
        return b"\xd0" + struct.pack(">b", n)  # int 8
    if -32768 <= n < 0:
        return b"\xd1" + struct.pack(">h", n)  # int 16
    if -2147483648 <= n < 0:
        return b"\xd2" + struct.pack(">i", n)  # int 32
    if -9223372036854775808 <= n < 0:
        return b"\xd3" + struct.pack(">q", n)  # int 64
    raise OverflowError(f"Integer {n} is too large for MessagePack")


def _encode_float(f: float) -> bytes:
    """Encode a float as float 64 (0xcb)."""
    return b"\xcb" + struct.pack(">d", f)


def _encode_str(s: str) -> bytes:
    """Encode a string with length-prefixed UTF-8 bytes."""
    raw = s.encode("utf-8")
    length = len(raw)
    if length <= 31:
        # fixstr: 0xa0 | length
        return bytes([0xA0 | length]) + raw
    if length <= 0xFF:
        return b"\xd9" + bytes([length]) + raw  # str 8
    if length <= 0xFFFF:
        return b"\xda" + struct.pack(">H", length) + raw  # str 16
    if length <= 0xFFFFFFFF:
        return b"\xdb" + struct.pack(">I", length) + raw  # str 32
    raise OverflowError(f"String too long ({length} bytes)")


def _encode_bin(b: bytes) -> bytes:
    """Encode raw binary data — this is what JSON can't do!"""
    length = len(b)
    if length <= 0xFF:
        return b"\xc4" + bytes([length]) + b  # bin 8
    if length <= 0xFFFF:
        return b"\xc5" + struct.pack(">H", length) + b  # bin 16
    if length <= 0xFFFFFFFF:
        return b"\xc6" + struct.pack(">I", length) + b  # bin 32
    raise OverflowError(f"Binary data too long ({length} bytes)")


def _encode_array(arr: list | tuple) -> bytes:
    """Encode an array with element count prefix."""
    length = len(arr)
    if length <= 15:
        header = bytes([0x90 | length])  # fixarray
    elif length <= 0xFFFF:
        header = b"\xdc" + struct.pack(">H", length)  # array 16
    elif length <= 0xFFFFFFFF:
        header = b"\xdd" + struct.pack(">I", length)  # array 32
    else:
        raise OverflowError(f"Array too long ({length} elements)")
    return header + b"".join(msgpack_encode(item) for item in arr)


def _encode_map(d: dict) -> bytes:
    """Encode a map with entry count prefix."""
    length = len(d)
    if length <= 15:
        header = bytes([0x80 | length])  # fixmap
    elif length <= 0xFFFF:
        header = b"\xde" + struct.pack(">H", length)  # map 16
    elif length <= 0xFFFFFFFF:
        header = b"\xdf" + struct.pack(">I", length)  # map 32
    else:
        raise OverflowError(f"Map too many entries ({length})")
    parts = [header]
    for key, value in d.items():
        parts.append(msgpack_encode(key))
        parts.append(msgpack_encode(value))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

class _Reader:
    """Byte stream reader with position tracking."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise ValueError("Unexpected end of data")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("Unexpected end of data")
        b = self.data[self.pos]
        self.pos += 1
        return b


def msgpack_decode(data: bytes) -> Any:
    """Decode MessagePack bytes into a Python object."""
    reader = _Reader(data)
    result = _decode_one(reader)
    return result


def _decode_one(reader: _Reader) -> Any:
    """Decode a single value from the reader."""
    b = reader.read_byte()

    # positive fixint: 0x00 - 0x7f
    if b <= 0x7F:
        return b

    # fixmap: 0x80 - 0x8f
    if 0x80 <= b <= 0x8F:
        return _decode_map(reader, b & 0x0F)

    # fixarray: 0x90 - 0x9f
    if 0x90 <= b <= 0x9F:
        return _decode_array(reader, b & 0x0F)

    # fixstr: 0xa0 - 0xbf
    if 0xA0 <= b <= 0xBF:
        length = b & 0x1F
        return reader.read(length).decode("utf-8")

    # nil
    if b == 0xC0:
        return None

    # false / true
    if b == 0xC2:
        return False
    if b == 0xC3:
        return True

    # bin 8 / 16 / 32
    if b == 0xC4:
        length = reader.read_byte()
        return reader.read(length)
    if b == 0xC5:
        length = struct.unpack(">H", reader.read(2))[0]
        return reader.read(length)
    if b == 0xC6:
        length = struct.unpack(">I", reader.read(4))[0]
        return reader.read(length)

    # float 32 / 64
    if b == 0xCA:
        return struct.unpack(">f", reader.read(4))[0]
    if b == 0xCB:
        return struct.unpack(">d", reader.read(8))[0]

    # uint 8 / 16 / 32 / 64
    if b == 0xCC:
        return reader.read_byte()
    if b == 0xCD:
        return struct.unpack(">H", reader.read(2))[0]
    if b == 0xCE:
        return struct.unpack(">I", reader.read(4))[0]
    if b == 0xCF:
        return struct.unpack(">Q", reader.read(8))[0]

    # int 8 / 16 / 32 / 64
    if b == 0xD0:
        return struct.unpack(">b", reader.read(1))[0]
    if b == 0xD1:
        return struct.unpack(">h", reader.read(2))[0]
    if b == 0xD2:
        return struct.unpack(">i", reader.read(4))[0]
    if b == 0xD3:
        return struct.unpack(">q", reader.read(8))[0]

    # str 8 / 16 / 32
    if b == 0xD9:
        length = reader.read_byte()
        return reader.read(length).decode("utf-8")
    if b == 0xDA:
        length = struct.unpack(">H", reader.read(2))[0]
        return reader.read(length).decode("utf-8")
    if b == 0xDB:
        length = struct.unpack(">I", reader.read(4))[0]
        return reader.read(length).decode("utf-8")

    # array 16 / 32
    if b == 0xDC:
        count = struct.unpack(">H", reader.read(2))[0]
        return _decode_array(reader, count)
    if b == 0xDD:
        count = struct.unpack(">I", reader.read(4))[0]
        return _decode_array(reader, count)

    # map 16 / 32
    if b == 0xDE:
        count = struct.unpack(">H", reader.read(2))[0]
        return _decode_map(reader, count)
    if b == 0xDF:
        count = struct.unpack(">I", reader.read(4))[0]
        return _decode_map(reader, count)

    # negative fixint: 0xe0 - 0xff
    if 0xE0 <= b <= 0xFF:
        return b - 256

    raise ValueError(f"Unknown MessagePack type byte: 0x{b:02x}")


def _decode_array(reader: _Reader, count: int) -> list:
    return [_decode_one(reader) for _ in range(count)]


def _decode_map(reader: _Reader, count: int) -> dict:
    result = {}
    for _ in range(count):
        key = _decode_one(reader)
        value = _decode_one(reader)
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Helpers for preparing Order data
# ---------------------------------------------------------------------------

def _prepare_for_msgpack(obj: Any) -> Any:
    """Convert Pydantic model dump values for msgpack encoding.

    Handles enum values (convert to string) and recursively processes
    nested structures. bytes fields are kept as-is (that's the point!).
    """
    if isinstance(obj, dict):
        return {k: _prepare_for_msgpack(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare_for_msgpack(v) for v in obj]
    if hasattr(obj, "value"):
        # Enum -> its string value
        return obj.value
    return obj


# ---------------------------------------------------------------------------
# Byte-level annotation
# ---------------------------------------------------------------------------

def annotate_bytes(data: bytes, max_bytes: int = 200) -> list[str]:
    """Produce human-readable annotations for the first max_bytes of a
    MessagePack payload.

    Returns a list of strings like:
        "0x85       fixmap (5 entries)"
        "0xa2       fixstr (length 2)"
        "0x69 0x64  'id'"
    """
    reader = _Reader(data)
    lines: list[str] = []
    _annotate_one(reader, lines, depth=0, max_pos=min(len(data), max_bytes))
    return lines


def _hex(bs: bytes) -> str:
    return " ".join(f"0x{b:02x}" for b in bs)


def _annotate_one(reader: _Reader, lines: list[str], depth: int, max_pos: int) -> None:
    if reader.pos >= max_pos:
        lines.append("  ... (truncated)")
        # Skip remaining
        reader.pos = len(reader.data)
        return

    indent = "  " * depth
    start = reader.pos
    b = reader.read_byte()

    # positive fixint
    if b <= 0x7F:
        lines.append(f"{indent}[{start:4d}] 0x{b:02x}         positive fixint = {b}")
        return

    # fixmap
    if 0x80 <= b <= 0x8F:
        count = b & 0x0F
        lines.append(f"{indent}[{start:4d}] 0x{b:02x}         fixmap ({count} entries)")
        for _ in range(count):
            if reader.pos >= max_pos:
                lines.append(f"{indent}  ... (truncated)")
                reader.pos = len(reader.data)
                return
            _annotate_one(reader, lines, depth + 1, max_pos)  # key
            _annotate_one(reader, lines, depth + 1, max_pos)  # value
        return

    # fixarray
    if 0x90 <= b <= 0x9F:
        count = b & 0x0F
        lines.append(f"{indent}[{start:4d}] 0x{b:02x}         fixarray ({count} elements)")
        for _ in range(count):
            if reader.pos >= max_pos:
                lines.append(f"{indent}  ... (truncated)")
                reader.pos = len(reader.data)
                return
            _annotate_one(reader, lines, depth + 1, max_pos)
        return

    # fixstr
    if 0xA0 <= b <= 0xBF:
        length = b & 0x1F
        raw = reader.read(length)
        text = raw.decode("utf-8", errors="replace")
        lines.append(f"{indent}[{start:4d}] 0x{b:02x} + {length}B    fixstr \"{text}\"")
        return

    # nil
    if b == 0xC0:
        lines.append(f"{indent}[{start:4d}] 0xc0         nil")
        return

    # false / true
    if b == 0xC2:
        lines.append(f"{indent}[{start:4d}] 0xc2         false")
        return
    if b == 0xC3:
        lines.append(f"{indent}[{start:4d}] 0xc3         true")
        return

    # bin 8
    if b == 0xC4:
        length = reader.read_byte()
        raw = reader.read(length)
        preview = _hex(raw[:16])
        suffix = "..." if length > 16 else ""
        lines.append(f"{indent}[{start:4d}] 0xc4 len={length:<4d} bin8 [{preview}{suffix}]")
        return

    # bin 16
    if b == 0xC5:
        length = struct.unpack(">H", reader.read(2))[0]
        raw = reader.read(length)
        preview = _hex(raw[:16])
        suffix = "..." if length > 16 else ""
        lines.append(f"{indent}[{start:4d}] 0xc5 len={length:<4d} bin16 [{preview}{suffix}]")
        return

    # float 64
    if b == 0xCB:
        val = struct.unpack(">d", reader.read(8))[0]
        lines.append(f"{indent}[{start:4d}] 0xcb + 8B    float64 = {val}")
        return

    # uint 8
    if b == 0xCC:
        val = reader.read_byte()
        lines.append(f"{indent}[{start:4d}] 0xcc 0x{val:02x}     uint8 = {val}")
        return

    # uint 16
    if b == 0xCD:
        val = struct.unpack(">H", reader.read(2))[0]
        lines.append(f"{indent}[{start:4d}] 0xcd + 2B    uint16 = {val}")
        return

    # uint 32
    if b == 0xCE:
        val = struct.unpack(">I", reader.read(4))[0]
        lines.append(f"{indent}[{start:4d}] 0xce + 4B    uint32 = {val}")
        return

    # uint 64
    if b == 0xCF:
        val = struct.unpack(">Q", reader.read(8))[0]
        lines.append(f"{indent}[{start:4d}] 0xcf + 8B    uint64 = {val}")
        return

    # int 8/16/32/64
    if b == 0xD0:
        val = struct.unpack(">b", reader.read(1))[0]
        lines.append(f"{indent}[{start:4d}] 0xd0 + 1B    int8 = {val}")
        return
    if b == 0xD1:
        val = struct.unpack(">h", reader.read(2))[0]
        lines.append(f"{indent}[{start:4d}] 0xd1 + 2B    int16 = {val}")
        return
    if b == 0xD2:
        val = struct.unpack(">i", reader.read(4))[0]
        lines.append(f"{indent}[{start:4d}] 0xd2 + 4B    int32 = {val}")
        return
    if b == 0xD3:
        val = struct.unpack(">q", reader.read(8))[0]
        lines.append(f"{indent}[{start:4d}] 0xd3 + 8B    int64 = {val}")
        return

    # str 8
    if b == 0xD9:
        length = reader.read_byte()
        raw = reader.read(length)
        text = raw.decode("utf-8", errors="replace")
        lines.append(f"{indent}[{start:4d}] 0xd9 len={length:<3d}  str8 \"{text[:60]}\"")
        return

    # str 16
    if b == 0xDA:
        length = struct.unpack(">H", reader.read(2))[0]
        raw = reader.read(length)
        text = raw.decode("utf-8", errors="replace")
        lines.append(f"{indent}[{start:4d}] 0xda len={length:<5d} str16 \"{text[:60]}\"")
        return

    # array 16
    if b == 0xDC:
        count = struct.unpack(">H", reader.read(2))[0]
        lines.append(f"{indent}[{start:4d}] 0xdc + 2B    array16 ({count} elements)")
        for _ in range(count):
            if reader.pos >= max_pos:
                lines.append(f"{indent}  ... (truncated)")
                reader.pos = len(reader.data)
                return
            _annotate_one(reader, lines, depth + 1, max_pos)
        return

    # map 16
    if b == 0xDE:
        count = struct.unpack(">H", reader.read(2))[0]
        lines.append(f"{indent}[{start:4d}] 0xde + 2B    map16 ({count} entries)")
        for _ in range(count):
            if reader.pos >= max_pos:
                lines.append(f"{indent}  ... (truncated)")
                reader.pos = len(reader.data)
                return
            _annotate_one(reader, lines, depth + 1, max_pos)
            _annotate_one(reader, lines, depth + 1, max_pos)
        return

    # negative fixint
    if 0xE0 <= b <= 0xFF:
        val = b - 256
        lines.append(f"{indent}[{start:4d}] 0x{b:02x}         negative fixint = {val}")
        return

    lines.append(f"{indent}[{start:4d}] 0x{b:02x}         (unhandled type)")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main() -> None:
    print("--- MessagePack from scratch ---\n")

    # 1. Simple examples
    print("Encoding simple values:")
    examples = [
        (42, "int 42 (positive fixint, single byte)"),
        (-5, "int -5 (negative fixint, single byte)"),
        (300, "int 300 (uint16)"),
        (True, "bool True"),
        (None, "nil"),
        ("hello", "string 'hello' (fixstr)"),
        (b"\x89PNG", "binary (bin8 -- no base64!)"),
        ([1, 2, 3], "array [1,2,3]"),
        ({"a": 1}, "map {'a': 1}"),
    ]

    for val, desc in examples:
        encoded = msgpack_encode(val)
        decoded = msgpack_decode(encoded)
        print(f"  {desc}")
        print(f"    encoded: {_hex(encoded)}  ({len(encoded)} bytes)")
        print(f"    decoded: {decoded!r}")
        print()

    # 2. Encode a FoodDash Order
    print("\n--- Encoding a FoodDash Order ---\n")
    order = make_typical_order()
    order_dict = _prepare_for_msgpack(order.model_dump())
    encoded = msgpack_encode(order_dict)

    # Compare with JSON (mode="json" converts bytes to base64 strings automatically,
    # but some bytes aren't valid UTF-8, so we use the default serializer)
    import base64

    def _json_default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)

    json_bytes = json.dumps(order.model_dump(), default=_json_default).encode()

    print(f"  MessagePack (from scratch): {len(encoded):,} bytes")
    print(f"  JSON:                       {len(json_bytes):,} bytes")
    savings = (1 - len(encoded) / len(json_bytes)) * 100
    print(f"  Savings:                    {savings:.1f}%")

    # 3. Verify roundtrip
    decoded = msgpack_decode(encoded)
    assert decoded["id"] == order_dict["id"], "Roundtrip failed for id"
    assert decoded["status"] == order_dict["status"], "Roundtrip failed for status"
    print("\n  Roundtrip verification: PASSED")

    # 4. Compare with msgpack library (if available)
    try:
        import msgpack as msgpack_lib
        lib_encoded = msgpack_lib.packb(order_dict, use_bin_type=True)
        print(f"\n  msgpack library output:     {len(lib_encoded):,} bytes")
        if encoded == lib_encoded:
            print("  Our output matches the library exactly!")
        else:
            print(f"  Difference: {len(encoded) - len(lib_encoded):+d} bytes")
            print("  (Minor differences are expected due to int/float size choices)")
    except ImportError:
        print("\n  (msgpack library not installed, skipping comparison)")

    # 5. Byte-level annotation
    print("\n--- Byte-level annotation (first 200 bytes) ---\n")
    annotations = annotate_bytes(encoded, max_bytes=200)
    for line in annotations:
        print(f"  {line}")

    # 6. The key insight: binary data
    print("\n\n--- The Binary Data Story ---\n")
    thumbnail = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    mp_bytes = msgpack_encode(thumbnail)
    json_str = json.dumps(base64.b64encode(thumbnail).decode())
    print("  72-byte PNG thumbnail:")
    print(f"    MessagePack: {len(mp_bytes)} bytes (2 byte header + raw binary)")
    print(f"    JSON base64: {len(json_str)} bytes (base64 + quotes)")
    print(f"    Overhead:    JSON needs {len(json_str) - len(mp_bytes)} extra bytes ({(len(json_str)/len(mp_bytes) - 1)*100:.0f}% more)")
    print("    And base64 is a decode step JSON readers must know about!")


if __name__ == "__main__":
    main()
