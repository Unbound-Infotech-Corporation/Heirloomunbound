#!/usr/bin/env bash
# Heirloom Twin Box installer for Ubuntu Server 24.04 LTS.
# Idempotent. Re-run after git pull. Credentials are never written by this script
# except a local CONNECTOR_SECRET_KEY generated on the machine.
if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "box/install.sh requires bash." >&2
  exit 1
fi
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=box/lib/models.sh
source "${ROOT}/box/lib/models.sh"

LOG_PATH="/var/log/heirloom-box-install.log"
DRY_RUN=0
DEV_TOOLS=0
WITH_TAILSCALE=0
WITH_CHATTERBOX=0
WITH_OBSERVER=0
WITH_PRESENCE=0
export DEBIAN_FRONTEND=noninteractive

usage() {
  cat <<'EOF'
Usage: sudo bash box/install.sh [--dry-run] [--dev-tools] [--tailscale] [--with-chatterbox] [--observer] [--presence]

  --dry-run           print the plan and write the log; change nothing
  --dev-tools         git, gh, Node.js LTS, Python 3.12, uv, Cursor CLI, Claude Code
  --tailscale         install Tailscale; you run `tailscale up` yourself
  --with-chatterbox   optional MIT Chatterbox TTS container
  --observer          watch the HDMI capture card and learn notes on this lab box
  --presence          watch USB webcams and greet people the owner has taught
EOF
}

log() {
  local line
  line="$(date -Is) $*"
  printf '%s\n' "${line}" | tee -a "${LOG_PATH}"
}

run() {
  log "RUN $*"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  "$@"
}

prepare_log() {
  local dir
  dir="$(dirname "${LOG_PATH}")"
  if [[ ! -w "${dir}" ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      LOG_PATH="${TMPDIR:-/tmp}/heirloom-box-install.log"
      printf 'Log directory is not writable; dry-run log is %s\n' "${LOG_PATH}" >&2
    else
      printf 'Cannot write %s. Re-run with sudo.\n' "${LOG_PATH}" >&2
      exit 1
    fi
  fi
  touch "${LOG_PATH}"
}

parse_args() {
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --dry-run) DRY_RUN=1 ;;
      --dev-tools) DEV_TOOLS=1 ;;
      --tailscale) WITH_TAILSCALE=1 ;;
      --with-chatterbox) WITH_CHATTERBOX=1 ;;
      --observer) WITH_OBSERVER=1 ;;
      --presence) WITH_PRESENCE=1 ;;
      -h|--help) usage; exit 0 ;;
      *)
        printf 'Unknown flag: %s\n' "${arg}" >&2
        usage >&2
        exit 2
        ;;
    esac
  done
}

require_ubuntu() {
  local id="" version=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    id="${ID:-}"
    version="${VERSION_ID:-}"
  fi
  if [[ "${id}" == "ubuntu" && "${version}" == "24.04" ]]; then
    log "OS Ubuntu ${version}"
    return 0
  fi
  log "This installer targets Ubuntu Server 24.04 LTS (found ${id:-unknown} ${version:-unknown})."
  if [[ "${DRY_RUN}" -eq 0 && "${HEIRLOOM_BOX_ALLOW_OS:-}" != "1" ]]; then
    exit 1
  fi
}

gpu_present() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  if [[ -e /dev/nvidia0 ]]; then
    return 0
  fi
  if command -v lspci >/dev/null 2>&1 && lspci -nn 2>/dev/null | grep -qi 'nvidia'; then
    return 0
  fi
  return 1
}

vram_mib() {
  local value=""
  if command -v nvidia-smi >/dev/null 2>&1; then
    value="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -d '[:space:]' || true)"
  fi
  if [[ "${value}" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "${value}"
  else
    printf '0\n'
  fi
}

ssh_keys_present() {
  local home="" file
  if [[ -n "${SUDO_USER:-}" ]]; then
    home="$(getent passwd "${SUDO_USER}" | cut -d: -f6 || true)"
    if [[ -n "${home}" && -s "${home}/.ssh/authorized_keys" ]]; then
      return 0
    fi
  fi
  shopt -s nullglob
  for file in /home/*/.ssh/authorized_keys /root/.ssh/authorized_keys; do
    if [[ -s "${file}" ]]; then
      shopt -u nullglob
      return 0
    fi
  done
  shopt -u nullglob
  return 1
}

upsert_env() {
  local key="$1"
  local value="$2"
  local file="$3"
  local tmp
  tmp="$(mktemp)"
  if [[ -f "${file}" ]] && grep -q "^${key}=" "${file}"; then
    awk -v k="${key}" -v v="${value}" '{
      if (index($0, k "=") == 1) print k "=" v; else print $0
    }' "${file}" > "${tmp}"
    mv "${tmp}" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${file}"
    rm -f "${tmp}"
  fi
}

install_base() {
  log "Installing Docker, Mongo client tools, Caddy dependencies, SSH, firewall, and unattended upgrades"
  run apt-get update
  run apt-get install -y \
    ca-certificates curl gnupg openssl \
    docker.io docker-compose-v2 \
    openssh-server ufw unattended-upgrades \
    python3 python3-venv python3-pip
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    systemctl enable --now docker
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
      usermod -aG docker "${SUDO_USER}"
      log "Added ${SUDO_USER} to the docker group. Open a new login, then heirloom-box status works without sudo."
    fi
    echo 'unattended-upgrades unattended-upgrades/enable_auto_updates boolean true' | debconf-set-selections
    dpkg-reconfigure -f noninteractive unattended-upgrades
  else
    log "would enable docker and unattended-upgrades, and add the installing user to the docker group"
  fi
}

install_nvidia() {
  if ! gpu_present; then
    log "No NVIDIA GPU detected. Ollama will run on CPU. Skipping driver and container toolkit."
    return 0
  fi
  log "NVIDIA GPU detected"
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    log "nvidia-smi already answers. Skipping the driver package."
  else
    log "Installing nvidia-driver-550-server. Reboot, then re-run box/install.sh before GPU containers start."
    run apt-get install -y nvidia-driver-550-server
    NEED_REBOOT=1
  fi
  log "Installing the NVIDIA container toolkit"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would add the NVIDIA container toolkit apt repo, install it, and restart Docker"
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
  apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
}

install_tailscale() {
  if [[ "${WITH_TAILSCALE}" -ne 1 ]]; then
    log "Tailscale not requested"
    return 0
  fi
  if command -v tailscale >/dev/null 2>&1; then
    log "Tailscale already installed. Log in with: sudo tailscale up"
    return 0
  fi
  log "Installing Tailscale. This does not log in."
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would run https://tailscale.com/install.sh"
    return 0
  fi
  curl -fsSL https://tailscale.com/install.sh | sh
  log "Tailscale is installed. Run: sudo tailscale up"
}

install_dev_tools() {
  if [[ "${DEV_TOOLS}" -ne 1 ]]; then
    log "Dev tools not requested. git is still installed so the box can update."
    run apt-get install -y git
    return 0
  fi
  log "Installing dev tools. No tokens are stored."
  run apt-get install -y git
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null || true)" != v22* ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "would install Node.js 22 from NodeSource"
    else
      curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
      apt-get install -y nodejs
    fi
  else
    log "Node.js $(node -v) already present"
  fi
  if ! command -v gh >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "would install GitHub CLI from cli.github.com"
    else
      install -d -m 0755 /etc/apt/keyrings
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
      chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | tee /etc/apt/sources.list.d/github-cli.list >/dev/null
      apt-get update
      apt-get install -y gh
    fi
  fi
  if ! command -v uv >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "would install uv into /usr/local/bin"
    else
      curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
    fi
  fi
  if ! command -v agent >/dev/null 2>&1 && ! command -v cursor-agent >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "would install the Cursor CLI from https://cursor.com/install"
    else
      curl -fsSL https://cursor.com/install | bash
    fi
  fi
  if ! command -v claude >/dev/null 2>&1; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      log "would npm install -g @anthropic-ai/claude-code"
    else
      npm install -g @anthropic-ai/claude-code
    fi
  fi
}

harden_ssh() {
  local dropin="/etc/ssh/sshd_config.d/99-heirloom-box.conf"
  if ! ssh_keys_present; then
    log "SSH password login stays on until ~/.ssh/authorized_keys exists. Add a key, then re-run box/install.sh."
    return 0
  fi
  log "Hardening SSH at ${dropin}: public-key only, root login off"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  install -d -m 0755 /etc/ssh/sshd_config.d
  cat > "${dropin}" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
  systemctl reload ssh
}

configure_ufw() {
  log "Configuring ufw: deny incoming, allow OpenSSH, 80/tcp, 443/tcp"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw default deny incoming
  ufw default allow outgoing
  ufw --force enable
}

write_tree() {
  log "Preparing /var/lib/heirloom and /etc/heirloom"
  run install -d -m 0750 /var/lib/heirloom
  run install -d -m 0750 /var/lib/heirloom/vault
  run install -d -m 0750 /var/lib/heirloom/lab
  run install -d -m 0750 /var/lib/heirloom/lab-reports
  run install -d -m 0750 /var/lib/heirloom/backups
  run install -d -m 0750 /var/lib/heirloom/mongo
  run install -d -m 0750 /var/lib/heirloom/ollama
  run install -d -m 0750 /var/lib/heirloom/caddy
  run install -d -m 0750 /var/lib/heirloom/caddy-config
  if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    run install -d -m 0750 /var/lib/heirloom/observer
  fi
  if [[ "${WITH_PRESENCE}" -eq 1 ]]; then
    run install -d -m 0750 /var/lib/heirloom/presence
    run install -d -m 0750 /var/lib/heirloom/presence/models
  fi
  run install -d -m 0755 /etc/heirloom
}

write_env() {
  local env_file="/var/lib/heirloom/box.env"
  local model="$1"
  local observer_model="$2"
  local vram="$3"
  local max_loaded="${4:-1}"
  local vision_keep="${5:-45s}"
  local secret=""
  log "Writing ${env_file} (local connector key only; no GitHub or vendor tokens)"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would set HEIRLOOM_LLM_PROVIDER=ollama OLLAMA_TWIN_MODEL=${model} HEIRLOOM_LAB_MODE=1"
    if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
      log "would set HEIRLOOM_OBSERVER=1 OLLAMA_OBSERVER_MODEL=${observer_model:-ocr} OBSERVER_VRAM_MIB=${vram} OLLAMA_MAX_LOADED_MODELS=${max_loaded} OBSERVER_VISION_KEEP_ALIVE=${vision_keep} OBSERVER_RAM_BUDGET_BYTES=67108864 OBSERVER_CLIPS=0"
    fi
    if [[ "${WITH_PRESENCE}" -eq 1 ]]; then
      log "would set HEIRLOOM_PRESENCE=1 PRESENCE_FPS=3 PRESENCE_VRAM_BUDGET_MIB=512 PRESENCE_UNKNOWN_THUMBNAILS=0 PRESENCE_THRESHOLD=0.36"
      log "Presence models: YuNet MIT, SFace Apache-2.0. InsightFace pretrained models are not installed."
    fi
    return 0
  fi
  touch "${env_file}"
  chmod 600 "${env_file}"
  upsert_env MONGO_URL "mongodb://mongo:27017" "${env_file}"
  upsert_env DB_NAME "heirloom" "${env_file}"
  upsert_env HEIRLOOM_BOX "1" "${env_file}"
  upsert_env HEIRLOOM_LLM_PROVIDER "ollama" "${env_file}"
  upsert_env OLLAMA_BASE_URL "http://ollama:11434" "${env_file}"
  upsert_env OLLAMA_TWIN_MODEL "${model}" "${env_file}"
  upsert_env HEIRLOOM_LAB_MODE "1" "${env_file}"
  upsert_env HEIRLOOM_LAB_DIR "/var/lib/heirloom/lab" "${env_file}"
  upsert_env HEIRLOOM_LAB_REPORT_DIR "/var/lib/heirloom/lab-reports" "${env_file}"
  upsert_env HEIRLOOM_AI_DISCLOSURE "1" "${env_file}"
  if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    upsert_env HEIRLOOM_OBSERVER "1" "${env_file}"
    upsert_env HEIRLOOM_OBSERVER_DIR "/var/lib/heirloom/observer" "${env_file}"
    upsert_env OLLAMA_OBSERVER_MODEL "${observer_model}" "${env_file}"
    upsert_env OBSERVER_OLLAMA_URL "http://127.0.0.1:11434" "${env_file}"
    upsert_env OBSERVER_SAMPLE_FPS "2" "${env_file}"
    upsert_env OBSERVER_BURST_FPS "8" "${env_file}"
    upsert_env OBSERVER_CLIPS "0" "${env_file}"
    upsert_env OBSERVER_CLIP_SECONDS "8" "${env_file}"
    upsert_env OBSERVER_CLIP_MAX_MINUTES_PER_DAY "10" "${env_file}"
    upsert_env OBSERVER_CLIP_TTL_DAYS "7" "${env_file}"
    upsert_env OBSERVER_DISK_CAP_BYTES "536870912" "${env_file}"
    upsert_env OBSERVER_HOTKEY_PHRASE '"HEIRLOOM PAUSE"' "${env_file}"
    upsert_env OBSERVER_VRAM_MIB "${vram}" "${env_file}"
    upsert_env OLLAMA_MAX_LOADED_MODELS "${max_loaded}" "${env_file}"
    upsert_env OLLAMA_KEEP_ALIVE "30m" "${env_file}"
    upsert_env OBSERVER_VISION_KEEP_ALIVE "${vision_keep}" "${env_file}"
    upsert_env OBSERVER_RING_SLOTS "4" "${env_file}"
    upsert_env OBSERVER_RAM_BUDGET_BYTES "67108864" "${env_file}"
  fi
  if [[ "${WITH_PRESENCE}" -eq 1 ]]; then
    local speak="0"
    if [[ "${WITH_CHATTERBOX}" -eq 1 ]]; then
      speak="1"
    fi
    upsert_env HEIRLOOM_PRESENCE "1" "${env_file}"
    upsert_env HEIRLOOM_PRESENCE_DIR "/var/lib/heirloom/presence" "${env_file}"
    upsert_env PRESENCE_FPS "3" "${env_file}"
    upsert_env PRESENCE_VRAM_BUDGET_MIB "512" "${env_file}"
    upsert_env PRESENCE_THRESHOLD "0.36" "${env_file}"
    upsert_env PRESENCE_DEBOUNCE_MINUTES "10" "${env_file}"
    upsert_env PRESENCE_UNKNOWN_THUMBNAILS "0" "${env_file}"
    upsert_env PRESENCE_SPEAK "${speak}" "${env_file}"
    upsert_env PRESENCE_SPEAK_URL "http://127.0.0.1:8010/speak" "${env_file}"
  fi
  if ! grep -q '^CONNECTOR_SECRET_KEY=.\+' "${env_file}"; then
    secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    upsert_env CONNECTOR_SECRET_KEY "${secret}" "${env_file}"
  fi
  chmod 600 "${env_file}"
}

write_compose_args() {
  local file="/etc/heirloom/compose.args"
  log "Recording compose files in ${file}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  {
    printf '%s\n' "-f"
    printf '%s\n' "${ROOT}/box/docker-compose.yml"
    if [[ "${USE_GPU}" -eq 1 ]]; then
      printf '%s\n' "-f"
      printf '%s\n' "${ROOT}/box/docker-compose.gpu.yml"
    fi
    if [[ "${WITH_CHATTERBOX}" -eq 1 ]]; then
      printf '%s\n' "--profile"
      printf '%s\n' "chatterbox"
    fi
  } > "${file}"
  printf '%s\n' "${ROOT}" > /etc/heirloom/root
  install -m 0755 "${ROOT}/box/heirloom-box" /usr/local/bin/heirloom-box
}

write_cron() {
  local cron_file="/etc/cron.d/heirloom-box"
  log "Nightly backup and lab report via ${cron_file}"
  if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    log "Nightly observer digest at 03:20"
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  {
    cat <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 3 * * * root /usr/local/bin/heirloom-box backup >> /var/log/heirloom-box-backup.log 2>&1
15 3 * * * root /usr/local/bin/heirloom-box report >> /var/log/heirloom-box-report.log 2>&1
EOF
    if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
      printf '%s\n' '20 3 * * * root /usr/local/bin/heirloom-box observer digest >> /var/log/heirloom-box-observer.log 2>&1'
    fi
  } > "${cron_file}"
  chmod 644 "${cron_file}"
}

install_observer() {
  if [[ "${WITH_OBSERVER}" -eq 0 ]]; then
    log "Observer not requested. Product builds leave it off."
    return 0
  fi
  log "Observer requested. Installing ffmpeg, v4l-utils, tesseract-ocr, the systemd unit, and the udev rule."
  run apt-get install -y ffmpeg v4l-utils tesseract-ocr
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would install /usr/local/bin/heirloom-observer, heirloom-observer.service, and 99-heirloom-observer.rules"
    log "would touch /etc/heirloom/observer.enabled and systemctl enable --now heirloom-observer.service"
    return 0
  fi
  install -m 0755 "${ROOT}/box/observer/heirloom-observer" /usr/local/bin/heirloom-observer
  install -m 0644 "${ROOT}/box/observer/heirloom-observer.service" /etc/systemd/system/heirloom-observer.service
  install -d -m 0755 /etc/udev/rules.d
  install -m 0644 "${ROOT}/box/observer/99-heirloom-observer.rules" /etc/udev/rules.d/99-heirloom-observer.rules
  install -d -m 0755 /etc/heirloom
  touch /etc/heirloom/observer.enabled
  chmod 644 /etc/heirloom/observer.enabled
  systemctl daemon-reload
  systemctl enable --now heirloom-observer.service || log "heirloom-observer did not start; heirloom-box status will show why"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=video4linux || true
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    usermod -aG video "${SUDO_USER}" || true
  fi
}

install_presence() {
  if [[ "${WITH_PRESENCE}" -eq 0 ]]; then
    log "Presence not requested. Product builds leave it off."
    return 0
  fi
  log "Presence requested. Installing python3-opencv, v4l-utils, ffmpeg, the systemd unit, and the udev rule."
  log "Face models: YuNet (MIT) and SFace (Apache-2.0) from the OpenCV Zoo. InsightFace pretrained models are not installed."
  log "GPU budget is 512 MiB free. Presence stays on CPU when Ollama leaves less than that."
  run apt-get install -y python3-opencv v4l-utils ffmpeg
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would download YuNet (MIT) https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    log "would download SFace (Apache-2.0) https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
    log "would keep each model's LICENSE file beside the weights"
    log "would install /usr/local/bin/heirloom-presence, heirloom-presence.service, and 99-heirloom-presence.rules"
    log "would touch /etc/heirloom/presence.enabled and systemctl enable --now heirloom-presence.service"
    return 0
  fi
  install -d -m 0750 /var/lib/heirloom/presence/models
  download_presence_model \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
    /var/lib/heirloom/presence/models/face_detection_yunet_2023mar.onnx \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/LICENSE" \
    /var/lib/heirloom/presence/models/face_detection_yunet.LICENSE
  download_presence_model \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
    /var/lib/heirloom/presence/models/face_recognition_sface_2021dec.onnx \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/LICENSE" \
    /var/lib/heirloom/presence/models/face_recognition_sface.LICENSE
  install -m 0755 "${ROOT}/box/presence/heirloom-presence" /usr/local/bin/heirloom-presence
  install -m 0644 "${ROOT}/box/presence/heirloom-presence.service" /etc/systemd/system/heirloom-presence.service
  install -d -m 0755 /etc/udev/rules.d
  install -m 0644 "${ROOT}/box/presence/99-heirloom-presence.rules" /etc/udev/rules.d/99-heirloom-presence.rules
  install -d -m 0755 /etc/heirloom
  touch /etc/heirloom/presence.enabled
  chmod 644 /etc/heirloom/presence.enabled
  systemctl daemon-reload
  systemctl enable --now heirloom-presence.service || log "heirloom-presence did not start; heirloom-box status will show why"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=video4linux || true
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    usermod -aG video "${SUDO_USER}" || true
  fi
}

download_presence_model() {
  local url="$1"
  local dest="$2"
  local license_url="$3"
  local license_dest="$4"
  if [[ -s "${dest}" && -s "${license_dest}" ]]; then
    log "Presence model already present: ${dest}"
    return 0
  fi
  log "Downloading ${url}"
  if ! curl -fsSL "${url}" -o "${dest}.partial"; then
    rm -f "${dest}.partial"
    log "Could not download ${url}. Presence will report the model as missing until the file is there."
    return 0
  fi
  mv "${dest}.partial" "${dest}"
  if ! curl -fsSL "${license_url}" -o "${license_dest}.partial"; then
    rm -f "${license_dest}.partial"
    log "Could not download the license file ${license_url}"
    return 0
  fi
  mv "${license_dest}.partial" "${license_dest}"
}

start_stack() {
  local model="$1"
  local observer_model="$2"
  local -a args=()
  args+=(-f "${ROOT}/box/docker-compose.yml")
  if [[ "${USE_GPU}" -eq 1 ]]; then
    args+=(-f "${ROOT}/box/docker-compose.gpu.yml")
  fi
  if [[ "${WITH_CHATTERBOX}" -eq 1 ]]; then
    args+=(--profile chatterbox)
  fi
  log "Starting containers from ${ROOT}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "would docker compose up -d and ollama pull ${model}"
    if [[ "${WITH_OBSERVER}" -eq 1 && -n "${observer_model}" ]]; then
      log "would ollama pull ${observer_model}"
    elif [[ "${WITH_OBSERVER}" -eq 1 ]]; then
      log "Observer vision model is empty; OCR and heuristics only"
    fi
    return 0
  fi
  docker compose "${args[@]}" up -d --build
  docker compose "${args[@]}" exec -T ollama ollama pull "${model}"
  if [[ "${WITH_OBSERVER}" -eq 1 && -n "${observer_model}" ]]; then
    docker compose "${args[@]}" exec -T ollama ollama pull "${observer_model}"
  elif [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    log "Observer vision model is empty; OCR and heuristics only"
  fi
}

print_next() {
  local ip=""
  ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  log "Install plan finished (dry-run=${DRY_RUN})."
  log "From another PC on the LAN: https://${ip:-this-machine}/"
  log "Trust Caddy's local CA after the first real start: /var/lib/heirloom/caddy/caddy/pki/authorities/local/root.crt"
  log "Status: heirloom-box status"
  if [[ "${DEV_TOOLS}" -eq 1 ]]; then
    log "Dev tools are on this machine. Sign in yourself. The installer did not save tokens."
    log "  gh auth login"
    log "  agent login    (Cursor CLI; some installs name it cursor-agent)"
    log "  claude         (then /login)"
  fi
  if [[ "${WITH_TAILSCALE}" -eq 1 ]]; then
    log "Tailscale login, when you want it: sudo tailscale up"
  fi
  if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    log "Observer is on for this box. Pause with: heirloom-box observer pause"
    log "Wiring and privacy rules: box/OBSERVER.md"
  fi
  if [[ "${WITH_PRESENCE}" -eq 1 ]]; then
    log "Presence is on for this box. Pause with: heirloom-box presence pause"
    log "Cameras, consent, and model licenses: box/PRESENCE.md"
  fi
  if [[ "${NEED_REBOOT}" -eq 1 ]]; then
    log "Reboot so the NVIDIA driver loads, then re-run: sudo bash box/install.sh"
  fi
}

main() {
  local mib="" model="" observer_model="" solo="" max_loaded="1" vision_keep="45s" expected=""
  NEED_REBOOT=0
  USE_GPU=0
  parse_args "$@"
  prepare_log
  if [[ "${WITH_OBSERVER}" -eq 0 && -f /etc/heirloom/observer.enabled ]]; then
    WITH_OBSERVER=1
    log "Observer marker /etc/heirloom/observer.enabled is present; keeping Observer on"
  fi
  if [[ "${WITH_PRESENCE}" -eq 0 && -f /etc/heirloom/presence.enabled ]]; then
    WITH_PRESENCE=1
    log "Presence marker /etc/heirloom/presence.enabled is present; keeping Presence on"
  fi
  if [[ "${DRY_RUN}" -eq 0 && "${EUID}" -ne 0 ]]; then
    printf 'Re-run as root: sudo bash box/install.sh\n' >&2
    exit 1
  fi
  log "Heirloom Twin Box installer root=${ROOT} dry_run=${DRY_RUN} dev_tools=${DEV_TOOLS} tailscale=${WITH_TAILSCALE} chatterbox=${WITH_CHATTERBOX} observer=${WITH_OBSERVER} presence=${WITH_PRESENCE}"
  require_ubuntu
  mib="$(vram_mib)"
  solo="$(heirloom_model_for_vram_mib "${mib}")"
  model="${solo}"
  observer_model=""
  if [[ "${WITH_OBSERVER}" -eq 1 ]]; then
    IFS=$'\t' read -r model observer_model max_loaded vision_keep expected <<< "$(heirloom_observer_residency_for_vram_mib "${mib}")"
    log "VRAM MiB=${mib} observer pair twin=${model} vision=${observer_model:-ocr} max_loaded=${max_loaded} vision_keep_alive=${vision_keep} expected_mib=${expected:-0} (Apache-2.0)"
    if [[ "${solo}" != "${model}" ]]; then
      log "Chat model ${solo} does not fit beside the vision model on this GPU; Observer uses ${model}"
    fi
  else
    log "VRAM MiB=${mib} default model=${model} (Apache-2.0 Qwen2.5)"
  fi
  if gpu_present && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    USE_GPU=1
  fi
  install_base
  install_nvidia
  if [[ "${NEED_REBOOT}" -eq 0 ]] && gpu_present && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    USE_GPU=1
  fi
  install_tailscale
  install_dev_tools
  harden_ssh
  configure_ufw
  write_tree
  write_env "${model}" "${observer_model}" "${mib}" "${max_loaded}" "${vision_keep}"
  write_compose_args
  write_cron
  install_observer
  install_presence
  start_stack "${model}" "${observer_model}"
  print_next
}

main "$@"
