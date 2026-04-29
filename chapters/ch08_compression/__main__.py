"""Chapter 08: Compression — run all demos.

Usage:
    uv run python -m chapters.ch08_compression
"""

from __future__ import annotations


def main() -> None:
    print("\n" + "#" * 80)
    print("#" + " " * 78 + "#")
    print("#" + "  CHAPTER 08: COMPRESSION".center(78) + "#")
    print("#" + "  Squeezing bytes out of serialized data".center(78) + "#")
    print("#" + " " * 78 + "#")
    print("#" * 80 + "\n")

    # --- Part 1: Compression basics ---
    print("\n" + "~" * 80)
    print("  PART 1: COMPRESSION BASICS")
    print("~" * 80 + "\n")
    from chapters.ch08_compression.compression_basics import main as basics_main
    basics_main()

    # --- Part 2: Format x Compression matrix ---
    print("\n\n" + "~" * 80)
    print("  PART 2: FORMAT x COMPRESSION MATRIX")
    print("~" * 80 + "\n")
    from chapters.ch08_compression.format_plus_compression import main as matrix_main
    matrix_main()

    # --- Part 3: Dictionary compression ---
    print("\n\n" + "~" * 80)
    print("  PART 3: DICTIONARY COMPRESSION")
    print("~" * 80 + "\n")
    from chapters.ch08_compression.dictionary_compression import main as dict_main
    dict_main()

    print("\n" + "#" * 80)
    print("  Chapter 08 complete.")
    print("  Next: Chapter 09 -- Schema Evolution")
    print("#" * 80 + "\n")


if __name__ == "__main__":
    main()
