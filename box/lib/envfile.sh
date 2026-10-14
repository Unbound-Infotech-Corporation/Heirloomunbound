#!/usr/bin/env bash
# Read KEY=value lines from an owner config file without evaluating them.
# Comments and blank lines are skipped. Values may contain '='.
# Only names the Twin Box scripts understand are assigned.

heirloom_load_env_file() {
  local file="$1"
  local line key val
  [[ -r "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    [[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    val="${line#*=}"
    if [[ "${val}" == \"*\" && "${val}" == *\" ]]; then
      val="${val:1:${#val}-2}"
    elif [[ "${val}" == \'*\' && "${val}" == *\' ]]; then
      val="${val:1:${#val}-2}"
    fi
    case "${key}" in
      HEIRLOOM_*|NVIDIA_*|EXPECTED_*|SSH_*|TAILSCALE_*|TARGET_*|UBUNTU_ISO_*|HOSTNAME|USERNAME|LOCALE|KEYBOARD_*|TIMEZONE|INITIAL_PASSWORD|PASSWORD_HASH)
        printf -v "${key}" '%s' "${val}"
        ;;
      *)
        printf 'Ignoring unknown config key %s in %s\n' "${key}" "${file}" >&2
        ;;
    esac
  done < "${file}"
}
