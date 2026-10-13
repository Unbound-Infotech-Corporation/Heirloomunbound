#!/usr/bin/env bash
# Rendered user-data must parse, keep the placeholder serial, and hash the password.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="${ROOT}/box/autoinstall/build-usb.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

cat > "${TMP}/id_ed25519.pub" <<'EOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHeirloomTestKeyOnlyNotARealKey heirloom-test
EOF

cat > "${TMP}/config.env" <<EOF
TARGET_DISK_SERIAL=HEIRLOOMTESTDISK01
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
INITIAL_PASSWORD=test-password-not-real
SSH_PASSWORD_AUTH=yes
SSH_AUTHORIZED_KEYS_FILE=${TMP}/id_ed25519.pub
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

bash "${BUILD}" --config "${TMP}/config.env" --render-only "${TMP}/render" >/dev/null

python3 - "${TMP}/render/nocloud/user-data" "${TMP}/render/heirloom/config.env" <<'PY'
import pathlib
import sys
import yaml

user_data = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
loaded = yaml.safe_load(user_data)
autoinstall = loaded["autoinstall"]
assert autoinstall["version"] == 1
assert autoinstall["interactive-sections"] == []
assert autoinstall["identity"]["hostname"] == "heirloom-twinbox"
assert autoinstall["identity"]["username"] == "heirloom"
assert autoinstall["identity"]["password"].startswith("$6$")
assert autoinstall["ssh"]["allow-pw"] is True
assert autoinstall["ssh"]["authorized-keys"]
assert autoinstall["storage"]["layout"]["match"]["serial"] == "HEIRLOOM-REFUSE-NO-DISK-MATCH"
assert autoinstall["early-commands"] == [["bash", "/cdrom/heirloom/resolve-disk.sh"]]
assert autoinstall["shutdown"] == "reboot"
assert "HEIRLOOMTESTDISK01" not in user_data
assert user_data.count("HEIRLOOM-REFUSE-NO-DISK-MATCH") == 1
assert "test-password-not-real" not in user_data

iso_config = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
assert "HEIRLOOMTESTDISK01" in iso_config
assert "INITIAL_PASSWORD=" not in iso_config
assert "test-password-not-real" not in iso_config
assert "UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8" in iso_config
PY

# Key-only SSH renders allow-pw false.
cat > "${TMP}/config-keys.env" <<EOF
TARGET_DISK_SERIAL=HEIRLOOMTESTDISK01
HOSTNAME=heirloom-twinbox
USERNAME=heirloom
SSH_PASSWORD_AUTH=no
SSH_AUTHORIZED_KEYS_FILE=${TMP}/id_ed25519.pub
HEIRLOOM_REPO_URL=https://example.invalid/heirloom.git
UBUNTU_ISO_SHA256=97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8
EOF
bash "${BUILD}" --config "${TMP}/config-keys.env" --render-only "${TMP}/render-keys" >/dev/null
python3 - "${TMP}/render-keys/nocloud/user-data" <<'PY'
import pathlib, sys, yaml
data = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert data["autoinstall"]["ssh"]["allow-pw"] is False
assert data["autoinstall"]["identity"]["password"].startswith("$6$")
PY

echo "autoinstall yaml ok"
