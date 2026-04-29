"""Chapter 01 — Plain Text / CSV

Run with:  uv run python -m chapters.ch01_plain_text_csv
"""

from __future__ import annotations


def main() -> None:
    # Import here to keep module-level clean
    from chapters.ch01_plain_text_csv.csv_from_scratch import main as scratch_main
    from chapters.ch01_plain_text_csv.csv_stdlib import main as stdlib_main
    from chapters.ch01_plain_text_csv.pain_points import main as pain_main

    scratch_main()
    print("\n")
    stdlib_main()
    print("\n")
    pain_main()


if __name__ == "__main__":
    main()
