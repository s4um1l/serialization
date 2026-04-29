"""Chapter 09 -- Schema Evolution: what breaks, what survives.

Run with: uv run python -m chapters.ch09_schema_evolution
"""

from chapters.ch09_schema_evolution.evolution_rules import main as rules_main
from chapters.ch09_schema_evolution.migration_demo import main as migration_main
from chapters.ch09_schema_evolution.compat_matrix import main as compat_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 09 -- Schema Evolution: Rules, Migration, Compatibility")
    print("=" * 70)

    print("\n\n>>> PART 1: Evolution Rules -- What Breaks, What Survives\n")
    rules_main()

    print("\n\n>>> PART 2: Migration Demo -- v1 -> v2 -> v3 Across Formats\n")
    migration_main()

    print("\n\n>>> PART 3: Compatibility Matrix & Schema Registry\n")
    compat_main()


if __name__ == "__main__":
    main()
