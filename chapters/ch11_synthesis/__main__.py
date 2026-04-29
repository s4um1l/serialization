"""Chapter 11: Synthesis -- the grand finale.

Runs head-to-head benchmarks, then extrapolates to production scale.
"""

from chapters.ch11_synthesis.head_to_head import main as head_to_head_main
from chapters.ch11_synthesis.at_scale import main as at_scale_main


def main() -> None:
    # Phase 1: Head-to-head benchmarks across all formats and sizes
    all_results = head_to_head_main()

    # Phase 2: Extrapolate typical-order results to 1M msg/s
    # Use the "Typical" results if available
    typical_results = all_results.get("Typical", None) if all_results else None
    at_scale_main(benchmark_results=typical_results)


if __name__ == "__main__":
    main()
