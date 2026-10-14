#!/usr/bin/env bash
# build-usb.sh refuses disks and empty serials, and stamps autoinstall onto GRUB lines once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="${ROOT}/box/autoinstall/build-usb.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

# shellcheck source=box/autoinstall/build-usb.sh
source "${BUILD}"

refuse_fails() {
  local path="$1"
  local needle="$2"
  set +e
  output="$(refuse_output_path "${path}" 2>&1)"
  local code=$?
  set -e
  if [[ "${code}" -eq 0 ]]; then
    printf 'refuse_output_path accepted %s\n' "${path}" >&2
    exit 1
  fi
  printf '%s\n' "${output}" | grep -F -- "${needle}" >/dev/null
}

refuse_fails "/dev/sda" "Refusing to write"
refuse_fails "/dev/sdb1" "Refusing to write"
refuse_fails $'\\\\.\\PhysicalDrive0' "Refusing to write"
refuse_fails "//./PhysicalDrive0" "Refusing to write"
refuse_fails "${TMP}/not-an-iso" "must be a .iso"

cat > "${TMP}/empty.env" <<'EOF'
TARGET_DISK_SERIAL=
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
INITIAL_PASSWORD=test-password-not-real
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8
EOF
set +e
empty_out="$(bash "${BUILD}" --config "${TMP}/empty.env" --render-only "${TMP}/nope" 2>&1)"
empty_code=$?
set -e
if [[ "${empty_code}" -eq 0 ]]; then
  printf 'empty serial was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${empty_out}" | grep -F 'TARGET_DISK_SERIAL is empty' >/dev/null

cat > "${TMP}/locked.env" <<'EOF'
TARGET_DISK_SERIAL=HEIRLOOMTESTDISK01
SSH_PASSWORD_AUTH=no
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8
EOF
set +e
lock_out="$(bash "${BUILD}" --config "${TMP}/locked.env" --render-only "${TMP}/locked" 2>&1)"
lock_code=$?
set -e
if [[ "${lock_code}" -eq 0 ]]; then
  printf 'passwordless SSH with no key was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${lock_out}" | grep -F 'lock you out' >/dev/null

cat > "${TMP}/grub.cfg" <<'EOF'
menuentry "Try or Install Ubuntu Server" {
	linux	/casper/vmlinuz  ---
	initrd	/casper/initrd
}
menuentry "Ubuntu Server with the HWE kernel" {
	linux	/casper/hwe-vmlinuz  ---
	initrd	/casper/hwe-initrd
}
menuentry 'Test memory' {
	linux16 /boot/memtest86+x64.bin
}
EOF

add_autoinstall_to_grub "${TMP}/grub.cfg" "${TMP}/grub.out" "console=ttyS0"
add_autoinstall_to_grub "${TMP}/grub.out" "${TMP}/grub.twice" "console=ttyS0"
python3 - "${TMP}/grub.out" "${TMP}/grub.twice" <<'PY'
import pathlib, sys
needle = "autoinstall ds=nocloud\\;s=/cdrom/nocloud/ console=ttyS0"
first = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
second = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
if first.count(needle) != 2:
    raise SystemExit(f"first stamp count {first.count(needle)}\n{first}")
if second.count(needle) != 2:
    raise SystemExit(f"second stamp count {second.count(needle)}")
if "linux16 /boot/memtest86+x64.bin" not in first:
    raise SystemExit("memtest line changed")
if "HEIRLOOM" in first:
    raise SystemExit("grub gained an unexpected token")
PY

# The ISO checksum keys in the example must load. They are not comments.
# shellcheck source=box/lib/envfile.sh
source "${ROOT}/box/lib/envfile.sh"
heirloom_load_env_file "${ROOT}/box/autoinstall/config.env.example"
if [[ "${UBUNTU_ISO_SHA256}" != "97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8" ]]; then
  printf 'UBUNTU_ISO_SHA256 did not load from the example\n' >&2
  exit 1
fi
if [[ -n "${TARGET_DISK_SERIAL}" ]]; then
  printf 'example serial should stay empty\n' >&2
  exit 1
fi

echo "build-usb ok"
