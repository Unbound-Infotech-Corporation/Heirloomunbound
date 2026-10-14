#!/usr/bin/env bash
# Early command for the Ubuntu autoinstall.
# Resolves TARGET_DISK_SERIAL to exactly one internal disk, then writes the
# match Subiquity actually compares: udev ID_SERIAL when it is present, and
# the path of that disk. lsblk's SERIAL is often the short serial, and
# layout match.serial is ID_SERIAL, so writing the short value aborts.
# Subiquity reloads /autoinstall.yaml after early commands, and only then
# may it partition. Any other result exits non-zero, which aborts the
# install before a disk is erased.
#
# This script does not partition or erase disks. A non-zero exit aborts autoinstall.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "resolve-disk.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The ISO copies envfile.sh next to this script. The repo copy lives in box/lib.
if ! declare -F heirloom_unquote >/dev/null 2>&1; then
  envfile=""
  if [[ -f "${SCRIPT_DIR}/../lib/envfile.sh" ]]; then
    envfile="${SCRIPT_DIR}/../lib/envfile.sh"
  elif [[ -f "${SCRIPT_DIR}/envfile.sh" ]]; then
    envfile="${SCRIPT_DIR}/envfile.sh"
  else
    echo "envfile.sh is missing. Refusing to guess a disk serial." >&2
    exit 15
  fi
  # shellcheck source=box/lib/envfile.sh
  source "${envfile}"
fi

log() {
  printf '%s\n' "$*" | tee -a "${HEIRLOOM_RESOLVE_LOG:-/var/log/heirloom-resolve-disk.log}" >&2 || true
  if [[ -w /dev/ttyS0 ]]; then
    printf '%s\n' "$*" > /dev/ttyS0 || true
  fi
}

read_serial() {
  # Quotes and surrounding whitespace are part of the config syntax, not the
  # serial. The build already accepts TARGET_DISK_SERIAL="ABC". The copy on
  # the stick used to keep those quotes, and the serial check then aborted.
  local raw="" line trimmed file
  if [[ -n "${HEIRLOOM_TARGET_DISK_SERIAL:-}" ]]; then
    raw="${HEIRLOOM_TARGET_DISK_SERIAL}"
  else
    for file in \
      "${HEIRLOOM_AUTOINSTALL_ENV:-}" \
      /cdrom/heirloom/config.env \
      /etc/heirloom/autoinstall.env
    do
      [[ -n "${file}" && -r "${file}" ]] || continue
      while IFS= read -r line || [[ -n "${line}" ]]; do
        trimmed="$(heirloom_trim "${line}")"
        [[ "${trimmed}" == "#"* || -z "${trimmed}" ]] && continue
        if [[ "${trimmed}" == TARGET_DISK_SERIAL=* ]]; then
          raw="${trimmed#TARGET_DISK_SERIAL=}"
          break 2
        fi
      done < "${file}"
    done
  fi
  heirloom_unquote "${raw}"
}

cdrom_names() {
  if [[ -n "${HEIRLOOM_CDROM_NAMES:-}" ]]; then
    printf '%s\n' "${HEIRLOOM_CDROM_NAMES}"
    return 0
  fi
  local names="" device name
  if [[ -r /proc/mounts ]]; then
    while read -r device _mount _rest; do
      case "${_mount}" in
        /cdrom|/cdrom/*|/run/live/medium|/run/live/medium/*)
          name="${device#/dev/}"
          names="${names},${name}"
          ;;
      esac
    done < /proc/mounts
  fi
  printf '%s\n' "${names#,}"
}

write_inventory() {
  local dest="$1"
  if [[ -n "${HEIRLOOM_DISK_INVENTORY:-}" ]]; then
    cp "${HEIRLOOM_DISK_INVENTORY}" "${dest}"
    return 0
  fi
  if ! command -v lsblk >/dev/null 2>&1; then
    log "lsblk is not available. Refusing to guess a disk."
    exit 15
  fi
  lsblk -d -J -o NAME,SERIAL,TRAN,RM,TYPE,SIZE,MODEL > "${dest}"
}

enrich_udev() {
  local dest="$1"
  if ! command -v udevadm >/dev/null 2>&1; then
    log "udevadm is not available. The installer match will use the device path."
    return 0
  fi
  python3 - "${dest}" <<'PY'
import json
import subprocess
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
devices = payload.get("blockdevices", []) if isinstance(payload, dict) else payload
if not isinstance(devices, list):
    raise SystemExit(0)
for device in devices:
    if not isinstance(device, dict):
        continue
    name = str(device.get("name") or "").strip()
    if not name or "/" in name:
        continue
    try:
        output = subprocess.check_output(
            ["udevadm", "info", "-q", "property", "-n", f"/dev/{name}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        continue
    props = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value.strip()
    if props.get("ID_SERIAL"):
        device["id_serial"] = props["ID_SERIAL"]
    if props.get("ID_SERIAL_SHORT"):
        device["id_serial_short"] = props["ID_SERIAL_SHORT"]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
}

main() {
  local serial inventory cdrom autoinstall record output code
  serial="$(read_serial)"
  inventory="$(mktemp)"
  write_inventory "${inventory}"
  if [[ -z "${HEIRLOOM_DISK_INVENTORY:-}" || "${HEIRLOOM_ENRICH_UDEV:-}" == 1 ]]; then
    enrich_udev "${inventory}"
  fi
  cdrom="$(cdrom_names)"
  autoinstall="${HEIRLOOM_AUTOINSTALL_YAML:-/autoinstall.yaml}"
  record="${HEIRLOOM_STORAGE_MATCH:-/run/heirloom-autoinstall/storage-match.yaml}"
  log "Heirloom disk guard serial=${serial:-<empty>} cdrom=${cdrom:-<none>}"
  if [[ ! -f "${autoinstall}" ]]; then
    log "Autoinstall file ${autoinstall} is missing. Refusing to erase any disk."
    rm -f "${inventory}"
    exit 15
  fi
  set +e
  output="$(
    python3 "${SCRIPT_DIR}/resolve_disk.py" \
      --serial "${serial}" \
      --inventory "${inventory}" \
      --cdrom "${cdrom}" \
      --autoinstall "${autoinstall}" \
      --record "${record}" 2>&1
  )"
  code=$?
  set -e
  rm -f "${inventory}"
  if [[ -n "${output}" ]]; then
    printf '%s\n' "${output}"
    log "${output}"
  fi
  if [[ "${code}" -ne 0 ]]; then
    log "Install aborted with code ${code}. No disk was erased."
    exit "${code}"
  fi
  log "Storage match written to ${autoinstall} and ${record}."
}

main "$@"
