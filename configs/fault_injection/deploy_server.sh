#!/bin/bash
# Set up a remote machine to run fault-injection campaigns:
#   ./deploy_server.sh user@host
#
# Needs key-based SSH login (ssh-copy-id user@host). It clones this fork's
# branch into ~/gem5, builds build/X86_MESI/gem5.opt, and copies the PARSEC
# disk image, the kernel and the ROI checkpoints, so the remote machine
# needs neither KVM nor a new boot: campaigns there restore the same
# checkpoints, so they reproduce the local baselines exactly.
set -euo pipefail

HOST=${1:?usage: $0 user@host}
REPO=https://github.com/mckostis245679/gem5.git
BRANCH=full-system-emul
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE_DIR=gem5-disk-images/x86-ubuntu-24.04-parsec/output
KERNEL=.cache/gem5/x86-linux-kernel-6.8.0-52-generic-1.0.0
REMOTE_FI=gem5/configs/fault_injection

ssh_run() { ssh -o BatchMode=yes "$HOST" "$@"; }

echo "== Remote machine"
ssh_run 'echo "cores: $(nproc)"; free -g | sed -n 2p; df -h ~ | tail -1;
    ls -l /dev/kvm 2>/dev/null || echo "no /dev/kvm (not needed)";
    for tool in git g++ python3 scons m4 rsync tmux; do
        printf "%-8s %s\n" $tool "$(command -v $tool || echo MISSING)"; done;
    python3 -c "import sysconfig; print(\"python headers:\",
        sysconfig.get_paths()[\"include\"])";
    python3 -c "import matplotlib" 2>/dev/null \
        && echo "matplotlib ok" || echo "matplotlib MISSING"'

echo "== Source ($BRANCH)"
ssh_run "if [ -d gem5/.git ]; then
        git -C gem5 fetch origin $BRANCH && git -C gem5 checkout $BRANCH &&
        git -C gem5 merge --ff-only origin/$BRANCH
    else
        git clone --branch $BRANCH $REPO gem5
    fi; git -C gem5 log --oneline -1"

echo "== Disk image, kernel and checkpoints"
ssh_run "mkdir -p $IMAGE_DIR $KERNEL $REMOTE_FI/checkpoints"
# -S keeps the 20 GB image sparse (7.6 GB used); -a keeps its mtime, which
# is part of the checkpoint key.
rsync -aSz --info=progress2 "$HOME/$IMAGE_DIR/" "$HOST:$IMAGE_DIR/"
rsync -az "$HOME/$KERNEL/" "$HOST:$KERNEL/"
rsync -az --exclude='*.lock' --exclude='*.partial' \
    "$HERE/checkpoints/" "$HOST:$REMOTE_FI/checkpoints/"

echo "== Build gem5 (log: ~/gem5/build-X86_MESI.log)"
ssh_run 'cd gem5 && { [ -f build/X86_MESI/gem5.build/config ] ||
        scons defconfig build/X86_MESI build_opts/X86_MESI_Two_Level; } &&
    scons build/X86_MESI/gem5.opt -j "$(nproc)" > build-X86_MESI.log 2>&1;
    status=$?; tail -3 build-X86_MESI.log; exit $status'

echo "== Done. Start a campaign on $HOST with:"
echo "  ssh $HOST"
echo "  tmux new -s fi 'cd ~/$REMOTE_FI && mkdir -p results &&" \
    "python3 run_experiment.py <experiment>.json 2>&1 | tee results/run.log'"
