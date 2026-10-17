#!/usr/bin/env bash
# Read KEY=value lines from an owner config file without evaluating them.
# Comments and blank lines are skipped. Values may contain '='.
# One matching pair of surrounding quotes is removed, and whitespace around
# the line and the value is removed. Only names the Twin Box scripts
# understand are assigned.

heirloom_trim() {
  local val="$1"
  val="${val%$'\r'}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  printf '%s\n' "${val}"
}

heirloom_unquote() {
  local val quote
  val="$(heirloom_trim "$1")"
  if [[ ${#val} -ge 2 ]]; then
    quote="${val:0:1}"
    if [[ ( "${quote}" == '"' || "${quote}" == "'" ) && "${val}" == "${quote}"*"${quote}" ]]; then
      val="$(heirloom_trim "${val:1:${#val}-2}")"
    fi
  fi
  printf '%s\n' "${val}"
}

heirloom_load_env_file() {
  local file="$1"
  local line key val
  [[ -r "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="$(heirloom_trim "${line}")"
    [[ "${line}" == \#* ]] && continue
    [[ -z "${line}" ]] && continue
    [[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    val="$(heirloom_unquote "${line#*=}")"
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
