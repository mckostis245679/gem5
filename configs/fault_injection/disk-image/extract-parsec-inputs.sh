#!/bin/bash
# Extract the PARSEC 3.0 simulation inputs (test, simdev, simsmall,
# simmedium, simlarge) from gem5's old Ubuntu 18.04 x86-parsec image.
#
# parsec.cs.princeton.edu, which hosted the input tarballs, is gone, and
# the darchr/parsec-benchmark repository does not include them. gem5's
# old image does, so we copy them out of it with debugfs (no root needed).
# The native inputs are skipped: they are several GB and not used in gem5.
#
# Usage: ./extract-parsec-inputs.sh [image.gz] [output_dir]

set -euo pipefail

IMAGE_URL=https://dist.gem5.org/dist/develop/images/x86/ubuntu-18-04/parsec.img.gz
WORK="${WORK:-$HOME/gem5-disk-images/parsec-inputs}"
IMAGE_GZ="${1:-$WORK/parsec-18.04.img.gz}"
OUT="${2:-$WORK/inputs}"
PARSEC_ROOT=/home/gem5/parsec-benchmark

mkdir -p "$WORK"
if [ ! -f "$IMAGE_GZ.complete" ]; then
    curl -L -C - --retry 5 -o "$IMAGE_GZ" "$IMAGE_URL"
    touch "$IMAGE_GZ.complete"
fi

# Copy only the root partition out of the compressed image.
PART="$WORK/parsec-18.04-root.img"
if [ ! -f "$PART" ]; then
    gunzip -c "$IMAGE_GZ" | head -c 1048576 > "$WORK/head.bin" || true
    read -r start size < <(sfdisk -J "$WORK/head.bin" | python3 -c '
import json, sys
p = json.load(sys.stdin)["partitiontable"]["partitions"][0]
print(p["start"], p["size"])')
    rm "$WORK/head.bin"
    gunzip -c "$IMAGE_GZ" | tail -c +$((start * 512 + 1)) \
        | head -c $((size * 512)) > "$PART.tmp" || true
    mv "$PART.tmp" "$PART"
fi

# Dump every pkgs/<group>/<benchmark>/inputs/input_*.tar except native.
mkdir -p "$OUT"
for group in apps kernels; do
    for bench in $(debugfs -R "ls -p $PARSEC_ROOT/pkgs/$group" "$PART" 2>/dev/null \
                   | awk -F/ '$6 != "." && $6 != ".." && $6 != "" {print $6}'); do
        inputs="$PARSEC_ROOT/pkgs/$group/$bench/inputs"
        files=$(debugfs -R "ls -p $inputs" "$PART" 2>/dev/null \
                | awk -F/ '$6 ~ /^input_.*\.tar$/ && $6 != "input_native.tar" {print $6}')
        [ -z "$files" ] && continue
        mkdir -p "$OUT/pkgs/$group/$bench/inputs"
        for f in $files; do
            debugfs -R "dump $inputs/$f $OUT/pkgs/$group/$bench/inputs/$f" \
                "$PART" 2>/dev/null
        done
        echo "$group/$bench: $(echo $files | wc -w) input sets"
    done
done

du -sh "$OUT"
