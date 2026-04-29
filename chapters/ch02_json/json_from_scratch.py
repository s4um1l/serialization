"""Build a recursive JSON encoder and decoder byte-by-byte — NO json module.

Demonstrates exactly what JSON is: a UTF-8 text format with six data types,
recursive structure, and specific escape rules for strings.
"""

from __future__ import annotations

import base64
import json  # only for comparison at the end, NOT used in our encoder/decoder


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def _encode_string(s: str) -> str:
    """Encode a Python string as a JSON string with proper escapes."""
    parts = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == '"':
            parts.append('\\"')
        elif ch == '\\':
            parts.append('\\\\')
        elif ch == '\n':
            parts.append('\\n')
        elif ch == '\t':
            parts.append('\\t')
        elif ch == '\r':
            parts.append('\\r')
        elif ch == '\b':
            parts.append('\\b')
        elif ch == '\f':
            parts.append('\\f')
        elif cp < 0x20:
            # Other control characters -> \uXXXX
            parts.append(f'\\u{cp:04x}')
        else:
            parts.append(ch)
    parts.append('"')
    return ''.join(parts)


def json_encode(obj: object) -> str:
    """Recursively encode a Python object to a JSON string.

    Handles: str, int, float, bool, None, list, dict, bytes (-> base64).
    Does NOT use the json module.
    """
    if obj is None:
        return 'null'

    if isinstance(obj, bool):
        # Must check bool before int — bool is a subclass of int in Python
        return 'true' if obj else 'false'

    if isinstance(obj, int):
        return str(obj)

    if isinstance(obj, float):
        # Handle special floats
        if obj != obj:  # NaN
            return 'null'  # JSON has no NaN
        if obj == float('inf') or obj == float('-inf'):
            return 'null'  # JSON has no Infinity
        return repr(obj)

    if isinstance(obj, str):
        return _encode_string(obj)

    if isinstance(obj, bytes):
        # Encode as base64 with a marker prefix
        encoded = base64.b64encode(obj).decode('ascii')
        return _encode_string(f'$base64:{encoded}')

    if isinstance(obj, (list, tuple)):
        items = ', '.join(json_encode(item) for item in obj)
        return f'[{items}]'

    if isinstance(obj, dict):
        pairs = []
        for key, value in obj.items():
            key_str = str(key) if not isinstance(key, str) else key
            pairs.append(f'{_encode_string(key_str)}: {json_encode(value)}')
        return '{' + ', '.join(pairs) + '}'

    # Fall back: try to convert to string
    return _encode_string(str(obj))


# ---------------------------------------------------------------------------
# Decoder — recursive descent parser
# ---------------------------------------------------------------------------

class _JSONDecoder:
    """Recursive descent JSON parser."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _skip_whitespace(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in ' \t\n\r':
            self.pos += 1

    def _peek(self) -> str:
        self._skip_whitespace()
        if self.pos >= len(self.text):
            raise ValueError("Unexpected end of input")
        return self.text[self.pos]

    def _advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def _expect(self, ch: str) -> None:
        self._skip_whitespace()
        actual = self._advance()
        if actual != ch:
            raise ValueError(f"Expected {ch!r}, got {actual!r} at position {self.pos - 1}")

    def parse(self) -> object:
        value = self._parse_value()
        self._skip_whitespace()
        if self.pos < len(self.text):
            raise ValueError(f"Unexpected trailing content at position {self.pos}")
        return value

    def _parse_value(self) -> object:
        ch = self._peek()
        if ch == '"':
            return self._parse_string()
        elif ch == '{':
            return self._parse_object()
        elif ch == '[':
            return self._parse_array()
        elif ch == 't':
            return self._parse_true()
        elif ch == 'f':
            return self._parse_false()
        elif ch == 'n':
            return self._parse_null()
        elif ch == '-' or ch.isdigit():
            return self._parse_number()
        else:
            raise ValueError(f"Unexpected character {ch!r} at position {self.pos}")

    def _parse_string(self) -> str:
        self._expect('"')
        parts: list[str] = []
        while self.pos < len(self.text):
            ch = self._advance()
            if ch == '"':
                result = ''.join(parts)
                # Check for base64 marker
                if result.startswith('$base64:'):
                    return base64.b64decode(result[8:])
                return result
            elif ch == '\\':
                esc = self._advance()
                if esc == '"':
                    parts.append('"')
                elif esc == '\\':
                    parts.append('\\')
                elif esc == '/':
                    parts.append('/')
                elif esc == 'n':
                    parts.append('\n')
                elif esc == 't':
                    parts.append('\t')
                elif esc == 'r':
                    parts.append('\r')
                elif esc == 'b':
                    parts.append('\b')
                elif esc == 'f':
                    parts.append('\f')
                elif esc == 'u':
                    hex_str = self.text[self.pos:self.pos + 4]
                    self.pos += 4
                    parts.append(chr(int(hex_str, 16)))
                else:
                    raise ValueError(f"Unknown escape \\{esc}")
            else:
                parts.append(ch)
        raise ValueError("Unterminated string")

    def _parse_object(self) -> dict:
        self._expect('{')
        result: dict = {}
        if self._peek() == '}':
            self._advance()
            return result
        while True:
            key = self._parse_string()
            self._expect(':')
            value = self._parse_value()
            result[key] = value
            ch = self._peek()
            if ch == '}':
                self._advance()
                return result
            self._expect(',')

    def _parse_array(self) -> list:
        self._expect('[')
        result: list = []
        if self._peek() == ']':
            self._advance()
            return result
        while True:
            result.append(self._parse_value())
            ch = self._peek()
            if ch == ']':
                self._advance()
                return result
            self._expect(',')

    def _parse_number(self) -> int | float:
        self._skip_whitespace()
        start = self.pos
        if self.text[self.pos] == '-':
            self.pos += 1
        # Integer part
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        is_float = False
        # Fractional part
        if self.pos < len(self.text) and self.text[self.pos] == '.':
            is_float = True
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
        # Exponent
        if self.pos < len(self.text) and self.text[self.pos] in ('e', 'E'):
            is_float = True
            self.pos += 1
            if self.pos < len(self.text) and self.text[self.pos] in ('+', '-'):
                self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
        num_str = self.text[start:self.pos]
        if is_float:
            return float(num_str)
        return int(num_str)

    def _parse_true(self) -> bool:
        self._skip_whitespace()
        if self.text[self.pos:self.pos + 4] == 'true':
            self.pos += 4
            return True
        raise ValueError(f"Expected 'true' at position {self.pos}")

    def _parse_false(self) -> bool:
        self._skip_whitespace()
        if self.text[self.pos:self.pos + 5] == 'false':
            self.pos += 5
            return False
        raise ValueError(f"Expected 'false' at position {self.pos}")

    def _parse_null(self) -> None:
        self._skip_whitespace()
        if self.text[self.pos:self.pos + 4] == 'null':
            self.pos += 4
            return None
        raise ValueError(f"Expected 'null' at position {self.pos}")


def json_decode(text: str) -> object:
    """Parse a JSON string into Python objects using recursive descent."""
    return _JSONDecoder(text).parse()


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _count_structural_bytes(text: str) -> dict[str, int]:
    """Count structural vs data bytes in a JSON string."""
    structural = 0  # { } [ ] : ,
    quotes = 0
    whitespace = 0
    data = 0

    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            data += 1
            escape_next = False
            continue

        if in_string:
            if ch == '\\':
                escape_next = True
                data += 1
            elif ch == '"':
                quotes += 1
                in_string = False
            else:
                data += 1
        else:
            if ch in '{}[]:,':
                structural += 1
            elif ch == '"':
                quotes += 1
                in_string = True
            elif ch in ' \t\n\r':
                whitespace += 1
            else:
                data += 1

    return {
        'structural': structural,
        'quotes': quotes,
        'whitespace': whitespace,
        'data': data,
        'total': len(text),
    }


# ---------------------------------------------------------------------------
# Custom JSON encoder for stdlib comparison (handles bytes)
# ---------------------------------------------------------------------------

class _BytesEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            return f'$base64:{base64.b64encode(o).decode("ascii")}'
        return super().default(o)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    from shared.sample_data import make_typical_order

    order = make_typical_order()
    order_dict = order.model_dump()

    print("--- From-Scratch JSON Encoder ---\n")

    # Encode with our encoder
    our_json = json_encode(order_dict)
    print(f"Our encoder output length: {len(our_json):,} characters")
    print(f"First 200 chars:\n{our_json[:200]}...\n")

    # Encode with stdlib for comparison
    stdlib_json = json.dumps(order_dict, cls=_BytesEncoder)
    print(f"stdlib json.dumps length: {len(stdlib_json):,} characters")

    # Decode our JSON and verify round-trip
    decoded = json_decode(our_json)
    print(f"\nRound-trip decode successful: {isinstance(decoded, dict)}")
    print(f"Decoded order ID: {decoded.get('id')}")
    print(f"Decoded customer name: {decoded.get('customer', {}).get('name')}")
    print(f"Number of items: {len(decoded.get('items', []))}")

    # Verify our output parses with stdlib (for correctness check)
    try:
        json.loads(our_json)
        print("stdlib json.loads can parse our output: True")
    except json.JSONDecodeError as e:
        print(f"stdlib json.loads FAILED on our output: {e}")

    # Byte-level structure analysis
    print("\n--- Byte-Level Structure Analysis ---\n")
    counts = _count_structural_bytes(our_json)
    total = counts['total']
    print(f"Total characters:      {total:>8,}")
    print(f"  Structural ({{}}[]:,): {counts['structural']:>8,}  ({counts['structural']/total*100:5.1f}%)")
    print(f"  Quote chars (\"):     {counts['quotes']:>8,}  ({counts['quotes']/total*100:5.1f}%)")
    print(f"  Data bytes:          {counts['data']:>8,}  ({counts['data']/total*100:5.1f}%)")
    print(f"  Whitespace:          {counts['whitespace']:>8,}  ({counts['whitespace']/total*100:5.1f}%)")
    overhead = counts['structural'] + counts['quotes']
    print(f"\n  Syntax overhead:     {overhead:>8,}  ({overhead/total*100:5.1f}%) <- bytes that carry no data")

    # Show a small example to illustrate
    print("\n--- Small Example ---\n")
    small = {"name": "Burger", "price": 1299, "veggie": False}
    encoded_small = json_encode(small)
    print(f"Object:  {small}")
    print(f"JSON:    {encoded_small}")
    print(f"Length:  {len(encoded_small)} characters")
    decoded_small = json_decode(encoded_small)
    print(f"Decoded: {decoded_small}")
    print(f"Match:   {decoded_small == small}")


if __name__ == "__main__":
    main()
