#!/bin/bash
# Runs as the gem5 user inside the packer VM: build every PARSEC 3.0
# benchmark with the gcc-hooks configuration. A failing benchmark does not
# stop the others; parsec-build-status.txt records which ones were built.

cd /home/gem5/parsec-benchmark
source env.sh

LOGS=/home/gem5/parsec-build-logs
STATUS=$LOGS/parsec-build-status.txt
mkdir -p "$LOGS"
: > "$STATUS"

# PARSEC's bundled cmake 2.6 installs into /usr/local, which needs root.
# parsecmgmt skips a package whose inst directory has a build-info file,
# so mark cmake as built and point it at Ubuntu's cmake instead.
mkdir -p pkgs/tools/cmake/inst/amd64-linux.gcc-hooks/bin
ln -sf /usr/bin/cmake pkgs/tools/cmake/inst/amd64-linux.gcc-hooks/bin/cmake
echo "Ubuntu $(cmake --version | head -1)" \
    > pkgs/tools/cmake/inst/amd64-linux.gcc-hooks/build-info

parsecmgmt -a build -p hooks -c gcc-hooks > "$LOGS/hooks.log" 2>&1

BENCHMARKS="blackscholes bodytrack canneal dedup facesim ferret fluidanimate
            freqmine raytrace streamcluster swaptions vips x264"

for bench in $BENCHMARKS; do
    start=$(date +%s)
    parsecmgmt -a build -p "$bench" -c gcc-hooks > "$LOGS/$bench.log" 2>&1
    elapsed=$(( $(date +%s) - start ))
    if ls pkgs/*/"$bench"/inst/amd64-linux.gcc-hooks/bin/* > /dev/null 2>&1; then
        echo "OK     $bench (${elapsed}s)" | tee -a "$STATUS"
    else
        echo "FAILED $bench (${elapsed}s), see $bench.log" | tee -a "$STATUS"
        tail -n 40 "$LOGS/$bench.log"
    fi
done

# The ROI markers must be in the hooks library the benchmarks load.
hooks_lib=pkgs/libs/hooks/inst/amd64-linux.gcc-hooks/lib/libhooks.so
if nm -D "$hooks_lib" | grep -q m5_hypercall_addr; then
    echo "OK     hooks: libhooks.so exports m5_hypercall_addr" | tee -a "$STATUS"
else
    echo "FAILED hooks: m5_hypercall_addr missing from libhooks.so" | tee -a "$STATUS"
fi

# Object files are not needed at run time.
rm -rf pkgs/*/*/obj

exit 0
