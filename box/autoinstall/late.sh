#!/usr/bin/env bash
# Runs in the live installer after the target system is unpacked.
# Copies first-boot files onto the new system and enables the oneshot.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "late.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

install -d -m 0755 /target/usr/local/sbin /target/usr/local/lib/heirloom /target/etc/heirloom /target/etc/systemd/system
install -m 0755 /cdrom/heirloom/firstboot.sh /target/usr/local/sbin/heirloom-firstboot
install -m 0755 /cdrom/heirloom/nvidia-stack.sh /target/usr/local/lib/heirloom/nvidia-stack.sh
install -m 0644 /cdrom/heirloom/envfile.sh /target/usr/local/lib/heirloom/envfile.sh
install -m 0644 /cdrom/heirloom/heirloom-firstboot.service /target/etc/systemd/system/heirloom-firstboot.service
install -m 0600 /cdrom/heirloom/config.env /target/etc/heirloom/autoinstall.env
if [[ -f /cdrom/heirloom/payload/heirloom.tar.gz ]]; then
  install -d -m 0755 /target/var/lib/heirloom-firstboot
  install -m 0644 /cdrom/heirloom/payload/heirloom.tar.gz /target/var/lib/heirloom-firstboot/heirloom.tar.gz
fi
curtin in-target -- systemctl enable heirloom-firstboot.service
