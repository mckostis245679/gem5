#!/bin/bash
# Runs as root inside the packer VM: restore the base image's default of
# no network, which keeps boot fast in gem5 (see gem5-resources'
# ubuntu-generic-diskimages README).

if [ -f /etc/netplan/50-cloud-init.yaml ]; then
    mv /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak
fi

systemctl disable systemd-networkd-wait-online.service
systemctl mask systemd-networkd-wait-online.service
