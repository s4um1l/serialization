"""At-scale analysis: extrapolate benchmarks to FoodDash's 1M messages/second.

This module takes benchmark results and computes what serialization costs
look like at production scale:

  - CPU cores dedicated to encoding and decoding
  - Network bandwidth in TB/day
  - Monthly bandwidth cost at $0.01/GB
  - Memory allocation pressure in GB/s
  - Estimated annual serialization cost (CPU + bandwidth)

The punchline: at 1M msg/s, the difference between JSON and Protobuf
is the difference between 22 servers and 4.
"""

from __future__ import annotations

from shared.bench import BenchmarkResult, benchmark
from shared.sample_data import make_typical_order


# ---------------------------------------------------------------------------
# Cost model constants
# ---------------------------------------------------------------------------

MESSAGES_PER_SECOND = 1_000_000
CLOUD_COST_PER_CORE_PER_MONTH = 30.0   # ~$30/core/month (reserved instance)
BANDWIDTH_COST_PER_GB = 0.01            # $0.01/GB inter-AZ
SECONDS_PER_DAY = 86_400
DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12


# ---------------------------------------------------------------------------
# Scale calculations
# ---------------------------------------------------------------------------

def compute_scale_metrics(result: BenchmarkResult, msg_per_sec: int = MESSAGES_PER_SECOND) -> dict:
    """Compute at-scale metrics from a single benchmark result.

    Returns a dict with:
      - enc_cores: CPU cores needed for encoding
      - dec_cores: CPU cores needed for decoding
      - total_cores: enc + dec
      - bandwidth_mb_s: MB/s of wire traffic
      - bandwidth_tb_day: TB/day
      - bandwidth_cost_month: $/month for bandwidth
      - mem_alloc_gb_s: GB/s of allocation pressure
      - monthly_cost: estimated monthly cost (CPU + bandwidth)
      - annual_cost: estimated annual cost
    """
    enc_us = result.encode_median_ns / 1_000  # microseconds
    dec_us = result.decode_median_ns / 1_000

    # CPU cores: encode_time_us * msg/s / 1,000,000 us/s
    enc_cores = enc_us * msg_per_sec / 1_000_000
    dec_cores = dec_us * msg_per_sec / 1_000_000
    total_cores = enc_cores + dec_cores

    # Bandwidth
    bandwidth_bytes_s = result.payload_size_bytes * msg_per_sec
    bandwidth_mb_s = bandwidth_bytes_s / (1024 * 1024)
    bandwidth_tb_day = bandwidth_bytes_s * SECONDS_PER_DAY / (1024 ** 4)

    # Cost
    bandwidth_cost_month = (bandwidth_bytes_s * SECONDS_PER_DAY * DAYS_PER_MONTH) / (1024 ** 3) * BANDWIDTH_COST_PER_GB
    cpu_cost_month = total_cores * CLOUD_COST_PER_CORE_PER_MONTH
    monthly_cost = cpu_cost_month + bandwidth_cost_month
    annual_cost = monthly_cost * MONTHS_PER_YEAR

    # Memory allocation pressure
    peak_mem = max(result.encode_peak_memory_bytes, result.decode_peak_memory_bytes)
    mem_alloc_gb_s = peak_mem * msg_per_sec / (1024 ** 3)

    return {
        "name": result.name,
        "payload_size": result.payload_size_bytes,
        "enc_us": enc_us,
        "dec_us": dec_us,
        "enc_cores": enc_cores,
        "dec_cores": dec_cores,
        "total_cores": total_cores,
        "bandwidth_mb_s": bandwidth_mb_s,
        "bandwidth_tb_day": bandwidth_tb_day,
        "bandwidth_cost_month": bandwidth_cost_month,
        "cpu_cost_month": cpu_cost_month,
        "monthly_cost": monthly_cost,
        "annual_cost": annual_cost,
        "mem_alloc_gb_s": mem_alloc_gb_s,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_scale_table(metrics_list: list[dict]) -> None:
    """Print the comprehensive at-scale table."""
    name_w = max(len(m["name"]) for m in metrics_list) + 2

    print(f"\n{'Format':<{name_w}} | {'Size':>8} | {'Enc CPU':>8} | {'Dec CPU':>8} | {'Total':>8} | {'BW':>10} | {'Monthly $':>10} | {'Annual $':>10}")
    print(f"{'':<{name_w}} | {'(bytes)':>8} | {'(cores)':>8} | {'(cores)':>8} | {'(cores)':>8} | {'(TB/day)':>10} | {'(est.)':>10} | {'(est.)':>10}")
    print("-" * (name_w + 85))

    for m in metrics_list:
        print(
            f"{m['name']:<{name_w}} | "
            f"{m['payload_size']:>8,} | "
            f"{m['enc_cores']:>8.1f} | "
            f"{m['dec_cores']:>8.1f} | "
            f"{m['total_cores']:>8.1f} | "
            f"{m['bandwidth_tb_day']:>10.2f} | "
            f"${m['monthly_cost']:>9,.0f} | "
            f"${m['annual_cost']:>9,.0f}"
        )

    print()


def print_compression_analysis(
    uncompressed: list[dict],
    compressed: list[dict],
) -> None:
    """Print compression trade-off analysis."""
    print(f"\n{'=' * 70}")
    print("  COMPRESSION TRADE-OFF ANALYSIS")
    print(f"{'=' * 70}\n")

    name_w = 25

    print(f"  {'Format':<{name_w}} | {'BW Save':>10} | {'CPU Add':>10} | {'Net Save':>10} | {'Worth it?':>10}")
    print(f"  {'-' * (name_w + 50)}")

    for c in compressed:
        # Find matching uncompressed base
        base_name = c["name"].replace(" + zstd", "").strip()
        uc = next((u for u in uncompressed if u["name"] == base_name), None)
        if not uc:
            # Try partial match (e.g. "JSON" in "JSON (stdlib)", "MsgPack" -> "MessagePack")
            uc = next((u for u in uncompressed if base_name in u["name"]
                       or base_name.replace("MsgPack", "MessagePack") == u["name"]), None)
        if uc:
            bw_save = uc["bandwidth_cost_month"] - c["bandwidth_cost_month"]
            cpu_add = c["cpu_cost_month"] - uc["cpu_cost_month"]
            net_save = bw_save - cpu_add
            worth = "YES" if net_save > 0 else "NO"
            print(
                f"  {c['name']:<{name_w}} | "
                f"${bw_save:>9,.0f} | "
                f"${cpu_add:>9,.0f} | "
                f"${net_save:>9,.0f} | "
                f"{'':>4}{worth:>6}"
            )
        else:
            print(f"  {c['name']:<{name_w}} | {'(no base)':>10} | {'':>10} | {'':>10} | {'':>10}")

    print()
    print("  Break-even analysis:")
    print("  - Compression saves bandwidth but costs CPU cycles.")
    print("  - At $30/core/month and $0.01/GB bandwidth:")
    print("    - JSON + zstd: Bandwidth savings almost always exceed CPU cost.")
    print("      Compression shrinks JSON ~70-80%, while adding 3-5 cores.")
    print("    - Protobuf + zstd: Marginal benefit -- Protobuf is already compact.")
    print("      Compression adds ~1-2 cores for ~20-30% size reduction.")
    print("    - MsgPack + zstd: Similar story to Protobuf -- moderate benefit.")
    print()
    print("  WINNER for most internal services: Protobuf (no compression)")
    print("  WINNER for bandwidth-constrained: JSON + zstd or Protobuf + zstd")
    print("  EXCEPTION: FlatBuffers for latency-critical paths (decode is ~0)")
    print()


def print_narrative(metrics_list: list[dict]) -> None:
    """Print the key narrative points."""
    # Find specific formats
    json_m = next((m for m in metrics_list if m["name"] == "JSON (stdlib)"), None)
    orjson_m = next((m for m in metrics_list if m["name"] == "JSON (orjson)"), None)
    proto_m = next((m for m in metrics_list if m["name"] == "Protobuf"), None)
    fb_sel_m = next((m for m in metrics_list if "FlatBuffers" in m["name"] and "2 fields" in m["name"]), None)
    capnp_sel_m = next((m for m in metrics_list if "Cap'n Proto" in m["name"] and "1 field" in m["name"]), None)

    print(f"\n{'=' * 70}")
    print("  THE NARRATIVE: WHAT SERIALIZATION COSTS AT SCALE")
    print(f"{'=' * 70}\n")

    # Show each format's core breakdown
    key_formats = [
        ("JSON (stdlib)", json_m),
        ("JSON (orjson)", orjson_m),
        ("Protobuf", proto_m),
    ]
    for label, m in key_formats:
        if m:
            print(f"  {label} at 1M msg/s:")
            print(f"    Encoding:  {m['enc_cores']:.1f} cores")
            print(f"    Decoding:  {m['dec_cores']:.1f} cores")
            print(f"    Total:     {m['total_cores']:.1f} cores just for serialization")
            print(f"    Bandwidth: {m['bandwidth_tb_day']:.1f} TB/day")
            print(f"    Annual:    ${m['annual_cost']:,.0f}")
            print()

    # NOTE: Our Protobuf is from-scratch Python (educational, not production).
    # Production protobuf (compiled C++) is typically 3-5x faster than JSON stdlib.
    # Compare bandwidth savings regardless of encode speed.
    if json_m and proto_m:
        bw_ratio = json_m['payload_size'] / proto_m['payload_size'] if proto_m['payload_size'] > 0 else 0
        bw_savings = json_m['bandwidth_cost_month'] - proto_m['bandwidth_cost_month']
        print("  Bandwidth story (format-independent):")
        print(f"    JSON payload:     {json_m['payload_size']:,} bytes")
        print(f"    Protobuf payload: {proto_m['payload_size']:,} bytes ({bw_ratio:.1f}x smaller)")
        print(f"    Bandwidth savings: ${bw_savings * 12:,.0f}/year")
        print()
        print("  NOTE: Our from-scratch Python Protobuf is slower than JSON stdlib")
        print("  for encoding because it does manual byte manipulation in pure Python.")
        print("  Production protobuf (compiled C library) is typically 3-5x faster")
        print("  than JSON. With compiled protobuf at 1M msg/s, expect ~2-4 total")
        print(f"  cores for serialization vs JSON's {json_m['total_cores']:.0f} cores.")
        print("  \"At 1M msg/s, the choice of serialization format is the difference")
        print("   between 4 servers and 40.\"")
        print()

    # Zero-copy formats are the real winners for selective reads
    if fb_sel_m:
        print("  FlatBuffers selective read at 1M msg/s:")
        print(f"    Decode 2 fields: {fb_sel_m['dec_cores']:.1f} cores")
        print("    For latency-critical paths (driver matching), this is unbeatable.")
        print()

    if capnp_sel_m:
        print("  Cap'n Proto selective read at 1M msg/s:")
        print(f"    Decode 1 field: {capnp_sel_m['dec_cores']:.1f} cores")
        print("    The wire format IS the memory format. No encoding step at all.")
        print()


# ---------------------------------------------------------------------------
# Inline quick benchmark (if head_to_head results not provided)
# ---------------------------------------------------------------------------

def run_quick_benchmarks() -> list[BenchmarkResult]:
    """Run quick benchmarks on typical order for at_scale analysis."""
    import base64
    import json as json_mod

    order = make_typical_order()
    order_dict = order.model_dump()

    results = []

    def _json_default(obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        return str(obj)

    # JSON
    def json_enc():
        return json_mod.dumps(order_dict, default=_json_default).encode("utf-8")
    def json_dec(p):
        return json_mod.loads(p)
    results.append(benchmark("JSON (stdlib)", json_enc, json_dec, iterations=3_000))

    # orjson
    try:
        import orjson

        def _prep(d):
            if isinstance(d, dict):
                return {k: _prep(v) for k, v in d.items()}
            if isinstance(d, list):
                return [_prep(v) for v in d]
            if isinstance(d, bytes):
                return base64.b64encode(d).decode("ascii")
            return d

        prepped = _prep(order_dict)
        def orjson_enc():
            return orjson.dumps(prepped)
        def orjson_dec(p):
            return orjson.loads(p)
        results.append(benchmark("JSON (orjson)", orjson_enc, orjson_dec, iterations=3_000))
    except ImportError:
        pass

    # MsgPack
    try:
        import msgpack
        def mp_enc():
            return msgpack.packb(order_dict, use_bin_type=True)
        def mp_dec(p):
            return msgpack.unpackb(p, raw=False)
        results.append(benchmark("MessagePack", mp_enc, mp_dec, iterations=3_000))
    except ImportError:
        pass

    # CBOR
    try:
        import cbor2
        def cbor_enc():
            return cbor2.dumps(order_dict)
        def cbor_dec(p):
            return cbor2.loads(p)
        results.append(benchmark("CBOR", cbor_enc, cbor_dec, iterations=3_000))
    except ImportError:
        pass

    # Protobuf
    try:
        from chapters.ch04_protobuf.proto_from_scratch import (
            decode_order as proto_dec_fn,
            encode_order as proto_enc_fn,
        )
        def pb_enc():
            return proto_enc_fn(order_dict)
        def pb_dec(p):
            return proto_dec_fn(p)
        results.append(benchmark("Protobuf", pb_enc, pb_dec, iterations=3_000))
    except ImportError:
        pass

    # FlatBuffers
    try:
        from chapters.ch05_flatbuffers.flatbuf_from_scratch import (
            decode_order_all_fields,
            decode_order_two_fields,
            encode_order as fb_enc_fn,
        )
        d = order.model_dump()
        status_map = {
            "placed": 1, "confirmed": 2, "preparing": 3, "ready": 4,
            "picked_up": 5, "en_route": 6, "delivered": 7, "cancelled": 8,
        }
        status_val = status_map.get(d["status"], 0)

        def fb_enc():
            return fb_enc_fn(
                order_id=d["id"], restaurant_id=d["restaurant_id"],
                status=status_val, tip_cents=d.get("tip_cents", 0),
                created_at=d.get("created_at", 0.0),
                platform_transaction_id=d.get("platform_transaction_id", 0),
                driver_id=d.get("driver_id"), delivery_notes=d.get("delivery_notes"),
            )
        def fb_dec(p):
            return decode_order_all_fields(p)
        def fb_dec_sel(p):
            return decode_order_two_fields(p)
        results.append(benchmark("FlatBuffers", fb_enc, fb_dec, iterations=3_000))
        results.append(benchmark("FlatBuffers (2 fields)", fb_enc, fb_dec_sel, iterations=3_000))
    except ImportError:
        pass

    # Avro
    try:
        from chapters.ch06_avro.avro_from_scratch import (
            avro_decode,
            avro_encode,
            order_to_avro_dict,
        )
        from pathlib import Path
        schema_path = Path(__file__).parent.parent / "ch06_avro" / "fooddash.avsc"
        with open(schema_path) as f:
            schema = json_mod.load(f)
        avro_dict = order_to_avro_dict(order)

        def avro_enc():
            return avro_encode(schema, avro_dict)
        def avro_dec(p):
            result, _ = avro_decode(schema, p, 0)
            return result
        results.append(benchmark("Avro", avro_enc, avro_dec, iterations=3_000))
    except (ImportError, FileNotFoundError):
        pass

    # Cap'n Proto
    try:
        from chapters.ch07_capnproto.capnp_from_scratch import (
            decode_order as capnp_dec_all,
            decode_order_one_field as capnp_dec_sel,
            encode_order as capnp_enc_fn,
        )
        d = order.model_dump()
        status_val = status_map.get(d["status"], 0)

        def capnp_enc():
            return capnp_enc_fn(
                order_id=d["id"], restaurant_id=d["restaurant_id"],
                status=status_val, tip_cents=d.get("tip_cents", 0),
                created_at=d.get("created_at", 0.0),
                platform_transaction_id=d.get("platform_transaction_id", 0),
                driver_id=d.get("driver_id"),
            )
        def capnp_dec(p):
            return capnp_dec_all(p)
        def capnp_dec_s(p):
            return capnp_dec_sel(p)
        results.append(benchmark("Cap'n Proto", capnp_enc, capnp_dec, iterations=3_000))
        results.append(benchmark("Cap'n Proto (1 field)", capnp_enc, capnp_dec_s, iterations=3_000))
    except (ImportError, NameError):
        pass

    # Compressed variants
    try:
        import zstandard
        cctx = zstandard.ZstdCompressor(level=3)
        dctx = zstandard.ZstdDecompressor()

        def json_zstd_enc():
            return cctx.compress(json_enc())
        def json_zstd_dec(p):
            return json_dec(dctx.decompress(p))
        results.append(benchmark("JSON + zstd", json_zstd_enc, json_zstd_dec, iterations=3_000))

        try:
            def pb_zstd_enc():
                return cctx.compress(pb_enc())
            def pb_zstd_dec(p):
                return pb_dec(dctx.decompress(p))
            results.append(benchmark("Protobuf + zstd", pb_zstd_enc, pb_zstd_dec, iterations=3_000))
        except NameError:
            pass

        try:
            def mp_zstd_enc():
                return cctx.compress(mp_enc())
            def mp_zstd_dec(p):
                return mp_dec(dctx.decompress(p))
            results.append(benchmark("MsgPack + zstd", mp_zstd_enc, mp_zstd_dec, iterations=3_000))
        except NameError:
            pass
    except ImportError:
        pass

    return results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(benchmark_results: list[BenchmarkResult] | None = None) -> None:
    print("=" * 70)
    print("  CHAPTER 11: THE SERIALIZATION TAX AT 1M MESSAGES/SECOND")
    print("  FoodDash's annual architecture review")
    print("=" * 70)

    print("\n  Scale assumptions:")
    print(f"    Messages/second:      {MESSAGES_PER_SECOND:>12,}")
    print(f"    Cloud cost/core/month: ${CLOUD_COST_PER_CORE_PER_MONTH:>10,.0f}")
    print(f"    Bandwidth cost/GB:     ${BANDWIDTH_COST_PER_GB:>10,.3f}")
    print()

    # Use provided results or run quick benchmarks
    if benchmark_results is None:
        print("  Running quick benchmarks on typical order...\n")
        benchmark_results = run_quick_benchmarks()

    # Compute scale metrics
    all_metrics = [compute_scale_metrics(r) for r in benchmark_results]

    # Split into base formats and compressed
    base_metrics = [m for m in all_metrics if "zstd" not in m["name"]]
    compressed_metrics = [m for m in all_metrics if "zstd" in m["name"]]

    # Main table
    print(f"\n{'=' * 70}")
    print(f"  AT-SCALE COST TABLE ({MESSAGES_PER_SECOND:,} msg/s, typical order)")
    print(f"{'=' * 70}")
    print_scale_table(base_metrics)

    # Compression table
    if compressed_metrics:
        print(f"\n{'=' * 70}")
        print(f"  WITH COMPRESSION ({MESSAGES_PER_SECOND:,} msg/s)")
        print(f"{'=' * 70}")
        print_scale_table(compressed_metrics)

        # Compression analysis
        print_compression_analysis(base_metrics, compressed_metrics)

    # Memory allocation pressure
    print(f"\n{'=' * 70}")
    print(f"  MEMORY ALLOCATION PRESSURE ({MESSAGES_PER_SECOND:,} msg/s)")
    print(f"{'=' * 70}\n")

    name_w = max(len(m["name"]) for m in all_metrics) + 2
    print(f"  {'Format':<{name_w}} | {'Peak Mem':>12} | {'Alloc Rate':>12}")
    print(f"  {'':>2}{'-' * (name_w + 30)}")
    for m in all_metrics:
        r = next(r for r in benchmark_results if r.name == m["name"])
        peak = max(r.encode_peak_memory_bytes, r.decode_peak_memory_bytes)
        rate = m["mem_alloc_gb_s"]
        print(f"  {m['name']:<{name_w}} | {peak:>10,} B | {rate:>10.2f} GB/s")
    print()

    # Narrative
    print_narrative(all_metrics)

    # Slider preview
    print(f"\n{'=' * 70}")
    print("  WHAT IF YOU SCALE DIFFERENTLY?")
    print(f"{'=' * 70}\n")

    for scale in [10_000, 100_000, 1_000_000, 10_000_000]:
        json_m = next((m for m in all_metrics if m["name"] == "JSON (stdlib)"), None)
        proto_m = next((m for m in all_metrics if m["name"] == "Protobuf"), None)
        if json_m and proto_m:
            j_cores = json_m["enc_us"] * scale / 1_000_000 + json_m["dec_us"] * scale / 1_000_000
            p_cores = proto_m["enc_us"] * scale / 1_000_000 + proto_m["dec_us"] * scale / 1_000_000
            print(f"  At {scale:>12,} msg/s:  JSON = {j_cores:>6.1f} cores,  Protobuf = {p_cores:>6.1f} cores")

    print()


if __name__ == "__main__":
    main()
