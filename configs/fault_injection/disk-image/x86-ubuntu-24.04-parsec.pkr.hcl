// Ubuntu 24.04 + PARSEC 3.0 disk image for gem5 v26.
// Based on gem5-resources' src/gapbs/x86-ubuntu-24-04-gapbs.pkr.hcl.
// Run through build-x86.sh, which sets the variables below.

packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1"
    }
  }
}

variable "base_image" {
  type = string
}

variable "base_md5" {
  type = string
}

variable "stage_dir" {
  type = string
}

variable "log_dir" {
  type = string
}

variable "output_dir" {
  type = string
}

variable "image_name" {
  type    = string
  default = "x86-ubuntu-24.04-parsec"
}

variable "ssh_password" {
  type    = string
  default = "12345"
}

variable "ssh_username" {
  type    = string
  default = "gem5"
}

source "qemu" "initialize" {
  accelerator      = "kvm"
  boot_command     = ["<wait120>",
                      "gem5<enter><wait>",
                      "12345<enter><wait>",
                      "sudo mv /etc/netplan/50-cloud-init.yaml.bak /etc/netplan/50-cloud-init.yaml<enter><wait>",
                      "12345<enter><wait>",
                      "sudo netplan apply<enter><wait>",
                      "<wait>"]
  cpus             = "8"
  disk_size        = "20000"
  format           = "raw"
  headless         = "true"
  disk_image       = "true"
  iso_checksum     = "md5:${var.base_md5}"
  iso_urls         = ["${var.base_image}"]
  memory           = "8192"
  output_directory = "${var.output_dir}"
  qemu_binary      = "/usr/bin/qemu-system-x86_64"
  qemuargs         = [["-cpu", "host"], ["-display", "none"]]
  shutdown_command = "echo '${var.ssh_password}'|sudo -S shutdown -P now"
  ssh_password     = "${var.ssh_password}"
  ssh_username     = "${var.ssh_username}"
  ssh_wait_timeout = "60m"
  vm_name          = "${var.image_name}"
  ssh_handshake_attempts = "1000"
}

build {
  sources = ["source.qemu.initialize"]

  provisioner "file" {
    source      = "${var.stage_dir}/parsec-benchmark.tar.gz"
    destination = "/home/gem5/parsec-benchmark.tar.gz"
  }

  provisioner "file" {
    source      = "${var.stage_dir}/build-parsec.sh"
    destination = "/home/gem5/build-parsec.sh"
  }

  provisioner "shell" {
    execute_command = "echo '${var.ssh_password}' | {{ .Vars }} sudo -E -S bash '{{ .Path }}'"
    scripts         = ["${path.root}/scripts/post-installation.sh"]
  }

  provisioner "file" {
    direction   = "download"
    source      = "/home/gem5/parsec-build-logs/"
    destination = "${var.log_dir}/"
  }

  provisioner "shell" {
    execute_command = "echo '${var.ssh_password}' | {{ .Vars }} sudo -E -S bash '{{ .Path }}'"
    scripts         = ["${path.root}/scripts/disable-network.sh"]
  }
}
