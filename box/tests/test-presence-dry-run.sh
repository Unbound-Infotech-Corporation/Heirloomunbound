#!/usr/bin/env bash
# Presence stays off unless --presence is passed. Dry-run must not create the marker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARKER="/etc/heirloom/presence.enabled"
before=0
if [[ -e "${MARKER}" ]]; then
  before=1
fi

out="$(bash "${ROOT}/box/install.sh" --dry-run --presence)"
printf '%s\n' "${out}" | grep -F "presence=1" >/dev/null
printf '%s\n' "${out}" | grep -F "YuNet (MIT)" >/dev/null
printf '%s\n' "${out}" | grep -F "SFace (Apache-2.0)" >/dev/null
printf '%s\n' "${out}" | grep -F "would touch /etc/heirloom/presence.enabled" >/dev/null
printf '%s\n' "${out}" | grep -F "InsightFace pretrained models are not installed" >/dev/null

if [[ "${before}" -eq 0 && -e "${MARKER}" ]]; then
  printf 'dry-run created %s\n' "${MARKER}" >&2
  exit 1
fi
echo "presence dry-run ok"
