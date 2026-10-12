from m5.params import *
from m5.SimObject import SimObject


class FaultInjector(SimObject):
    type = "FaultInjector"
    cxx_header = "learning_gem5/fi/fault_injector.hh"
    cxx_class = "gem5::FaultInjector"

    time_to_wait = Param.Latency("Time before firing the event")
    number_of_fires = Param.Int(
        1, "Number of times to fire the event before " "goodbye"
    )
