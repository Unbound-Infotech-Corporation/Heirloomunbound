#!/usr/bin/env bash
# Default Ollama models for the Twin Box.
# Every default chat tag is Apache-2.0, so a buyer can use it commercially.
# Llama 3.1 stays available by setting OLLAMA_TWIN_MODEL; it is not the default here.
# Do not install XTTS-v2, F5-TTS weights, or LivePortrait bundled face models.

# Chat model per GPU tier. backend/model_tiers.py is the source of truth (it also
# reads AMD cards and HEIRLOOM_MODEL_OVERRIDE); this copy is for a box without
# python3. tests/test_model_tiers.py keeps the two in step. Picks come from the
# heirloom-box bench-models runs in docs/MODEL-TIERS.md.
heirloom_model_for_vram_mib() {
  local mib="${1:-0}"
  if [[ ! "${mib}" =~ ^[0-9]+$ ]]; then
    mib=0
  fi
  local here py
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  py="${HEIRLOOM_TIERS_PY:-${here}/../../backend/model_tiers.py}"
  if command -v python3 >/dev/null 2>&1 && [[ -f "${py}" ]]; then
    local picked=""
    if (( mib > 0 )); then
      picked="$(python3 "${py}" choose --vram-mib "${mib}" 2>/dev/null || true)"
    else
      picked="$(python3 "${py}" choose 2>/dev/null || true)"
    fi
    if [[ -n "${picked}" ]]; then
      printf '%s\n' "${picked}"
      return 0
    fi
  fi
  # MiB floors, same as TIERS in backend/model_tiers.py (voice on the same GPU).
  if (( mib >= 30720 )); then
    printf '%s\n' "gemma4:26b"
  elif (( mib >= 22528 )); then
    printf '%s\n' "gemma4:12b"
  elif (( mib >= 15360 )); then
    printf '%s\n' "gemma4:12b"
  elif (( mib >= 11264 )); then
    printf '%s\n' "qwen3.5:4b"
  elif (( mib >= 7168 )); then
    printf '%s\n' "qwen3.5:4b"
  else
    printf '%s\n' "gemma4:e4b"
  fi
}

# Context per tier (OLLAMA_CONTEXT_LENGTH), same as num_ctx in TIERS.
heirloom_ctx_for_vram_mib() {
  local mib="${1:-0}"
  if [[ ! "${mib}" =~ ^[0-9]+$ ]]; then
    mib=0
  fi
  if (( mib >= 11264 )); then
    printf '%s\n' 16384
  else
    printf '%s\n' 8192
  fi
}

# Ollama library card sizes in MiB, rounded up. Same numbers as WEIGHTS_MIB.
heirloom_weight_mib() {
  case "${1:-}" in
    qwen2.5:3b) printf '%s\n' 2048 ;;
    qwen2.5:7b) printf '%s\n' 4915 ;;
    qwen2.5:14b) printf '%s\n' 9216 ;;
    qwen2.5:32b) printf '%s\n' 20480 ;;
    qwen2.5:72b) printf '%s\n' 48128 ;;
    moondream) printf '%s\n' 1741 ;;
    qwen2.5vl:3b) printf '%s\n' 3277 ;;
    qwen2.5vl:7b) printf '%s\n' 6144 ;;
    *) printf '%s\n' 0 ;;
  esac
}

# Prints: twin, vision, max_loaded, vision_keep_alive, expected_mib (tab-separated).
# RTX 3090 (24576 MiB) -> qwen2.5:14b + qwen2.5vl:7b, both loaded, 45s vision keep-alive.
# Keep this in sync with observer_pair_for_vram_mib in backend/observer_models.py.
heirloom_observer_residency_for_vram_mib() {
  local mib="${1:-0}"
  local headroom=4096
  local twin="" vision="" max_loaded=1 keep="0" expected=0
  local candidate_twin="" candidate_vision="" tw=0 vw=0
  if [[ ! "${mib}" =~ ^[0-9]+$ ]]; then
    mib=0
  fi
  if (( mib <= 0 )); then
    printf '%s\t%s\t%s\t%s\t%s\n' "qwen2.5:3b" "" "1" "0" "2048"
    return 0
  fi
  local -a pairs=(
    "qwen2.5:14b qwen2.5vl:7b"
    "qwen2.5:7b qwen2.5vl:7b"
    "qwen2.5:7b qwen2.5vl:3b"
    "qwen2.5:3b qwen2.5vl:3b"
    "qwen2.5:3b moondream"
  )
  local pair
  for pair in "${pairs[@]}"; do
    candidate_twin="${pair%% *}"
    candidate_vision="${pair#* }"
    tw="$(heirloom_weight_mib "${candidate_twin}")"
    vw="$(heirloom_weight_mib "${candidate_vision}")"
    if (( tw + vw + headroom <= mib )); then
      expected=$((tw + vw + headroom))
      printf '%s\t%s\t%s\t%s\t%s\n' "${candidate_twin}" "${candidate_vision}" "2" "45s" "${expected}"
      return 0
    fi
  done
  local -a visions=(qwen2.5vl:7b qwen2.5vl:3b moondream)
  local -a chats=(qwen2.5:72b qwen2.5:32b qwen2.5:14b qwen2.5:7b qwen2.5:3b)
  vision=""
  local tag
  for tag in "${visions[@]}"; do
    vw="$(heirloom_weight_mib "${tag}")"
    if (( vw + headroom <= mib )); then
      vision="${tag}"
      break
    fi
  done
  twin="qwen2.5:3b"
  for tag in "${chats[@]}"; do
    tw="$(heirloom_weight_mib "${tag}")"
    if (( tw + headroom <= mib )); then
      twin="${tag}"
      break
    fi
  done
  tw="$(heirloom_weight_mib "${twin}")"
  vw=0
  if [[ -n "${vision}" ]]; then
    vw="$(heirloom_weight_mib "${vision}")"
  fi
  if (( vw > tw )); then
    expected=$((vw + headroom))
  else
    expected=$((tw + headroom))
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "${twin}" "${vision}" "${max_loaded}" "${keep}" "${expected}"
}

# Observer vision tags. Apache-2.0 only. Empty means OCR and heuristics.
# Keep this table in sync with vision_model_for_vram_mib in backend/observer_models.py.
heirloom_observer_model_for_vram_mib() {
  local mib="${1:-0}"
  if [[ ! "${mib}" =~ ^[0-9]+$ ]]; then
    mib=0
  fi
  if (( mib <= 0 )); then
    printf '%s\n' ""
  elif (( mib < 6144 )); then
    printf '%s\n' "moondream"
  elif (( mib < 12288 )); then
    printf '%s\n' "qwen2.5vl:3b"
  else
    printf '%s\n' "qwen2.5vl:7b"
  fi
}
