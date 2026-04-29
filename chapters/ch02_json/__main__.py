"""Chapter 02 — JSON: the lingua franca of web APIs.

Run with: uv run python -m chapters.ch02_json
"""

from chapters.ch02_json.json_from_scratch import main as from_scratch_main
from chapters.ch02_json.json_stdlib import main as stdlib_main
from chapters.ch02_json.pain_points import main as pain_points_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 02 — JSON")
    print("=" * 70)

    print("\n\n>>> PART 1: JSON from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: JSON stdlib (+ orjson) benchmarks\n")
    stdlib_main()

    print("\n\n>>> PART 3: Pain points\n")
    pain_points_main()


if __name__ == "__main__":
    main()
