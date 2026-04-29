"""Chapter 07 -- Cap'n Proto: the wire format IS the memory format.

Run with: uv run python -m chapters.ch07_capnproto
"""

from chapters.ch07_capnproto.capnp_from_scratch import main as from_scratch_main
from chapters.ch07_capnproto.capnp_demo import main as demo_main
from chapters.ch07_capnproto.rpc_demo import main as rpc_main


def main() -> None:
    print("=" * 70)
    print("  CHAPTER 07 -- Cap'n Proto: Wire Format = Memory Format")
    print("=" * 70)

    print("\n\n>>> PART 1: Cap'n Proto from scratch\n")
    from_scratch_main()

    print("\n\n>>> PART 2: Cap'n Proto library demo + benchmarks\n")
    demo_main()

    print("\n\n>>> PART 3: RPC and promise pipelining\n")
    rpc_main()


if __name__ == "__main__":
    main()
