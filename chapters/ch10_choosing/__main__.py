"""Chapter 10 -- Choosing a Format: the decision framework.

Run with: uv run python -m chapters.ch10_choosing
"""

from chapters.ch10_choosing.decision_framework import main as framework_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 10 -- Choosing a Format: Decision Framework")
    print("=" * 70)

    print("\n\n>>> Decision Framework -- Weighted Scoring Across 5 Scenarios\n")
    framework_main()


if __name__ == "__main__":
    main()
