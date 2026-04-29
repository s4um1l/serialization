"""Chapter 04 -- Protocol Buffers: schema-driven binary serialization.

Run with: uv run python -m chapters.ch04_protobuf
"""

from chapters.ch04_protobuf.proto_from_scratch import main as from_scratch_main
from chapters.ch04_protobuf.proto_lib import main as proto_lib_main
from chapters.ch04_protobuf.schema_evolution import main as schema_evolution_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 04 -- Protocol Buffers")
    print("=" * 70)

    print("\n\n>>> PART 1: Protobuf wire format from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: Library comparison & benchmarks\n")
    proto_lib_main()

    print("\n\n>>> PART 3: Schema evolution\n")
    schema_evolution_main()


if __name__ == "__main__":
    main()
