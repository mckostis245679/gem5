#!/usr/bin/env bash
# Smoke test for the MESI Two Level fault injector in SE mode.
#
# 1. Runs a fault-free baseline to find the workload's end tick.
# 2. Injects one fault at the midpoint for each case below and checks
#    that the injector actually fired.
#
# Usage: configs/fault_injection/test_fi_se.sh [output_dir]

set -u

GEM5_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GEM5="${GEM5:-$GEM5_ROOT/build/X86_MESI/gem5.opt}"
CONFIG="$GEM5_ROOT/configs/fault_injection/test_fi_se.py"
BINARY="${BINARY:-/home/kostas/gem5/configs/fault_injection/microbenchmarks/build/no-false-sharing}"
BIN_ARGS="${BIN_ARGS:-6}"
OUT="${1:-$(mktemp -d -t fi_smoke.XXXXXX)}"
TIMEOUT="${TIMEOUT:-600}"

mkdir -p "$OUT"
echo "gem5:    $GEM5"
echo "binary:  $BINARY $BIN_ARGS"
echo "output:  $OUT"
echo

run_gem5() {
    local name="$1"
    shift
    timeout "$TIMEOUT" "$GEM5" -d "$OUT/$name" "$CONFIG" \
        --binary "$BINARY" --args $BIN_ARGS "$@" \
        > "$OUT/$name.log" 2>&1
}

# Baseline
run_gem5 baseline
end_tick=$(grep -oP 'Exiting at tick \K[0-9]+' "$OUT/baseline.log")
if [[ -z "$end_tick" ]] || grep -q "Diff found" "$OUT/baseline.log"; then
    echo "FAIL baseline (see $OUT/baseline.log)"
    tail -20 "$OUT/baseline.log"
    exit 1
fi
inject_tick=$((end_tick / 2))
max_ticks=$((end_tick * 5))
echo "PASS baseline: end tick $end_tick, injecting at $inject_tick"
echo

failures=0

# name | expected log tag | extra args
CASES=(
    "l1d_state|RUBY_FAULT_INJECTED|--target L1D --fault-type state --state I"
    "l1d_bitflip|RUBY_DATA_FAULT_INJECTED|--target L1D --fault-type data_bitflip --bit 3"
    "l2_state|RUBY_FAULT_INJECTED|--target L2 --fault-type state --state M"
)

for case in "${CASES[@]}"; do
    IFS='|' read -r name tag extra <<< "$case"
    # shellcheck disable=SC2086
    run_gem5 "$name" $extra --idx 0 --tick "$inject_tick" \
        --max-ticks "$max_ticks"
    rc=$?
    log="$OUT/$name.log"

    outcome="exit=$rc"
    if grep -q "Diff found" "$log"; then
        outcome="$outcome, SDC (Diff found)"
    elif grep -qE "^panic|^fatal|Possible Deadlock" "$log"; then
        outcome="$outcome, crash: $(grep -m1 -E '^panic|^fatal|Possible Deadlock' "$log")"
    elif grep -q "Exiting at tick" "$log"; then
        outcome="$outcome, $(grep -m1 -oP 'because: \K.*' "$log")"
    fi

    if grep -q "$tag" "$log"; then
        echo "PASS $name: $(grep -m1 "$tag" "$log" | sed 's/^info: //')"
    elif grep -q "RUBY_FAULT_NOT_INJECTED" "$log"; then
        echo "WARN $name: injector fired but skipped: $(grep -m1 RUBY_FAULT_NOT_INJECTED "$log" | sed 's/^warn: //')"
    else
        echo "FAIL $name: no injection logged (see $log)"
        failures=$((failures + 1))
    fi
    echo "     outcome: $outcome"
done

echo
if ((failures)); then
    echo "$failures case(s) failed"
    exit 1
fi
echo "All fault-injection smoke tests passed"
