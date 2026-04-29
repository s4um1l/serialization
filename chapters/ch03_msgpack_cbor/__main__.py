"""Chapter 03 -- MessagePack / CBOR: binary JSON.

Run with: uv run python -m chapters.ch03_msgpack_cbor
"""

from chapters.ch03_msgpack_cbor.msgpack_from_scratch import main as from_scratch_main
from chapters.ch03_msgpack_cbor.msgpack_lib import main as msgpack_lib_main
from chapters.ch03_msgpack_cbor.cbor_lib import main as cbor_lib_main
from chapters.ch03_msgpack_cbor.pain_points import main as pain_points_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 03 -- MessagePack / CBOR")
    print("=" * 70)

    print("\n\n>>> PART 1: MessagePack from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: MessagePack library benchmarks\n")
    msgpack_lib_main()

    print("\n\n>>> PART 3: CBOR comparison\n")
    cbor_lib_main()

    print("\n\n>>> PART 4: Pain points\n")
    pain_points_main()


if __name__ == "__main__":
    main()
