#include "mem/ruby/fi_v2/ruby_coherence_fault_injector.hh"

#include <cstdint>
#include <string>

#include "base/logging.hh"
#include "mem/ruby/common/DataBlock.hh"
#include "mem/ruby/protocol/MESI_Two_Level/L1Cache_Entry.hh"
#include "mem/ruby/protocol/MESI_Two_Level/L1Cache_State.hh"
#include "mem/ruby/protocol/MESI_Two_Level/L2Cache_Entry.hh"
#include "mem/ruby/protocol/MESI_Two_Level/L2Cache_State.hh"
#include "mem/ruby/slicc_interface/AbstractCacheEntry.hh"
#include "mem/ruby/structures/CacheMemory.hh"
#include <limits>
#include <sstream>

#include "base/trace.hh"
#include "debug/RubyFaultCache.hh"
namespace gem5
{

namespace ruby
{

using namespace MESI_Two_Level;

namespace
{

bool
isPowerOfTwo(unsigned value)
{
    return value != 0 && (value & (value - 1)) == 0;
}

L1Cache_State
parseL1State(const std::string &state)
{
    if (state == "I") {
        return L1Cache_State_I;
    }

    if (state == "S") {
        return L1Cache_State_S;
    }

    if (state == "E") {
        return L1Cache_State_E;
    }

    if (state == "M") {
        return L1Cache_State_M;
    }

    fatal(
        "Invalid L1 MESI state '%s'. "
        "Valid L1 states are I, S, E, and M.",
        state.c_str()
    );
}

L2Cache_State
parseL2State(const std::string &state)
{
    if (state == "SS") {
        return L2Cache_State_SS;
    }

    if (state == "M") {
        return L2Cache_State_M;
    }

    if (state == "MT") {
        return L2Cache_State_MT;
    }

    fatal(
        "Invalid L2 MESI state '%s'. "
        "Valid L2 states are SS, M, and MT.",
        state.c_str()
    );
}

} // anonymous namespace

RubyCoherenceFaultInjector::RubyCoherenceFaultInjector(
    const Params &p
) :
    SimObject(p),
    targetCache(p.target_cache),
    targetLevel(p.target_level),
    targetIdx(p.target_idx),
    injectionTick(p.injection_tick),
    faultType(p.fault_type),
    newState(p.new_state),
    bitPosition(p.bit_position),
    cacheLineSize(p.cache_line_size),
    injectionEvent(
        [this] { inject(); },
        name() + ".injection_event"
    ),
    postInjectionDumpDelay(p.post_injection_dump_delay),
    postInjectionDumpEvent(
        [this] { printTargetCache("delayed_after_injection"); },
        name() + ".post_injection_dump_event"
    )
{
    fatal_if(
        targetCache == nullptr,
        "%s: target_cache cannot be null",
        name()
    );

    fatal_if(
        targetLevel != "L1" && targetLevel != "L2",
        "%s: target_level must be L1 or L2",
        name()
    );

    fatal_if(
        !isPowerOfTwo(cacheLineSize),
        "%s: cache_line_size must be a power of two",
        name()
    );

    fatal_if(
        faultType != "state" &&
        faultType != "data_bitflip",
        "%s: fault_type must be state or data_bitflip",
        name()
    );

    /*
     * Validate only the parameters used by the selected fault type.
     */
    if (faultType == "state") {
        fatal_if(
            newState.empty(),
            "%s: new_state cannot be empty for a state fault",
            name()
        );

        /*
         * Parse the requested state now so invalid Python
         * configurations fail before simulation starts.
         */
        if (targetLevel == "L1") {
            parseL1State(newState);
        } else {
            parseL2State(newState);
        }
    } else {
        fatal_if(
            bitPosition >= cacheLineSize * 8,
            "%s: bit_position %u is outside a %u-byte cache line",
            name(),
            bitPosition,
            cacheLineSize
        );
    }
}

void
RubyCoherenceFaultInjector::startup()
{
    fatal_if(
        injectionTick <= curTick(),
        "%s: injection_tick (%llu) must be greater than "
        "the current tick (%llu)",
        name(),
        static_cast<unsigned long long>(injectionTick),
        static_cast<unsigned long long>(curTick())
    );


    schedule(injectionEvent, injectionTick);
}


void
RubyCoherenceFaultInjector::printTargetCache(const char *phase)
{
    if (!DTRACE(RubyFaultCache)) {
        return;
    }

    const int numBlocks = targetCache->getNumBlocks();

    DPRINTF(RubyFaultCache,
        "CACHE_DUMP_BEGIN phase=%s tick=%llu cache=%s "
        "target_idx=%u total_slots=%d\n",
        phase,
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str(),
        targetIdx,
        numBlocks);

    for (int idx = 0; idx < numBlocks; ++idx) {
        AbstractCacheEntry *entry = targetCache->getEntryAtIdx(idx);

        const char *selected =
            static_cast<unsigned>(idx) == targetIdx ? "yes" : "no";

        if (entry == nullptr) {
            DPRINTF(RubyFaultCache,
                "CACHE_SLOT phase=%s idx=%d selected=%s entry=null\n",
                phase, idx, selected);
            continue;
        }

        std::string state = "unknown";

        if (targetLevel == "L1") {
            if (auto *l1 = dynamic_cast<L1Cache_Entry *>(entry)) {
                state = L1Cache_State_to_string(l1->getCacheState());
            }
        } else {
            if (auto *l2 = dynamic_cast<L2Cache_Entry *>(entry)) {
                state = L2Cache_State_to_string(l2->getCacheState());
            }
        }

        std::ostringstream data;
        entry->getDataBlk().print(data);

        DPRINTF(RubyFaultCache,
            "CACHE_SLOT phase=%s idx=%d line=%#llx "
            "permission=%d state=%s selected=%s data=%s\n",
            phase,
            idx,
            static_cast<unsigned long long>(entry->m_Address),
            static_cast<int>(entry->m_Permission),
            state.c_str(),
            selected,
            data.str().c_str());
    }

    DPRINTF(RubyFaultCache,
        "CACHE_DUMP_END phase=%s tick=%llu cache=%s\n",
        phase,
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str());
}



void
RubyCoherenceFaultInjector::inject()
{
    printTargetCache("before_injection");

    performInjection();

    printTargetCache("immediately_after_injection");

    schedule(
        postInjectionDumpEvent,
        curTick() + postInjectionDumpDelay
    );
}

void
RubyCoherenceFaultInjector::performInjection()
{
    const int numBlocks = targetCache->getNumBlocks();

    /*
     * targetIdx identifies exactly one physical cache slot (set/way).
     * Never substitute another slot.
     */
    if (targetIdx >= static_cast<unsigned>(numBlocks)) {
        warn(
            "RUBY_FAULT_NOT_INJECTED "
            "tick=%llu cache=%s fault_type=%s "
            "reason=idx_out_of_range idx=%u num_blocks=%d",
            static_cast<unsigned long long>(curTick()),
            targetCache->name().c_str(),
            faultType.c_str(),
            targetIdx,
            numBlocks
        );
        return;
    }

    /*
     * Permission-agnostic target selection.
     *
     * Unlike getAddressAtIdx(), getEntryAtIdx() does NOT reject entries
     * merely because their permission is Invalid or NotPresent.
     */
    AbstractCacheEntry *baseEntry =
        targetCache->getEntryAtIdx(targetIdx);

    /*
     * A nullptr is the only slot condition that prevents injection:
     * no AbstractCacheEntry object exists, so there is no DataBlock or
     * coherence-state field to corrupt.
     */
    if (baseEntry == nullptr) {
        warn(
            "RUBY_FAULT_NOT_INJECTED "
            "tick=%llu cache=%s fault_type=%s "
            "reason=selected_idx_null_entry idx=%u",
            static_cast<unsigned long long>(curTick()),
            targetCache->name().c_str(),
            faultType.c_str(),
            targetIdx
        );
        return;
    }

    /*
     * Read the address directly from the entry. Do not call
     * getAddressAtIdx(), because that function filters Invalid/NotPresent
     * entries.
     */
    const Addr lineAddress = baseEntry->m_Address;

    inform(
        "RUBY_FAULT_SELECTED "
        "tick=%llu cache=%s fault_type=%s idx=%u line=%#llx "
        "permission=%d",
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str(),
        faultType.c_str(),
        targetIdx,
        static_cast<unsigned long long>(lineAddress),
        static_cast<int>(baseEntry->m_Permission)
    );

    if (faultType == "data_bitflip") {
        injectDataBitFlip(baseEntry, lineAddress);
        return;
    }

    /*
     * For a state fault, if the selected entry already has the requested
     * state, record a masked/no-effect injection and do not choose another
     * cache slot.
     */
    if (targetLevel == "L1") {
        auto *entry =
            dynamic_cast<L1Cache_Entry *>(baseEntry);

        fatal_if(
            entry == nullptr,
            "%s: target cache does not contain "
            "MESI Two Level L1 entries",
            name()
        );

        const L1Cache_State oldState =
            entry->getCacheState();
        const L1Cache_State forcedState =
            parseL1State(newState);

        if (oldState == forcedState) {
            warn(
                "RUBY_FAULT_NOT_INJECTED "
                "tick=%llu cache=%s fault_type=state "
                "reason=selected_idx_already_in_requested_state "
                "idx=%u line=%#llx state=%s",
                static_cast<unsigned long long>(curTick()),
                targetCache->name().c_str(),
                targetIdx,
                static_cast<unsigned long long>(lineAddress),
                newState.c_str()
            );
            return;
        }

        injectL1(baseEntry, lineAddress);
    } else {
        auto *entry =
            dynamic_cast<L2Cache_Entry *>(baseEntry);

        fatal_if(
            entry == nullptr,
            "%s: target cache does not contain "
            "MESI Two Level L2 entries",
            name()
        );

        const L2Cache_State oldState =
            entry->getCacheState();
        const L2Cache_State forcedState =
            parseL2State(newState);

        if (oldState == forcedState) {
            warn(
                "RUBY_FAULT_NOT_INJECTED "
                "tick=%llu cache=%s fault_type=state "
                "reason=selected_idx_already_in_requested_state "
                "idx=%u line=%#llx state=%s",
                static_cast<unsigned long long>(curTick()),
                targetCache->name().c_str(),
                targetIdx,
                static_cast<unsigned long long>(lineAddress),
                newState.c_str()
            );
            return;
        }

        injectL2(baseEntry, lineAddress);
    }
}

void
RubyCoherenceFaultInjector::injectDataBitFlip(
    AbstractCacheEntry *baseEntry,
    Addr lineAddress
)
{
    fatal_if(
        baseEntry == nullptr,
        "%s: cannot flip data in a null cache entry",
        name()
    );

    const unsigned byteOffset = bitPosition / 8;
    const unsigned bitInByte = bitPosition % 8;

    DataBlock &dataBlock = baseEntry->getDataBlk();

    const uint8_t oldByte =
        dataBlock.getByte(byteOffset);

    const uint8_t mask =
        static_cast<uint8_t>(1U << bitInByte);

    const uint8_t newByte =
        static_cast<uint8_t>(oldByte ^ mask);

    dataBlock.setByte(byteOffset, newByte);

    inform(
        "RUBY_DATA_FAULT_INJECTED "
        "tick=%llu cache=%s level=%s idx=%u line=%#llx "
        "bit_position=%u byte_offset=%u bit_in_byte=%u "
        "old_byte=%#x new_byte=%#x",
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str(),
        targetLevel.c_str(),
        targetIdx,
        static_cast<unsigned long long>(lineAddress),
        bitPosition,
        byteOffset,
        bitInByte,
        static_cast<unsigned>(oldByte),
        static_cast<unsigned>(newByte)
    );
}

void
RubyCoherenceFaultInjector::injectL1(
    AbstractCacheEntry *baseEntry,
    Addr lineAddress
)
{
    auto *entry =
        dynamic_cast<L1Cache_Entry *>(baseEntry);

    fatal_if(
        entry == nullptr,
        "%s: target cache does not contain "
        "MESI Two Level L1 entries",
        name()
    );

    const L1Cache_State oldState =
        entry->getCacheState();

    const L1Cache_State forcedState =
        parseL1State(newState);

    const std::string oldStateName =
        L1Cache_State_to_string(oldState);

    const std::string newStateName =
        L1Cache_State_to_string(forcedState);

    const int oldPermission =
        static_cast<int>(entry->m_Permission);

    /*
     * Change the protocol-specific coherence state.
     */
    entry->setCacheState(forcedState);

    /*
     * In this fault model, local validity/access permission follows the
     * corrupted coherence state. The rest of the coherence system is NOT
     * updated, so the fault can create a real local/global inconsistency.
     */
    entry->changePermission(
        L1Cache_State_to_permission(forcedState)
    );

    const int newPermission =
        static_cast<int>(entry->m_Permission);

    inform(
        "RUBY_FAULT_INJECTED "
        "tick=%llu cache=%s level=L1 idx=%u line=%#llx "
        "old_state=%s new_state=%s "
        "old_permission=%d new_permission=%d",
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str(),
        targetIdx,
        static_cast<unsigned long long>(lineAddress),
        oldStateName.c_str(),
        newStateName.c_str(),
        oldPermission,
        newPermission
    );
}

void
RubyCoherenceFaultInjector::injectL2(
    AbstractCacheEntry *baseEntry,
    Addr lineAddress
)
{
    auto *entry =
        dynamic_cast<L2Cache_Entry *>(baseEntry);

    fatal_if(
        entry == nullptr,
        "%s: target cache does not contain "
        "MESI Two Level L2 entries",
        name()
    );

    const L2Cache_State oldState =
        entry->getCacheState();

    const L2Cache_State forcedState =
        parseL2State(newState);

    const std::string oldStateName =
        L2Cache_State_to_string(oldState);

    const std::string newStateName =
        L2Cache_State_to_string(forcedState);

    const int oldPermission =
        static_cast<int>(entry->m_Permission);

    entry->setCacheState(forcedState);

    entry->changePermission(
        L2Cache_State_to_permission(forcedState)
    );

    const int newPermission =
        static_cast<int>(entry->m_Permission);

    inform(
        "RUBY_FAULT_INJECTED "
        "tick=%llu cache=%s level=L2 idx=%u line=%#llx "
        "old_state=%s new_state=%s "
        "old_permission=%d new_permission=%d",
        static_cast<unsigned long long>(curTick()),
        targetCache->name().c_str(),
        targetIdx,
        static_cast<unsigned long long>(lineAddress),
        oldStateName.c_str(),
        newStateName.c_str(),
        oldPermission,
        newPermission
    );
}

} // namespace ruby
} // namespace gem5
