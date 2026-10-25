#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_FILE="$SCRIPT_DIR/mask_generator.py"

python3 "$PYTHON_FILE" \
  --l1d-size-kib 2 \
  --l1d-assoc 8 \
  --l2-size-kib 4 \
  --l2-assoc 8 \
  --num-cores 2 \
  --cycles 1000000 \
  --error 0.05 \
  --confidence 0.95 \
  --fault-type both \
  --target L1D \
  --seed 1234 \
  --output "$SCRIPT_DIR/fault_campaign.json"
