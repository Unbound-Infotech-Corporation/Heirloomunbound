#!/usr/bin/env bash
# --odysseus-url records the local workspace. A public address is refused.
# The dry-run log names the token file and does not contain a token value.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$(bash "${ROOT}/box/install.sh" --dry-run --odysseus-url=http://192.168.0.110:7011)"
printf '%s\n' "${out}" | grep -F "HEIRLOOM_ODYSSEUS_URL=http://192.168.0.110:7011" >/dev/null
printf '%s\n' "${out}" | grep -F "HEIRLOOM_ODYSSEUS=1" >/dev/null
printf '%s\n' "${out}" | grep -F "HEIRLOOM_ODYSSEUS_TOKEN_FILE=" >/dev/null
if printf '%s\n' "${out}" | grep -F "ody_" >/dev/null; then
  printf 'dry-run log contained a token prefix\n' >&2
  exit 1
fi

out_service="$(bash "${ROOT}/box/install.sh" --dry-run --odysseus-url=http://odysseus:7000)"
printf '%s\n' "${out_service}" | grep -F "HEIRLOOM_ODYSSEUS_URL=http://odysseus:7000" >/dev/null

if bash "${ROOT}/box/install.sh" --dry-run --odysseus-url=http://8.8.8.8:7011 >/tmp/heirloom-odysseus-reject.txt 2>&1; then
  printf 'public Odysseus URL was accepted\n' >&2
  exit 1
fi
grep -F "LAN" /tmp/heirloom-odysseus-reject.txt >/dev/null

if bash "${ROOT}/box/install.sh" --dry-run --odysseus-url=http://192.168.0.16:7011 >/tmp/heirloom-odysseus-forbidden.txt 2>&1; then
  printf 'forbidden host was accepted\n' >&2
  exit 1
fi

echo "odysseus url dry-run ok"
