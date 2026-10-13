#!/usr/bin/env bash
# The autoinstall disk guard must abort unless exactly one internal disk matches.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GUARD="${ROOT}/box/autoinstall/resolve-disk.sh"
PY="${ROOT}/box/autoinstall/resolve_disk.py"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
mkdir -p "${TMP}/sysfs"

cat > "${TMP}/base.yaml" <<'EOF'
#cloud-config
autoinstall:
  version: 1
  storage:
    layout:
      name: direct
      match:
        serial: "HEIRLOOM-REFUSE-NO-DISK-MATCH"
EOF

cat > "${TMP}/inner.yaml" <<'EOF'
version: 1
storage:
  layout:
    name: direct
    match:
      serial: "HEIRLOOM-REFUSE-NO-DISK-MATCH"
EOF

write_inventory() {
  local dest="$1"
  shift
  python3 - "${dest}" "$@" <<'PY'
import json
import sys
dest = sys.argv[1]
devices = []
for raw in sys.argv[2:]:
    parts = raw.split("|")
    name, serial, tran, rm, typ = parts[:5]
    device = {
        "name": name,
        "serial": serial,
        "tran": tran,
        "rm": rm in {"1", "true"},
        "type": typ,
        "size": "1T",
        "model": "test",
    }
    if len(parts) > 5 and parts[5]:
        device["id_serial"] = parts[5]
    if len(parts) > 6 and parts[6]:
        device["id_serial_short"] = parts[6]
    devices.append(device)
with open(dest, "w", encoding="utf-8") as handle:
    json.dump({"blockdevices": devices}, handle)
PY
}

assert_unchanged() {
  local yaml="$1"
  grep -F 'HEIRLOOM-REFUSE-NO-DISK-MATCH' "${yaml}" >/dev/null
}

run_guard() {
  local serial="$1"
  local inventory="$2"
  local yaml="$3"
  local cdrom="${4:-}"
  local envfile="${TMP}/empty.env"
  printf 'TARGET_DISK_SERIAL=\n' > "${envfile}"
  local log="${TMP}/resolve.log"
  local record="${TMP}/storage-match.yaml"
  rm -f "${record}" "${log}"
  set +e
  HEIRLOOM_TARGET_DISK_SERIAL="${serial}" \
    HEIRLOOM_DISK_INVENTORY="${inventory}" \
    HEIRLOOM_CDROM_NAMES="${cdrom}" \
    HEIRLOOM_AUTOINSTALL_YAML="${yaml}" \
    HEIRLOOM_STORAGE_MATCH="${record}" \
    HEIRLOOM_RESOLVE_LOG="${log}" \
    HEIRLOOM_SYSFS_BLOCK="${TMP}/sysfs" \
    HEIRLOOM_AUTOINSTALL_ENV="${envfile}" \
    bash "${GUARD}" >"${TMP}/stdout" 2>"${TMP}/stderr"
  local code=$?
  set -e
  printf '%s\n' "${code}"
}

expect_code() {
  local label="$1"
  local got="$2"
  local want="$3"
  if [[ "${got}" -ne "${want}" ]]; then
    printf '%s: exit %s, want %s\n' "${label}" "${got}" "${want}" >&2
    printf 'stderr:\n' >&2
    cat "${TMP}/stderr" >&2 || true
    exit 1
  fi
}

# Empty and placeholder serials.
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
write_inventory "${TMP}/inv.json" "sda|OTHERDISK12345|sata|0|disk"
code="$(run_guard "" "${TMP}/inv.json" "${TMP}/work.yaml")"
expect_code "empty serial" "${code}" 10
assert_unchanged "${TMP}/work.yaml"
grep -F 'HEIRLOOM_DISK_ABORT' "${TMP}/resolve.log" >/dev/null

cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "HEIRLOOM-REFUSE-NO-DISK-MATCH" "${TMP}/inv.json" "${TMP}/work.yaml")"
expect_code "placeholder serial" "${code}" 10
assert_unchanged "${TMP}/work.yaml"

cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "bad serial" "${TMP}/inv.json" "${TMP}/work.yaml")"
expect_code "bad characters" "${code}" 14
assert_unchanged "${TMP}/work.yaml"

cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "NOMATCHSERIAL1" "${TMP}/inv.json" "${TMP}/work.yaml")"
expect_code "no match" "${code}" 11
assert_unchanged "${TMP}/work.yaml"

# Two internal disks, same serial.
write_inventory "${TMP}/amb.json" \
  "sda|SAME_SERIAL_01|sata|0|disk" \
  "nvme0n1|SAME_SERIAL_01|nvme|0|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "SAME_SERIAL_01" "${TMP}/amb.json" "${TMP}/work.yaml")"
expect_code "ambiguous" "${code}" 12
assert_unchanged "${TMP}/work.yaml"

# USB disk alone.
write_inventory "${TMP}/usb.json" "sdb|USBONLYSERIAL1|usb|1|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "USBONLYSERIAL1" "${TMP}/usb.json" "${TMP}/work.yaml")"
expect_code "usb only" "${code}" 13
assert_unchanged "${TMP}/work.yaml"

# Same serial on the internal disk and a USB disk. Do not pick one.
write_inventory "${TMP}/both.json" \
  "sda|SHARED_SERIAL1|sata|0|disk" \
  "sdb|SHARED_SERIAL1|usb|1|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "SHARED_SERIAL1" "${TMP}/both.json" "${TMP}/work.yaml")"
expect_code "usb plus internal" "${code}" 12
assert_unchanged "${TMP}/work.yaml"

# The boot medium itself, even when it looks like a disk.
write_inventory "${TMP}/cd.json" "sda|CDROM_SERIAL_01|sata|0|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "CDROM_SERIAL_01" "${TMP}/cd.json" "${TMP}/work.yaml" "sda")"
expect_code "cdrom name" "${code}" 13
assert_unchanged "${TMP}/work.yaml"

# One internal disk, plus a different USB disk. The match is allowed.
write_inventory "${TMP}/ok.json" \
  "sda|HEIRLOOMTESTDISK01|sata|0|disk" \
  "sdb|USBDISKSERIAL9|usb|1|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "HEIRLOOMTESTDISK01" "${TMP}/ok.json" "${TMP}/work.yaml" "sr0")"
expect_code "good match" "${code}" 0
if grep -F 'HEIRLOOM-REFUSE-NO-DISK-MATCH' "${TMP}/work.yaml" >/dev/null; then
  printf 'placeholder survived a good match\n' >&2
  exit 1
fi
python3 - "${TMP}/work.yaml" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
if 'path: "/dev/sda"' not in text:
    raise SystemExit("missing path match")
if "serial:" in text:
    raise SystemExit("short serial was written without a udev ID_SERIAL")
if "HEIRLOOMTESTDISK01" in text:
    raise SystemExit("owner serial leaked into the installer match")
PY
grep -F 'device: /dev/sda' "${TMP}/storage-match.yaml" >/dev/null
grep -F 'path: "/dev/sda"' "${TMP}/storage-match.yaml" >/dev/null
if grep -F 'sdb' "${TMP}/storage-match.yaml" >/dev/null; then
  printf 'record named the USB disk\n' >&2
  exit 1
fi
grep -F 'HEIRLOOM_DISK_MATCH' "${TMP}/stdout" >/dev/null
grep -F 'path=/dev/sda' "${TMP}/stdout" >/dev/null

# The same match against the inner autoinstall document subiquity reloads.
cp "${TMP}/inner.yaml" "${TMP}/work.yaml"
code="$(run_guard "HEIRLOOMTESTDISK01" "${TMP}/ok.json" "${TMP}/work.yaml" "sr0")"
expect_code "inner yaml" "${code}" 0
grep -F 'path: "/dev/sda"' "${TMP}/work.yaml" >/dev/null
if grep -F 'serial:' "${TMP}/work.yaml" >/dev/null; then
  printf 'inner yaml kept a serial match\n' >&2
  exit 1
fi

# Owner short serial, udev ID_SERIAL is the string Subiquity compares.
write_inventory "${TMP}/udev.json" \
  "sda|HEIRLOOMTESTDISK01|sata|0|disk|QEMU_QEMU_HARDDISK_HEIRLOOMTESTDISK01|HEIRLOOMTESTDISK01" \
  "sdb|USBDISKSERIAL9|usb|1|disk"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "HEIRLOOMTESTDISK01" "${TMP}/udev.json" "${TMP}/work.yaml" "sr0")"
expect_code "udev serial" "${code}" 0
grep -F 'serial: "QEMU_QEMU_HARDDISK_HEIRLOOMTESTDISK01"' "${TMP}/work.yaml" >/dev/null
grep -F 'path: "/dev/sda"' "${TMP}/work.yaml" >/dev/null
python3 - "${TMP}/work.yaml" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
# The short serial may appear only inside the longer udev serial.
short = text.replace("QEMU_QEMU_HARDDISK_HEIRLOOMTESTDISK01", "")
if "HEIRLOOMTESTDISK01" in short:
    raise SystemExit("short serial written as its own match value")
PY

# The owner may paste the long udev serial instead of the lsblk column.
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "QEMU_QEMU_HARDDISK_HEIRLOOMTESTDISK01" "${TMP}/udev.json" "${TMP}/work.yaml" "sr0")"
expect_code "owner pasted ID_SERIAL" "${code}" 0
grep -F 'path: "/dev/sda"' "${TMP}/work.yaml" >/dev/null

# A glob character in ID_SERIAL must not become the match pattern.
write_inventory "${TMP}/glob.json" \
  "nvme0n1|DISKSERIALGLOB1|nvme|0|disk|VENDOR_DISK_*_DISKSERIALGLOB1|DISKSERIALGLOB1"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "DISKSERIALGLOB1" "${TMP}/glob.json" "${TMP}/work.yaml")"
expect_code "glob udev serial" "${code}" 0
grep -F 'path: "/dev/nvme0n1"' "${TMP}/work.yaml" >/dev/null
if grep -F 'serial:' "${TMP}/work.yaml" >/dev/null; then
  printf 'globbed udev serial was written into the match\n' >&2
  exit 1
fi

# The same owner string on one disk's short serial and another's udev serial.
write_inventory "${TMP}/cross.json" \
  "sda|SHARED_SERIAL1|sata|0|disk" \
  "nvme0n1|OTHERDISK12345|nvme|0|disk|SHARED_SERIAL1|"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(run_guard "SHARED_SERIAL1" "${TMP}/cross.json" "${TMP}/work.yaml")"
expect_code "cross identifier" "${code}" 12
assert_unchanged "${TMP}/work.yaml"

# Live udevadm enrichment fills ID_SERIAL before the match is written.
mkdir -p "${TMP}/bin"
cat > "${TMP}/bin/udevadm" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" | grep -q sda || exit 1
printf '%s\n' 'ID_SERIAL=ENRICHED_ID_SERIAL_01'
printf '%s\n' 'ID_SERIAL_SHORT=HEIRLOOMTESTDISK01'
EOF
chmod +x "${TMP}/bin/udevadm"
cp "${TMP}/base.yaml" "${TMP}/work.yaml"
code="$(
  PATH="${TMP}/bin:${PATH}" HEIRLOOM_ENRICH_UDEV=1 \
    HEIRLOOM_TARGET_DISK_SERIAL="HEIRLOOMTESTDISK01" \
    HEIRLOOM_DISK_INVENTORY="${TMP}/ok.json" \
    HEIRLOOM_CDROM_NAMES="sr0" \
    HEIRLOOM_AUTOINSTALL_YAML="${TMP}/work.yaml" \
    HEIRLOOM_STORAGE_MATCH="${TMP}/storage-match.yaml" \
    HEIRLOOM_RESOLVE_LOG="${TMP}/resolve.log" \
    HEIRLOOM_SYSFS_BLOCK="${TMP}/sysfs" \
    HEIRLOOM_AUTOINSTALL_ENV="${TMP}/empty.env" \
    bash "${GUARD}" >"${TMP}/stdout" 2>"${TMP}/stderr"
  printf '%s\n' "$?"
)"
expect_code "udev enrich" "${code}" 0
grep -F 'serial: "ENRICHED_ID_SERIAL_01"' "${TMP}/work.yaml" >/dev/null
grep -F 'path: "/dev/sda"' "${TMP}/work.yaml" >/dev/null

# Missing autoinstall file.
rm -f "${TMP}/missing.yaml"
code="$(run_guard "HEIRLOOMTESTDISK01" "${TMP}/ok.json" "${TMP}/missing.yaml")"
expect_code "missing autoinstall" "${code}" 15

# The guard must not name disk-erasing tools. Comments were written to avoid them too.
if grep -E -n 'wipefs|mkfs|parted|sgdisk|(^|[^[:alnum:]_])dd([^[:alnum:]_]|$)' "${GUARD}" "${PY}" >/dev/null; then
  printf 'disk guard names an erase tool\n' >&2
  grep -E -n 'wipefs|mkfs|parted|sgdisk|(^|[^[:alnum:]_])dd([^[:alnum:]_]|$)' "${GUARD}" "${PY}" >&2 || true
  exit 1
fi

echo "serial guard ok"
