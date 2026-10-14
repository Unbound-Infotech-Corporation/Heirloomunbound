#!/usr/bin/env bash
# load_box_env exports HEIRLOOM_* keys and does not source the file.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib/box-env.sh
source "${root}/lib/box-env.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
marker="${tmp}/pwned"
envfile="${tmp}/box.env"
{
  printf '%s\n' 'HEIRLOOM_BOX=1'
  printf '%s\n' 'HEIRLOOM_LAN_IP=192.168.0.111'
  printf '%s\n' "HEIRLOOM_EVIL=\$(touch ${marker})"
  printf '%s\n' 'CONNECTOR_SECRET_KEY=do-not-export'
  printf '%s\n' 'OTHER=no'
} > "${envfile}"

unset HEIRLOOM_BOX HEIRLOOM_LAN_IP HEIRLOOM_EVIL CONNECTOR_SECRET_KEY OTHER || true
load_box_env "${envfile}"

[[ "${HEIRLOOM_BOX}" == "1" ]]
[[ "${HEIRLOOM_LAN_IP}" == "192.168.0.111" ]]
[[ "${HEIRLOOM_EVIL}" == "\$(touch ${marker})" ]]
[[ ! -e "${marker}" ]]
[[ -z "${CONNECTOR_SECRET_KEY:-}" ]]
[[ -z "${OTHER:-}" ]]

missing="${tmp}/missing.env"
load_box_env "${missing}"

echo "box-env ok"
