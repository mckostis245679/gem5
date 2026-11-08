from m5.params import *
from m5.SimObject import SimObject


class RubyCoherenceFaultInjector(SimObject):
    type = "RubyCoherenceFaultInjector"

    cxx_class = "gem5::ruby::RubyCoherenceFaultInjector"

    cxx_header = "mem/ruby/fi_v2/ruby_coherence_fault_injector.hh"

    target_cache = Param.RubyCache(
        "Ruby cache containing the target cache line"
    )

    target_level = Param.String(
        "L1",
        "Protocol entry type: L1 or L2",
    )

    target_idx = Param.Unsigned("Cache slot index to target")

    injection_tick = Param.Tick(
        "Absolute simulation tick for the state corruption"
    )

    fault_type = Param.String(
        "state",
        "Fault type: state or data_bitflip",
    )
    new_state = Param.String(
        "",
        "Stable coherence state to force for a state fault",
    )

    bit_position = Param.Unsigned(
        0,
        "Bit position within the cache line for a data bit flip",
    )
    post_injection_dump_delay = Param.Tick(
        1000,
        "Ticks after injection for the delayed cache dump; must be positive",
    )

    cache_line_size = Param.Unsigned(
        64,
        "Ruby cache-line size in bytes",
    )

    exit_if_masked = Param.Bool(
        False,
        "End the simulation at the injection tick when the fault cannot "
        "have an effect: the selected slot holds no entry or an Invalid/"
        "NotPresent line, or the line already has the requested state",
    )
    masked_exit_hypercall_id = Param.UInt64(
        4096,
        "Custom ExitHandler hypercall ID of that exit; its payload carries "
        "the reason",
    )
