#!/usr/bin/env bash
# Remaster the Ubuntu ISO and boot it in QEMU.
# A wrong disk serial must leave the disk untouched.
# A matching serial must log the match and write a GPT header.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ISO_SRC="${HEIRLOOM_UBUNTU_ISO:-/tmp/ubuntu-24.04.5-live-server-amd64.iso}"
WORK="${HEIRLOOM_QEMU_WORK:-/tmp/heirloom-autoinstall-qemu}"
ARTIFACTS="${HEIRLOOM_QEMU_ARTIFACTS:-/opt/cursor/artifacts}"
SERIAL="HEIRLOOMTESTDISK01"
BOOT_TIMEOUT="${HEIRLOOM_QEMU_BOOT_TIMEOUT:-720}"

if [[ ! -f "${ISO_SRC}" ]]; then
  printf 'Ubuntu ISO not found at %s\n' "${ISO_SRC}" >&2
  exit 1
fi
command -v qemu-system-x86_64 >/dev/null
command -v xorriso >/dev/null
command -v timeout >/dev/null

mkdir -p "${WORK}" "${ARTIFACTS}"
rm -rf "${WORK}/staging"
mkdir -p "${WORK}/staging"

cat > "${WORK}/config.env" <<EOF
TARGET_DISK_SERIAL=${SERIAL}
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
INITIAL_PASSWORD=test-password-not-real
SSH_PASSWORD_AUTH=yes
NVIDIA_DRIVER_BRANCH=latest
NVIDIA_KERNEL_MODULES=open
EXPECTED_GPU_NAME=3090
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
HEIRLOOM_REPO_REF=main
LOCALE=en_US.UTF-8
KEYBOARD_LAYOUT=us
TIMEZONE=UTC
UBUNTU_ISO_URL=https://releases.ubuntu.com/24.04/ubuntu-24.04.5-live-server-amd64.iso
UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8
UBUNTU_ISO_NAME=ubuntu-24.04.5-live-server-amd64.iso
EOF

ISO_OUT="${WORK}/heirloom-twinbox-autoinstall.iso"
bash "${ROOT}/box/autoinstall/build-usb.sh" \
  --config "${WORK}/config.env" \
  --iso "${ISO_SRC}" \
  --output "${ISO_OUT}" \
  --kernel-extra "console=ttyS0,115200"

xorriso -osirrox on -indev "${ISO_OUT}" -extract /boot/grub/grub.cfg "${WORK}/grub.cfg" >/dev/null
if ! grep -F 'autoinstall ds=nocloud\;s=/cdrom/nocloud/' "${WORK}/grub.cfg" >/dev/null; then
  printf 'remastered grub.cfg has no autoinstall command line\n' >&2
  cat "${WORK}/grub.cfg" >&2
  exit 1
fi
xorriso -osirrox on -indev "${ISO_OUT}" -extract /nocloud/user-data "${WORK}/user-data" >/dev/null
if grep -F "${SERIAL}" "${WORK}/user-data" >/dev/null; then
  printf 'remastered user-data contains the disk serial\n' >&2
  exit 1
fi
xorriso -osirrox on -indev "${ISO_OUT}" -extract /heirloom/config.env "${WORK}/iso-config.env" >/dev/null
grep -F "TARGET_DISK_SERIAL=${SERIAL}" "${WORK}/iso-config.env" >/dev/null
xorriso -osirrox on -indev "${ISO_OUT}" -extract /casper/vmlinuz "${WORK}/vmlinuz" >/dev/null
xorriso -osirrox on -indev "${ISO_OUT}" -extract /casper/initrd "${WORK}/initrd" >/dev/null

# This VM can open /dev/kvm and still not execute a guest. Prefer KVM only when SeaBIOS actually runs.
ACCEL="tcg"
QEMU_MEM="2560"
BOOT_TIMEOUT="${HEIRLOOM_QEMU_BOOT_TIMEOUT:-1500}"
if [[ -w /dev/kvm ]]; then
  probe="$(mktemp)"
  timeout 4 qemu-system-x86_64 -accel kvm -cpu host -m 128 -nographic </dev/null >"${probe}" 2>&1 || true
  if grep -q 'SeaBIOS' "${probe}"; then
    ACCEL="kvm"
    QEMU_MEM="4096"
    BOOT_TIMEOUT="${HEIRLOOM_QEMU_BOOT_TIMEOUT:-720}"
  fi
  rm -f "${probe}"
fi
printf 'QEMU accel=%s memory=%s timeout=%s\n' "${ACCEL}" "${QEMU_MEM}" "${BOOT_TIMEOUT}" >&2

disk_is_blank() {
  python3 - "$1" <<'PY'
import sys
with open(sys.argv[1], "rb") as handle:
    blob = handle.read(1024 * 1024)
if blob != bytes(len(blob)):
    raise SystemExit(1)
PY
}

disk_has_gpt() {
  python3 - "$1" <<'PY'
import sys
with open(sys.argv[1], "rb") as handle:
    handle.seek(512)
    if handle.read(8) != b"EFI PART":
        raise SystemExit(1)
PY
}

stop_qemu() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
    wait "${pid}" 2>/dev/null || true
  fi
}

wait_for_text() {
  local file="$1"
  local needle="$2"
  local pid="$3"
  local ticks=$((BOOT_TIMEOUT / 5))
  local i
  for ((i = 0; i < ticks; i++)); do
    if [[ -f "${file}" ]] && grep -F -q -- "${needle}" "${file}"; then
      return 0
    fi
    if ! kill -0 "${pid}" 2>/dev/null; then
      return 1
    fi
    sleep 5
  done
  return 1
}

QEMU_PID=""
cleanup_qemu() {
  if [[ -n "${QEMU_PID}" ]]; then
    stop_qemu "${QEMU_PID}"
    QEMU_PID=""
  fi
}
trap cleanup_qemu EXIT

boot_case() {
  local label="$1"
  local serial="$2"
  local disk="${WORK}/${label}.img"
  local log="${WORK}/${label}.serial"
  rm -f "${disk}" "${log}"
  truncate -s 16G "${disk}"
  local -a cpu_args=()
  if [[ "${ACCEL}" == "kvm" ]]; then
    cpu_args+=(-cpu host)
  fi
  # Direct kernel boot uses the ISO's casper kernel and the same autoinstall command line GRUB would pass.
  qemu-system-x86_64 \
    -accel "${ACCEL}" \
    "${cpu_args[@]}" \
    -m "${QEMU_MEM}" \
    -smp 2 \
    -nographic \
    -no-reboot \
    -kernel "${WORK}/vmlinuz" \
    -initrd "${WORK}/initrd" \
    -append "autoinstall ds=nocloud;s=/cdrom/nocloud/ console=ttyS0,115200 ---" \
    -drive "file=${ISO_OUT},format=raw,if=ide,media=cdrom,readonly=on" \
    -drive "file=${disk},format=raw,if=none,id=hd" \
    -device virtio-scsi-pci,id=scsi \
    -device "scsi-hd,bus=scsi.0,drive=hd,serial=${serial}" \
    >"${log}" 2>"${WORK}/${label}.qemu" &
  QEMU_PID=$!
  printf '%s qemu pid %s\n' "${label}" "${QEMU_PID}" >&2
}

# Wrong serial: the guest must abort and the disk must stay blank.
boot_case mismatch WRONGSERIAL99
mismatch_pid="${QEMU_PID}"
set +e
wait_for_text "${WORK}/mismatch.serial" "HEIRLOOM_DISK_ABORT" "${mismatch_pid}"
mismatch_wait=$?
set -e
stop_qemu "${mismatch_pid}"
QEMU_PID=""
cp -f "${WORK}/mismatch.serial" "${ARTIFACTS}/qemu-serial-mismatch.log" 2>/dev/null || true
if [[ "${mismatch_wait}" -ne 0 ]]; then
  printf 'mismatch boot did not log HEIRLOOM_DISK_ABORT\n' >&2
  tail -n 40 "${WORK}/mismatch.qemu" >&2 || true
  tail -n 80 "${WORK}/mismatch.serial" >&2 || true
  exit 1
fi
if ! disk_is_blank "${WORK}/mismatch.img"; then
  printf 'mismatch disk was modified\n' >&2
  exit 1
fi

# Matching serial: the guard logs the disk, then curtin writes a GPT.
boot_case match "${SERIAL}"
match_pid="${QEMU_PID}"
set +e
wait_for_text "${WORK}/match.serial" "HEIRLOOM_DISK_MATCH" "${match_pid}"
match_wait=$?
set -e
if [[ "${match_wait}" -ne 0 ]]; then
  stop_qemu "${match_pid}"
  cp -f "${WORK}/match.serial" "${ARTIFACTS}/qemu-serial-match.log" 2>/dev/null || true
  printf 'match boot did not log HEIRLOOM_DISK_MATCH\n' >&2
  tail -n 40 "${WORK}/match.qemu" >&2 || true
  tail -n 80 "${WORK}/match.serial" >&2 || true
  exit 1
fi
gpt_ok=1
for _ in $(seq 1 36); do
  if disk_has_gpt "${WORK}/match.img"; then
    gpt_ok=0
    break
  fi
  if [[ -f "${WORK}/match.serial" ]] && grep -F -q -e "Failed to find matching device" -e "An error occurred" "${WORK}/match.serial"; then
    break
  fi
  if ! kill -0 "${match_pid}" 2>/dev/null; then
    break
  fi
  sleep 10
done
stop_qemu "${match_pid}"
QEMU_PID=""
cp -f "${WORK}/match.serial" "${ARTIFACTS}/qemu-serial-match.log" 2>/dev/null || true
if [[ "${gpt_ok}" -ne 0 ]]; then
  printf 'matching disk did not gain a GPT header\n' >&2
  exit 1
fi
if ! grep -F "device=/dev/" "${WORK}/match.serial" >/dev/null; then
  printf 'match log did not name a device\n' >&2
  exit 1
fi

echo "qemu autoinstall ok"
