#!/usr/bin/env bash
# --brain-url records the LAN brain. A public address is refused.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$(bash "${ROOT}/box/install.sh" --dry-run --brain-url=http://192.168.0.50:11434)"
printf '%s\n' "${out}" | grep -F "HEIRLOOM_BRAIN_URL=http://192.168.0.50:11434" >/dev/null
printf '%s\n' "${out}" | grep -F "HEIRLOOM_BRAIN_MODEL=llama3.3:70b" >/dev/null

if bash "${ROOT}/box/install.sh" --dry-run --brain-url=http://8.8.8.8:11434 >/tmp/heirloom-brain-reject.txt 2>&1; then
  printf 'public brain URL was accepted\n' >&2
  exit 1
fi
grep -F "LAN" /tmp/heirloom-brain-reject.txt >/dev/null

if bash "${ROOT}/box/install.sh" --dry-run --brain-url=http://192.168.0.16:11434 >/tmp/heirloom-brain-forbidden.txt 2>&1; then
  printf 'forbidden host was accepted\n' >&2
  exit 1
fi

echo "brain url dry-run ok"
