"""Run all foundation demos."""

from chapters.ch00_foundations import memory_layout, endianness, alignment


def main() -> None:
    print()
    print("#" * 60)
    print("#  CHAPTER 00: FOUNDATIONS")
    print("#  Why you can't just send memory")
    print("#" * 60)
    print()

    print()
    print("~" * 60)
    print("  PART 1: MEMORY LAYOUT")
    print("~" * 60)
    print()
    memory_layout.main()

    print()
    print("~" * 60)
    print("  PART 2: ENDIANNESS")
    print("~" * 60)
    print()
    endianness.main()

    print()
    print("~" * 60)
    print("  PART 3: ALIGNMENT")
    print("~" * 60)
    print()
    alignment.main()


main()
