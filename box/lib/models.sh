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
