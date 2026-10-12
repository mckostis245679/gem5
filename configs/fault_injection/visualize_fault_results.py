#!/usr/bin/env python3

import argparse
import json
from collections import (
    Counter,
    defaultdict,
)
from pathlib import Path

import matplotlib.pyplot as plt

OUTCOME_ORDER = ["NO_CHANGE", "SDC", "SYSTEM_CRASH"]


def load_runs(path: Path):
    runs = []

    with path.open(errors="replace") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"Skipping invalid JSON on line " f"{line_number}: {exc}"
                )
                continue

            outcome = record.get("outcome") or {}
            fault = record.get("fault") or {}

            # Only analyze faults that were actually injected.
            if not outcome.get("injection_seen", False):
                continue

            selected_idx = fault.get(
                "idx",
                outcome.get("injected_idx"),
            )

            bit_position = fault.get(
                "bit",
                outcome.get("injected_bit_position"),
            )

            byte_offset = outcome.get("injected_byte_offset")

            bit_in_byte = outcome.get("injected_bit_in_byte")

            # If the parser did not record these derived values,
            # derive them from the generated bit position.
            if isinstance(bit_position, int):
                if byte_offset is None:
                    byte_offset = bit_position // 8

                if bit_in_byte is None:
                    bit_in_byte = bit_position % 8

            runs.append(
                {
                    "run": record.get("run"),
                    "category": outcome.get(
                        "category",
                        "UNKNOWN",
                    ),
                    "target": fault.get(
                        "target",
                        "",
                    ),
                    "level": outcome.get(
                        "injection_level",
                        "",
                    ),
                    "idx": selected_idx,
                    "address": outcome.get(
                        "injected_address",
                        "",
                    ),
                    "tick": outcome.get(
                        "injection_tick",
                        fault.get("tick"),
                    ),
                    "bit_position": bit_position,
                    "byte_offset": byte_offset,
                    "bit_in_byte": bit_in_byte,
                    "old_byte": outcome.get(
                        "injected_old_byte",
                        "",
                    ),
                    "new_byte": outcome.get(
                        "injected_new_byte",
                        "",
                    ),
                }
            )

    return runs


def save_outcome_counts(runs, outdir):
    counts = Counter(r["category"] for r in runs)

    categories = [
        category for category in OUTCOME_ORDER if counts[category] > 0
    ]

    categories += sorted(
        category for category in counts if category not in categories
    )

    values = [counts[category] for category in categories]

    plt.figure(figsize=(7, 5))
    plt.bar(categories, values)
    plt.title("Data bit-flip outcomes")
    plt.xlabel("Outcome")
    plt.ylabel("Number of injected faults")
    plt.tight_layout()
    plt.savefig(
        outdir / "01_outcome_counts.png",
        dpi=160,
    )
    plt.close()


def save_outcomes_by_target(runs, outdir):
    targets = sorted({r["target"] for r in runs if r["target"]})

    if not targets:
        return

    by_target = defaultdict(Counter)

    for r in runs:
        if r["target"]:
            by_target[r["target"]][r["category"]] += 1

    plt.figure(figsize=(7, 5))
    bottom = [0] * len(targets)

    for category in OUTCOME_ORDER:
        values = [by_target[target][category] for target in targets]

        plt.bar(
            targets,
            values,
            bottom=bottom,
            label=category,
        )

        bottom = [
            old + new
            for old, new in zip(
                bottom,
                values,
            )
        ]

    plt.title("Outcomes by cache target")
    plt.xlabel("Cache target")
    plt.ylabel("Number of injected faults")
    plt.legend()
    plt.tight_layout()
    plt.savefig(
        outdir / "02_outcomes_by_target.png",
        dpi=160,
    )
    plt.close()


def save_tick_scatter(runs, outdir):
    outcome_y = {
        "NO_CHANGE": 0,
        "SDC": 1,
        "SYSTEM_CRASH": 2,
    }

    plt.figure(figsize=(9, 5))

    for category in OUTCOME_ORDER:
        points = [
            r
            for r in runs
            if r["category"] == category and isinstance(r["tick"], int)
        ]

        if not points:
            continue

        x = [r["tick"] for r in points]

        y = [outcome_y[category]] * len(points)

        plt.scatter(
            x,
            y,
            label=category,
            alpha=0.7,
        )

    plt.yticks(
        [0, 1, 2],
        [
            "NO_CHANGE",
            "SDC",
            "SYSTEM_CRASH",
        ],
    )

    plt.title("Outcome versus injection tick")
    plt.xlabel("Injection tick")
    plt.ylabel("Outcome")
    plt.legend()
    plt.tight_layout()
    plt.savefig(
        outdir / "03_outcome_vs_tick.png",
        dpi=160,
    )
    plt.close()


def save_idx_distribution(runs, outdir):
    targets = sorted({r["target"] for r in runs if r["target"]})

    for target in targets:
        indices = [
            r["idx"]
            for r in runs
            if r["target"] == target and isinstance(r["idx"], int)
        ]

        if not indices:
            continue

        plt.figure(figsize=(9, 5))
        plt.hist(
            indices,
            bins=32,
        )
        plt.title(f"Selected cache-index distribution: {target}")
        plt.xlabel("Selected cache idx")
        plt.ylabel("Number of injected faults")
        plt.tight_layout()
        plt.savefig(
            outdir / f"04_idx_distribution_{target}.png",
            dpi=160,
        )
        plt.close()


def save_outcomes_by_bit_in_byte(runs, outdir):
    by_bit = defaultdict(Counter)

    for r in runs:
        bit = r["bit_in_byte"]

        if isinstance(bit, int):
            by_bit[bit][r["category"]] += 1

    bit_positions = list(range(8))

    if not any(by_bit[bit] for bit in bit_positions):
        return

    plt.figure(figsize=(9, 5))
    bottom = [0] * len(bit_positions)

    for category in OUTCOME_ORDER:
        values = [by_bit[bit][category] for bit in bit_positions]

        plt.bar(
            bit_positions,
            values,
            bottom=bottom,
            label=category,
        )

        bottom = [
            old + new
            for old, new in zip(
                bottom,
                values,
            )
        ]

    plt.title("Outcomes by flipped bit within byte")
    plt.xlabel("Bit position within byte")
    plt.ylabel("Number of injected faults")
    plt.xticks(range(8))
    plt.legend()
    plt.tight_layout()
    plt.savefig(
        outdir / "05_outcomes_by_bit_in_byte.png",
        dpi=160,
    )
    plt.close()


def save_byte_offset_distribution(runs, outdir):
    offsets = [
        r["byte_offset"]
        for r in runs
        if isinstance(
            r["byte_offset"],
            int,
        )
    ]

    if not offsets:
        return

    plt.figure(figsize=(9, 5))
    plt.hist(
        offsets,
        bins=64,
        range=(0, 64),
    )
    plt.title("Injected byte-offset distribution")
    plt.xlabel("Byte offset within 64-byte cache line")
    plt.ylabel("Number of injected faults")
    plt.tight_layout()
    plt.savefig(
        outdir / "06_byte_offset_distribution.png",
        dpi=160,
    )
    plt.close()


def save_top_addresses(runs, outdir):
    counts = Counter(r["address"] for r in runs if r["address"])

    top = counts.most_common(15)

    if not top:
        return

    addresses = [address for address, _ in top]

    values = [count for _, count in top]

    plt.figure(figsize=(9, 6))
    plt.barh(
        addresses,
        values,
    )
    plt.title("Most frequently injected cache-line addresses")
    plt.xlabel("Number of successful injections")
    plt.ylabel("Injected address")
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(
        outdir / "07_top_injected_addresses.png",
        dpi=160,
    )
    plt.close()


def save_top_indices(runs, outdir):
    for target in sorted({r["target"] for r in runs if r["target"]}):
        counts = Counter(
            r["idx"]
            for r in runs
            if r["target"] == target and isinstance(r["idx"], int)
        )

        top = counts.most_common(15)

        if not top:
            continue

        labels = [str(idx) for idx, _ in top]

        values = [count for _, count in top]

        plt.figure(figsize=(9, 6))
        plt.barh(
            labels,
            values,
        )
        plt.title(f"Most frequently injected indices: {target}")
        plt.xlabel("Number of successful injections")
        plt.ylabel("Cache idx")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig(
            outdir / f"08_top_indices_{target}.png",
            dpi=160,
        )
        plt.close()


def verify_bit_flips(runs):
    checked = 0
    incorrect = []

    for r in runs:
        old_text = r["old_byte"]
        new_text = r["new_byte"]
        bit_in_byte = r["bit_in_byte"]

        if (
            not old_text
            or not new_text
            or not isinstance(
                bit_in_byte,
                int,
            )
        ):
            continue

        try:
            old_byte = int(
                old_text,
                16,
            )
            new_byte = int(
                new_text,
                16,
            )
        except ValueError:
            continue

        checked += 1

        expected_mask = 1 << bit_in_byte

        actual_mask = old_byte ^ new_byte

        if actual_mask != expected_mask:
            incorrect.append(
                {
                    "run": r["run"],
                    "idx": r["idx"],
                    "address": r["address"],
                    "old_byte": old_text,
                    "new_byte": new_text,
                    "bit_in_byte": bit_in_byte,
                    "expected_mask": (f"0x{expected_mask:02x}"),
                    "actual_mask": (f"0x{actual_mask:02x}"),
                }
            )

    return checked, incorrect


def print_summary(runs):
    counts = Counter(r["category"] for r in runs)

    targets = Counter(r["target"] for r in runs if r["target"])

    total = len(runs)

    print()
    print(f"Successfully injected runs: {total}")

    for category in OUTCOME_ORDER:
        count = counts[category]

        percentage = 100.0 * count / total if total else 0.0

        print(f"{category:13s}: " f"{count:5d} " f"({percentage:6.2f}%)")

    masked = counts["NO_CHANGE"]

    unmasked = counts["SDC"] + counts["SYSTEM_CRASH"]

    if total:
        print()
        print(f"Masked:   {masked} " f"({100.0 * masked / total:.2f}%)")
        print(f"Unmasked: {unmasked} " f"({100.0 * unmasked / total:.2f}%)")

    if targets:
        print()
        print("Successful injections by target:")

        for target in sorted(targets):
            print(f"  {target:5s}: " f"{targets[target]}")

    checked, incorrect = verify_bit_flips(runs)

    print()
    print(f"Bit-flip log checks: {checked}")

    if incorrect:
        print(
            "WARNING: "
            f"{len(incorrect)} injection(s) did not "
            "change exactly the logged bit."
        )

        for item in incorrect[:10]:
            print(
                "  "
                f"run={item['run']} "
                f"idx={item['idx']} "
                f"address={item['address']} "
                f"old={item['old_byte']} "
                f"new={item['new_byte']} "
                f"expected={item['expected_mask']} "
                f"actual={item['actual_mask']}"
            )
    elif checked:
        print("All checked injections changed " "exactly the requested bit.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Create plots from an index-based gem5 "
            "cache-data bit-flip campaign summary.jsonl."
        )
    )

    parser.add_argument(
        "summary",
        type=Path,
        help="Path to summary.jsonl",
    )

    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("fault_graphs"),
        help=("Directory for generated PNG files"),
    )

    args = parser.parse_args()

    if not args.summary.exists():
        parser.error(f"File not found: {args.summary}")

    args.outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    runs = load_runs(args.summary)

    if not runs:
        raise SystemExit("No successfully injected runs found.")

    print_summary(runs)

    save_outcome_counts(
        runs,
        args.outdir,
    )

    save_outcomes_by_target(
        runs,
        args.outdir,
    )

    save_tick_scatter(
        runs,
        args.outdir,
    )

    save_idx_distribution(
        runs,
        args.outdir,
    )

    save_outcomes_by_bit_in_byte(
        runs,
        args.outdir,
    )

    save_byte_offset_distribution(
        runs,
        args.outdir,
    )

    save_top_addresses(
        runs,
        args.outdir,
    )

    save_top_indices(
        runs,
        args.outdir,
    )

    print()
    print(f"Graphs saved in: {args.outdir}")

    for path in sorted(args.outdir.glob("*.png")):
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
