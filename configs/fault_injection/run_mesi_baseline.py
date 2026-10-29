#!/usr/bin/env python3
"""
Restore the ROI checkpoint and run the PARSEC ROI fault-free on the
configured (timing) CPU, recording how long the ROI takes.
"""

import argparse
import json
from pathlib import Path

from parsec_fs import (
    build_board,
    checkpoint_tick,
    set_parsec_workload,
)

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.processors.cpu_types import CPUTypes
from gem5.isas import ISA
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

parser = argparse.ArgumentParser()
parser.add_argument("--checkpoint", required=True, type=Path)
parser.add_argument("--config", required=True)
parser.add_argument("--cycles-file", required=True)
args = parser.parse_args()

with open(args.config) as config_file:
    config = json.load(config_file)
system = config["system"]

requires(
    isa_required=ISA.X86,
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

board = build_board(
    config, CPUTypes[system["cpu_type"].upper()], cache_hierarchy
)
set_parsec_workload(board, config, checkpoint=args.checkpoint)

reached_roi_end = False


def on_workend():
    global reached_roi_end
    reached_roi_end = True
    yield True


simulator = Simulator(
    board=board,
    on_exit_event={ExitEvent.WORKEND: on_workend()},
)
simulator.run()

if not reached_roi_end:
    raise RuntimeError("Baseline ROI did not finish; inspect the baseline log")

# The ROI starts at the checkpoint tick, so all ROI-relative values
# are measured from there.
roi_start_tick = checkpoint_tick(args.checkpoint)
ticks = int(simulator.get_current_tick()) - roi_start_tick
period = int(board.get_clock_domain().clock[0].period.getValue())
cycles = (ticks + period - 1) // period

Path(args.cycles_file).write_text(
    json.dumps(
        {
            "cycles": cycles,
            "ticks": ticks,
            "clock_period_ticks": period,
            "roi_start_tick": roi_start_tick,
        }
    )
)

print(f"ROI execution cycles: {cycles}")

print(
    "Exiting at tick {} because: {}".format(
        simulator.get_current_tick(),
        simulator.get_last_exit_event_cause(),
    )
)
