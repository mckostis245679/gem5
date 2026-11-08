#!/bin/bash
# The four 200-fault data_bitflip campaigns (blackscholes/canneal x 2c/4c,
# O3), started together. They share 72 gem5 job slots (job_slots in the
# configs), so at most 72 gem5 processes run at a time across all four.
cd ~/gem5/configs/fault_injection
export PATH=$HOME/gem5-venv/bin:$PATH
mkdir -p results/o3_bitflip
for f in experiment_{blackscholes,canneal}_simmedium_o3_{2,4}c_bitflip.json; do
    log=results/o3_bitflip/$(basename $f .json).log
    ( python run_experiment.py $f > $log 2>&1; echo "RUN_EXIT $?" >> $log ) &
done
wait
echo ALL_DONE > results/o3_bitflip/ALL_DONE
