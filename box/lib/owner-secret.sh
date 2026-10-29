#!/usr/bin/env bash
# Owner password file for the Twin Box API container.
# Compose bind-mounts the owner directory read-only. The file must already
# exist as a regular file: Docker turns a missing file mount into a directory,
# and an atomic rename would hide a new password from a file bind.

owner_password_file() {
  local root="${1:-${HEIRLOOM_DATA_ROOT:-/var/lib/heirloom}}"
  printf '%s\n' "${root}/owner/owner.pass"
}

ensure_owner_secret() {
  local root="${1:-${HEIRLOOM_DATA_ROOT:-/var/lib/heirloom}}"
  local dir="${root}/owner"
  local file="${dir}/owner.pass"
  local legacy="${root}/owner.pass"
  if [[ -d "${legacy}" ]]; then
    printf '%s\n' "${legacy} is a directory. Remove it, then run: heirloom-box set-owner" >&2
    return 1
  fi
  if [[ -d "${file}" ]]; then
    printf '%s\n' "${file} is a directory. Remove it, then run: heirloom-box set-owner" >&2
    return 1
  fi
  install -d -m 2750 "${dir}"
  if [[ -f "${legacy}" && ! -s "${file}" ]]; then
    mv "${legacy}" "${file}"
  fi
  if [[ ! -e "${file}" ]]; then
    : > "${file}"
  fi
  chmod 0640 "${file}"
  if getent group heirloom >/dev/null 2>&1; then
    chgrp heirloom "${dir}" "${file}" || true
  fi
}
