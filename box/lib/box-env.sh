#!/usr/bin/env bash
# Export HEIRLOOM_[A-Z0-9_]+ keys from a Twin Box env file.
# The file is not sourced, so a value cannot run a command.

load_box_env() {
  local file="${1:-${HEIRLOOM_DATA_ROOT:-/var/lib/heirloom}/box.env}"
  local line key val
  [[ -r "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    [[ "${line}" =~ ^HEIRLOOM_[A-Z0-9_]+= ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    if [[ "${val}" == \"*\" && "${val}" == *\" ]]; then
      val="${val:1:${#val}-2}"
    elif [[ "${val}" == \'*\' && "${val}" == *\' ]]; then
      val="${val:1:${#val}-2}"
    fi
    printf -v "${key}" '%s' "${val}"
    # shellcheck disable=SC2163
    export "${key?}"
  done < "${file}"
}
