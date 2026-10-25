#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource, FileResource
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires


parser = argparse.ArgumentParser()
parser.add_argument("--binary", required=True)
parser.add_argument("--config", required=True)
parser.add_argument("--cycles-file", required=True)
args = parser.parse_args()

with open(args.config) as config_file:
    config = json.load(config_file)
system = config["system"]

requires(
    isa_required=ISA[system["isa"].upper()],
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
)

cache_hierarchy = MESITwoLevelCacheHierarchy(
    l1i_size=system["l1i_size"],
    l1i_assoc=system["l1i_assoc"],
    l1d_size=system["l1d_size"],
    l1d_assoc=system["l1d_assoc"],
    l2_size=system["l2_size"],
    l2_assoc=system["l2_assoc"],
    num_l2_banks=system["l2_banks"],
)

processor = SimpleProcessor(
    cpu_type=CPUTypes[system["cpu_type"].upper()],
    isa=ISA[system["isa"].upper()],
    num_cores=system["num_cores"],
)

memory = SingleChannelDDR3_1600(size=system["memory_size"])

board = SimpleBoard(
    clk_freq=system["clk_freq"],
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

workload_options = {"arguments": config["workload"]["arguments"]}
if config["workload"]["stdin"]:
    workload_options["stdin_file"] = FileResource(local_path=config["workload"]["stdin"])
board.set_se_binary_workload(BinaryResource(local_path=args.binary), **workload_options)

simulator = Simulator(board=board)
simulator.run()

if simulator.get_last_exit_event_code() != 0:
    raise RuntimeError("Baseline workload failed; inspect the baseline log")

ticks = int(simulator.get_current_tick())
period = int(board.get_clock_domain().clock[0].period.getValue())
cycles = (ticks + period - 1) // period

Path(args.cycles_file).write_text(
    json.dumps({
        "cycles": cycles,
        "ticks": ticks,
        "clock_period_ticks": period,  
    })
)

print(f"Execution cycles: {cycles}")

print(
    "Exiting at tick {} because: {}".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)