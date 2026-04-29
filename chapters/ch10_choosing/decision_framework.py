"""Interactive decision matrix for choosing a serialization format.

Scores 8 formats on 8 criteria (1-5 scale), then applies weighted
requirements to produce ranked recommendations. Run standalone or
import recommend() for programmatic use.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Criteria definitions
# ---------------------------------------------------------------------------

CRITERIA = [
    "human_readability",
    "wire_size",
    "encode_speed",
    "decode_speed",
    "schema_enforcement",
    "schema_evolution",
    "ecosystem_tooling",
    "browser_compatibility",
]

CRITERIA_DESCRIPTIONS = {
    "human_readability": "Can a human read and edit the encoded output without tools?",
    "wire_size": "How compact is the encoded payload on the wire?",
    "encode_speed": "How fast can data be serialized into the format?",
    "decode_speed": "How fast can encoded data be deserialized?",
    "schema_enforcement": "Does the format enforce a schema contract at encode/decode time?",
    "schema_evolution": "How well does the format handle schema changes over time?",
    "ecosystem_tooling": "How rich is the ecosystem of libraries, tools, and community support?",
    "browser_compatibility": "How well does the format work in browser/JavaScript environments?",
}


# ---------------------------------------------------------------------------
# Format scores with rationale
# ---------------------------------------------------------------------------

@dataclass
class FormatScore:
    """A single format's score on a single criterion."""
    score: int          # 1-5
    rationale: str


# fmt: off
FORMAT_SCORES: dict[str, dict[str, FormatScore]] = {
    "CSV": {
        "human_readability":    FormatScore(5, "Plain text, columns separated by commas -- readable in any text editor or spreadsheet"),
        "wire_size":            FormatScore(2, "No type tags, but field names repeated per row (header) and no compression; verbose for nested data"),
        "encode_speed":         FormatScore(4, "String concatenation is fast; no schema processing overhead"),
        "decode_speed":         FormatScore(3, "Line-by-line parsing is simple but string-to-type conversion adds overhead"),
        "schema_enforcement":   FormatScore(1, "No schema -- columns are positional, types are implicit, anything goes"),
        "schema_evolution":     FormatScore(1, "Adding/removing columns breaks positional readers; no built-in versioning"),
        "ecosystem_tooling":    FormatScore(4, "Universal support: Excel, pandas, databases, every language has a CSV parser"),
        "browser_compatibility": FormatScore(3, "Browsers can fetch CSV text; no native parsing API but libraries exist"),
    },
    "JSON": {
        "human_readability":    FormatScore(5, "The lingua franca of human-readable data exchange; pretty-printable"),
        "wire_size":            FormatScore(1, "Field names in every message, string-encoded numbers, base64 for binary -- the most verbose format"),
        "encode_speed":         FormatScore(3, "Reflection-based encoding; faster with orjson/ujson but still string-heavy"),
        "decode_speed":         FormatScore(2, "String parsing is inherently slow; must parse quoted keys, handle escapes, convert types"),
        "schema_enforcement":   FormatScore(1, "No schema -- JSON Schema exists but is opt-in validation, not wire enforcement"),
        "schema_evolution":     FormatScore(3, "Self-describing keys help; unknown fields survive; but no formal evolution rules"),
        "ecosystem_tooling":    FormatScore(5, "The most supported format in existence: every language, tool, API, and browser"),
        "browser_compatibility": FormatScore(5, "Native JSON.parse/stringify in every browser; the default format for web APIs"),
    },
    "MessagePack": {
        "human_readability":    FormatScore(1, "Binary format -- not readable without tooling"),
        "wire_size":            FormatScore(3, "Compact type tags and no field name overhead for small values; but still self-describing"),
        "encode_speed":         FormatScore(4, "Binary encoding without string conversion; fast for typed data"),
        "decode_speed":         FormatScore(3, "Type-tagged binary is faster than JSON string parsing but still self-describing"),
        "schema_enforcement":   FormatScore(1, "No schema -- same as JSON but binary; anything the encoder writes, the decoder accepts"),
        "schema_evolution":     FormatScore(1, "Same problems as JSON but without human readability for debugging changes"),
        "ecosystem_tooling":    FormatScore(3, "Good library support in major languages; less universal than JSON"),
        "browser_compatibility": FormatScore(1, "No native browser support; requires a JavaScript library to decode"),
    },
    "CBOR": {
        "human_readability":    FormatScore(1, "Binary format -- requires tooling to inspect"),
        "wire_size":            FormatScore(3, "Similar to MessagePack; efficient type encoding but self-describing overhead"),
        "encode_speed":         FormatScore(4, "Efficient binary encoding with well-defined type mappings"),
        "decode_speed":         FormatScore(3, "Tag-based decoding is systematic but still per-field processing"),
        "schema_enforcement":   FormatScore(1, "CDDL schemas exist but are rarely used for wire enforcement in practice"),
        "schema_evolution":     FormatScore(1, "Self-describing like JSON; no formal evolution machinery"),
        "ecosystem_tooling":    FormatScore(2, "IETF standard with decent support but smaller community than JSON or Protobuf"),
        "browser_compatibility": FormatScore(1, "No native browser support; niche JavaScript libraries exist"),
    },
    "Protobuf": {
        "human_readability":    FormatScore(1, "Binary wire format -- completely opaque without the .proto schema file"),
        "wire_size":            FormatScore(5, "Field tags instead of names; varint encoding; zero-value omission -- extremely compact"),
        "encode_speed":         FormatScore(4, "Generated code with no reflection; direct field-to-byte mapping"),
        "decode_speed":         FormatScore(4, "Tag-based dispatch with generated code; very efficient for structured data"),
        "schema_enforcement":   FormatScore(5, "Strong schema contract via .proto files; generated code rejects unknown types at compile time"),
        "schema_evolution":     FormatScore(4, "Field numbers enable safe addition/deprecation; well-defined compatibility rules"),
        "ecosystem_tooling":    FormatScore(4, "Google-backed; gRPC ecosystem; protoc compiler; support in all major languages"),
        "browser_compatibility": FormatScore(3, "grpc-web exists; protobuf.js works; but not native -- requires code generation or libraries"),
    },
    "FlatBuffers": {
        "human_readability":    FormatScore(1, "Binary format with vtable indirection -- impossible to read without tools"),
        "wire_size":            FormatScore(4, "Compact with vtable sharing; padding for alignment adds some overhead vs Protobuf"),
        "encode_speed":         FormatScore(4, "Builder pattern is fast but requires careful construction order"),
        "decode_speed":         FormatScore(5, "Zero-copy: fields accessed directly from the buffer with pointer arithmetic -- no deserialization"),
        "schema_enforcement":   FormatScore(4, "Strong schema via .fbs files; generated accessors enforce types"),
        "schema_evolution":     FormatScore(3, "Field addition safe; but vtable-based layout has more constraints than Protobuf"),
        "ecosystem_tooling":    FormatScore(3, "Google-backed but smaller community; fewer language bindings than Protobuf"),
        "browser_compatibility": FormatScore(1, "JavaScript support exists but zero-copy benefits are less relevant in browsers"),
    },
    "Avro": {
        "human_readability":    FormatScore(1, "Binary wire format -- schema required for any interpretation"),
        "wire_size":            FormatScore(5, "No field tags or names on the wire -- just values in schema order; maximally compact"),
        "encode_speed":         FormatScore(4, "Schema-driven sequential writes; very efficient for columnar/batch data"),
        "decode_speed":         FormatScore(4, "Schema resolution enables efficient sequential reads; no per-field tag parsing"),
        "schema_enforcement":   FormatScore(4, "Schema required for read and write; JSON-based schema definition"),
        "schema_evolution":     FormatScore(5, "Reader/writer schema resolution is the gold standard; designed for schema evolution"),
        "ecosystem_tooling":    FormatScore(5, "Dominant in Hadoop/Kafka ecosystem; Confluent Schema Registry; native Spark/Hive/Flink support; strong Java/Python libraries"),
        "browser_compatibility": FormatScore(1, "No meaningful browser support; primarily a server-side and data pipeline format"),
    },
    "Cap'n Proto": {
        "human_readability":    FormatScore(1, "Binary format with pointer-based layout -- requires tooling"),
        "wire_size":            FormatScore(4, "Compact but uses fixed-width fields and padding for zero-copy alignment"),
        "encode_speed":         FormatScore(5, "In-place construction: the in-memory layout IS the wire format -- encode is a no-op"),
        "decode_speed":         FormatScore(5, "Zero-copy like FlatBuffers: no deserialization step, direct pointer access"),
        "schema_enforcement":   FormatScore(4, "Strong schema via .capnp files; generated code enforces structure"),
        "schema_evolution":     FormatScore(4, "Field ordinals enable safe evolution; similar to Protobuf's approach"),
        "ecosystem_tooling":    FormatScore(2, "Smaller community; fewer language bindings; less production adoption than Protobuf"),
        "browser_compatibility": FormatScore(1, "Minimal browser support; designed for systems programming use cases"),
    },
}
# fmt: on

FORMATS = list(FORMAT_SCORES.keys())


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

def recommend(
    requirements: dict[str, int],
) -> list[tuple[str, float, dict[str, float]]]:
    """Rank formats by weighted score against requirements.

    Args:
        requirements: Mapping of criterion -> weight (1-5). Criteria not
            listed are treated as weight 0 (don't care).

    Returns:
        List of (format_name, total_score, breakdown) tuples sorted by
        score descending. breakdown maps criterion -> weighted contribution.
    """
    results: list[tuple[str, float, dict[str, float]]] = []

    for fmt_name, scores in FORMAT_SCORES.items():
        total = 0.0
        breakdown: dict[str, float] = {}
        for criterion, weight in requirements.items():
            if criterion not in scores:
                continue
            contribution = scores[criterion].score * weight
            breakdown[criterion] = contribution
            total += contribution
        results.append((fmt_name, total, breakdown))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, int | str]] = {
    "Public REST API": {
        "description": "Browser-facing API serving the FoodDash customer app. "
                       "Needs to work in every browser, be debuggable in DevTools, "
                       "and have broad ecosystem support.",
        "browser_compatibility": 5,
        "human_readability": 4,
        "ecosystem_tooling": 4,
        "schema_evolution": 2,
        "wire_size": 1,
        "encode_speed": 1,
        "decode_speed": 1,
        "schema_enforcement": 2,
    },
    "Internal Microservice RPC": {
        "description": "gRPC calls between FoodDash microservices (order-service "
                       "to kitchen-service, payment-service, etc.). Need strong "
                       "contracts and compact payloads at 1M msg/s.",
        "wire_size": 5,
        "encode_speed": 4,
        "decode_speed": 4,
        "schema_enforcement": 5,
        "schema_evolution": 3,
        "ecosystem_tooling": 3,
        "human_readability": 1,
        "browser_compatibility": 1,
    },
    "Data Pipeline / Kafka": {
        "description": "Events flowing through Kafka into the data lake. Schema "
                       "evolves over months/years; readers and writers are decoupled "
                       "and deployed independently.",
        "schema_evolution": 5,
        "wire_size": 4,
        "schema_enforcement": 3,
        "encode_speed": 2,
        "decode_speed": 2,
        "ecosystem_tooling": 4,
        "human_readability": 1,
        "browser_compatibility": 1,
    },
    "Latency-Critical Hot Path": {
        "description": "The driver-matching engine processes location pings in "
                       "real time. Every microsecond of decode latency adds up. "
                       "Zero-copy access is the goal.",
        "decode_speed": 5,
        "encode_speed": 4,
        "wire_size": 3,
        "schema_enforcement": 2,
        "schema_evolution": 1,
        "ecosystem_tooling": 1,
        "human_readability": 0,
        "browser_compatibility": 0,
    },
    "Quick Data Export": {
        "description": "One-off data exports for analysts, partner integrations, "
                       "or debugging. Needs to be openable in Excel or a text editor "
                       "without special tools.",
        "human_readability": 5,
        "ecosystem_tooling": 5,
        "browser_compatibility": 2,
        "wire_size": 1,
        "encode_speed": 1,
        "decode_speed": 1,
        "schema_enforcement": 1,
        "schema_evolution": 1,
    },
}


def _print_scenario(name: str, scenario: dict) -> None:
    """Print scored results for a single scenario."""
    description = scenario.get("description", "")
    requirements = {k: v for k, v in scenario.items() if k != "description"}

    print(f"\n{'─' * 70}")
    print(f"  Scenario: {name}")
    print(f"{'─' * 70}")
    if description:
        # Word-wrap description at ~68 chars
        words = description.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 68:
                print(line)
                line = "  " + word
            else:
                line += " " + word if line.strip() else "  " + word
        if line.strip():
            print(line)
        print()

    # Print weights
    print("  Weights:")
    for criterion in CRITERIA:
        weight = requirements.get(criterion, 0)
        bar = "█" * weight + "░" * (5 - weight)
        label = criterion.replace("_", " ").title()
        print(f"    {label:<24} {bar} ({weight})")
    print()

    # Get and print recommendations
    ranked = recommend(requirements)
    max_score = ranked[0][1] if ranked else 1

    print("  Ranked Results:")
    print(f"  {'Format':<16} {'Score':>7} {'Bar':<30}")
    print(f"  {'─' * 55}")

    for i, (fmt_name, score, breakdown) in enumerate(ranked):
        bar_len = int((score / max_score) * 25) if max_score > 0 else 0
        bar = "▓" * bar_len + "░" * (25 - bar_len)
        marker = " ◄ RECOMMENDED" if i == 0 else ""
        print(f"  {fmt_name:<16} {score:>7.0f} {bar}{marker}")

    # Show top pick rationale
    top_name, top_score, top_breakdown = ranked[0]
    print(f"\n  Why {top_name}?")
    top_criteria = sorted(top_breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
    for criterion, contrib in top_criteria:
        raw_score = FORMAT_SCORES[top_name][criterion].score
        weight = requirements.get(criterion, 0)
        rationale = FORMAT_SCORES[top_name][criterion].rationale
        label = criterion.replace("_", " ").title()
        print(f"    {label}: {raw_score}/5 x weight {weight} = {contrib:.0f}")
        print(f"      {rationale}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all demo scenarios and print the decision framework."""

    # Print the full score matrix first
    print("SERIALIZATION FORMAT DECISION MATRIX")
    print("=" * 70)
    print()
    print("Scores are on a 1-5 scale:")
    print("  1 = Poor/None   2 = Below average   3 = Average")
    print("  4 = Good         5 = Excellent")
    print()

    # Header
    hdr_fmt = f"  {'Criterion':<24}"
    for fmt in FORMATS:
        hdr_fmt += f" {fmt:>8}"
    print(hdr_fmt)
    print("  " + "─" * (24 + 9 * len(FORMATS)))

    # Rows
    for criterion in CRITERIA:
        label = criterion.replace("_", " ").title()
        row = f"  {label:<24}"
        for fmt in FORMATS:
            score = FORMAT_SCORES[fmt][criterion].score
            row += f" {score:>8}"
        print(row)

    print()

    # Run each scenario
    for name, scenario in SCENARIOS.items():
        _print_scenario(name, scenario)

    # Summary
    print(f"\n\n{'=' * 70}")
    print("  SUMMARY: THE RIGHT FORMAT FOR EACH BOUNDARY")
    print(f"{'=' * 70}")
    print()
    print("  Browser boundary          -> JSON   (universal, debuggable)")
    print("  Service-to-service RPC    -> Protobuf (compact, typed, gRPC)")
    print("  Data pipeline / Kafka     -> Avro   (schema evolution, compact)")
    print("  Latency-critical hot path -> FlatBuffers / Cap'n Proto (zero-copy)")
    print("  Quick export / debugging  -> CSV or JSON (human-readable)")
    print()
    print("  The real-world answer: use MULTIPLE formats.")
    print("  Each boundary has different constraints.")
    print("  The API gateway translates between them.")
    print()


if __name__ == "__main__":
    main()
