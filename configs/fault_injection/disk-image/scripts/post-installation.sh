#!/bin/bash
# Runs as root inside the packer VM: install PARSEC's build dependencies,
# grow the root partition, unpack the staged PARSEC tree and build it.

set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y build-essential autotools-dev automake autoconf m4 \
    gettext texinfo pkg-config cmake perl python-is-python3 unzip \
    libx11-dev libxext-dev libxmu-dev libxi-dev xorg-dev freeglut3-dev

# The disk was enlarged to disk_size; grow partition 2 (root) to fill it.
(
  echo d
  echo 2
  echo n
  echo 2
  echo
  echo
  echo N
  echo w
) | fdisk /dev/vda || true
partprobe /dev/vda || true
resize2fs /dev/vda2
df -h /

cd /home/gem5
tar xzf parsec-benchmark.tar.gz
rm parsec-benchmark.tar.gz
chown -R gem5:gem5 parsec-benchmark build-parsec.sh
su gem5 -c "bash /home/gem5/build-parsec.sh"
rm build-parsec.sh
df -h /
