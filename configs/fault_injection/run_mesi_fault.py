#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from fault_injecting_mesi import (
    FaultInjectingMESITwoLevel,
)
from parsec_fs import (
    build_board,
    set_parsec_workload,
)

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.processors.cpu_types import CPUTypes
from gem5.isas import ISA
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires


def load_fault(path):
    with path.open("r") as fault_file:
        fault = json.load(fault_file)

    return fault


parser = argparse.ArgumentParser(
    description=(
        "Restore the PARSEC ROI checkpoint on a MESI Two Level "
        "full-system board and inject a fault loaded from JSON."
    )
)

parser.add_argument(
    "--checkpoint",
    required=True,
    type=Path,
    help="ROI checkpoint created by run_mesi_checkpoint.py",
)

parser.add_argument(
    "--fault-json",
    required=True,
    type=Path,
    help="Path to the generated fault JSON file",
)

parser.add_argument("--config", required=True)
parser.add_argument(
    "--max-ticks",
    type=int,
    help="Absolute tick at which to stop the simulation",
)
args = parser.parse_args()

with open(args.config) as config_file:
    config = json.load(config_file)
system = config["system"]

requires(
    isa_required=ISA.X86,
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


board = build_board(
    config, CPUTypes[system["cpu_type"].upper()], cache_hierarchy
)
set_parsec_workload(board, config, checkpoint=args.checkpoint)


def on_workend():
    print("ROI finished")
    yield True


simulator = Simulator(
    board=board,
    on_exit_event={ExitEvent.WORKEND: on_workend()},
)
if args.max_ticks is not None:
    simulator.set_max_ticks(args.max_ticks)
simulator.run()


print(
    "Exiting at tick {} because: {}".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)
