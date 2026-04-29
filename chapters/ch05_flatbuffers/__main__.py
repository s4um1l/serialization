"""Chapter 05 -- FlatBuffers: zero-copy deserialization.

Run with: uv run python -m chapters.ch05_flatbuffers
"""

from chapters.ch05_flatbuffers.flatbuf_from_scratch import main as from_scratch_main
from chapters.ch05_flatbuffers.flatbuf_demo import main as demo_main
from chapters.ch05_flatbuffers.zero_copy_proof import main as proof_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 05 -- FlatBuffers: Zero-Copy Deserialization")
    print("=" * 70)

    print("\n\n>>> PART 1: FlatBuffers from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: FlatBuffers library demo + benchmarks\n")
    demo_main()

    print("\n\n>>> PART 3: Zero-copy proof (tracemalloc)\n")
    proof_main()


if __name__ == "__main__":
    main()
