#!/usr/bin/env bash
# Build an Ubuntu Server 24.04 autoinstall ISO for the Heirloom Twin Box.
# This script writes an .iso file only. It never opens a USB device.
# Flash the ISO with Rufus in DD Image mode, or with balenaEtcher.
# Boot that stick only on the Twin Box.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "build-usb.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=box/lib/envfile.sh
source "${SCRIPT_DIR}/../lib/envfile.sh"

# Assigned from config.env by heirloom_load_env_file. Defaults live in validate_identity.
TARGET_DISK_SERIAL=""
HOSTNAME=""
USERNAME=""
LOCALE=""
KEYBOARD_LAYOUT=""
TIMEZONE=""
SSH_PASSWORD_AUTH=""
SSH_AUTHORIZED_KEYS_FILE=""
NVIDIA_DRIVER_BRANCH=""
NVIDIA_KERNEL_MODULES=""
EXPECTED_GPU_NAME=""
INITIAL_PASSWORD=""
PASSWORD_HASH=""
PASSWORD_HASH_VALUE=""
HEIRLOOM_REPO_URL=""
HEIRLOOM_PAYLOAD=""
UBUNTU_ISO_URL=""
UBUNTU_ISO_SHA256=""
UBUNTU_ISO_NAME=""
KEY_BLOCK=""
KEY_COUNT=0

CONFIG="${SCRIPT_DIR}/config.env"
OUTPUT=""
ISO_PATH=""
RENDER_DIR=""
KERNEL_EXTRA=""
SKIP_CHECKSUM=0

usage() {
  cat <<'EOF'
Usage: bash box/autoinstall/build-usb.sh [options]

  --config FILE       owner config (default: box/autoinstall/config.env)
                      A Windows path such as C:\Users\...\config.env is
                      converted with wslpath. /dev/* and \\.\ paths are refused.
  --iso FILE          Ubuntu 24.04 live-server ISO (downloaded when omitted)
  --output FILE       ISO to write (default: box/autoinstall/out/heirloom-twinbox-autoinstall.iso)
  --render-only DIR   write nocloud/ and heirloom/ and stop (no ISO)
  --kernel-extra STR  extra kernel arguments (tests use console=ttyS0)
  --skip-checksum     do not check the Ubuntu ISO SHA256 (tests only)

The output must be a normal file ending in .iso. /dev/* paths are refused.
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

# /dev/*, //./ paths, \\.\ physical drives, and a bare Windows drive root.
raw_device_path() {
  local path="$1"
  local prefix=""
  local windows_drive=$'\\\\.\\'
  if [[ ${#path} -ge 4 ]]; then
    prefix="${path:0:4}"
  fi
  [[ "${path}" == /dev/* || "${path}" == //.* || "${prefix}" == "${windows_drive}" || "${path}" =~ ^[A-Za-z]:\\?$ ]]
}

windows_file_path() {
  local path="$1"
  local unc=$'\\\\'
  [[ "${path}" =~ ^[A-Za-z]:[\\/].+ || "${path}" == "${unc}"* ]]
}

# Owner configs are often written as C:\...\config.env. WSL opens the /mnt/c form.
# Device paths stay refused. This does not require a .iso suffix.
to_wsl_path() {
  local path="$1"
  local converted=""
  if [[ -z "${path}" ]]; then
    printf '\n'
    return 0
  fi
  if raw_device_path "${path}"; then
    die "Refusing to use ${path}. This script only reads files and writes an ISO file. Flash it with Rufus or balenaEtcher."
  fi
  if windows_file_path "${path}"; then
    command -v wslpath >/dev/null 2>&1 || die "Windows path ${path} needs wslpath so WSL can open it."
    converted="$(wslpath -a "${path}")" || die "Could not convert ${path} to a WSL path."
    converted="$(heirloom_trim "${converted}")"
    if [[ -z "${converted}" ]]; then
      die "Could not convert ${path} to a WSL path."
    fi
    if raw_device_path "${converted}"; then
      die "Refusing to use ${converted}. This script only reads files and writes an ISO file. Flash it with Rufus or balenaEtcher."
    fi
    printf '%s\n' "${converted}"
    return 0
  fi
  printf '%s\n' "${path}"
}

refuse_output_path() {
  local out="$1"
  if raw_device_path "${out}"; then
    die "Refusing to write ${out}. This script only writes an ISO file. Flash it with Rufus or balenaEtcher."
  fi
  if [[ "${out}" != *.iso ]]; then
    die "Output must be a .iso file path, not ${out}."
  fi
  if [[ -e "${out}" && ( -b "${out}" || -c "${out}" ) ]]; then
    die "Refusing to write device node ${out}."
  fi
}

load_owner_config() {
  [[ -f "${CONFIG}" ]] || die "Missing ${CONFIG}. Copy box/autoinstall/config.env.example to box/autoinstall/config.env and set TARGET_DISK_SERIAL."
  heirloom_load_env_file "${CONFIG}"
}

validate_serial() {
  local serial="${TARGET_DISK_SERIAL:-}"
  if [[ -z "${serial}" || "${serial}" == "HEIRLOOM-REFUSE-NO-DISK-MATCH" ]]; then
    die "TARGET_DISK_SERIAL is empty. The USB is not built, and no disk would be selected."
  fi
  if [[ ! "${serial}" =~ ^[A-Za-z0-9][A-Za-z0-9._:+-]{2,126}$ ]]; then
    die "TARGET_DISK_SERIAL must be the lsblk serial, letters and digits only, with no spaces."
  fi
}

validate_identity() {
  HOSTNAME="${HOSTNAME:-heirloom-twinbox}"
  USERNAME="${USERNAME:-heirloom}"
  LOCALE="${LOCALE:-en_US.UTF-8}"
  KEYBOARD_LAYOUT="${KEYBOARD_LAYOUT:-us}"
  TIMEZONE="${TIMEZONE:-UTC}"
  SSH_PASSWORD_AUTH="${SSH_PASSWORD_AUTH:-yes}"
  NVIDIA_DRIVER_BRANCH="${NVIDIA_DRIVER_BRANCH:-latest}"
  NVIDIA_KERNEL_MODULES="${NVIDIA_KERNEL_MODULES:-open}"
  EXPECTED_GPU_NAME="${EXPECTED_GPU_NAME:-3090}"
  [[ "${HOSTNAME}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || die "HOSTNAME is not a valid hostname."
  [[ "${USERNAME}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "USERNAME is not a valid account name."
  [[ "${SSH_PASSWORD_AUTH}" == "yes" || "${SSH_PASSWORD_AUTH}" == "no" ]] || die "SSH_PASSWORD_AUTH must be yes or no."
  [[ "${NVIDIA_KERNEL_MODULES}" == "open" || "${NVIDIA_KERNEL_MODULES}" == "proprietary" ]] || die "NVIDIA_KERNEL_MODULES must be open or proprietary."
  if [[ "${NVIDIA_DRIVER_BRANCH}" != "latest" && ! "${NVIDIA_DRIVER_BRANCH}" =~ ^[0-9]{3}(\.[0-9]+)*$ ]]; then
    die "NVIDIA_DRIVER_BRANCH must be latest or a branch such as 580."
  fi
  [[ "${LOCALE}" =~ ^[A-Za-z0-9@_.-]+$ ]] || die "LOCALE looks unsafe."
  [[ "${KEYBOARD_LAYOUT}" =~ ^[A-Za-z0-9,_-]+$ ]] || die "KEYBOARD_LAYOUT looks unsafe."
  [[ "${TIMEZONE}" =~ ^[A-Za-z0-9/_+-]+$ ]] || die "TIMEZONE looks unsafe."
  local gpu_re='^[A-Za-z0-9._ -]+$'
  [[ "${EXPECTED_GPU_NAME}" =~ ${gpu_re} ]] || die "EXPECTED_GPU_NAME looks unsafe."
}

resolve_path() {
  local path="$1"
  if [[ "${path}" == /* ]]; then
    printf '%s\n' "${path}"
  else
    printf '%s\n' "${ROOT}/${path}"
  fi
}

collect_ssh_keys() {
  local file="${SSH_AUTHORIZED_KEYS_FILE:-}"
  local line
  KEY_BLOCK=""
  KEY_COUNT=0
  if [[ -n "${file}" ]]; then
    file="$(resolve_path "${file}")"
  fi
  if [[ -n "${file}" && -f "${file}" ]]; then
    while IFS= read -r line || [[ -n "${line}" ]]; do
      [[ "${line}" =~ ^[[:space:]]*# ]] && continue
      [[ -z "${line//[[:space:]]/}" ]] && continue
      [[ "${line}" != *\"* ]] || die "An SSH public key contains a double quote. Remove it and rebuild."
      KEY_BLOCK+="      - \"${line}\""$'\n'
      KEY_COUNT=$((KEY_COUNT + 1))
    done < "${file}"
  fi
  if [[ "${KEY_COUNT}" -eq 0 ]]; then
    KEY_BLOCK="    authorized-keys: []"
  else
    KEY_BLOCK="    authorized-keys:"$'\n'"${KEY_BLOCK%$'\n'}"
  fi
  if [[ "${SSH_PASSWORD_AUTH}" == "no" && "${KEY_COUNT}" -eq 0 ]]; then
    die "SSH_PASSWORD_AUTH=no needs at least one key in SSH_AUTHORIZED_KEYS_FILE, or the new box would lock you out."
  fi
  if [[ "${SSH_PASSWORD_AUTH}" == "yes" && "${KEY_COUNT}" -eq 0 && -z "${INITIAL_PASSWORD:-}" && -z "${PASSWORD_HASH:-}" ]]; then
    die "Set INITIAL_PASSWORD or an SSH public key so you can log in after install."
  fi
}

make_password_hash() {
  if [[ -n "${PASSWORD_HASH:-}" ]]; then
    PASSWORD_HASH_VALUE="${PASSWORD_HASH}"
  elif [[ -n "${INITIAL_PASSWORD:-}" ]]; then
    PASSWORD_HASH_VALUE="$(openssl passwd -6 "${INITIAL_PASSWORD}")"
  else
    PASSWORD_HASH_VALUE="$(openssl rand -base64 24 | openssl passwd -6 -stdin)"
    printf 'Generated a random local password because an SSH key is set. It is not saved. Log in with the key.\n' >&2
  fi
  [[ "${PASSWORD_HASH_VALUE}" == \$6\$* ]] || die "Password hash is not a SHA-512 crypt hash."
}

render_user_data() {
  local dest="$1"
  local allow="false"
  if [[ "${SSH_PASSWORD_AUTH}" == "yes" ]]; then
    allow="true"
  fi
  HEIRLOOM_RENDER_LOCALE="${LOCALE}" \
    HEIRLOOM_RENDER_KEYBOARD="${KEYBOARD_LAYOUT}" \
    HEIRLOOM_RENDER_HOSTNAME="${HOSTNAME}" \
    HEIRLOOM_RENDER_USERNAME="${USERNAME}" \
    HEIRLOOM_RENDER_HASH="${PASSWORD_HASH_VALUE}" \
    HEIRLOOM_RENDER_ALLOW="${allow}" \
    HEIRLOOM_RENDER_TIMEZONE="${TIMEZONE}" \
    HEIRLOOM_RENDER_KEYS="${KEY_BLOCK}" \
    HEIRLOOM_RENDER_SERIAL="${TARGET_DISK_SERIAL}" \
    python3 - "${SCRIPT_DIR}/user-data.template" "${dest}" <<'PY'
import os
import pathlib
import sys

template, dest = sys.argv[1], sys.argv[2]
text = pathlib.Path(template).read_text(encoding="utf-8")
replacements = {
    "__LOCALE__": os.environ["HEIRLOOM_RENDER_LOCALE"],
    "__KEYBOARD_LAYOUT__": os.environ["HEIRLOOM_RENDER_KEYBOARD"],
    "__HOSTNAME__": os.environ["HEIRLOOM_RENDER_HOSTNAME"],
    "__USERNAME__": os.environ["HEIRLOOM_RENDER_USERNAME"],
    "__PASSWORD_HASH__": os.environ["HEIRLOOM_RENDER_HASH"],
    "__SSH_ALLOW_PW__": os.environ["HEIRLOOM_RENDER_ALLOW"],
    "__TIMEZONE__": os.environ["HEIRLOOM_RENDER_TIMEZONE"],
}
for key, value in replacements.items():
    if key not in text:
        raise SystemExit(f"template is missing {key}")
    text = text.replace(key, value)
marker = "    authorized-keys: []"
block = os.environ["HEIRLOOM_RENDER_KEYS"]
if marker not in text:
    raise SystemExit("template is missing the authorized-keys marker")
text = text.replace(marker, block, 1)
if "HEIRLOOM-REFUSE-NO-DISK-MATCH" not in text:
    raise SystemExit("storage placeholder was lost")
serial = os.environ["HEIRLOOM_RENDER_SERIAL"]
if serial and serial in text:
    raise SystemExit("user-data must not contain the disk serial; the early command writes it")
pathlib.Path(dest).write_text(text, encoding="utf-8")
PY
  python3 - "${dest}" <<'PY'
import sys
import yaml
data = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
autoinstall = data["autoinstall"]
assert autoinstall["version"] == 1
assert autoinstall["interactive-sections"] == []
assert autoinstall["storage"]["layout"]["match"]["serial"] == "HEIRLOOM-REFUSE-NO-DISK-MATCH"
assert autoinstall["early-commands"]
assert autoinstall["shutdown"] == "reboot"
PY
}

render_meta_data() {
  local dest="$1"
  cat > "${dest}" <<EOF
instance-id: ${HOSTNAME}
local-hostname: ${HOSTNAME}
EOF
}

write_iso_config() {
  local dest="$1"
  # Write the serial the early command compares, without the quotes or
  # padding the owner file may have used. Passwords stay off the stick.
  HEIRLOOM_ISO_SERIAL="${TARGET_DISK_SERIAL}" awk '
    index($0, "INITIAL_PASSWORD=") == 1 { next }
    index($0, "PASSWORD_HASH=") == 1 { next }
    $0 ~ /^[[:space:]]*TARGET_DISK_SERIAL=/ {
      print "TARGET_DISK_SERIAL=" ENVIRON["HEIRLOOM_ISO_SERIAL"]
      next
    }
    { print }
  ' "${CONFIG}" > "${dest}"
  chmod 600 "${dest}" || true
}

stage_tree() {
  local dir="$1"
  local payload=""
  rm -rf "${dir}"
  mkdir -p "${dir}/nocloud" "${dir}/heirloom/payload"
  render_user_data "${dir}/nocloud/user-data"
  render_meta_data "${dir}/nocloud/meta-data"
  cp "${SCRIPT_DIR}/resolve-disk.sh" "${SCRIPT_DIR}/resolve_disk.py" \
    "${SCRIPT_DIR}/firstboot.sh" "${SCRIPT_DIR}/late.sh" \
    "${SCRIPT_DIR}/heirloom-firstboot.service" "${dir}/heirloom/"
  cp "${ROOT}/box/lib/nvidia-stack.sh" "${ROOT}/box/lib/envfile.sh" "${dir}/heirloom/"
  chmod 755 "${dir}/heirloom/"*.sh "${dir}/heirloom/"*.py
  write_iso_config "${dir}/heirloom/config.env"
  if [[ -n "${HEIRLOOM_PAYLOAD:-}" ]]; then
    payload="$(resolve_path "${HEIRLOOM_PAYLOAD}")"
  elif [[ -f "${SCRIPT_DIR}/payload/heirloom.tar.gz" ]]; then
    payload="${SCRIPT_DIR}/payload/heirloom.tar.gz"
  fi
  if [[ -n "${payload}" ]]; then
    [[ -f "${payload}" ]] || die "Payload not found: ${payload}"
    cp "${payload}" "${dir}/heirloom/payload/heirloom.tar.gz"
  elif [[ -z "${HEIRLOOM_REPO_URL:-}" ]]; then
    die "Set HEIRLOOM_REPO_URL or place a repo tarball at box/autoinstall/payload/heirloom.tar.gz."
  fi
}

add_autoinstall_to_grub() {
  local src="$1"
  local dest="$2"
  local extra="${3:-}"
  local injection='autoinstall ds=nocloud\;s=/cdrom/nocloud/'
  local line
  if [[ -n "${extra}" ]]; then
    injection="${injection} ${extra}"
  fi
  : > "${dest}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == *linux* && "${line}" == *casper* && "${line}" != *autoinstall* ]]; then
      if [[ "${line}" == *" ---"* ]]; then
        line="${line/ ---/ ${injection} ---}"
      else
        line="${line} ${injection}"
      fi
    fi
    printf '%s\n' "${line}"
  done < "${src}" > "${dest}"
}

verify_sha256() {
  local file="$1"
  local expected="$2"
  local actual
  [[ -n "${expected}" ]] || die "UBUNTU_ISO_SHA256 is empty."
  actual="$(sha256sum "${file}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    die "SHA256 mismatch for ${file}. Expected ${expected}. Actual ${actual}."
  fi
  printf 'SHA256 ok %s\n' "${actual}"
}

download_iso() {
  local dest="$1"
  local url="${UBUNTU_ISO_URL:-https://releases.ubuntu.com/24.04/ubuntu-24.04.5-live-server-amd64.iso}"
  if [[ -f "${dest}" ]]; then
    return 0
  fi
  printf 'Downloading %s\n' "${url}"
  curl -fL --retry 3 --retry-delay 2 -o "${dest}.partial" "${url}"
  mv "${dest}.partial" "${dest}"
}

remaster_iso() {
  local src="$1"
  local dest="$2"
  local staging="$3"
  local work
  work="$(mktemp -d)"
  xorriso -osirrox on -indev "${src}" -extract /boot/grub/grub.cfg "${work}/grub.cfg"
  add_autoinstall_to_grub "${work}/grub.cfg" "${work}/grub.new" "${KERNEL_EXTRA}"
  local -a args=()
  args+=(-indev "${src}" -outdev "${dest}")
  args+=(-map "${work}/grub.new" /boot/grub/grub.cfg)
  if xorriso -osirrox on -indev "${src}" -extract /boot/grub/loopback.cfg "${work}/loopback.cfg"; then
    add_autoinstall_to_grub "${work}/loopback.cfg" "${work}/loopback.new" "${KERNEL_EXTRA}"
    args+=(-map "${work}/loopback.new" /boot/grub/loopback.cfg)
  fi
  args+=(-map "${staging}/nocloud" /nocloud)
  args+=(-map "${staging}/heirloom" /heirloom)
  args+=(-boot_image any replay)
  rm -f "${dest}"
  xorriso "${args[@]}"
  rm -rf "${work}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config)
        CONFIG="$2"
        shift 2
        ;;
      --iso)
        ISO_PATH="$2"
        shift 2
        ;;
      --output)
        OUTPUT="$2"
        shift 2
        ;;
      --render-only)
        RENDER_DIR="$2"
        shift 2
        ;;
      --kernel-extra)
        KERNEL_EXTRA="$2"
        shift 2
        ;;
      --skip-checksum)
        SKIP_CHECKSUM=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

main() {
  local staging iso_cache
  parse_args "$@"
  CONFIG="$(to_wsl_path "${CONFIG}")" || exit 1
  load_owner_config
  validate_serial
  validate_identity
  collect_ssh_keys
  make_password_hash
  printf '%s\n' "BOOT THIS USB ONLY ON THE TWIN BOX."
  printf '%s\n' "The installer erases only the internal disk whose serial is ${TARGET_DISK_SERIAL}."
  printf '%s\n' "This script does not write a USB device."
  if [[ -n "${RENDER_DIR}" ]]; then
    stage_tree "${RENDER_DIR}"
    printf 'Rendered %s\n' "${RENDER_DIR}"
    return 0
  fi
  OUTPUT="${OUTPUT:-${ROOT}/box/autoinstall/out/heirloom-twinbox-autoinstall.iso}"
  refuse_output_path "${OUTPUT}"
  command -v xorriso >/dev/null 2>&1 || die "xorriso is not installed."
  mkdir -p "$(dirname "${OUTPUT}")"
  if [[ -z "${ISO_PATH}" ]]; then
    iso_cache="${TMPDIR:-/tmp}/${UBUNTU_ISO_NAME:-ubuntu-24.04.5-live-server-amd64.iso}"
    download_iso "${iso_cache}"
    ISO_PATH="${iso_cache}"
  fi
  [[ -f "${ISO_PATH}" ]] || die "ISO not found: ${ISO_PATH}"
  if [[ "${SKIP_CHECKSUM}" -eq 0 ]]; then
    verify_sha256 "${ISO_PATH}" "${UBUNTU_ISO_SHA256:-}"
  fi
  staging="$(mktemp -d)"
  stage_tree "${staging}"
  remaster_iso "${ISO_PATH}" "${OUTPUT}" "${staging}"
  rm -rf "${staging}"
  [[ -f "${OUTPUT}" && ! -b "${OUTPUT}" ]] || die "ISO output is missing."
  printf 'Wrote %s\n' "${OUTPUT}"
  printf 'SHA256 %s\n' "$(sha256sum "${OUTPUT}" | awk '{print $1}')"
  printf '%s\n' "Flash this file with Rufus (DD Image mode) or balenaEtcher."
  printf '%s\n' "Do not boot it on any PC except the Twin Box."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
