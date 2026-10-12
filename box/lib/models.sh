#!/usr/bin/env bash
# Default Ollama models for the Twin Box.
# Qwen2.5 weights are Apache-2.0, so the lab machine can use them commercially.
# Llama 3.1 stays available by setting OLLAMA_TWIN_MODEL; it is not the default here.
# Do not install XTTS-v2, F5-TTS weights, or LivePortrait bundled face models.

heirloom_model_for_vram_mib() {
  local mib="${1:-0}"
  if [[ ! "${mib}" =~ ^[0-9]+$ ]]; then
    mib=0
  fi
  # MiB boundaries. A 4–7 GB card stays on 3B so context still fits.
  if (( mib < 8192 )); then
    printf '%s\n' "qwen2.5:3b"
  elif (( mib < 12288 )); then
    printf '%s\n' "qwen2.5:7b"
  elif (( mib < 20480 )); then
    printf '%s\n' "qwen2.5:14b"
  elif (( mib < 40960 )); then
    printf '%s\n' "qwen2.5:32b"
  else
    printf '%s\n' "qwen2.5:72b"
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
