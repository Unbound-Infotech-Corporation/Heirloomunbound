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

# Quoted and padded values load as the bare serial. A quoted placeholder is still empty.
[[ "$(heirloom_unquote '  "HEIRLOOMTESTDISK01"  ')" == "HEIRLOOMTESTDISK01" ]]
[[ "$(heirloom_unquote "  'HEIRLOOMTESTDISK01'  ")" == "HEIRLOOMTESTDISK01" ]]
[[ -z "$(heirloom_unquote '""')" ]]
[[ -z "$(heirloom_unquote '"   "')" ]]
[[ "$(heirloom_unquote 'HEIRLOOM-REFUSE-NO-DISK-MATCH')" == "HEIRLOOM-REFUSE-NO-DISK-MATCH" ]]

cat > "${TMP}/quoted.env" <<'EOF'
TARGET_DISK_SERIAL=" HEIRLOOMTESTDISK01 "
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
INITIAL_PASSWORD=test-password-not-real
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8
EOF
bash "${BUILD}" --config "${TMP}/quoted.env" --render-only "${TMP}/quoted" >/dev/null
grep -x 'TARGET_DISK_SERIAL=HEIRLOOMTESTDISK01' "${TMP}/quoted/heirloom/config.env" >/dev/null
if grep -F 'TARGET_DISK_SERIAL="' "${TMP}/quoted/heirloom/config.env" >/dev/null; then
  printf 'quoted serial was copied onto the install config\n' >&2
  exit 1
fi
if grep -F 'INITIAL_PASSWORD=' "${TMP}/quoted/heirloom/config.env" >/dev/null; then
  printf 'password was copied onto the install config\n' >&2
  exit 1
fi

cat > "${TMP}/placeholder.env" <<'EOF'
TARGET_DISK_SERIAL="HEIRLOOM-REFUSE-NO-DISK-MATCH"
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
INITIAL_PASSWORD=test-password-not-real
EOF
set +e
placeholder_out="$(bash "${BUILD}" --config "${TMP}/placeholder.env" --render-only "${TMP}/placeholder" 2>&1)"
placeholder_code=$?
set -e
if [[ "${placeholder_code}" -eq 0 ]]; then
  printf 'quoted placeholder serial was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${placeholder_out}" | grep -F 'TARGET_DISK_SERIAL is empty' >/dev/null

mkdir -p "${TMP}/bin" "${TMP}/bin-fail"
cat > "${TMP}/bin/wslpath" <<'EOF'
#!/bin/bash
target=""
for arg in "$@"; do
  case "${arg}" in
    -a|-u|-m|-w) ;;
    *) target="${arg}" ;;
  esac
done
case "${target}" in
  'C:\Users\owner\config.env')
    printf '%s\n' "${HEIRLOOM_TEST_WIN_CONFIG:?}"
    ;;
  'D:\danger\config.env')
    printf '%s\n' "/dev/sdb"
    ;;
  *)
    printf 'unexpected wslpath %s\n' "${target}" >&2
    exit 1
    ;;
esac
EOF
cat > "${TMP}/bin-fail/wslpath" <<EOF
#!/bin/bash
printf '%s\n' called > "${TMP}/wslpath-called"
exit 1
EOF
chmod 755 "${TMP}/bin/wslpath" "${TMP}/bin-fail/wslpath"

set +e
dev_out="$(bash "${BUILD}" --config /dev/sda --render-only "${TMP}/dev-config" 2>&1)"
dev_code=$?
set -e
if [[ "${dev_code}" -eq 0 ]]; then
  printf 'config /dev/sda was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${dev_out}" | grep -F 'Refusing to use' >/dev/null

set +e
phys_out="$(bash "${BUILD}" --config $'\\\\.\\PhysicalDrive0' --render-only "${TMP}/phys-config" 2>&1)"
phys_code=$?
set -e
if [[ "${phys_code}" -eq 0 ]]; then
  printf 'config \\\\.\\PhysicalDrive0 was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${phys_out}" | grep -F 'Refusing to use' >/dev/null

rm -f "${TMP}/wslpath-called"
set +e
linux_out="$(PATH="${TMP}/bin-fail:${PATH}" bash "${BUILD}" --config "${TMP}/empty.env" --render-only "${TMP}/linux-config" 2>&1)"
linux_code=$?
set -e
if [[ "${linux_code}" -eq 0 ]]; then
  printf 'empty serial was accepted while checking wslpath\n' >&2
  exit 1
fi
printf '%s\n' "${linux_out}" | grep -F 'TARGET_DISK_SERIAL is empty' >/dev/null
if [[ -f "${TMP}/wslpath-called" ]]; then
  printf 'a Linux config path was sent to wslpath\n' >&2
  exit 1
fi

cp "${TMP}/quoted.env" "${TMP}/win.env"
set +e
mapped_out="$(
  PATH="${TMP}/bin:${PATH}" HEIRLOOM_TEST_WIN_CONFIG="${TMP}/win.env" \
    bash "${BUILD}" --config 'D:\danger\config.env' --render-only "${TMP}/mapped-dev" 2>&1
)"
mapped_code=$?
set -e
if [[ "${mapped_code}" -eq 0 ]]; then
  printf 'wslpath result /dev/sdb was accepted as a config\n' >&2
  exit 1
fi
printf '%s\n' "${mapped_out}" | grep -F 'Refusing to use' >/dev/null

PATH="${TMP}/bin:${PATH}" HEIRLOOM_TEST_WIN_CONFIG="${TMP}/win.env" \
  bash "${BUILD}" --config 'C:\Users\owner\config.env' --render-only "${TMP}/win-render" >/dev/null
grep -x 'TARGET_DISK_SERIAL=HEIRLOOMTESTDISK01' "${TMP}/win-render/heirloom/config.env" >/dev/null

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -File "${ROOT}/box/tests/test-build-usb.ps1"
fi

echo "build-usb ok"
