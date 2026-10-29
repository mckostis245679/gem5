#!/usr/bin/env python3
"""
Classify the fault runs of a full-system PARSEC campaign and summarise them.

    python3 fault_outcomes.py results/<campaign>

Each fault run is compared with the campaign's fault-free baseline and
classified as:

    masked  the benchmark finished and its output matches the baseline
    sdc     the benchmark finished but its output differs (silent data
            corruption)
    crash   gem5 stopped with a panic/fatal (e.g. an invalid coherence
            transition or a deadlock), the guest kernel panicked, or the
            benchmark itself died (segfault, abort, ...)
    hang    the run hit its tick limit or host timeout without finishing

The output compared is the benchmark's console output (from parsecmgmt's
"Beginning of output" marker to FI_PROGRAM_END), without lines that report
wall-clock time (simulated time legitimately differs between runs), plus
the SHA-256 of every file the benchmark wrote (FI_OUTPUT_FILES_* block
printed by the run script in parsec_fs.py).

Writes fault_summary.csv (one row per fault) and outcome_distribution.png
into the campaign directory.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

OUTCOMES = ("masked", "sdc", "crash", "hang")

CONSOLE = "board.pc.com_1.device"
OUTPUT_BEGIN = "[PARSEC] [---------- Beginning of output ----------]"
OUTPUT_END = "[PARSEC] [----------    End of output    ----------]"

# Lines whose content depends on (simulated) wall-clock time.
TIMING_LINE = re.compile(
    r"^(real|user|sys)\s|\[HOOKS\]"
    r"|\b(time|timing|elapsed|seconds?|secs?|fps|ms|throughput|speed)\b",
    re.IGNORECASE,
)
SIMULATOR_ERROR = re.compile(
    r"^(\S+: )?(panic|fatal): |Possible Deadlock|^Traceback \(most recent"
)
KERNEL_ERROR = re.compile(
    r"Kernel panic|Oops|BUG: |general protection fault|soft lockup"
)
APPLICATION_ERROR = re.compile(
    r"Segmentation fault|Bus error|Illegal instruction|Aborted"
    r"|core dumped|Floating point exception|Killed|terminate called"
    r"|double free|stack smashing|Assertion .* failed"
)
# parsecmgmt tees the benchmark's console output, timing lines included,
# into the run directory; that output is compared without timing lines.
IGNORED_FILES = {"benchmark.out"}
INJECTION = re.compile(
    r"(RUBY_FAULT_INJECTED|RUBY_DATA_FAULT_INJECTED|RUBY_FAULT_NOT_INJECTED)"
    r"(.*)"
)


def read_lines(path):
    if not path.exists():
        return []
    return path.read_text(errors="replace").splitlines()


def parse_console(lines):
    """Extract the benchmark output and the output-file hashes."""
    program, files = [], {}
    section = None
    fingerprinted = False
    for line in lines:
        line = line.rstrip("\r")
        if line == OUTPUT_BEGIN:
            section = "program"
        elif line in (OUTPUT_END, "FI_PROGRAM_END"):
            section = None
        elif line == "FI_OUTPUT_FILES_BEGIN":
            section = "files"
        elif line == "FI_OUTPUT_FILES_END":
            section = None
            fingerprinted = True
        elif section == "program":
            program.append(line)
        elif section == "files":
            digest, _, name = line.partition("  ")
            if name and name not in IGNORED_FILES:
                files[name] = digest
    return {
        "program": program,
        "comparable": [l for l in program if not TIMING_LINE.search(l)],
        "files": files,
        "fingerprinted": fingerprinted,
    }


def first_match(pattern, lines):
    for line in lines:
        if pattern.search(line):
            return line.strip()
    return None


def compare_output(run, golden):
    """Return a description of how run differs from golden, or None."""
    differences = []
    if run["comparable"] != golden["comparable"]:
        differences.append("benchmark output differs")
    for name, digest in sorted(golden["files"].items()):
        if name not in run["files"]:
            differences.append(f"{name} missing")
        elif run["files"][name] != digest:
            differences.append(f"{name} differs")
    for name in sorted(set(run["files"]) - set(golden["files"])):
        differences.append(f"unexpected file {name}")
    return "; ".join(differences) or None


def classify(folder, golden, host_status):
    """Classify one fault run; returns (outcome, detail)."""
    log = read_lines(folder / "gem5.log")
    console_lines = read_lines(folder / CONSOLE)
    console = parse_console(console_lines)
    status_file = folder / "run_status.json"
    state = json.loads(status_file.read_text()) if status_file.exists() else {}

    error = first_match(SIMULATOR_ERROR, log)
    if error:
        return "crash", f"simulator: {error}"
    if host_status == "timeout":
        return "hang", "host timeout"
    if host_status != "ok":
        return "crash", f"simulator: gem5 {host_status}"
    error = first_match(KERNEL_ERROR, console_lines)
    if error:
        return "crash", f"kernel: {error}"
    error = first_match(APPLICATION_ERROR, console["program"])
    if error:
        return "crash", f"application: {error}"
    if not state.get("script_done"):
        roi = "finished" if state.get("roi_end_tick") else "not finished"
        return "hang", f"tick limit reached (ROI {roi})"
    if not console["fingerprinted"]:
        return "crash", "application: run script did not complete"
    difference = compare_output(console, golden)
    if difference:
        return "sdc", difference
    return "masked", "output matches baseline"


def injection_info(folder):
    """What the injector reported: (injected, line, old_state, new_state)."""
    for line in read_lines(folder / "gem5.log"):
        match = INJECTION.search(line)
        if not match:
            continue
        tag, rest = match.groups()
        fields = dict(re.findall(r"(\w+)=(\S+)", rest))
        injected = "no" if tag == "RUBY_FAULT_NOT_INJECTED" else "yes"
        old = fields.get("old_state", fields.get("old_byte", ""))
        new = fields.get("new_state", fields.get("new_byte", ""))
        return (
            injected,
            fields.get("line", ""),
            old,
            new,
            fields.get("reason", ""),
        )
    return "unknown", "", "", "", ""


def summarize(campaign_dir):
    campaign_dir = Path(campaign_dir)
    golden = parse_console(read_lines(campaign_dir / "baseline" / CONSOLE))
    if not golden["fingerprinted"]:
        raise RuntimeError(
            f"{campaign_dir}/baseline has no output fingerprint; the "
            "baseline must run to the end of the benchmark"
        )
    host = {}
    results_file = campaign_dir / "results.json"
    if results_file.exists():
        host = {
            r["index"]: r["status"]
            for r in json.loads(results_file.read_text())
        }

    rows = []
    for folder in sorted(campaign_dir.glob("fault_[0-9]*")):
        index = int(folder.name.split("_")[1])
        fault = json.loads((folder / "fault.json").read_text())
        outcome, detail = classify(folder, golden, host.get(index, "ok"))
        injected, line, old, new, reason = injection_info(folder)
        rows.append(
            {
                "fault_index": index,
                "fault_type": fault.get("fault_type", ""),
                "target": fault.get("target", ""),
                "core": fault.get("core", ""),
                "idx": fault.get("idx", ""),
                "bit": fault.get("bit", ""),
                "forced_state": fault.get("state", ""),
                "cycle": fault.get("cycle", ""),
                "tick": fault.get("tick", ""),
                "injected": injected,
                "not_injected_reason": reason,
                "line_address": line,
                "old_value": old,
                "new_value": new,
                "outcome": outcome,
                "detail": detail,
            }
        )

    if not rows:
        raise RuntimeError(f"No fault_* runs in {campaign_dir}")
    with (campaign_dir / "fault_summary.csv").open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    plot(rows, campaign_dir)

    counts = Counter(row["outcome"] for row in rows)
    for outcome in OUTCOMES:
        print(
            f"{outcome:7s} {counts[outcome]:5d} "
            f"({100 * counts[outcome] / len(rows):5.1f}%)"
        )
    skipped = sum(row["injected"] == "no" for row in rows)
    if skipped:
        print(f"({skipped} masked runs are faults the injector skipped)")
    print(f"Wrote {campaign_dir / 'fault_summary.csv'}")
    print(f"Wrote {campaign_dir / 'outcome_distribution.png'}")
    return rows


# Status palette: outcomes are states, and each colour is always paired
# with its label.
COLORS = {
    "masked": "#0ca30c",
    "hang": "#fab219",
    "sdc": "#ec835a",
    "crash": "#d03b3b",
}
LABELS = {"masked": "Masked", "sdc": "SDC", "crash": "Crash", "hang": "Hang"}
FAULT_TYPES = {"state": "Coherence state", "data_bitflip": "Data bit flip"}
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot(rows, campaign_dir):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    total = len(rows)
    counts = Counter(row["outcome"] for row in rows)
    types = [t for t in FAULT_TYPES if any(r["fault_type"] == t for r in rows)]
    by_type = len(types) > 1

    plt.rcParams.update(
        {
            "font.size": 10,
            "text.color": TEXT,
            "axes.labelcolor": TEXT_2,
            "xtick.color": TEXT_2,
            "ytick.color": TEXT,
        }
    )
    fig, axes = plt.subplots(
        2 if by_type else 1,
        1,
        figsize=(8, 5.6 if by_type else 3.4),
        gridspec_kw={"height_ratios": [4, len(types)]} if by_type else None,
        facecolor=SURFACE,
    )
    axes = list(axes) if by_type else [axes]

    config = {}
    config_file = campaign_dir / "experiment.json"
    if config_file.exists():
        config = json.loads(config_file.read_text())
    workload = config.get("workload", {})
    target = rows[0]["target"]
    title = "Fault outcomes"
    if workload:
        title += f": {workload['benchmark']} ({workload['size']})"
    fig.suptitle(title, x=0.02, ha="left", fontsize=13, fontweight="bold")
    subtitle = f"{total} faults injected into {target}"
    skipped = sum(row["injected"] == "no" for row in rows)
    if skipped:
        subtitle += f"; Masked includes {skipped} the injector skipped"
    fig.text(0.02, 0.905 if by_type else 0.83, subtitle, color=TEXT_2)

    # Overall count per outcome.
    ax = axes[0]
    order = list(reversed(OUTCOMES))
    values = [counts[o] for o in order]
    ax.barh(
        [LABELS[o] for o in order],
        values,
        height=0.6,
        color=[COLORS[o] for o in order],
    )
    for y, value in enumerate(values):
        ax.text(
            value + total * 0.01,
            y,
            f"{value}  ({100 * value / total:.1f}%)",
            va="center",
            color=TEXT,
        )
    ax.set_xlim(0, total * 1.18)
    ax.set_xlabel("Fault runs")
    style(ax)

    # Share of each outcome per fault type (100% stacked).
    if by_type:
        ax = axes[1]
        for y, fault_type in enumerate(reversed(types)):
            subset = [r for r in rows if r["fault_type"] == fault_type]
            type_counts = Counter(r["outcome"] for r in subset)
            left = 0.0
            for outcome in OUTCOMES:
                share = 100 * type_counts[outcome] / len(subset)
                if not share:
                    continue
                ax.barh(
                    y,
                    share,
                    left=left,
                    height=0.6,
                    color=COLORS[outcome],
                    edgecolor=SURFACE,
                    linewidth=2,
                    label=LABELS[outcome] if y == 0 else None,
                )
                if share >= 8:
                    ax.text(
                        left + share / 2,
                        y,
                        f"{share:.0f}%",
                        ha="center",
                        va="center",
                        color=TEXT,
                    )
                left += share
        ax.set_yticks(
            range(len(types)),
            [
                f"{FAULT_TYPES[t]} (n={sum(r['fault_type'] == t for r in rows)})"
                for t in reversed(types)
            ],
        )
        ax.set_xlim(0, 100)
        ax.set_xlabel("Share of fault runs (%)")
        handles = [
            plt.Rectangle((0, 0), 1, 1, color=COLORS[o]) for o in OUTCOMES
        ]
        ax.legend(
            handles,
            [LABELS[o] for o in OUTCOMES],
            ncol=4,
            frameon=False,
            loc="lower left",
            bbox_to_anchor=(0, 1.0),
        )
        style(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.9 if by_type else 0.82))
    fig.savefig(campaign_dir / "outcome_distribution.png", dpi=200)
    plt.close(fig)


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", color=GRID)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    summarize(sys.argv[1])
