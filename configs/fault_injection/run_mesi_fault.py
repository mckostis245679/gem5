#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from fault_injecting_mesi import (
    FaultInjectingMESITwoLevel,
)

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.memory.single_channel import (
    SingleChannelDDR3_1600,
)
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import (
    SimpleProcessor,
)
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource, FileResource
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires



def load_fault(path):
    with path.open("r") as fault_file:
        fault = json.load(fault_file)

    return fault


parser = argparse.ArgumentParser(
    description=(
        "Run two-core MESI Two Level using a "
        "fault description loaded from JSON."
    )
)

parser.add_argument(
    "--binary",
    required=True,
    help="Path to a statically linked x86 workload",
)

parser.add_argument(
    "--fault-json",
    required=True,
    type=Path,
    help="Path to the generated fault JSON file",
)

parser.add_argument("--config", required=True)
parser.add_argument("--max-ticks", type=int)
args = parser.parse_args()

with open(args.config) as config_file:
    config = json.load(config_file)
system = config["system"]

requires(
    isa_required=ISA[system["isa"].upper()],
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
)

fault = load_fault(args.fault_json)

print("Loaded fault:")

print(json.dumps(fault, indent=4))
print(f"Target cache idx: {fault['idx']}")


cache_hierarchy = FaultInjectingMESITwoLevel(
    fault=fault,
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
if args.max_ticks is not None:
    simulator.set_max_ticks(args.max_ticks)
simulator.run()


print(
    "Exiting at tick {} because: {}".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)