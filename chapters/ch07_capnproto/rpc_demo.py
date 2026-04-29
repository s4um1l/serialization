"""Cap'n Proto RPC concepts -- promise pipelining explained.

Cap'n Proto isn't just a serialization format -- it includes an RPC framework
with a killer feature: PROMISE PIPELINING.

This module explains the concept with a FoodDash use case, using pseudocode
and timing simulations.  If pycapnp is available with RPC support, we show
a live example; otherwise we demonstrate the concept with simulation.
"""

from __future__ import annotations

import time

try:
    import capnp  # noqa: F401

    HAS_PYCAPNP = True
except ImportError:
    HAS_PYCAPNP = False


# ─────────────────────────────────────────────────────────────────────
# Promise pipelining simulation
# ─────────────────────────────────────────────────────────────────────

def simulate_traditional_rpc(rtt_ms: float = 50.0) -> float:
    """Simulate traditional RPC: 2 sequential round trips.

    Use case: Get an order, then get the driver location for that order.

    Traditional flow:
      Client -> Server: getOrder("ord00042")
      Client <- Server: { order_id: "ord00042", driver_id: "driv0001", ... }
      Client -> Server: getDriverLocation("driv0001")
      Client <- Server: { lat: 40.752, lng: -73.978 }

    Total: 2 round trips = 2 * RTT
    """
    # Simulate two sequential round trips
    start = time.perf_counter()
    time.sleep(rtt_ms / 1000)  # First round trip
    time.sleep(rtt_ms / 1000)  # Second round trip
    elapsed = time.perf_counter() - start
    return elapsed * 1000  # ms


def simulate_pipelined_rpc(rtt_ms: float = 50.0) -> float:
    """Simulate Cap'n Proto pipelined RPC: 1 round trip.

    Same use case, but with promise pipelining:

      Client -> Server: getOrder("ord00042")
                        .then(order => getDriverLocation(order.driver_id))
      Client <- Server: { lat: 40.752, lng: -73.978 }

    The CLIENT sends BOTH requests at once.  The second request says
    "use the driver_id field from the result of request #1".
    The SERVER resolves the promise chain locally -- no round trip needed.

    Total: 1 round trip = 1 * RTT
    """
    # Simulate one round trip (server resolves the chain locally)
    start = time.perf_counter()
    time.sleep(rtt_ms / 1000)  # Single round trip
    elapsed = time.perf_counter() - start
    return elapsed * 1000  # ms


def explain_promise_pipelining() -> None:
    """Print a detailed explanation of promise pipelining."""

    print("""
  PROMISE PIPELINING -- Cap'n Proto's RPC Killer Feature
  ======================================================

  The Problem:
  ────────────
  FoodDash needs to show a delivery tracking screen.  This requires:
    1. Get the order details (to find the driver_id)
    2. Get the driver's current location (using the driver_id from step 1)

  Step 2 DEPENDS on step 1 -- you can't look up the driver until you know
  which driver is assigned to the order.


  Traditional RPC (REST, gRPC unary):
  ────────────────────────────────────
  Client                              Server
    |                                   |
    |-- getOrder("ord00042") ---------> |
    |                                   |  (server processes)
    | <-------- { driver_id: "driv0001" |
    |               ... }               |
    |                                   |
    |-- getDriverLocation("driv0001") ->|
    |                                   |  (server processes)
    | <------- { lat: 40.752,           |
    |            lng: -73.978 }         |
    |                                   |

  Total: 2 round trips.  At 50ms RTT, that's 100ms of network latency.
  In a data center, RTT might be 1-5ms, but across regions it's 50-200ms.


  Cap'n Proto RPC (promise pipelining):
  ─────────────────────────────────────
  Client                              Server
    |                                   |
    |-- getOrder("ord00042")            |
    |   .then(order =>                  |
    |     getDriverLocation(            |
    |       order.driverId))  --------> |
    |                                   |  (server resolves the chain:
    |                                   |   1. gets order
    |                                   |   2. reads driver_id
    |                                   |   3. gets driver location)
    | <------- { lat: 40.752,           |
    |            lng: -73.978 }         |
    |                                   |

  Total: 1 round trip.  The client sends BOTH requests in a SINGLE message.
  The second request references a PROMISE -- "the driver_id field of the
  result of request #1".  The server resolves this locally.


  How It Works Under the Hood:
  ────────────────────────────
  Cap'n Proto RPC uses "promise pointers" (also called capabilities).
  When you call a remote method, you get back a promise.  You can
  immediately call methods ON that promise, passing it as an argument
  to other calls.  The server maintains a table of outstanding promises
  and resolves them as results become available.

  Pseudocode:

    # Client-side (all sent in ONE network message):
    order_promise = server.getOrder("ord00042")

    # This doesn't wait for order_promise to resolve!
    # It sends a request that says "use field driverId of promise #1"
    location = server.getDriverLocation(order_promise.driverId)

    # NOW we wait -- but only one round trip
    result = await location
    print(f"Driver is at {result.lat}, {result.lng}")


  Why This Matters for FoodDash:
  ──────────────────────────────
  The delivery tracking screen needs to make 3-4 chained lookups:
    1. Get order -> find driver_id
    2. Get driver -> find current location
    3. Get restaurant -> find restaurant location
    4. Compute ETA from driver location to restaurant to customer

  Traditional RPC: 4 round trips = 200ms at 50ms RTT
  Promise pipelining: 1 round trip = 50ms

  That's a 4x latency reduction with ZERO code complexity increase.


  Comparison with Other RPC Approaches:
  ─────────────────────────────────────
  REST:          Each call is independent.  N dependencies = N round trips.
  gRPC:          Streaming helps throughput, but unary calls still need
                 sequential round trips for dependencies.
  GraphQL:       Server resolves the chain, but you must know the full
                 query shape upfront.  Can't pipeline arbitrary method calls.
  Cap'n Proto:   Client sends a DAG of calls with promise references.
                 Server resolves the DAG locally.  Minimum round trips.
""")


# ─────────────────────────────────────────────────────────────────────
# Timing simulation
# ─────────────────────────────────────────────────────────────────────

def run_timing_simulation() -> None:
    """Run a timing simulation comparing traditional vs pipelined RPC."""

    print("  --- Timing Simulation ---\n")
    print("  Simulating network latency for the FoodDash tracking use case:\n")

    rtt_values = [1.0, 5.0, 50.0, 150.0]
    labels = ["Same DC (1ms)", "Cross-AZ (5ms)", "Cross-region (50ms)", "Cross-continent (150ms)"]

    print(f"    {'Scenario':<28s} {'Traditional':>14s} {'Pipelined':>14s} {'Savings':>10s}")
    print(f"    {'─' * 28} {'─' * 14} {'─' * 14} {'─' * 10}")

    for rtt, label in zip(rtt_values, labels):
        traditional_ms = rtt * 2  # 2 round trips
        pipelined_ms = rtt * 1    # 1 round trip
        savings_pct = (1 - pipelined_ms / traditional_ms) * 100

        print(
            f"    {label:<28s} "
            f"{traditional_ms:>11.1f} ms "
            f"{pipelined_ms:>11.1f} ms "
            f"{savings_pct:>8.0f}%"
        )

    print()
    print("  For deeper chains (4 calls): traditional = 4 * RTT, pipelined = 1 * RTT")
    print()

    for rtt, label in zip(rtt_values, labels):
        traditional_ms = rtt * 4
        pipelined_ms = rtt * 1
        savings_pct = (1 - pipelined_ms / traditional_ms) * 100

        print(
            f"    {label:<28s} "
            f"{traditional_ms:>11.1f} ms "
            f"{pipelined_ms:>11.1f} ms "
            f"{savings_pct:>8.0f}%"
        )

    print()


# ─────────────────────────────────────────────────────────────────────
# Live pycapnp RPC demo (if available)
# ─────────────────────────────────────────────────────────────────────

def pycapnp_rpc_note() -> None:
    """Note about pycapnp RPC capabilities."""
    if HAS_PYCAPNP:
        print("  pycapnp is available.")
        print("  Cap'n Proto RPC requires defining interfaces in .capnp schema files")
        print("  and running a server.  The RPC system supports:")
        print("    - Promise pipelining (as described above)")
        print("    - Capability-based security (object capabilities as RPC references)")
        print("    - Bi-directional communication")
        print("    - Time travel (send dependent calls before previous results arrive)")
        print()
    else:
        print("  pycapnp not available.  To try Cap'n Proto RPC:")
        print("    brew install capnp")
        print("    pip install pycapnp")
        print()
        print("  Even without the library, the concepts above apply to any")
        print("  Cap'n Proto RPC implementation (C++, Rust, Go, etc.)")
        print()


# ─────────────────────────────────────────────────────────────────────
# RPC schema pseudocode
# ─────────────────────────────────────────────────────────────────────

def show_rpc_schema() -> None:
    """Show what a Cap'n Proto RPC schema would look like for FoodDash."""

    print("""  --- Cap'n Proto RPC Schema (hypothetical) ---

  If we extended our fooddash.capnp schema with RPC interfaces:

    interface OrderService {
      getOrder @0 (id :Text) -> (order :Order);
      placeOrder @1 (order :Order) -> (confirmation :OrderConfirmation);
      updateStatus @2 (id :Text, status :OrderStatus) -> ();
    }

    interface DriverService {
      getDriver @0 (id :Text) -> (driver :Driver);
      getLocation @1 (id :Text) -> (location :GeoPoint);
      assignToOrder @2 (driverId :Text, orderId :Text) -> ();
    }

    interface TrackingService {
      # This is where promise pipelining shines:
      # The client can call getOrderTracking, which internally calls
      # OrderService.getOrder and then DriverService.getLocation,
      # all in a single round trip.
      getOrderTracking @0 (orderId :Text) -> (tracking :TrackingInfo);
    }

    struct TrackingInfo {
      order @0 :Order;
      driverLocation @1 :GeoPoint;
      estimatedArrivalMinutes @2 :Int32;
    }

  With promise pipelining, a client could write:

    # Python pseudocode with pycapnp RPC:
    order_promise = order_service.getOrder("ord00042")
    # This call references order_promise.order.driverId
    # -- it's sent IMMEDIATELY, not after getOrder completes
    location_promise = driver_service.getLocation(
        order_promise.order.driverId
    )
    # Only ONE round trip for both calls!
    location = await location_promise
    print(f"Driver at ({location.latitude}, {location.longitude})")
""")


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  Cap'n Proto RPC -- Promise Pipelining")
    print("=" * 70)

    explain_promise_pipelining()

    run_timing_simulation()

    show_rpc_schema()

    print("  --- Library Status ---\n")
    pycapnp_rpc_note()


if __name__ == "__main__":
    main()
