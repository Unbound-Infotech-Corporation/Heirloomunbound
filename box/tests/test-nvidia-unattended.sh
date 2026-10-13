#!/usr/bin/env bash
# NVIDIA stack dry-run, unattended installer flag, and heirloom-box update-drivers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STACK="${ROOT}/box/lib/nvidia-stack.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

latest="$(HEIRLOOM_NVIDIA_ENV="${TMP}/none.env" bash "${STACK}" --dry-run 2>&1)"
for needle in cuda-keyring nvidia-open cuda-toolkit cudnn nvtop nvidia-container-toolkit "linux-headers-" "branch=latest"; do
  if ! printf '%s\n' "${latest}" | grep -F -- "${needle}" >/dev/null; then
    printf 'latest dry-run missing %s\n' "${needle}" >&2
    printf '%s\n' "${latest}" >&2
    exit 1
  fi
done
if printf '%s\n' "${latest}" | grep -F 'nvidia-driver-pinning-' >/dev/null; then
  printf 'latest dry-run pinned a branch\n' >&2
  exit 1
fi

pinned="$(HEIRLOOM_NVIDIA_BRANCH=580 HEIRLOOM_NVIDIA_ENV="${TMP}/none.env" bash "${STACK}" --dry-run --upgrade 2>&1)"
printf '%s\n' "${pinned}" | grep -F 'nvidia-driver-pinning-580' >/dev/null
printf '%s\n' "${pinned}" | grep -F 'Upgrading the NVIDIA driver stack' >/dev/null

prop="$(HEIRLOOM_NVIDIA_MODULES=proprietary HEIRLOOM_NVIDIA_ENV="${TMP}/none.env" bash "${STACK}" --dry-run 2>&1)"
printf '%s\n' "${prop}" | grep -F 'driver=cuda-drivers' >/dev/null

set +e
bad="$(HEIRLOOM_NVIDIA_BRANCH='580;rm' HEIRLOOM_NVIDIA_ENV="${TMP}/none.env" bash "${STACK}" --dry-run 2>&1)"
bad_code=$?
set -e
if [[ "${bad_code}" -eq 0 ]]; then
  printf 'unsafe branch was accepted\n' >&2
  exit 1
fi
printf '%s\n' "${bad}" | grep -F 'NVIDIA branch must be' >/dev/null

install_out="$(bash "${ROOT}/box/install.sh" --dry-run --unattended 2>&1)"
install_code=0
printf '%s\n' "${install_out}" | grep -F 'unattended=1' >/dev/null
printf '%s\n' "${install_out}" | grep -F 'Unattended mode:' >/dev/null
printf '%s\n' "${install_out}" | grep -F 'sudo heirloom-box update-drivers' >/dev/null
if printf '%s\n' "${install_out}" | grep -F 'exits 75' >/dev/null; then
  printf 'dry-run claimed exit 75\n' >&2
  exit 1
fi

drivers="$(bash "${ROOT}/box/heirloom-box" update-drivers --dry-run 2>&1)"
printf '%s\n' "${drivers}" | grep -F 'cuda-keyring' >/dev/null
printf '%s\n' "${drivers}" | grep -F 'nvidia-open' >/dev/null

# Existing presence dry-run still passes.
bash "${ROOT}/box/tests/test-presence-dry-run.sh" >/dev/null

echo "nvidia unattended ok (install dry-run exit ${install_code})"
