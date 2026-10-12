#include "learning_gem5/fi/fault_injector.hh"

#include <iostream>

namespace gem5
{

FaultInjector::FaultInjector(const FaultInjectorParams &params) :
    SimObject(params), event([this]{processEvent();}, name()),
    latency(params.time_to_wait),
    timesLeft(params.number_of_fires)
{
    DPRINTF(FIExample, "Created the hello object\n");
}

void
FaultInjector::startup()
{
    schedule(event, latency);
}

void
FaultInjector::processEvent()
{
    timesLeft--;
    DPRINTF(FIExample, "Hello world! Processing the event! %d left\n", timesLeft);

    if (timesLeft <= 0) {
        DPRINTF(FIExample, "Done firing!\n");
    } else {
        schedule(event, curTick() + latency);
    }
}
} // namespace gem5
