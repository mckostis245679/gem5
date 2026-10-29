#!/usr/bin/env python3
"""
Boot Linux with KVM cores and take a checkpoint when the PARSEC
benchmark reaches its ROI (work-begin hypercall). The baseline and the
fault runs restore from this checkpoint.
"""

import argparse
import json
from pathlib import Path

from parsec_fs import (
    build_board,
    set_parsec_workload,
)

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.processors.cpu_types import CPUTypes
from gem5.isas import ISA
from gem5.simulate.exit_handler import WorkBeginExitHandler
from gem5.simulate.simulator import Simulator
from gem5.utils.override import overrides
from gem5.utils.requires import requires

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--checkpoint-dir", required=True, type=Path)
args = parser.parse_args()

with open(args.config) as config_file:
    config = json.load(config_file)
system = config["system"]

requires(
    isa_required=ISA.X86,
    coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
    kvm_required=True,
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

board = build_board(config, CPUTypes.KVM, cache_hierarchy)
set_parsec_workload(board, config)

reached_roi = False


class CheckpointAtROIBegin(WorkBeginExitHandler):
    @overrides(WorkBeginExitHandler)
    def _process(self, simulator):
        global reached_roi
        reached_roi = True
        print(
            f"ROI begins at tick {simulator.get_current_tick()}; "
            "saving checkpoint"
        )
        simulator.save_checkpoint(args.checkpoint_dir)

    @overrides(WorkBeginExitHandler)
    def _exit_simulation(self):
        return True


simulator = Simulator(board=board)
simulator.run()

if not reached_roi:
    raise RuntimeError(
        "Benchmark exited before its ROI: "
        f"{simulator.get_last_exit_event_cause()}"
    )
