#!/usr/bin/env python3

import argparse
import json
import math
import random
from pathlib import Path
from statistics import NormalDist

LINE_SIZE_BYTES = 64
DATA_BITS_PER_LINE = LINE_SIZE_BYTES * 8  # 512 bits
# Stable MESI Two Level L1 states that RubyCoherenceFaultInjector can force
# (its new_state parameter). A state fault forces one of them; forcing the
# line's current state is reported by the injector as not injected.
L1_STATES = ("I", "S", "E", "M")


def required_injections(N, error, confidence, p=0.5):
    """
    Finite-population sample-size equation from the paper:

        n = N * t^2 * p(1-p)
            -------------------------------
            e^2 * (N - 1) + t^2 * p(1-p)

    where:
      N = total fault population
      e = target margin of error
      t = normal critical value for the requested confidence
      p = estimated proportion; use 0.5 conservatively
    """
    t = NormalDist().inv_cdf((1.0 + confidence) / 2.0)

    numerator = N * (t**2) * p * (1.0 - p)
    denominator = (error**2) * (N - 1) + (t**2) * p * (1.0 - p)

    return math.ceil(numerator / denominator), t


def cache_geometry(size_kib, assoc, name):
    size_bytes = size_kib * 1024

    if size_bytes % LINE_SIZE_BYTES != 0:
        raise ValueError(
            f"{name} size must be an exact multiple of {LINE_SIZE_BYTES} bytes"
        )

    num_lines = size_bytes // LINE_SIZE_BYTES

    if num_lines % assoc != 0:
        raise ValueError(
            f"{name}: number of lines ({num_lines}) must be divisible by "
            f"associativity ({assoc})"
        )

    num_sets = num_lines // assoc
    return size_bytes, num_lines, num_sets


def sites_per_line_for_fault_type(fault_type):
    if fault_type == "data_bitflip":
        return DATA_BITS_PER_LINE
    if fault_type == "state":
        return len(L1_STATES)
    if fault_type == "both":
        return DATA_BITS_PER_LINE + len(L1_STATES)
    raise ValueError(f"Unknown fault type: {fault_type}")


def decode_site(site, campaign_fault_type):
    """
    Convert a per-line fault site into the fault fields understood by
    RubyCoherenceFaultInjector:
      - data_bitflip: {"fault_type": "data_bitflip", "bit": <0..511>}
      - state:        {"fault_type": "state", "state": <I|S|E|M>}

    For a 'both' campaign, the per-line sites are the union of:
      data bits     0..511
      L1 states     512..515 (I, S, E, M)

    This means each site has equal selection probability.
    """
    if campaign_fault_type == "data_bitflip":
        return {"fault_type": "data_bitflip", "bit": site}

    if campaign_fault_type == "state":
        return {"fault_type": "state", "state": L1_STATES[site]}

    # both
    if site < DATA_BITS_PER_LINE:
        return {"fault_type": "data_bitflip", "bit": site}

    return {
        "fault_type": "state",
        "state": L1_STATES[site - DATA_BITS_PER_LINE],
    }


def generate_unique_fault_ids(rng, N, n):
    """
    Uniform sampling without replacement.

    Python's random.Random uses the Mersenne Twister (MT19937).
    """
    chosen = set()

    while len(chosen) < n:
        chosen.add(rng.randrange(N))

    return list(chosen)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a statistical cache fault-injection campaign."
    )

    parser.add_argument("--l1d-size-kib", type=int, required=True)
    parser.add_argument("--l1d-assoc", type=int, required=True)

    parser.add_argument("--l2-size-kib", type=int, required=True)
    parser.add_argument("--l2-assoc", type=int, required=True)

    parser.add_argument("--num-cores", type=int, required=True)
    parser.add_argument("--cycles", type=int, required=True)

    parser.add_argument(
        "--error",
        type=float,
        required=True,
        help="Target margin of error, e.g. 0.05 for +/-5%%.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        required=True,
        help="Confidence level, e.g. 0.95 for 95%%.",
    )

    parser.add_argument(
        "--fault-type",
        choices=["data_bitflip", "state", "both"],
        required=True,
        help=(
            "Faults eligible for injection during this campaign: data bit "
            "flips, forced L1 coherence states, or both."
        ),
    )

    parser.add_argument(
        "--target",
        choices=["L1D"],
        required=True,
        help="Cache level targeted by this campaign.",
    )

    parser.add_argument("--seed", type=int, default=None)

    parser.add_argument(
        "--output", type=Path, default=Path("fault_campaign.json")
    )

    args = parser.parse_args()

    if args.l1d_size_kib <= 0 or args.l2_size_kib <= 0:
        parser.error("Cache sizes must be > 0")
    if args.l1d_assoc <= 0 or args.l2_assoc <= 0:
        parser.error("Associativity must be > 0")
    if args.num_cores <= 0:
        parser.error("--num-cores must be > 0")
    if args.cycles <= 0:
        parser.error("--cycles must be > 0")
    if not 0.0 < args.error < 1.0:
        parser.error("--error must be between 0 and 1")
    if not 0.0 < args.confidence < 1.0:
        parser.error("--confidence must be between 0 and 1")

    try:
        _, l1_lines_per_core, l1_sets = cache_geometry(
            args.l1d_size_kib,
            args.l1d_assoc,
            "L1D",
        )

        _, l2_lines, l2_sets = cache_geometry(
            args.l2_size_kib,
            args.l2_assoc,
            "L2",
        )
    except ValueError as exc:
        parser.error(str(exc))

    target_sites_per_line = sites_per_line_for_fault_type(args.fault_type)

    if args.target == "L1D":
        total_target_lines = args.num_cores * l1_lines_per_core
    else:
        # One shared L2.
        total_target_lines = l2_lines

    sites_per_cycle = total_target_lines * target_sites_per_line

    # Population:
    #   every eligible fault site × every eligible workload cycle
    N = sites_per_cycle * args.cycles

    n, t = required_injections(
        N=N,
        error=args.error,
        confidence=args.confidence,
        p=0.5,
    )

    rng = random.Random(args.seed)  # Mersenne Twister

    fault_ids = generate_unique_fault_ids(rng, N, n)

    faults = []

    for fault_id in fault_ids:
        # Population layout:
        # [cycle][cache-line slot][eligible fault site]
        cycle = fault_id // sites_per_cycle
        inside_cycle = fault_id % sites_per_cycle

        global_line = inside_cycle // target_sites_per_line
        site = inside_cycle % target_sites_per_line

        if args.target == "L1D":
            core = global_line // l1_lines_per_core
            idx = global_line % l1_lines_per_core
        else:
            # Shared L2.
            core = 0
            idx = global_line

        fault = {
            "target": args.target,
            "core": core,
            "bank": 0,
            "idx": idx,
            "cycle": cycle,
            **decode_site(site, args.fault_type),
        }

        faults.append(fault)

    campaign = {
        "metadata": {
            "line_size_bytes": LINE_SIZE_BYTES,
            "data_bits_per_line": DATA_BITS_PER_LINE,
            "l1_states": list(L1_STATES),
            "l1d_size_kib_per_core": args.l1d_size_kib,
            "l1d_assoc": args.l1d_assoc,
            "l1d_sets_per_core": l1_sets,
            "l1d_lines_per_core": l1_lines_per_core,
            "l2_size_kib": args.l2_size_kib,
            "l2_assoc": args.l2_assoc,
            "l2_sets": l2_sets,
            "l2_lines": l2_lines,
            "num_cores": args.num_cores,
            "cycles": args.cycles,
            "campaign_fault_type": args.fault_type,
            "target": args.target,
            "population_size_N": N,
            "required_injections_n": n,
            "target_error_e": args.error,
            "confidence": args.confidence,
            "critical_value_t": t,
            "p": 0.5,
            "rng": "Mersenne Twister (Python random.Random / MT19937)",
            "seed": args.seed,
            "sampling": "uniform without replacement",
            "idx_definition": "flat cache-line slot index within the selected cache",
        },
        "faults": faults,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w") as f:
        json.dump(campaign, f, indent=4)
        f.write("\n")

    print(f"Target: {args.target}")
    print(f"Campaign fault type: {args.fault_type}")
    print(f"Target cache-line slots: {total_target_lines}")
    print(f"Eligible fault sites per line: {target_sites_per_line}")
    print(f"Eligible fault sites per cycle: {sites_per_cycle}")
    print(f"Population size N: {N}")
    print(f"Critical value t: {t:.6f}")
    print(f"Required injections n: {n}")
    print(f"Saved campaign to: {args.output}")


if __name__ == "__main__":
    main()
