#!/usr/bin/env bash
# First boot of the Heirloom Twin Box.
# Idempotent. Waits for the network, upgrades Ubuntu, installs the HWE kernel
# and the NVIDIA CUDA stack, reboots, checks that nvidia-smi sees the expected
# GPU, then runs box/install.sh --unattended --dev-tools --observer --presence.
# Logs to /var/log/heirloom-firstboot.log. Disables itself only after success.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "heirloom-firstboot requires bash." >&2
  exit 1
fi
set -euo pipefail

STATE="${HEIRLOOM_FIRSTBOOT_STATE:-/var/lib/heirloom-firstboot}"
LOG_PATH="${HEIRLOOM_FIRSTBOOT_LOG:-/var/log/heirloom-firstboot.log}"
DRY_RUN=0
SIMULATE_REBOOT=0
USED_TAILSCALE=0

usage() {
  cat <<'EOF'
Usage: heirloom-firstboot [--dry-run]

  --dry-run    print the boot plan and change nothing
EOF
}

log() {
  local line
  line="$(date -Is) $*"
  if [[ -n "${LOG_PATH:-}" ]]; then
    printf '%s\n' "${line}" >> "${LOG_PATH}"
  fi
  printf '%s\n' "${line}" >&2
}

run_cmd() {
  log "RUN $*"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  "$@" 2>&1 | tee -a "${LOG_PATH}"
}

read_phase() {
  if [[ -f "${STATE}/phase" ]]; then
    tr -d '[:space:]' < "${STATE}/phase"
    return 0
  fi
  printf '%s\n' "start"
}

write_phase() {
  mkdir -p "${STATE}"
  printf '%s\n' "$1" > "${STATE}/phase"
}

load_config() {
  local file="${HEIRLOOM_AUTOINSTALL_ENV:-/etc/heirloom/autoinstall.env}"
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local envfile=""
  if [[ -f "${here}/../lib/envfile.sh" ]]; then
    envfile="${here}/../lib/envfile.sh"
  elif [[ -f /usr/local/lib/heirloom/envfile.sh ]]; then
    envfile=/usr/local/lib/heirloom/envfile.sh
  fi
  if [[ -n "${envfile}" ]]; then
    # shellcheck source=box/lib/envfile.sh
    source "${envfile}"
    heirloom_load_env_file "${file}"
  fi
  export HEIRLOOM_NVIDIA_BRANCH="${NVIDIA_DRIVER_BRANCH:-${HEIRLOOM_NVIDIA_BRANCH:-latest}}"
  export HEIRLOOM_NVIDIA_MODULES="${NVIDIA_KERNEL_MODULES:-${HEIRLOOM_NVIDIA_MODULES:-open}}"
  export EXPECTED_GPU_NAME="${EXPECTED_GPU_NAME:-3090}"
}

prepare_log() {
  local dir
  if [[ "${DRY_RUN}" -eq 1 || "${SIMULATE_REBOOT}" -eq 1 ]]; then
    if ! mkdir -p "${STATE}" 2>/dev/null || [[ ! -w "${STATE}" ]]; then
      STATE="${TMPDIR:-/tmp}/heirloom-firstboot-state"
      mkdir -p "${STATE}"
    fi
    dir="$(dirname "${LOG_PATH}")"
    if [[ ! -d "${dir}" || ! -w "${dir}" ]]; then
      LOG_PATH="${TMPDIR:-/tmp}/heirloom-firstboot.log"
    fi
  else
    dir="$(dirname "${LOG_PATH}")"
    if [[ ! -d "${dir}" || ! -w "${dir}" ]]; then
      printf 'Cannot write %s\n' "${LOG_PATH}" >&2
      exit 1
    fi
    mkdir -p "${STATE}"
  fi
  touch "${LOG_PATH}"
}

wait_for_network() {
  local attempt
  log "Waiting until the network can reach the Ubuntu archive"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would retry DNS and HTTPS until archive.ubuntu.com answers"
    return 0
  fi
  for attempt in $(seq 1 90); do
    if getent hosts archive.ubuntu.com >/dev/null 2>&1; then
      log "Network is up (attempt ${attempt})"
      return 0
    fi
    sleep 10
  done
  log "Network did not come up. The service will retry."
  return 1
}

secure_boot_enabled() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 1
  fi
  if command -v mokutil >/dev/null 2>&1; then
    if mokutil --sb-state 2>/dev/null | grep -qi 'SecureBoot enabled'; then
      return 0
    fi
    return 1
  fi
  local var byte
  var="$(find /sys/firmware/efi/efivars -name 'SecureBoot-*' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${var}" ]]; then
    byte="$(od -An -t u1 "${var}" 2>/dev/null | awk '{print $NF}' || true)"
    [[ "${byte}" == "1" ]]
    return
  fi
  return 1
}

check_secure_boot() {
  log "Checking Secure Boot. The NVIDIA open modules are not enrolled for unattended MOK."
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would stop with exit 42 if Secure Boot is enabled. Turn it off in firmware. A blue MOK screen still needs a person, so this path does not enroll a key."
    return 0
  fi
  if secure_boot_enabled; then
    log "ERROR: Secure Boot is enabled."
    log "Turn Secure Boot off in the Twin Box firmware setup, then reboot."
    log "Non-interactive MOK enrollment is not possible. The firmware confirmation screen needs someone at the keyboard."
    log "The NVIDIA driver was not installed. No Heirloom install was started."
    printf '%s\n' "secure-boot" > "${STATE}/hard-fail"
    exit 42
  fi
  log "Secure Boot is off, or this machine has no UEFI Secure Boot variable."
}

kernel_is_newest_installed() {
  local running newest file ver
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  running="$(uname -r)"
  newest="${running}"
  shopt -s nullglob
  for file in /boot/vmlinuz-*; do
    ver="${file#/boot/vmlinuz-}"
    if command -v linux-version >/dev/null 2>&1; then
      newest="$(printf '%s\n%s\n' "${newest}" "${ver}" | linux-version sort | tail -n 1)"
    elif [[ "${ver}" > "${newest}" ]]; then
      newest="${ver}"
    fi
  done
  shopt -u nullglob
  [[ "${running}" == "${newest}" ]]
}

upgrade_system() {
  log "Full apt upgrade, HWE kernel (linux-generic-hwe-24.04), and current linux-firmware"
  export DEBIAN_FRONTEND=noninteractive
  export NEEDRESTART_MODE=a
  export APT_LISTCHANGES_FRONTEND=none
  run_cmd apt-get update
  run_cmd apt-get full-upgrade -y \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold
  run_cmd apt-get install -y \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    linux-generic-hwe-24.04 linux-firmware mokutil ca-certificates curl git
}

do_reboot() {
  local reason="$1"
  log "Rebooting: ${reason}"
  if [[ "${DRY_RUN}" -eq 1 || "${SIMULATE_REBOOT}" -eq 1 ]]; then
    log "would reboot now (${reason})"
    return 0
  fi
  sync
  systemctl reboot || reboot || true
  sleep 30
  log "ERROR: reboot did not happen."
  exit 1
}

nvidia_script() {
  if [[ -n "${HEIRLOOM_NVIDIA_STACK:-}" && -f "${HEIRLOOM_NVIDIA_STACK}" ]]; then
    printf '%s\n' "${HEIRLOOM_NVIDIA_STACK}"
    return 0
  fi
  if [[ -f /usr/local/lib/heirloom/nvidia-stack.sh ]]; then
    printf '%s\n' /usr/local/lib/heirloom/nvidia-stack.sh
    return 0
  fi
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "${here}/../lib/nvidia-stack.sh" ]]; then
    printf '%s\n' "${here}/../lib/nvidia-stack.sh"
    return 0
  fi
  return 1
}

install_drivers() {
  local script
  script="$(nvidia_script)"
  log "Installing the NVIDIA production stack from the CUDA apt repo before Heirloom starts"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    bash "${script}" --dry-run
    return 0
  fi
  bash "${script}" 2>&1 | tee -a "${LOG_PATH}"
}

verify_gpu() {
  local expected out
  expected="${EXPECTED_GPU_NAME:-3090}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would require nvidia-smi to report a GPU whose name contains ${expected}"
    log "would fail loudly and skip the Heirloom install if it does not"
    return 0
  fi
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    log "ERROR: nvidia-smi is missing after the driver reboot."
    printf '%s\n' "nvidia-smi-missing" > "${STATE}/hard-fail"
    return 42
  fi
  if ! out="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1)"; then
    log "ERROR: nvidia-smi failed after the driver reboot."
    log "${out}"
    printf '%s\n' "nvidia-smi-failed" > "${STATE}/hard-fail"
    return 42
  fi
  log "nvidia-smi: ${out}"
  if ! grep -q -F -- "${expected}" <<<"${out}"; then
    log "ERROR: nvidia-smi did not report a GPU matching '${expected}'."
    log "The Twin Box card is an RTX 3090. Heirloom install will not start."
    printf '%s\n' "gpu-mismatch" > "${STATE}/hard-fail"
    return 42
  fi
  log "GPU check passed (${expected})."
}

scrub_tailscale_key() {
  local file="${HEIRLOOM_AUTOINSTALL_ENV:-/etc/heirloom/autoinstall.env}"
  [[ -f "${file}" ]] || return 0
  local tmp
  tmp="$(mktemp)"
  awk 'index($0, "TAILSCALE_AUTH_KEY=") != 1 { print }' "${file}" > "${tmp}"
  cat "${tmp}" > "${file}"
  rm -f "${tmp}"
  chmod 600 "${file}" || true
}

bring_up_tailscale() {
  if [[ -z "${TAILSCALE_AUTH_KEY:-}" ]]; then
    log "No Tailscale auth key. The box will not join a tailnet by itself."
    return 0
  fi
  USED_TAILSCALE=1
  log "Installing Tailscale and joining the tailnet. The auth key is not written to this log."
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would run tailscale up --ssh --hostname=${HOSTNAME:-heirloom-twinbox}"
    return 0
  fi
  if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  local keyfile
  keyfile="${STATE}/tailscale.auth"
  printf '%s' "${TAILSCALE_AUTH_KEY}" > "${keyfile}"
  chmod 600 "${keyfile}"
  tailscale up \
    --auth-key="$(cat "${keyfile}")" \
    --ssh \
    --hostname="${HOSTNAME:-heirloom-twinbox}" \
    --accept-dns=true
  rm -f "${keyfile}"
  scrub_tailscale_key
  unset TAILSCALE_AUTH_KEY
}

unpack_payload() {
  local archive="$1"
  local dest="$2"
  mkdir -p "${dest}"
  if tar -tzf "${archive}" | grep -Eq '(^|/)box/install\.sh$'; then
    if tar -tzf "${archive}" | grep -Eq '^box/install\.sh$'; then
      tar -xzf "${archive}" -C "${dest}"
    else
      tar -xzf "${archive}" -C "${dest}" --strip-components=1
    fi
  else
    log "ERROR: ${archive} does not contain box/install.sh"
    return 42
  fi
  [[ -f "${dest}/box/install.sh" ]]
}

obtain_repo() {
  local dest="${HEIRLOOM_REPO_DIR:-/opt/heirloom}"
  local code=0
  if [[ -f "${dest}/box/install.sh" ]]; then
    log "Heirloom repo already present at ${dest}"
    printf '%s\n' "${dest}"
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    if [[ -n "${HEIRLOOM_REPO_URL:-}" ]]; then
      log "would git clone ${HEIRLOOM_REPO_URL} (${HEIRLOOM_REPO_REF:-main}) to ${dest}"
    elif [[ -f "${STATE}/heirloom.tar.gz" ]]; then
      log "would unpack ${STATE}/heirloom.tar.gz to ${dest}"
    else
      log "would fail: set HEIRLOOM_REPO_URL or place a payload tarball on the USB"
    fi
    printf '%s\n' "${dest}"
    return 0
  fi
  if [[ -f "${STATE}/heirloom.tar.gz" ]]; then
    log "Unpacking the Heirloom payload"
    unpack_payload "${STATE}/heirloom.tar.gz" "${dest}"
    printf '%s\n' "${dest}"
    return 0
  fi
  if [[ -z "${HEIRLOOM_REPO_URL:-}" ]]; then
    log "ERROR: HEIRLOOM_REPO_URL is empty and there is no payload tarball."
    return 42
  fi
  log "Cloning ${HEIRLOOM_REPO_URL}"
  # obtain_repo runs in a command substitution, where bash ignores set -e
  # inside functions. A failed clone must be returned or the next line would
  # publish the path and the boot would look successful.
  if clone_repo "${dest}"; then
    code=0
  else
    code=$?
    return "${code}"
  fi
  printf '%s\n' "${dest}"
}

# git clone into dest itself leaves that directory behind when the network
# drops. The next boot then refuses the non-empty path and box/install.sh is
# still missing. Clone beside dest, and only publish the tree after install.sh
# is there. A failed attempt removes its partial directory.
clone_repo() {
  local dest="$1"
  local parent staging old
  if [[ -z "${dest}" || "${dest}" == "/" || "${dest}" != /* ]]; then
    log "ERROR: refusing repo path ${dest:-<empty>}"
    return 42
  fi
  if [[ -L "${dest}" ]]; then
    log "ERROR: ${dest} is a symlink. Refusing to replace it."
    return 42
  fi
  parent="$(dirname "${dest}")"
  if [[ -z "${parent}" || "${parent}" == "/" ]]; then
    log "ERROR: refusing to clone into ${dest}"
    return 42
  fi
  mkdir -p "${parent}" || return 1
  while IFS= read -r old; do
    [[ -n "${old}" ]] || continue
    rm -rf -- "${old:?}" || return 1
  done < <(find "${parent}" -mindepth 1 -maxdepth 1 -name '.heirloom-clone.*' -print)
  staging="$(mktemp -d "${parent}/.heirloom-clone.XXXXXX")" || return 1
  case "${staging}" in
    "${parent}/.heirloom-clone."*) ;;
    *)
      log "ERROR: unexpected clone directory ${staging}"
      return 42
      ;;
  esac
  if ! git clone --branch "${HEIRLOOM_REPO_REF:-main}" --depth 1 "${HEIRLOOM_REPO_URL}" "${staging}" >> "${LOG_PATH}" 2>&1; then
    rm -rf -- "${staging:?}"
    log "ERROR: git clone failed. Removed the partial checkout so the next attempt can clone again."
    return 1
  fi
  if [[ ! -f "${staging}/box/install.sh" ]]; then
    rm -rf -- "${staging:?}"
    log "ERROR: clone does not contain box/install.sh"
    return 42
  fi
  if [[ -e "${dest}" ]]; then
    rm -rf -- "${dest:?}"
  fi
  if ! mv "${staging}" "${dest}"; then
    rm -rf -- "${staging:?}"
    log "ERROR: could not move the clone into ${dest}"
    return 1
  fi
}

run_heirloom_install() {
  local root="$1"
  local script="${HEIRLOOM_INSTALL_SH:-${root}/box/install.sh}"
  local -a args=(--unattended --dev-tools --observer --presence)
  if [[ "${USED_TAILSCALE}" -eq 1 || -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
    args+=(--tailscale)
  fi
  log "Starting Heirloom: bash ${script} ${args[*]}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  local code=0
  set +e
  bash "${script}" "${args[@]}" 2>&1 | tee -a "${LOG_PATH}"
  code=${PIPESTATUS[0]}
  set -e
  if [[ "${code}" -eq 75 ]]; then
    log "Installer asked for a reboot before containers start."
    do_reboot "installer exit 75"
    return 0
  fi
  return "${code}"
}

add_user_groups() {
  local user="${USERNAME:-heirloom}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would add ${user} to the docker and video groups"
    return 0
  fi
  if ! id "${user}" >/dev/null 2>&1; then
    log "User ${user} does not exist yet. Skipping group membership."
    return 0
  fi
  if getent group docker >/dev/null 2>&1; then
    usermod -aG docker "${user}" || true
  fi
  if getent group video >/dev/null 2>&1; then
    usermod -aG video "${user}" || true
  fi
}

finish() {
  local status_bin="${HEIRLOOM_BOX_BIN:-}"
  log "Running heirloom-box status"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would run heirloom-box status"
    log "would systemctl disable heirloom-firstboot.service"
    log "First boot finished. This service will not run again."
    return 0
  fi
  if [[ -n "${status_bin}" ]]; then
    "${status_bin}" status || log "heirloom-box status returned non-zero. See the output above."
  elif [[ -x /usr/local/bin/heirloom-box ]]; then
    /usr/local/bin/heirloom-box status || log "heirloom-box status returned non-zero. See the output above."
  else
    log "heirloom-box is not installed yet."
  fi
  if [[ "${SIMULATE_REBOOT}" -eq 1 ]]; then
    log "would systemctl disable heirloom-firstboot.service"
  else
    systemctl disable heirloom-firstboot.service || log "could not disable heirloom-firstboot.service"
  fi
  write_phase "done"
  mkdir -p "${STATE}"
  touch "${STATE}/done"
  log "First boot finished. This service will not run again."
}

dry_run_plan() {
  local root
  wait_for_network
  check_secure_boot
  upgrade_system
  do_reboot "load the HWE kernel after apt full-upgrade"
  install_drivers
  do_reboot "load the NVIDIA driver"
  verify_gpu
  bring_up_tailscale
  root="$(obtain_repo)"
  run_heirloom_install "${root}"
  add_user_groups
  finish
}

continue_after_reboot() {
  [[ "${DRY_RUN}" -eq 1 || "${SIMULATE_REBOOT}" -eq 1 ]]
}

main() {
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --dry-run) DRY_RUN=1 ;;
      -h|--help) usage; exit 0 ;;
      *)
        printf 'Unknown flag: %s\n' "${arg}" >&2
        usage >&2
        exit 2
        ;;
    esac
  done
  if [[ "${HEIRLOOM_FIRSTBOOT_SIMULATE_REBOOT:-}" == "1" ]]; then
    SIMULATE_REBOOT=1
  fi
  prepare_log
  load_config
  log "Heirloom first boot dry_run=${DRY_RUN} state=${STATE} branch=${HEIRLOOM_NVIDIA_BRANCH:-latest} gpu=${EXPECTED_GPU_NAME:-3090}"
  if [[ -f "${STATE}/done" ]]; then
    log "First boot already finished. Nothing to do."
    exit 0
  fi
  if [[ "${DRY_RUN}" -eq 1 && "${SIMULATE_REBOOT}" -ne 1 ]]; then
    dry_run_plan
    exit 0
  fi
  local guard=0 phase root
  while (( guard < 8 )); do
    guard=$((guard + 1))
    phase="$(read_phase)"
    log "phase=${phase}"
    case "${phase}" in
      start)
        wait_for_network
        check_secure_boot
        upgrade_system
        write_phase upgraded
        do_reboot "load the HWE kernel after apt full-upgrade"
        continue_after_reboot || exit 0
        ;;
      upgraded)
        if ! kernel_is_newest_installed && [[ ! -f "${STATE}/kernel-extra-reboot" ]]; then
          mkdir -p "${STATE}"
          touch "${STATE}/kernel-extra-reboot"
          do_reboot "running kernel is older than the installed HWE kernel"
          continue_after_reboot || exit 0
        fi
        install_drivers
        write_phase drivers-installed
        do_reboot "load the NVIDIA driver"
        continue_after_reboot || exit 0
        ;;
      drivers-installed)
        verify_gpu || exit 42
        write_phase gpu-ok
        ;;
      gpu-ok)
        bring_up_tailscale
        root="$(obtain_repo)" || exit $?
        run_heirloom_install "${root}"
        add_user_groups
        write_phase heirloom
        ;;
      heirloom)
        finish
        exit 0
        ;;
      done)
        log "First boot already finished. Nothing to do."
        exit 0
        ;;
      *)
        log "ERROR: unknown phase ${phase}"
        exit 42
        ;;
    esac
  done
  log "ERROR: first boot did not finish after ${guard} steps."
  exit 1
}

main "$@"
