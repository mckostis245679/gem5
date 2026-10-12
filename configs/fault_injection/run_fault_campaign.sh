#!/usr/bin/env bash
set -u

# Run the one-shot data-bit-flip experiment repeatedly and save each result.
#
# Usage:
#   ./run_fault_campaign.sh [NUM_RUNS] [OUTPUT_DIR]

NUM_RUNS="${1:-1000}"
OUTPUT_DIR="${2:-fault_campaign_$(date +%Y%m%d_%H%M%S)}"

RUN_ONE="${RUN_ONE:-./run_one_fault.sh}"
PARSER="${PARSER:-./parse_stdout_outcome.py}"
BASELINE="${BASELINE:-./baselines/no-false-sharing.out}"
FAULT_JSON="${FAULT_JSON:-./fault.json}"
FAULT_OUT="${FAULT_OUT:-./fault.out}"

mkdir -p "$OUTPUT_DIR/runs"

CAMPAIGN_LOG="$OUTPUT_DIR/campaign.log"
SUMMARY_JSONL="$OUTPUT_DIR/summary.jsonl"
SUMMARY_CSV="$OUTPUT_DIR/summary.csv"

: > "$CAMPAIGN_LOG"
: > "$SUMMARY_JSONL"

python3 - "$SUMMARY_CSV" <<'PYCSV'
import csv
import sys

with open(sys.argv[1], "w", newline="") as f:
    csv.writer(f).writerow([
        "run",
        "category",
        "target",
        "selected_idx",
        "bit_position",
        "injection_seen",
        "injected_address",
        "not_injected_reason",
        "confidence",
        "completion_seen",
        "outputs_equal",
        "one_shot_exit_status",
        "run_dir",
    ])
PYCSV

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$CAMPAIGN_LOG"
}

if ! [[ "$NUM_RUNS" =~ ^[1-9][0-9]*$ ]]; then
    echo "NUM_RUNS must be a positive integer, got: $NUM_RUNS" >&2
    exit 2
fi

if [ ! -f "$RUN_ONE" ]; then
    echo "Cannot find one-shot runner: $RUN_ONE" >&2
    exit 2
fi

if [ ! -f "$PARSER" ]; then
    echo "Cannot find parser: $PARSER" >&2
    exit 2
fi

log "Starting data-bit-flip campaign: $NUM_RUNS runs"
log "One-shot runner: $RUN_ONE"
log "Output directory: $OUTPUT_DIR"

for ((run=1; run<=NUM_RUNS; run++)); do
    run_name=$(printf 'run_%04d' "$run")
    run_dir="$OUTPUT_DIR/runs/$run_name"
    mkdir -p "$run_dir"

    one_shot_log="$run_dir/run_one_output.txt"
    parser_txt="$run_dir/parser_output.txt"
    outcome_json="$run_dir/outcome.json"
    saved_fault_json="$run_dir/fault.json"
    saved_fault_out="$run_dir/fault.out"

    log "[$run/$NUM_RUNS] Starting $run_name"

    # Remove stale per-run files. The baseline is intentionally preserved.
    rm -f "$FAULT_JSON" "$FAULT_OUT"

    bash "$RUN_ONE" > "$one_shot_log" 2>&1
    one_shot_status=$?

    if [ -f "$FAULT_JSON" ]; then
        cp "$FAULT_JSON" "$saved_fault_json"
    fi

    if [ -f "$FAULT_OUT" ]; then
        cp "$FAULT_OUT" "$saved_fault_out"
    fi

    if [ ! -f "$BASELINE" ] || [ ! -f "$saved_fault_out" ]; then
        log "[$run/$NUM_RUNS] Missing baseline or fault output; see $one_shot_log"

        python3 - \
            "$run" \
            "$one_shot_status" \
            "$run_dir" \
            "$SUMMARY_JSONL" \
            "$SUMMARY_CSV" <<'PYFAIL'
import csv
import json
import sys

run = int(sys.argv[1])
status = int(sys.argv[2])
run_dir = sys.argv[3]
jsonl_path = sys.argv[4]
csv_path = sys.argv[5]

record = {
    "run": run,
    "status": "RUN_FAILED",
    "one_shot_exit_status": status,
    "run_dir": run_dir,
}

with open(jsonl_path, "a") as f:
    f.write(json.dumps(record, sort_keys=True) + "\n")

with open(csv_path, "a", newline="") as f:
    csv.writer(f).writerow([
        run, "RUN_FAILED", "", "", "", "", "", "", "", "", "",
        status, run_dir,
    ])
PYFAIL
        continue
    fi

    # Use the same program-output filter as run_one_fault.sh.
    python3 "$PARSER" \
        --baseline "$BASELINE" \
        --fault "$saved_fault_out" \
        --include-regex '^thread [01] output ' \
        --show-diff \
        --json "$outcome_json" \
        > "$parser_txt" 2>&1
    parser_status=$?

    if [ "$parser_status" -ne 0 ] || [ ! -s "$outcome_json" ]; then
        log "[$run/$NUM_RUNS] Parser failed; see $parser_txt"

        python3 - \
            "$run" \
            "$one_shot_status" \
            "$parser_status" \
            "$run_dir" \
            "$SUMMARY_JSONL" \
            "$SUMMARY_CSV" <<'PYPARSERFAIL'
import csv
import json
import sys

run = int(sys.argv[1])
one_shot_status = int(sys.argv[2])
parser_status = int(sys.argv[3])
run_dir = sys.argv[4]
jsonl_path = sys.argv[5]
csv_path = sys.argv[6]

record = {
    "run": run,
    "status": "PARSER_FAILED",
    "one_shot_exit_status": one_shot_status,
    "parser_exit_status": parser_status,
    "run_dir": run_dir,
}

with open(jsonl_path, "a") as f:
    f.write(json.dumps(record, sort_keys=True) + "\n")

with open(csv_path, "a", newline="") as f:
    csv.writer(f).writerow([
        run, "PARSER_FAILED", "", "", "", "", "", "", "", "", "",
        one_shot_status, run_dir,
    ])
PYPARSERFAIL
        continue
    fi

    # Keep generated idx/bit and actual injected cache-line address separate.
    python3 - \
        "$run" \
        "$one_shot_status" \
        "$run_dir" \
        "$saved_fault_json" \
        "$outcome_json" \
        "$SUMMARY_JSONL" \
        "$SUMMARY_CSV" <<'PYSUMMARY'
import csv
import json
import os
import sys

run = int(sys.argv[1])
one_shot_status = int(sys.argv[2])
run_dir = sys.argv[3]
fault_path = sys.argv[4]
outcome_path = sys.argv[5]
jsonl_path = sys.argv[6]
csv_path = sys.argv[7]

fault = None
if os.path.exists(fault_path):
    with open(fault_path) as f:
        fault = json.load(f)

with open(outcome_path) as f:
    outcome = json.load(f)

record = {
    "run": run,
    "one_shot_exit_status": one_shot_status,
    "run_dir": run_dir,
    "fault": fault,
    "outcome": outcome,
}

with open(jsonl_path, "a") as f:
    f.write(json.dumps(record, sort_keys=True) + "\n")

with open(csv_path, "a", newline="") as f:
    csv.writer(f).writerow([
        run,
        outcome.get("category", ""),
        fault.get("target", "") if fault else "",
        fault.get("idx", "") if fault else "",
        fault.get("bit", "") if fault else "",
        outcome.get("injection_seen", ""),
        outcome.get("injected_address", ""),
        outcome.get("not_injected_reason", ""),
        outcome.get("confidence", ""),
        outcome.get("completion_seen", ""),
        outcome.get("outputs_equal", ""),
        one_shot_status,
        run_dir,
    ])
PYSUMMARY

    category=$(python3 -c \
        'import json,sys; print(json.load(open(sys.argv[1])).get("category", "UNKNOWN"))' \
        "$outcome_json")

    injected=$(python3 -c \
        'import json,sys; print(json.load(open(sys.argv[1])).get("injection_seen", False))' \
        "$outcome_json")

    log "[$run/$NUM_RUNS] $run_name -> $category injected=$injected"
done

log "Campaign complete"
log "Parser text per run: $OUTPUT_DIR/runs/run_XXXX/parser_output.txt"
log "Parser JSON per run: $OUTPUT_DIR/runs/run_XXXX/outcome.json"
log "Aggregate JSONL: $SUMMARY_JSONL"
log "Aggregate CSV: $SUMMARY_CSV"
