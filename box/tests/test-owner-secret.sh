#!/usr/bin/env bash
# The owner password is a file inside a directory the API container mounts read-only.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib/owner-secret.sh
source "${root}/lib/owner-secret.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

[[ "$(owner_password_file "${tmp}")" == "${tmp}/owner/owner.pass" ]]
ensure_owner_secret "${tmp}"
[[ -d "${tmp}/owner" ]]
[[ -f "${tmp}/owner/owner.pass" ]]
[[ ! -d "${tmp}/owner/owner.pass" ]]
mode="$(stat -c '%a' "${tmp}/owner/owner.pass")"
[[ "${mode}" == "640" ]]

# A second call keeps the placeholder a file.
ensure_owner_secret "${tmp}"
[[ -f "${tmp}/owner/owner.pass" ]]

# An older host file is moved into the mounted directory when the new file is empty.
legacy="${tmp}/legacy"
mkdir -p "${legacy}"
printf '%s\n' 'email=ada@example.com' > "${legacy}/owner.pass"
ensure_owner_secret "${legacy}"
[[ -f "${legacy}/owner/owner.pass" ]]
[[ ! -e "${legacy}/owner.pass" ]]
grep -q 'ada@example.com' "${legacy}/owner/owner.pass"

blocked="${tmp}/blocked"
mkdir -p "${blocked}/owner.pass"
if ensure_owner_secret "${blocked}" 2>/dev/null; then
  echo "a directory at owner.pass must fail" >&2
  exit 1
fi

compose="${root}/docker-compose.yml"
grep -q 'HEIRLOOM_OWNER_PASSWORD_FILE:' "${compose}"
grep -q '/owner:ro' "${compose}"
grep -q 'ensure_owner_secret' "${root}/install.sh"
grep -q 'HEIRLOOM_OWNER_PASSWORD_FILE' "${root}/install.sh"
grep -q 'HEIRLOOM_OWNER_PASSWORD_FILE' "${root}/heirloom-box"

echo "owner-secret ok"
