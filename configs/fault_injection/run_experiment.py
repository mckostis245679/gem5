#!/usr/bin/env python3
"""python3 run_experiment.py [experiment.json]"""

import ast
import fcntl
import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fault_outcomes import summarize

HERE = Path(__file__).resolve().parent

# System settings the ROI checkpoint depends on. Cache geometry, L2 banks
# and the detailed CPU type are not part of it (the checkpoint is taken on
# KVM, which bypasses the Ruby caches), so campaigns varying only those
# share a checkpoint.
CHECKPOINT_SYSTEM_KEYS = ("isa", "num_cores", "memory_size", "clk_freq")


def run_script_text():
    """parsec_fs.RUN_SCRIPT, read without importing gem5."""
    tree = ast.parse((HERE / "parsec_fs.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "RUN_SCRIPT"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError("RUN_SCRIPT not found in parsec_fs.py")


def checkpoint_key(config):
    """Name and description of the guest setup a checkpoint captures.

    A rebuilt disk image or a changed guest run script (read before the
    checkpoint) also needs a new boot.
    """
    workload = config["workload"]
    system = config["system"]
    image = Path(workload["disk_image"]).expanduser().resolve()
    key = {
        "workload": workload,
        "system": {k: system[k] for k in CHECKPOINT_SYSTEM_KEYS},
        "disk_image": {
            "path": str(image),
            "size": image.stat().st_size,
            "mtime_ns": image.stat().st_mtime_ns,
        },
        "run_script": run_script_text(),
    }
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True).encode()
    ).hexdigest()[:12]
    name = (
        f"{workload['benchmark']}_{workload['size']}_"
        f"{system['num_cores']}c_{digest}"
    )
    return name, key


def main():
    config_path = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else HERE / "experiment.json"
    )
    config = json.loads(config_path.read_text())
    system, campaign, runtime = (
        config[key] for key in ("system", "campaign", "runtime")
    )
    runtime.setdefault("checkpoint_dir", "checkpoints")
    # Resolve paths once, before each simulation changes to its own directory.
    for key in (
        "gem5_binary",
        "fault_module_path",
        "output_dir",
        "checkpoint_dir",
    ):
        if runtime[key] is not None:
            runtime[key] = str(
                (
                    config_path.parent / Path(runtime[key]).expanduser()
                ).resolve()
            )

    output = Path(runtime["output_dir"]) / datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )
    output.mkdir(parents=True, exist_ok=False)
    saved_config = output / "experiment.json"
    saved_config.write_text(json.dumps(config, indent=2))
    print(f"Results: {output}", flush=True)

    gem5 = [runtime["gem5_binary"], "--listener-mode=off"]
    if runtime["fault_module_path"]:
        gem5 += ["--path", runtime["fault_module_path"]]

    def run_gem5(script, folder, extra, timeout):
        folder.mkdir(parents=True, exist_ok=True)
        command = (
            gem5
            + [
                f"--outdir={folder}",
                str(HERE / script),
                "--config",
                str(saved_config),
            ]
            + extra
        )
        with (folder / "gem5.log").open("w") as log:
            subprocess.run(
                command,
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
            )

    # 0. Boot Linux with KVM and checkpoint at the start of the PARSEC ROI,
    # once per guest setup. The KVM boot is not deterministic, so every
    # campaign with the same setup restores the same checkpoint; that way
    # the benchmark's execution only depends on what the campaign varies.
    name, key = checkpoint_key(config)
    checkpoint_dir = Path(runtime["checkpoint_dir"])
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    stored = checkpoint_dir / name
    checkpoint = stored / "cpt"
    # Campaigns started together with the same setup wait for one boot
    # instead of racing on the same directories.
    with open(checkpoint_dir / f"{name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (checkpoint / "m5.cpt").exists():
            print(f"Reusing ROI checkpoint: {checkpoint}", flush=True)
        else:
            # Leftovers of an interrupted boot.
            partial = stored.with_name(f"{name}.partial")
            shutil.rmtree(stored, ignore_errors=True)
            shutil.rmtree(partial, ignore_errors=True)
            run_gem5(
                "run_mesi_checkpoint.py",
                partial / "boot",
                ["--checkpoint-dir", str(partial / "cpt")],
                runtime["checkpoint_timeout_seconds"],
            )
            (partial / "key.json").write_text(json.dumps(key, indent=2))
            partial.rename(stored)
            print(f"New ROI checkpoint: {checkpoint}", flush=True)
    (output / "checkpoint").symlink_to(stored)

    # 1. Baseline restores the checkpoint and writes the ROI cycles and ticks.
    baseline_file = output / "baseline.json"
    started = time.monotonic()
    run_gem5(
        "run_mesi_baseline.py",
        output / "baseline",
        ["--checkpoint", str(checkpoint), "--cycles-file", str(baseline_file)],
        runtime["baseline_timeout_seconds"],
    )
    baseline_seconds = time.monotonic() - started
    baseline = json.loads(baseline_file.read_text())
    print(f"Baseline cycles: {baseline['cycles']}", flush=True)

    # Hangs are detected by the tick limit below; the host timeout is only a
    # safety net, so it must leave room for a run that reaches that limit
    # while slowed down by the other parallel runs (2x margin).
    fault_timeout = max(
        runtime["fault_timeout_seconds"],
        2 * runtime["fault_max_ticks_factor"] * baseline_seconds,
    )
    print(
        f"Baseline took {baseline_seconds:.0f} s; fault run host timeout "
        f"{fault_timeout:.0f} s",
        flush=True,
    )

    # 2. Call the ORIGINAL mask generator through its existing CLI.
    def kib(size):
        # Its CLI accepts integer KiB, so reject sizes that cannot be represented.
        for unit, multiplier in (
            ("KiB", 1024),
            ("MiB", 1024**2),
            ("GiB", 1024**3),
            ("B", 1),
        ):
            if size.endswith(unit):
                size_bytes = int(size[: -len(unit)]) * multiplier
                if size_bytes <= 0 or size_bytes % 1024:
                    break
                return size_bytes // 1024
        raise ValueError(f"Use a positive whole-KiB cache size: {size}")

    campaign_file = output / "fault_campaign.json"
    command = [
        sys.executable,
        str(HERE / "mask_generator.py"),
        "--l1d-size-kib",
        str(kib(system["l1d_size"])),
        "--l1d-assoc",
        str(system["l1d_assoc"]),
        "--l2-size-kib",
        str(kib(system["l2_size"])),
        "--l2-assoc",
        str(system["l2_assoc"]),
        "--num-cores",
        str(system["num_cores"]),
        "--cycles",
        str(baseline["cycles"]),
        "--confidence",
        str(campaign["confidence"]),
        "--error",
        str(campaign["error"]),
        "--fault-type",
        campaign["fault_type"],
        "--target",
        campaign["target"],
        "--output",
        str(campaign_file),
    ]
    if campaign["seed"] is not None:
        command += ["--seed", str(campaign["seed"])]
    subprocess.run(command, check=True)
    faults = json.loads(campaign_file.read_text())["faults"]
    # Optional cap for quick smoke tests; it breaks the campaign's
    # statistical sample size, so leave it null for real campaigns.
    if runtime.get("fault_limit"):
        faults = faults[: runtime["fault_limit"]]

    # 3. Each free worker takes the next fault and launches a separate gem5 process.
    # Ticks are absolute, and the ROI begins at the checkpoint tick. Fault
    # runs continue until the benchmark finishes, so the limit scales the
    # baseline's whole run, not just its ROI.
    roi_start = baseline["roi_start_tick"]
    max_ticks = str(
        roi_start
        + int(baseline["end_ticks"] * runtime["fault_max_ticks_factor"])
    )

    def run_fault(item):
        index, fault = item
        folder = output / f"fault_{index:06d}"
        folder.mkdir()
        fault_file = folder / "fault.json"
        # Convert the selected 0-based ROI cycle into the absolute tick expected
        # by the injector; it must lie after the checkpoint tick it restores at.
        fault = dict(fault)
        fault["tick"] = (
            roi_start + (fault["cycle"] + 1) * baseline["clock_period_ticks"]
        )
        fault_file.write_text(json.dumps(fault, indent=2))
        try:
            run_gem5(
                "run_mesi_fault.py",
                folder,
                [
                    "--checkpoint",
                    str(checkpoint),
                    "--fault-json",
                    str(fault_file),
                    "--max-ticks",
                    max_ticks,
                ],
                fault_timeout,
            )
            status = "ok"
        except subprocess.TimeoutExpired:
            status = "timeout"
        except subprocess.CalledProcessError as error:
            status = f"exit {error.returncode}"
        except OSError as error:
            status = f"error {error}"
        print(f"Fault {index}: {status}", flush=True)
        return {"index": index, "status": status}

    with ThreadPoolExecutor(max_workers=runtime["parallel_jobs"]) as pool:
        results = list(pool.map(run_fault, enumerate(faults)))
    (output / "results.json").write_text(json.dumps(results, indent=2))

    # 4. Classify every run (masked/sdc/crash/hang), write fault_summary.csv
    # and outcome_distribution.png. A failing gem5 run is an outcome here,
    # not an error of the campaign.
    summarize(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
