#!/usr/bin/env bash
# First boot dry-run prints the plan. A simulated GPU failure stops before Heirloom.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIRSTBOOT="${ROOT}/box/autoinstall/firstboot.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

cat > "${TMP}/autoinstall.env" <<'EOF'
NVIDIA_DRIVER_BRANCH=latest
NVIDIA_KERNEL_MODULES=open
EXPECTED_GPU_NAME=3090
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
HEIRLOOM_REPO_REF=main
HOSTNAME=heirloom-twinbox
USERNAME=heirloom-nosuch
EOF

plan_log="${TMP}/plan.log"
HEIRLOOM_FIRSTBOOT_STATE="${TMP}/plan-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${plan_log}" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/autoinstall.env" \
  bash "${FIRSTBOOT}" --dry-run >"${TMP}/plan.out" 2>&1

plan="${TMP}/plan.out"
cat "${plan_log}" >> "${plan}"
need() {
  if ! grep -F -- "$1" "${plan}" >/dev/null; then
    printf 'dry-run plan missing: %s\n' "$1" >&2
    cat "${plan}" >&2
    exit 1
  fi
}
need "Waiting until the network"
need "apt-get full-upgrade"
need "linux-generic-hwe-24.04"
need "linux-firmware"
need "nvidia-open"
need "cuda-toolkit"
need "cudnn"
need "nvtop"
need "nvidia-container-toolkit"
need "would reboot now (load the HWE kernel after apt full-upgrade)"
need "would reboot now (load the NVIDIA driver)"
need "would require nvidia-smi to report a GPU whose name contains 3090"
need "--unattended --dev-tools --observer --presence"
need "would run heirloom-box status"
need "would systemctl disable heirloom-firstboot.service"
if [[ -f "${TMP}/plan-state/phase" ]]; then
  printf 'dry-run wrote a phase file\n' >&2
  exit 1
fi

# Already finished: no second install.
: > "${plan_log}"
mkdir -p "${TMP}/plan-state"
touch "${TMP}/plan-state/done"
HEIRLOOM_FIRSTBOOT_STATE="${TMP}/plan-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${plan_log}" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/autoinstall.env" \
  bash "${FIRSTBOOT}" --dry-run >"${TMP}/done.out" 2>&1
cat "${plan_log}" >> "${TMP}/done.out"
grep -F 'already finished' "${TMP}/done.out" >/dev/null
if grep -F 'box/install.sh' "${TMP}/done.out" >/dev/null; then
  printf 'finished state still planned an install\n' >&2
  exit 1
fi

# GPU missing after the driver reboot.
mkdir -p "${TMP}/bin" "${TMP}/gpu-state" "${TMP}/repo/box"
printf '#!/bin/bash\nexit 0\n' > "${TMP}/bin/install-stub.sh"
chmod 755 "${TMP}/bin/install-stub.sh"
printf 'phase\n' > "${TMP}/gpu-state/phase"
printf 'drivers-installed\n' > "${TMP}/gpu-state/phase"
cat > "${TMP}/gpu.env" <<'EOF'
EXPECTED_GPU_NAME=3090
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
USERNAME=heirloom-nosuch
HOSTNAME=heirloom-twinbox
EOF
set +e
HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/gpu.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/gpu.env" \
  HEIRLOOM_INSTALL_SH="${TMP}/bin/install-stub.sh" \
  HEIRLOOM_REPO_DIR="${TMP}/repo" \
  bash "${FIRSTBOOT}" >"${TMP}/gpu.out" 2>&1
gpu_code=$?
set -e
if [[ "${gpu_code}" -ne 42 ]]; then
  printf 'missing nvidia-smi exited %s\n' "${gpu_code}" >&2
  cat "${TMP}/gpu.log" "${TMP}/gpu.out" >&2
  exit 1
fi
grep -F 'ERROR: nvidia-smi is missing' "${TMP}/gpu.log" >/dev/null
if grep -F 'Starting Heirloom' "${TMP}/gpu.log" >/dev/null; then
  printf 'Heirloom install started without a GPU\n' >&2
  exit 1
fi
grep -F 'nvidia-smi-missing' "${TMP}/gpu-state/hard-fail" >/dev/null

# Wrong GPU name.
cat > "${TMP}/bin/nvidia-smi" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == --query-gpu=* ]]; then
  echo "NVIDIA GeForce RTX 4090, 24576 MiB, 580.00"
  exit 0
fi
exit 1
EOF
chmod 755 "${TMP}/bin/nvidia-smi"
printf 'drivers-installed\n' > "${TMP}/gpu-state/phase"
rm -f "${TMP}/gpu-state/hard-fail"
set +e
PATH="${TMP}/bin:${PATH}" \
  HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/mismatch.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/gpu.env" \
  HEIRLOOM_INSTALL_SH="${TMP}/bin/install-stub.sh" \
  bash "${FIRSTBOOT}" >"${TMP}/mismatch.out" 2>&1
mismatch_code=$?
set -e
if [[ "${mismatch_code}" -ne 42 ]]; then
  printf 'GPU mismatch exited %s\n' "${mismatch_code}" >&2
  cat "${TMP}/mismatch.log" >&2
  exit 1
fi
grep -F "did not report a GPU matching '3090'" "${TMP}/mismatch.log" >/dev/null
grep -F 'gpu-mismatch' "${TMP}/gpu-state/hard-fail" >/dev/null

# Matching 3090 continues into the Heirloom install. The Tailscale key stays out of the log.
cat > "${TMP}/bin/nvidia-smi" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == --query-gpu=* ]]; then
  echo "NVIDIA GeForce RTX 3090, 24576 MiB, 580.00"
  exit 0
fi
exit 1
EOF
cat > "${TMP}/bin/tailscale" <<EOF
#!/bin/bash
printf '%s\n' "\$*" >> "${TMP}/tailscale.args"
exit 0
EOF
chmod 755 "${TMP}/bin/tailscale"
cat > "${TMP}/bin/install-stub.sh" <<EOF
#!/bin/bash
printf '%s\n' "\$*" > "${TMP}/install.args"
exit 0
EOF
chmod 755 "${TMP}/bin/install-stub.sh"
cat > "${TMP}/bin/heirloom-box" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == status ]]; then
  echo "heirloom-box status ok"
  exit 0
fi
exit 1
EOF
chmod 755 "${TMP}/bin/heirloom-box"
printf '#!/bin/bash\nexit 0\n' > "${TMP}/repo/box/install.sh"
chmod 755 "${TMP}/repo/box/install.sh"
cat > "${TMP}/success.env" <<'EOF'
EXPECTED_GPU_NAME=3090
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
USERNAME=heirloom-nosuch
HOSTNAME=heirloom-twinbox
TAILSCALE_AUTH_KEY=tskey-auth-TESTSECRETVALUE
NVIDIA_DRIVER_BRANCH=latest
NVIDIA_KERNEL_MODULES=open
EOF
printf 'drivers-installed\n' > "${TMP}/gpu-state/phase"
rm -f "${TMP}/gpu-state/hard-fail" "${TMP}/gpu-state/done"
PATH="${TMP}/bin:${PATH}" \
  HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/success.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/success.env" \
  HEIRLOOM_INSTALL_SH="${TMP}/bin/install-stub.sh" \
  HEIRLOOM_REPO_DIR="${TMP}/repo" \
  HEIRLOOM_BOX_BIN="${TMP}/bin/heirloom-box" \
  bash "${FIRSTBOOT}" >"${TMP}/success.out" 2>&1
grep -F 'GPU check passed (3090).' "${TMP}/success.log" >/dev/null
grep -F 'nvidia-smi: NVIDIA GeForce RTX 3090' "${TMP}/success.log" >/dev/null
grep -F -- '--unattended --dev-tools --observer --presence' "${TMP}/install.args" >/dev/null
grep -F -- '--tailscale' "${TMP}/install.args" >/dev/null
grep -F 'heirloom-box status ok' "${TMP}/success.out" >/dev/null || grep -F 'heirloom-box status ok' "${TMP}/success.log" >/dev/null
if grep -F 'TESTSECRETVALUE' "${TMP}/success.log" >/dev/null; then
  printf 'Tailscale auth key was written to the first-boot log\n' >&2
  exit 1
fi
if grep -F 'TAILSCALE_AUTH_KEY=' "${TMP}/success.env" >/dev/null; then
  printf 'Tailscale auth key was left in autoinstall.env\n' >&2
  exit 1
fi
[[ -f "${TMP}/gpu-state/done" ]]

# Secure Boot stops before apt upgrade.
cat > "${TMP}/bin/mokutil" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == --sb-state ]]; then
  echo "SecureBoot enabled"
  exit 0
fi
exit 0
EOF
printf '#!/bin/bash\nexit 0\n' > "${TMP}/bin/getent"
cat > "${TMP}/bin/apt-get" <<EOF
#!/bin/bash
echo apt-was-called >> "${TMP}/apt.log"
exit 0
EOF
chmod 755 "${TMP}/bin/mokutil" "${TMP}/bin/getent" "${TMP}/bin/apt-get"
printf 'start\n' > "${TMP}/gpu-state/phase"
rm -f "${TMP}/gpu-state/done" "${TMP}/gpu-state/hard-fail" "${TMP}/apt.log"
set +e
PATH="${TMP}/bin:${PATH}" \
  HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/sb.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/gpu.env" \
  bash "${FIRSTBOOT}" >"${TMP}/sb.out" 2>&1
sb_code=$?
set -e
if [[ "${sb_code}" -ne 42 ]]; then
  printf 'secure boot exited %s\n' "${sb_code}" >&2
  cat "${TMP}/sb.log" >&2
  exit 1
fi
grep -F 'Secure Boot is enabled' "${TMP}/sb.log" >/dev/null
grep -F 'secure-boot' "${TMP}/gpu-state/hard-fail" >/dev/null
if [[ -f "${TMP}/apt.log" ]]; then
  printf 'apt ran while Secure Boot was on\n' >&2
  exit 1
fi

# A failed git clone must not leave a directory that makes the next boot refuse to clone.
mkdir -p "${TMP}/clone-parent/clone-repo/.git" "${TMP}/clone-parent/.heirloom-clone.stale"
printf 'partial\n' > "${TMP}/clone-parent/clone-repo/.git/HEAD"
printf 'junk\n' > "${TMP}/clone-parent/clone-repo/KEEPME"
printf 'stale\n' > "${TMP}/clone-parent/.heirloom-clone.stale/marker"
cat > "${TMP}/bin/git" <<EOF
#!/bin/bash
dest=""
for arg in "\$@"; do
  dest="\${arg}"
done
printf '%s\n' "\${dest}" >> "${TMP}/git-dests"
attempts=0
if [[ -f "${TMP}/git-attempts" ]]; then
  attempts="\$(cat "${TMP}/git-attempts")"
fi
attempts=\$((attempts + 1))
printf '%s\n' "\${attempts}" > "${TMP}/git-attempts"
if [[ "\${attempts}" -eq 1 ]]; then
  mkdir -p "\${dest}/.git"
  printf 'partial\n' > "\${dest}/.git/config"
  printf 'simulated clone failure\n' >&2
  exit 1
fi
mkdir -p "\${dest}/box"
printf '#!/bin/bash\nexit 0\n' > "\${dest}/box/install.sh"
chmod 755 "\${dest}/box/install.sh"
exit 0
EOF
chmod 755 "${TMP}/bin/git"
cat > "${TMP}/clone.env" <<'EOF'
EXPECTED_GPU_NAME=3090
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
HEIRLOOM_REPO_REF=main
USERNAME=heirloom-nosuch
HOSTNAME=heirloom-twinbox
NVIDIA_DRIVER_BRANCH=latest
NVIDIA_KERNEL_MODULES=open
EOF
printf 'gpu-ok\n' > "${TMP}/gpu-state/phase"
rm -f "${TMP}/gpu-state/done" "${TMP}/gpu-state/hard-fail" "${TMP}/git-dests" "${TMP}/git-attempts"
set +e
PATH="${TMP}/bin:${PATH}" \
  HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/clone-fail.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/clone.env" \
  HEIRLOOM_INSTALL_SH="${TMP}/bin/install-stub.sh" \
  HEIRLOOM_REPO_DIR="${TMP}/clone-parent/clone-repo" \
  HEIRLOOM_BOX_BIN="${TMP}/bin/heirloom-box" \
  bash "${FIRSTBOOT}" >"${TMP}/clone-fail.out" 2>&1
clone_fail_code=$?
set -e
if [[ "${clone_fail_code}" -eq 0 ]]; then
  printf 'failed clone exited 0\n' >&2
  cat "${TMP}/clone-fail.log" >&2
  exit 1
fi
grep -F 'Removed the partial checkout' "${TMP}/clone-fail.log" >/dev/null
if [[ -f "${TMP}/clone-parent/clone-repo/box/install.sh" ]]; then
  printf 'failed clone published a repo\n' >&2
  exit 1
fi
if [[ ! -f "${TMP}/clone-parent/clone-repo/KEEPME" ]]; then
  printf 'failed clone deleted the previous incomplete tree\n' >&2
  exit 1
fi
shopt -s nullglob
stale=("${TMP}/clone-parent"/.heirloom-clone.*)
shopt -u nullglob
if [[ ${#stale[@]} -ne 0 ]]; then
  printf 'partial clone directory left behind: %s\n' "${stale[*]}" >&2
  exit 1
fi
if [[ ! -s "${TMP}/git-dests" ]]; then
  printf 'git was not invoked\n' >&2
  exit 1
fi
while IFS= read -r git_dest; do
  if [[ "${git_dest}" == "${TMP}/clone-parent/clone-repo" ]]; then
    printf 'git clone targeted the final repo directory\n' >&2
    exit 1
  fi
  case "${git_dest}" in
    "${TMP}/clone-parent/.heirloom-clone."*) ;;
    *)
      printf 'git clone target was not a staging directory: %s\n' "${git_dest}" >&2
      exit 1
      ;;
  esac
done < "${TMP}/git-dests"

printf 'gpu-ok\n' > "${TMP}/gpu-state/phase"
rm -f "${TMP}/gpu-state/done" "${TMP}/install.args"
PATH="${TMP}/bin:${PATH}" \
  HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT=1 \
  HEIRLOOM_FIRSTBOOT_STATE="${TMP}/gpu-state" \
  HEIRLOOM_FIRSTBOOT_LOG="${TMP}/clone-retry.log" \
  HEIRLOOM_AUTOINSTALL_ENV="${TMP}/clone.env" \
  HEIRLOOM_INSTALL_SH="${TMP}/bin/install-stub.sh" \
  HEIRLOOM_REPO_DIR="${TMP}/clone-parent/clone-repo" \
  HEIRLOOM_BOX_BIN="${TMP}/bin/heirloom-box" \
  bash "${FIRSTBOOT}" >"${TMP}/clone-retry.out" 2>&1
[[ -f "${TMP}/clone-parent/clone-repo/box/install.sh" ]]
if [[ -f "${TMP}/clone-parent/clone-repo/KEEPME" ]]; then
  printf 'retry left the failed checkout in place\n' >&2
  exit 1
fi
grep -F -- '--unattended --dev-tools --observer --presence' "${TMP}/install.args" >/dev/null
[[ -f "${TMP}/gpu-state/done" ]]
shopt -s nullglob
stale=("${TMP}/clone-parent"/.heirloom-clone.*)
shopt -u nullglob
if [[ ${#stale[@]} -ne 0 ]]; then
  printf 'staging directory survived a successful clone: %s\n' "${stale[*]}" >&2
  exit 1
fi

echo "firstboot dry-run ok"
