"""
Full-system X86 board running a PARSEC 3.0 benchmark from the Ubuntu
24.04 PARSEC disk image built by disk-image/build-x86.sh. Shared by the
checkpoint, baseline and fault scripts so that all of them build an
identical system.

The image's PARSEC hooks mark the ROI with hypercalls 4 (work begin) and
5 (work end). Once the benchmark exits, the run script prints a SHA-256 of
every file the benchmark wrote between the FI_OUTPUT_FILES_* markers on
the console, which fault_outcomes.py compares against the baseline, and
ends the simulation with hypercall 3.
"""

from pathlib import Path

from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import (
    DiskImageResource,
    obtain_resource,
)
from gem5.simulate.exit_handler import (
    AfterBootScriptExitHandler,
    WorkEndExitHandler,
)
from gem5.utils.override import overrides

# Kernel arguments of gem5's x86-ubuntu-24.04-boot-with-systemd workload;
# the root file system is on the image's second partition.
KERNEL_ARGS = [
    "earlyprintk=ttyS0",
    "console=ttyS0",
    "lpj=7999923",
    "root=/dev/sda2",
]

# Run by the image's after_boot.sh, as the gem5 user, via readfile; it is
# read before the ROI checkpoint, so changing it needs a new checkpoint.
# parsecmgmt runs the benchmark through fi_submit.sh (-s), which prints the
# output fingerprint as soon as the benchmark exits and then ends the
# simulation, skipping parsecmgmt's post-run work on the slow detailed CPU.
# fi_submit.sh writes to the console directly because parsecmgmt pipes the
# benchmark's output through tee. The input list is built before the ROI.
RUN_SCRIPT = r"""#!/bin/bash
cd /home/gem5/parsec-benchmark
source env.sh
console=$(readlink -f /proc/$$/fd/1)
echo benchmark.out > /tmp/inputs.lst
input_tar=$(ls pkgs/*/@BENCH@/inputs/input_@SIZE@.tar 2>/dev/null)
[ -n "$input_tar" ] && tar tf "$input_tar" | sed 's|^\./||' >> /tmp/inputs.lst
cat > /tmp/fi_submit.sh <<EOF
#!/bin/bash
exec >> $console 2>&1
time "\$@"
echo FI_PROGRAM_END
echo FI_OUTPUT_FILES_BEGIN
find . -type f | sed 's|^\./||' | sort | grep -vxFf /tmp/inputs.lst \
    | xargs -r -d '\n' sha256sum
echo FI_OUTPUT_FILES_END
gem5-bridge hypercall 3
EOF
chmod +x /tmp/fi_submit.sh
parsecmgmt -a run -p @BENCH@ -c gcc-hooks -i @SIZE@ -n @THREADS@ \
    -s /tmp/fi_submit.sh
"""


def build_board(config, cpu_type, cache_hierarchy):
    system = config["system"]

    processor = SimpleProcessor(
        cpu_type=cpu_type,
        isa=ISA.X86,
        num_cores=system["num_cores"],
        clk_freq=system["clk_freq"],
    )
    if cpu_type == CPUTypes.KVM:
        # Host perf counters are usually locked down
        # (perf_event_paranoid > 1) and are not needed to boot.
        for core in processor.get_cores():
            core.core.usePerf = False

    memory = SingleChannelDDR3_1600(size=system["memory_size"])

    return X86Board(
        clk_freq=system["clk_freq"],
        processor=processor,
        memory=memory,
        cache_hierarchy=cache_hierarchy,
    )


def checkpoint_tick(checkpoint):
    """Tick at which the checkpoint was taken (globals section curTick).

    gem5 v26 renamed the section from [Globals] to [root.globals].
    """
    in_globals = False
    with open(f"{checkpoint}/m5.cpt") as cpt:
        for line in cpt:
            line = line.strip()
            if line.startswith("["):
                in_globals = line in ("[root.globals]", "[Globals]")
            elif in_globals and line.startswith("curTick="):
                return int(line.split("=", 1)[1])
    raise ValueError(f"No curTick in {checkpoint}/m5.cpt")


def set_parsec_workload(board, config, checkpoint=None):
    workload = config["workload"]
    bench = workload["benchmark"]
    size = workload["size"]

    # Run by the image's after_boot.sh, as the gem5 user, via readfile.
    command = (
        RUN_SCRIPT.replace("@BENCH@", bench)
        .replace("@SIZE@", size)
        .replace("@THREADS@", str(config["system"]["num_cores"]))
    )

    board.set_kernel_disk_workload(
        kernel=obtain_resource(
            workload["kernel"],
            resource_version=workload["kernel_version"],
        ),
        disk_image=DiskImageResource(
            local_path=str(Path(workload["disk_image"]).expanduser()),
            root_partition="2",
        ),
        kernel_args=KERNEL_ARGS,
        readfile_contents=command,
        checkpoint=checkpoint,
    )


def run_to_script_end(simulator, max_ticks=None):
    """Run a restored simulation until the guest's run script finishes.

    The benchmark writes its output after the ROI, so the run continues
    past the work-end hypercall (stats are still dumped there) until the
    run script's hypercall 3. Returns the ROI end tick (None if the ROI
    never finished), whether the run script finished, and the final tick.
    """
    state = {"roi_end_tick": None, "script_done": False}

    class RecordROIEnd(WorkEndExitHandler):
        @overrides(WorkEndExitHandler)
        def _process(self, simulator):
            state["roi_end_tick"] = simulator.get_current_tick()
            super()._process(simulator)

    class RecordScriptEnd(AfterBootScriptExitHandler):
        @overrides(AfterBootScriptExitHandler)
        def _process(self, simulator):
            state["script_done"] = True

    if max_ticks is not None:
        simulator.set_max_ticks(max_ticks)
    simulator.run()
    state["final_tick"] = simulator.get_current_tick()
    state["max_ticks"] = max_ticks
    return state
