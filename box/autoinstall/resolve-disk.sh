#!/usr/bin/env bash
# Early command for the Ubuntu autoinstall.
# Resolves TARGET_DISK_SERIAL to exactly one internal disk and writes that
# serial into /autoinstall.yaml. Subiquity reloads that file after early
# commands, and only then may it partition. Any other result exits non-zero,
# which aborts the install before a disk is erased.
#
# This script does not partition or erase disks. A non-zero exit aborts autoinstall.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "resolve-disk.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  printf '%s\n' "$*" | tee -a "${HEIRLOOM_RESOLVE_LOG:-/var/log/heirloom-resolve-disk.log}" >&2 || true
  if [[ -w /dev/ttyS0 ]]; then
    printf '%s\n' "$*" > /dev/ttyS0 || true
  fi
}

read_serial() {
  if [[ -n "${HEIRLOOM_TARGET_DISK_SERIAL:-}" ]]; then
    printf '%s\n' "${HEIRLOOM_TARGET_DISK_SERIAL}"
    return 0
  fi
  local file line
  for file in \
    "${HEIRLOOM_AUTOINSTALL_ENV:-}" \
    /cdrom/heirloom/config.env \
    /etc/heirloom/autoinstall.env
  do
    [[ -n "${file}" && -r "${file}" ]] || continue
    while IFS= read -r line || [[ -n "${line}" ]]; do
      [[ "${line}" =~ ^[[:space:]]*# ]] && continue
      if [[ "${line}" == TARGET_DISK_SERIAL=* ]]; then
        printf '%s\n' "${line#TARGET_DISK_SERIAL=}"
        return 0
      fi
    done < "${file}"
  done
  printf '\n'
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

main() {
  local serial inventory cdrom autoinstall record output code
  serial="$(read_serial)"
  inventory="$(mktemp)"
  write_inventory "${inventory}"
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
