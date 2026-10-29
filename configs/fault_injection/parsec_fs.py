"""
Full-system X86 board running a PARSEC 3.0 benchmark from the Ubuntu
24.04 PARSEC disk image built by disk-image/build-x86.sh. Shared by the
checkpoint, baseline and fault scripts so that all of them build an
identical system.

The image's PARSEC hooks mark the ROI with hypercalls 4 (work begin) and
5 (work end); the image sends hypercall 3 once the run script finishes.
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

# Kernel arguments of gem5's x86-ubuntu-24.04-boot-with-systemd workload;
# the root file system is on the image's second partition.
KERNEL_ARGS = [
    "earlyprintk=ttyS0",
    "console=ttyS0",
    "lpj=7999923",
    "root=/dev/sda2",
]


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

    # Run by the image's after_boot.sh, as the gem5 user, via readfile.
    command = (
        "#!/bin/bash\n"
        "cd /home/gem5/parsec-benchmark\n"
        "source env.sh\n"
        f"parsecmgmt -a run -p {workload['benchmark']} -c gcc-hooks "
        f"-i {workload['size']} -n {config['system']['num_cores']}\n"
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
