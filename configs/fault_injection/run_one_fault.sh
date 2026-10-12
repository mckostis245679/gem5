#!/usr/bin/env bash
set -u

GEM5="$HOME/gem5/build/X86_MESI/gem5.opt"

BINARY="./microbenchmarks/build/no-false-sharing"
BASELINE_CONFIG="./run_mesi_baseline.py"
FAULT_CONFIG="./run_mesi_fault.py"

GENERATOR="./generate_random_fault.py"
PARSER="./parse_stdout_outcome.py"

BASELINE_DIR="./baselines"
BINARY_NAME="$(basename "$BINARY")"
BASELINE="$BASELINE_DIR/${BINARY_NAME}.out"
mkdir -p "$BASELINE_DIR"

FAULT_JSON="./fault.json"
FAULT_OUT="./fault.out"


# 1. Create a genuine no-fault baseline once.
if [ ! -f "$BASELINE" ]; then
    echo "Creating fault-free baseline..."

    rm -rf m5out_baseline

    "$GEM5" -d m5out_baseline "$BASELINE_CONFIG" \
        --binary "$BINARY" \
        > "$BASELINE" 2>&1

    if [ $? -ne 0 ]; then
        echo "Baseline run failed."
        tail -n 30 "$BASELINE"
        exit 1
    fi

    echo "Baseline created."
fi

EXIT_TICK=$(
    sed -n 's/.*Exiting at tick \([0-9][0-9]*\).*/\1/p' "$BASELINE" |
    tail -1
)

if [ -z "$EXIT_TICK" ]; then
    echo "Could not find baseline exit tick."
    exit 1
fi

TICK_MIN=$((EXIT_TICK * 3 / 10))
TICK_MAX=$((EXIT_TICK * 9 / 10))

# 2. Generate one random fault.
echo
echo "Generating random fault..."

python3 "$GENERATOR" \
    --output "$FAULT_JSON" \
    --target L1D \
    --fault-type data_bitflip \
    --num-cores 2 \
    --tick-min "$TICK_MIN" \
    --tick-max "$TICK_MAX" \
    || exit 1

# 3. Run gem5 with the generated fault.
echo
echo "Running fault-injected simulation..."

rm -rf m5out_fault

"$GEM5" -d m5out_fault "$FAULT_CONFIG" \
    --binary "$BINARY" \
    --fault-json "$FAULT_JSON" \
    > "$FAULT_OUT" 2>&1 || true

# 4. Parse against the no-fault baseline.
echo
echo "Parsing outcome..."

python3 "$PARSER" \
    --baseline "$BASELINE" \
    --fault "$FAULT_OUT" \
    --include-regex '^thread [01] output ' \
    --show-diff
