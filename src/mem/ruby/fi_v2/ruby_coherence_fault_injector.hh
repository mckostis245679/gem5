#ifndef __MEM_RUBY_FAULT_RUBY_COHERENCE_FAULT_INJECTOR_HH__
#define __MEM_RUBY_FAULT_RUBY_COHERENCE_FAULT_INJECTOR_HH__

#include <string>

#include "base/types.hh"
#include "params/RubyCoherenceFaultInjector.hh"
#include "sim/eventq.hh"
#include "sim/sim_object.hh"

namespace gem5
{

namespace ruby
{

class AbstractCacheEntry;
class CacheMemory;

class RubyCoherenceFaultInjector : public SimObject
{
  public:
    using Params = RubyCoherenceFaultInjectorParams;

    RubyCoherenceFaultInjector(const Params &p);

    void startup() override;

  private:
    void inject();

    void injectL1(
        AbstractCacheEntry *baseEntry,
        Addr lineAddress
    );

    void injectL2(
        AbstractCacheEntry *baseEntry,
        Addr lineAddress
    );

    void injectDataBitFlip(
        AbstractCacheEntry *baseEntry,
        Addr lineAddress
    );

    CacheMemory *const targetCache;
    const std::string faultType;
    const unsigned bitPosition;
    const std::string targetLevel;
    const unsigned targetIdx;
    const Tick injectionTick;
    const std::string newState;
    const unsigned cacheLineSize;

    EventFunctionWrapper injectionEvent;
};

} // namespace ruby
} // namespace gem5

#endif
