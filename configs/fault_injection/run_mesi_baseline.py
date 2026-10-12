#!/usr/bin/env python3

import argparse

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

requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
)

parser = argparse.ArgumentParser()
parser.add_argument("--binary", required=True)
args = parser.parse_args()

cache_hierarchy = MESITwoLevelCacheHierarchy(
    l1i_size="2KiB",
    l1i_assoc=8,
    l1d_size="2KiB",
    l1d_assoc=8,
    l2_size="4KiB",
    l2_assoc=8,
    num_l2_banks=1,
)

processor = SimpleProcessor(
    cpu_type=CPUTypes.TIMING,
    isa=ISA.X86,
    num_cores=2,
)

memory = SingleChannelDDR3_1600(size="1GiB")

board = SimpleBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

board.set_se_binary_workload(BinaryResource(local_path=args.binary))

simulator = Simulator(board=board)
simulator.run()

print(
    "Exiting at tick {} because: {}".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)
