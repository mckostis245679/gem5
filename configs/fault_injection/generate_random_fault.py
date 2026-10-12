#!/usr/bin/env python3

import argparse
import json
import random
from pathlib import Path

L1_STATES = ["I", "S", "E", "M"]
L2_STATES = ["SS", "M", "MT"]

# Based on your fixed cache configuration:
# L1D: 2 KiB / 64 B = 32 cache slots
# L2:  4 KiB / 64 B = 64 cache slots
L1_NUM_BLOCKS = 32
L2_NUM_BLOCKS = 64


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate one random MESI state fault or cache-data bit-flip "
            "fault and save it as JSON."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("fault.json"),
        help="Output JSON file.",
    )

    parser.add_argument(
        "--fault-type",
        choices=["state", "data_bitflip", "random"],
        default="random",
        help=("Fault type. 'random' currently generates a data bit flip."),
    )

    parser.add_argument(
        "--target",
        choices=["L1D", "L2", "random"],
        default="random",
        help="Fault target. 'random' chooses between L1D and L2.",
    )

    parser.add_argument(
        "--num-cores",
        type=int,
        default=2,
        help="Number of CPU cores.",
    )

    parser.add_argument(
        "--tick-min",
        type=int,
        required=True,
        help="Minimum injection tick.",
    )

    parser.add_argument(
        "--tick-max",
        type=int,
        required=True,
        help="Maximum injection tick.",
    )

    parser.add_argument(
        "--line-size",
        type=int,
        default=64,
        help="Cache line size in bytes.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        help="Optional RNG seed for reproducibility.",
    )

    args = parser.parse_args()

    if args.num_cores <= 0:
        parser.error("--num-cores must be > 0")

    if args.tick_min > args.tick_max:
        parser.error("--tick-min must be <= --tick-max")

    if args.line_size <= 0 or (args.line_size & (args.line_size - 1)) != 0:
        parser.error("--line-size must be a power of two")

    rng = random.Random(args.seed)

    fault_type = (
        rng.choice(["data_bitflip", "state"])
        if args.fault_type == "random"
        else args.fault_type
    )

    target = (
        rng.choice(["L1D", "L2"]) if args.target == "random" else args.target
    )

    tick = rng.randint(
        args.tick_min,
        args.tick_max,
    )

    # Select an appropriate cache slot index.
    if target == "L1D":
        core = rng.randrange(args.num_cores)
        idx = rng.randrange(L1_NUM_BLOCKS)  # 0..511
    else:
        core = 0
        idx = rng.randrange(L2_NUM_BLOCKS)  # 0..4095

    # You always have one L2 bank.
    bank = 0

    fault = {
        "fault_type": fault_type,
        "target": target,
        "core": core,
        "bank": bank,
        "idx": idx,
        "tick": tick,
    }

    if fault_type == "state":
        if target == "L1D":
            fault["state"] = rng.choice(L1_STATES)
        else:
            fault["state"] = rng.choice(L2_STATES)

    else:
        # Random bit within the complete cache line.
        #
        # For a 64-byte line:
        # 64 * 8 = 512 bits
        # valid positions are 0..511
        fault["bit"] = rng.randrange(args.line_size * 8)

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with args.output.open("w") as output_file:
        json.dump(
            fault,
            output_file,
            indent=4,
        )
        output_file.write("\n")

    print(f"Saved random fault to {args.output}")
    print(json.dumps(fault, indent=4))

    print(f"Selected cache idx: {idx}")

    if target == "L1D":
        print(f"Valid idx range: 0..{L1_NUM_BLOCKS-1}")
    else:
        print(f"Valid idx range: 0..{L2_NUM_BLOCKS-1}")

    if fault_type == "data_bitflip":
        bit = fault["bit"]
        byte_offset = bit // 8
        bit_in_byte = bit % 8
        mask = 1 << bit_in_byte

        print(f"Bit position: {bit}")
        print(f"Byte offset: {byte_offset}")
        print(f"Bit in byte: {bit_in_byte}")
        print(f"Byte mask: 0x{mask:02x}")


if __name__ == "__main__":
    main()
