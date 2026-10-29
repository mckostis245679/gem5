"""
Full-system X86 board running a PARSEC benchmark from the gem5
x86-parsec disk image. Shared by the checkpoint, baseline and fault
scripts so that all of them build an identical system.
"""

from gem5.components.boards.x86_board import X86Board
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import obtain_resource


def build_board(config, cpu_type, cache_hierarchy):
    system = config["system"]

    processor = SimpleProcessor(
        cpu_type=cpu_type,
        isa=ISA.X86,
        num_cores=system["num_cores"],
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
    """Tick at which the checkpoint was taken ([Globals] curTick)."""
    in_globals = False
    with open(f"{checkpoint}/m5.cpt") as cpt:
        for line in cpt:
            line = line.strip()
            if line.startswith("["):
                in_globals = line == "[Globals]"
            elif in_globals and line.startswith("curTick="):
                return int(line.split("=", 1)[1])
    raise ValueError(f"No curTick in {checkpoint}/m5.cpt")


def set_parsec_workload(board, config, checkpoint=None):
    workload = config["workload"]

    # Executed by the image's init script through `m5 readfile`.
    # The gcc-hooks build emits m5 workbegin/workend around the ROI.
    command = (
        "cd /home/gem5/parsec-benchmark;"
        "source env.sh;"
        f"parsecmgmt -a run -p {workload['benchmark']} -c gcc-hooks "
        f"-i {workload['size']} -n {config['system']['num_cores']};"
        "sleep 5;"
        "m5 exit;"
    )

    board.set_kernel_disk_workload(
        kernel=obtain_resource(
            workload["kernel"],
            resource_version=workload["kernel_version"],
        ),
        disk_image=obtain_resource(
            workload["disk_image"],
            resource_version=workload["disk_image_version"],
        ),
        readfile_contents=command,
        checkpoint=checkpoint,
    )
