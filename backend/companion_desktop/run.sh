#!/usr/bin/env bash
# Heirloom — on a Mac, double-click this (or run: bash run.sh)
cd "$(dirname "$0")" || exit 1

INSTALL_DIR="${HOME}/.heirloom"
APP_DIR="${INSTALL_DIR}/app"
VENV_DIR="${INSTALL_DIR}/venv"
LOG="${INSTALL_DIR}/setup.log"
mkdir -p "${INSTALL_DIR}" "${APP_DIR}"
{
  echo
  echo "Heirloom setup $(date)"
} >> "${LOG}"

if [[ ! -f "./heirloom/__main__.py" ]]; then
  echo "Unzip the Heirloom folder first, then double-click run.sh inside that folder."
  echo "Don't run it from inside the zip — copy the folder to your Desktop first."
  echo "Details: ${LOG}"
  read -r _
  exit 1
fi

rm -rf "${APP_DIR}/heirloom"
cp -R ./heirloom "${APP_DIR}/heirloom"
if [[ -f ./requirements.txt ]]; then
  cp -f ./requirements.txt "${INSTALL_DIR}/requirements.txt"
fi
if [[ -f ./README.txt ]]; then
  cp -f ./README.txt "${INSTALL_DIR}/README.txt"
fi

PY=""
if command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="python3"
  fi
fi
if [[ -z "${PY}" ]]; then
  echo "Python 3.10 or newer is missing. Opening the download page."
  echo "Install Python, then double-click run.sh again." | tee -a "${LOG}"
  if command -v open >/dev/null 2>&1; then
    open "https://www.python.org/downloads/"
  else
    xdg-open "https://www.python.org/downloads/" >/dev/null 2>&1 || true
  fi
  read -r _
  exit 1
fi

NEED=0
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  NEED=1
fi
if [[ ! -f "${INSTALL_DIR}/requirements.ok" ]]; then
  NEED=1
fi
if [[ -f "${INSTALL_DIR}/requirements.txt" && -f "${INSTALL_DIR}/requirements.ok" ]]; then
  if ! cmp -s "${INSTALL_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.ok"; then
    NEED=1
  fi
fi
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  if ! "${VENV_DIR}/bin/python" -c "import PySide6, requests, PIL, mss" >>"${LOG}" 2>&1; then
    NEED=1
  fi
fi

if [[ "${NEED}" -eq 1 ]]; then
  echo "Setting up Heirloom for the first time — about a minute."
  echo "Leave this window open."
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    if ! "${PY}" -m venv "${VENV_DIR}" >>"${LOG}" 2>&1; then
      echo "Couldn't prepare Heirloom. Check your internet and try again."
      echo "Details: ${LOG}"
      read -r _
      exit 1
    fi
  fi
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip >>"${LOG}" 2>&1
  if ! "${VENV_DIR}/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt" >>"${LOG}" 2>&1; then
    echo "Install didn't finish. Check your internet, then run this again."
    echo "Details: ${LOG}"
    read -r _
    exit 1
  fi
  if ! "${VENV_DIR}/bin/python" -c "import PySide6, requests, PIL, mss" >>"${LOG}" 2>&1; then
    echo "Heirloom didn't finish installing. Run this again."
    echo "Details: ${LOG}"
    read -r _
    exit 1
  fi
  cp -f "${INSTALL_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.ok"
fi

echo "Opening Heirloom..."
cd "${APP_DIR}" || exit 1
exec "${VENV_DIR}/bin/python" -m heirloom
