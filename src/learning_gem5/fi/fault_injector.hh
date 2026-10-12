#ifndef __LEARNING_GEM5_FAULT_INJECTOR_HH__
#define __LEARNING_GEM5_FAULT_INJECTOR_HH__

#include "base/trace.hh"
#include "debug/FIExample.hh"
#include "params/FaultInjector.hh"
#include "sim/sim_object.hh"

namespace gem5
{

class FaultInjector : public SimObject
{
  private:
    void processEvent();

    EventFunctionWrapper event;

    const Tick latency;

    int timesLeft;
  public:
    FaultInjector(const FaultInjectorParams &p);
    void startup() override;
};

} // namespace gem5

#endif // __LEARNING_GEM5_FAULT_INJECTOR_HH__
