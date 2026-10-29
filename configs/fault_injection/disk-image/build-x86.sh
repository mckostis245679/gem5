#!/bin/bash
# Build an x86 Ubuntu 24.04 disk image with PARSEC 3.0 for gem5 v26.
#
# The image is gem5's x86-ubuntu-24.04-img (v4.0.0, used with the
# x86-linux-kernel-6.8.0-52-generic kernel) with PARSEC 3.0 from
# darchr/parsec-benchmark built in /home/gem5/parsec-benchmark using the
# gcc-hooks configuration. The PARSEC hooks library is rebuilt around this
# gem5 tree's address-mode m5ops, and marks the ROI with gem5 hypercalls
# 4 (work begin) and 5 (work end).
#
# Prerequisites: qemu-system-x86_64, KVM access, and the inputs from
# extract-parsec-inputs.sh.
#
# Usage: configs/fault_injection/disk-image/build-x86.sh
# Output: $WORK/output/x86-ubuntu-24.04-parsec
# Logs:   $WORK/build.log (whole build, live), and after the PARSEC step
#         $WORK/logs/parsec-build-logs/ (<benchmark>.log, parsec-build-status.txt)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GEM5_ROOT="$(cd "$HERE/../../.." && pwd)"
WORK="${WORK:-$HOME/gem5-disk-images/x86-ubuntu-24.04-parsec}"
INPUTS="${INPUTS:-$HOME/gem5-disk-images/parsec-inputs/inputs}"

PACKER_VERSION=1.10.0
BASE_IMAGE="${BASE_IMAGE:-$HOME/.cache/gem5/x86-ubuntu-24.04-img-4.0.0}"
BASE_URL=https://dist.gem5.org/dist/develop/images/x86/ubuntu-24-04/x86-ubuntu-24.04-20250515.gz
BASE_MD5=fb91c0ef6a6120a3411cddb7d7fce47e
PARSEC_REPO=https://github.com/darchr/parsec-benchmark.git
PARSEC_COMMIT=153367d3056567e0f1ea56d72f80dda7337a0dad

mkdir -p "$WORK"
cd "$WORK"
exec > >(tee "$WORK/build.log") 2>&1

if [ ! -x ./packer ]; then
    wget -q "https://releases.hashicorp.com/packer/${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip"
    unzip -o "packer_${PACKER_VERSION}_linux_amd64.zip" packer
    rm "packer_${PACKER_VERSION}_linux_amd64.zip"
fi

# Base image: reuse gem5's resource cache when it holds the same image.
if [ ! -f "$BASE_IMAGE" ]; then
    BASE_IMAGE="$WORK/x86-ubuntu-24.04-20250515"
    if [ ! -f "$BASE_IMAGE" ]; then
        wget -O "$BASE_IMAGE.gz" "$BASE_URL"
        gunzip "$BASE_IMAGE.gz"
    fi
fi

if [ ! -d "$INPUTS/pkgs" ]; then
    echo "No PARSEC inputs in $INPUTS; run extract-parsec-inputs.sh first." >&2
    exit 1
fi

# Stage the PARSEC tree with our patches and inputs, as one tarball.
rm -rf stage
mkdir stage
git clone -q "$PARSEC_REPO" stage/parsec-benchmark
git -C stage/parsec-benchmark checkout -q "$PARSEC_COMMIT"
rm -rf stage/parsec-benchmark/.git

# Hooks: use gem5 v26's address-mode m5ops and hypercall ROI markers.
HOOKS=stage/parsec-benchmark/pkgs/libs/hooks/src
cp "$GEM5_ROOT/util/m5/src/abi/x86/m5op_addr.S" "$HOOKS/m5op_x86.S"
cp "$GEM5_ROOT/util/m5/src/m5_mmap.c" "$GEM5_ROOT/util/m5/src/m5_mmap.h" "$HOOKS/"
rm -rf "$HOOKS/include/asm"
cp -r "$GEM5_ROOT/include/gem5" "$HOOKS/include/"
sed -i '0,/#include "config.h"/s||#include "config.h"\n\n#include <gem5/m5ops.h>\n#include "m5_mmap.h"|' \
    "$HOOKS/hooks.c"
sed -i 's|m5_work_begin(0,0);|m5_hypercall_addr(M5_HYPERCALL_WORK_BEGIN);|; s|m5_work_end(0,0);|m5_hypercall_addr(M5_HYPERCALL_WORK_END);|' \
    "$HOOKS/hooks.c"
sed -i 's|-D_XOPEN_SOURCE=600 -c \$<|-D_XOPEN_SOURCE=600 -Iinclude -c $<|' \
    "$HOOKS/Makefile.shared"
grep -q "m5_hypercall_addr(M5_HYPERCALL_WORK_BEGIN)" "$HOOKS/hooks.c"
grep -q "m5_hypercall_addr(M5_HYPERCALL_WORK_END)" "$HOOKS/hooks.c"

# PARSEC 3.0 predates GCC 10+ defaults (-fno-common, C++17). C++14 still
# accepts `register` and dynamic exception specifications, and darchr's
# tree already uses C++11 features such as noexcept.
cat >> stage/parsec-benchmark/config/gcc.bldconf <<'EOF'

# Ubuntu 24.04 (GCC 13) compatibility.
CFLAGS="${CFLAGS} -fcommon -Wno-error -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion -Wno-incompatible-pointer-types"
CXXFLAGS="${CXXFLAGS} -std=gnu++14 -fcommon -Wno-error -Wno-narrowing"
EOF

cp -r "$INPUTS/pkgs" stage/parsec-benchmark/
cp "$HERE/scripts/build-parsec.sh" stage/
tar -C stage -czf stage/parsec-benchmark.tar.gz parsec-benchmark

mkdir -p logs
./packer init "$HERE/x86-ubuntu-24.04-parsec.pkr.hcl"
./packer build -force \
    -var "base_image=$BASE_IMAGE" \
    -var "base_md5=$BASE_MD5" \
    -var "stage_dir=$WORK/stage" \
    -var "log_dir=$WORK/logs" \
    -var "output_dir=$WORK/output" \
    "$HERE/x86-ubuntu-24.04-parsec.pkr.hcl"

echo
cat logs/parsec-build-logs/parsec-build-status.txt
echo "Disk image: $WORK/output/x86-ubuntu-24.04-parsec"
