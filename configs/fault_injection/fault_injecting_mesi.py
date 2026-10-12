from m5.objects import RubyCoherenceFaultInjector

from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)


class FaultInjectingMESITwoLevel(MESITwoLevelCacheHierarchy):
    """
    MESI Two Level hierarchy with one scheduled fault.
    """

    def __init__(self, fault, **kwargs):
        self._fault = fault
        super().__init__(**kwargs)

    def incorporate_cache(self, board):
        super().incorporate_cache(board)

        target = self._fault["target"]

        if target in ("L1D", "L1I"):
            core_id = self._fault["core"]

            if not 0 <= core_id < len(self._l1_controllers):
                raise ValueError(
                    f"Invalid core {core_id}. "
                    f"The system has "
                    f"{len(self._l1_controllers)} cores."
                )

            controller = self._l1_controllers[core_id]

            if target == "L1D":
                target_cache = controller.L1Dcache
            else:
                target_cache = controller.L1Icache

            target_level = "L1"

        elif target == "L2":
            # There is always exactly one L2 bank.
            target_cache = self._l2_controllers[0].L2cache

            target_level = "L2"

        else:
            raise ValueError("target must be L1D, L1I, or L2")

        injector = RubyCoherenceFaultInjector(
            target_cache=target_cache,
            target_level=target_level,
            # The generator now selects a cache slot index
            # instead of an address.
            target_idx=self._fault["idx"],
            injection_tick=self._fault["tick"],
            fault_type=self._fault.get(
                "fault_type",
                "state",
            ),
            new_state=self._fault.get(
                "state",
                "",
            ),
            bit_position=self._fault.get(
                "bit",
                0,
            ),
            cache_line_size=board.get_cache_line_size(),
        )

        # Make the injector a child of RubySystem so it is
        # included when gem5 instantiates the SimObject tree.
        self.ruby_system.coherence_fault_injector = injector
