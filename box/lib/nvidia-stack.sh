#!/usr/bin/env bash
# Latest production NVIDIA driver, CUDA toolkit, cuDNN, container toolkit, and nvtop.
# Packages come from NVIDIA's CUDA apt repository for Ubuntu 24.04 (cuda-keyring).
# The RTX 3090 (Ampere) uses the open kernel modules by default.
# Source this file, or run it: sudo bash box/lib/nvidia-stack.sh [--dry-run] [--upgrade]
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "nvidia-stack.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

HEIRLOOM_NVIDIA_STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=box/lib/envfile.sh
source "${HEIRLOOM_NVIDIA_STACK_DIR}/envfile.sh"

: "${DRY_RUN:=0}"
CUDA_KEYRING_URL="${CUDA_KEYRING_URL:-https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb}"

nv_log() {
  if declare -F log >/dev/null 2>&1; then
    log "$@"
    return 0
  fi
  printf '%s %s\n' "$(date -Is)" "$*"
}

nv_run() {
  nv_log "RUN $*"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  "$@"
}

heirloom_nvidia_branch() {
  printf '%s\n' "${HEIRLOOM_NVIDIA_BRANCH:-${NVIDIA_DRIVER_BRANCH:-latest}}"
}

heirloom_nvidia_modules() {
  printf '%s\n' "${HEIRLOOM_NVIDIA_MODULES:-${NVIDIA_KERNEL_MODULES:-open}}"
}

heirloom_nvidia_validate_branch() {
  local branch="$1"
  if [[ "${branch}" == "latest" ]]; then
    return 0
  fi
  if [[ "${branch}" =~ ^[0-9]{3}(\.[0-9]+)*$ ]]; then
    return 0
  fi
  printf 'NVIDIA branch must be "latest" or a production branch such as 580. Got: %s\n' "${branch}" >&2
  return 1
}

heirloom_nvidia_validate_modules() {
  local modules="$1"
  case "${modules}" in
    open|proprietary) return 0 ;;
  esac
  printf 'NVIDIA kernel modules must be open or proprietary. Got: %s\n' "${modules}" >&2
  return 1
}

heirloom_nvidia_load_saved_branch() {
  local file="${HEIRLOOM_NVIDIA_ENV:-/etc/heirloom/nvidia.env}"
  if [[ -r "${file}" ]]; then
    heirloom_load_env_file "${file}"
  fi
}

heirloom_nvidia_write_saved_branch() {
  local file="${HEIRLOOM_NVIDIA_ENV:-/etc/heirloom/nvidia.env}"
  local branch modules
  branch="$(heirloom_nvidia_branch)"
  modules="$(heirloom_nvidia_modules)"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    nv_log "would write ${file} branch=${branch} modules=${modules}"
    return 0
  fi
  install -d -m 0755 "$(dirname "${file}")"
  cat > "${file}" <<EOF
HEIRLOOM_NVIDIA_BRANCH=${branch}
HEIRLOOM_NVIDIA_MODULES=${modules}
EXPECTED_GPU_NAME=${EXPECTED_GPU_NAME:-3090}
EOF
  chmod 644 "${file}"
}

heirloom_enable_universe() {
  local sources="/etc/apt/sources.list.d/ubuntu.sources"
  nv_log "Ensuring universe is enabled so nvtop can install"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if [[ -f "${sources}" ]]; then
    python3 - "${sources}" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("Components:") and "universe" not in line.split():
        line = line + " universe"
    lines.append(line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  fi
  if [[ -f /etc/apt/sources.list ]] && grep -q '^deb ' /etc/apt/sources.list; then
    sed -i -E '/^deb .*ubuntu/ { /universe/! s/$/ universe/ }' /etc/apt/sources.list
  fi
}

heirloom_install_container_toolkit() {
  nv_log "Installing the NVIDIA container toolkit and configuring Docker when Docker is running"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    nv_log "would add https://nvidia.github.io/libnvidia-container and install nvidia-container-toolkit"
    return 0
  fi
  install -d -m 0755 /usr/share/keyrings
  rm -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
  apt-get update
  apt-get install -y \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    nvidia-container-toolkit
  if command -v docker >/dev/null 2>&1 && systemctl is-active --quiet docker; then
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
  else
    nv_log "Docker is not running yet. The container toolkit package is installed. box/install.sh configures the runtime after Docker starts."
  fi
}

heirloom_install_cudnn() {
  local pkg
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    nv_log "would install the latest cuDNN meta package (cudnn, then cudnn9-cuda-13, then cudnn9-cuda-12)"
    return 0
  fi
  apt-get update
  for pkg in cudnn cudnn9-cuda-13 cudnn9-cuda-12; do
    if apt-cache show "${pkg}" >/dev/null 2>&1; then
      nv_log "Installing cuDNN package ${pkg}"
      apt-get install -y \
        -o Dpkg::Options::=--force-confdef \
        -o Dpkg::Options::=--force-confold \
        "${pkg}"
      return 0
    fi
  done
  printf 'No cuDNN package was found in the CUDA apt repository.\n' >&2
  return 1
}

heirloom_apt_install() {
  nv_run apt-get install -y \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    "$@"
}

heirloom_nvidia_install_stack() {
  local branch modules header_pkg driver_pkg
  heirloom_nvidia_load_saved_branch
  branch="$(heirloom_nvidia_branch)"
  modules="$(heirloom_nvidia_modules)"
  heirloom_nvidia_validate_branch "${branch}"
  heirloom_nvidia_validate_modules "${modules}"
  header_pkg="linux-headers-$(uname -r)"
  if [[ "${modules}" == "open" ]]; then
    driver_pkg="nvidia-open"
  else
    driver_pkg="cuda-drivers"
  fi
  nv_log "NVIDIA CUDA repo stack branch=${branch} modules=${modules} driver=${driver_pkg}"
  nv_log "Also installing ${header_pkg}, cuda-toolkit, cuDNN, nvtop, and nvidia-container-toolkit"
  export DEBIAN_FRONTEND=noninteractive
  export NEEDRESTART_MODE=a
  export APT_LISTCHANGES_FRONTEND=none
  heirloom_enable_universe
  nv_run apt-get update
  heirloom_apt_install ca-certificates curl gnupg "${header_pkg}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    nv_log "would download ${CUDA_KEYRING_URL} and dpkg -i cuda-keyring"
  else
    local keyring_deb
    keyring_deb="$(mktemp --suffix=-cuda-keyring.deb)"
    curl -fsSL -o "${keyring_deb}" "${CUDA_KEYRING_URL}"
    dpkg -i "${keyring_deb}"
    rm -f "${keyring_deb}"
    apt-get update
  fi
  if [[ "${branch}" != "latest" ]]; then
    heirloom_apt_install "nvidia-driver-pinning-${branch}"
  else
    nv_log "Branch latest: no nvidia-driver-pinning package, nvidia-open tracks the current production branch"
  fi
  heirloom_apt_install "${driver_pkg}" cuda-toolkit nvtop
  heirloom_install_cudnn
  heirloom_install_container_toolkit
  heirloom_nvidia_write_saved_branch
  if [[ "${DRY_RUN}" -eq 0 ]] && { ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; }; then
    nv_log "nvidia-smi does not answer yet. Reboot so the new driver can load."
    printf '%s\n' "reboot" > /run/heirloom-nvidia-reboot-needed 2>/dev/null || true
  fi
}

heirloom_nvidia_main() {
  local arg upgrade=0
  for arg in "$@"; do
    case "${arg}" in
      --dry-run) DRY_RUN=1 ;;
      --upgrade) upgrade=1 ;;
      -h|--help)
        cat <<'EOF'
Usage: sudo bash box/lib/nvidia-stack.sh [--dry-run] [--upgrade]

Installs or upgrades the latest production NVIDIA open driver from the Ubuntu
24.04 CUDA apt repo, plus the CUDA toolkit, cuDNN, nvtop, and the NVIDIA
container toolkit. Set HEIRLOOM_NVIDIA_BRANCH=latest or a branch such as 580.
Set HEIRLOOM_NVIDIA_MODULES=open (default) or proprietary.
EOF
        return 0
        ;;
      *)
        printf 'Unknown flag: %s\n' "${arg}" >&2
        return 2
        ;;
    esac
  done
  if [[ "${upgrade}" -eq 1 ]]; then
    nv_log "Upgrading the NVIDIA driver stack"
  fi
  if [[ "${DRY_RUN}" -eq 0 && "${EUID}" -ne 0 ]]; then
    printf 'Re-run as root: sudo bash box/lib/nvidia-stack.sh\n' >&2
    return 1
  fi
  heirloom_nvidia_install_stack
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  heirloom_nvidia_main "$@"
fi
