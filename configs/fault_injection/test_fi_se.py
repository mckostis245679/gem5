#!/usr/bin/env python3
"""
Small SE-mode smoke test for the MESI Two Level fault injector.

Runs a 2-core TIMING system with tiny caches. Without --fault-type it
runs a fault-free baseline; otherwise it schedules a single fault through
FaultInjectingMESITwoLevel.

Example:
    build/X86_MESI/gem5.opt configs/fault_injection/test_fi_se.py \
        --binary configs/fault_injection/microbenchmarks/build/true-sharing \
        --args 6 --fault-type state --target L1D --idx 0 \
        --tick 50000000 --state I
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fault_injecting_mesi import FaultInjectingMESITwoLevel

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--binary", required=True)
parser.add_argument("--args", nargs="*", default=[])
parser.add_argument(
    "--fault-type",
    choices=["state", "data_bitflip"],
    help="Omit to run a fault-free baseline",
)
parser.add_argument("--target", choices=["L1D", "L1I", "L2"], default="L1D")
parser.add_argument("--core", type=int, default=0)
parser.add_argument("--idx", type=int, default=0)
parser.add_argument("--tick", type=int, default=0)
parser.add_argument("--state", default="I")
parser.add_argument("--bit", type=int, default=0)
parser.add_argument("--max-ticks", type=int)
args = parser.parse_args()

requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
)

cache_params = dict(
    l1i_size="2KiB",
    l1i_assoc=8,
    l1d_size="2KiB",
    l1d_assoc=8,
    l2_size="4KiB",
    l2_assoc=8,
    num_l2_banks=1,
)

if args.fault_type is None:
    cache_hierarchy = MESITwoLevelCacheHierarchy(**cache_params)
else:
    fault = {
        "target": args.target,
        "core": args.core,
        "idx": args.idx,
        "tick": args.tick,
        "fault_type": args.fault_type,
        "state": args.state,
        "bit": args.bit,
    }
    print(f"Scheduled fault: {fault}")
    cache_hierarchy = FaultInjectingMESITwoLevel(fault=fault, **cache_params)

board = SimpleBoard(
    clk_freq="3GHz",
    processor=SimpleProcessor(
        cpu_type=CPUTypes.TIMING, isa=ISA.X86, num_cores=2
    ),
    memory=SingleChannelDDR3_1600(size="1GiB"),
    cache_hierarchy=cache_hierarchy,
)
board.set_se_binary_workload(
    BinaryResource(local_path=args.binary), arguments=args.args
)

simulator = Simulator(board=board)
if args.max_ticks is not None:
    simulator.set_max_ticks(args.max_ticks)
simulator.run()

print(
    f"Exiting at tick {simulator.get_current_tick()} because: "
    f"{simulator.get_last_exit_event_cause()}"
)
