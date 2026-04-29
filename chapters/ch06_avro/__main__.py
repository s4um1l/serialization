"""Chapter 06 -- Apache Avro: schema-driven encoding with automatic resolution.

Run with: uv run python -m chapters.ch06_avro
"""

from chapters.ch06_avro.avro_from_scratch import main as from_scratch_main
from chapters.ch06_avro.avro_lib import main as lib_main
from chapters.ch06_avro.schema_registry import main as registry_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 06 -- Apache Avro: Schema-Driven Encoding")
    print("=" * 70)

    print("\n\n>>> PART 1: Avro encoding from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: fastavro library & benchmarks\n")
    lib_main()

    print("\n\n>>> PART 3: Schema Registry & schema resolution\n")
    registry_main()


if __name__ == "__main__":
    main()
