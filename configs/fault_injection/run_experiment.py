#!/usr/bin/env python3
"""python3 run_experiment.py [experiment.json]"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


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
    # Resolve paths once, before each simulation changes to its own directory.
    for key in ("gem5_binary", "fault_module_path", "output_dir"):
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

    # 0. Boot Linux with KVM and checkpoint at the start of the PARSEC ROI.
    checkpoint = output / "checkpoint"
    run_gem5(
        "run_mesi_checkpoint.py",
        output / "boot",
        ["--checkpoint-dir", str(checkpoint)],
        runtime["checkpoint_timeout_seconds"],
    )
    print(f"ROI checkpoint: {checkpoint}", flush=True)

    # 1. Baseline restores the checkpoint and writes the ROI cycles and ticks.
    baseline_file = output / "baseline.json"
    run_gem5(
        "run_mesi_baseline.py",
        output / "baseline",
        ["--checkpoint", str(checkpoint), "--cycles-file", str(baseline_file)],
        runtime["baseline_timeout_seconds"],
    )
    baseline = json.loads(baseline_file.read_text())
    print(f"Baseline cycles: {baseline['cycles']}", flush=True)

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

    # 3. Each free worker takes the next fault and launches a separate gem5 process.
    # Ticks are absolute, and the ROI begins at the checkpoint tick.
    roi_start = baseline["roi_start_tick"]
    max_ticks = str(
        roi_start + int(baseline["ticks"] * runtime["fault_max_ticks_factor"])
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
                runtime["fault_timeout_seconds"],
            )
            status = "ok"
        except (subprocess.SubprocessError, OSError) as error:
            status = str(error)
        print(f"Fault {index}: {status}", flush=True)
        return {"index": index, "status": status}

    with ThreadPoolExecutor(max_workers=runtime["parallel_jobs"]) as pool:
        results = list(pool.map(run_fault, enumerate(faults)))
    (output / "results.json").write_text(json.dumps(results, indent=2))
    return 0 if all(result["status"] == "ok" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
