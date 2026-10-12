#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=box/lib/models.sh
source "${ROOT}/lib/models.sh"

[[ "$(heirloom_observer_model_for_vram_mib 0)" == "" ]]
[[ "$(heirloom_observer_model_for_vram_mib none)" == "" ]]
[[ "$(heirloom_observer_model_for_vram_mib 4096)" == "moondream" ]]
[[ "$(heirloom_observer_model_for_vram_mib 6143)" == "moondream" ]]
[[ "$(heirloom_observer_model_for_vram_mib 6144)" == "qwen2.5vl:3b" ]]
[[ "$(heirloom_observer_model_for_vram_mib 12287)" == "qwen2.5vl:3b" ]]
[[ "$(heirloom_observer_model_for_vram_mib 12288)" == "qwen2.5vl:7b" ]]

IFS=$'\t' read -r twin vision loaded keep expected <<< "$(heirloom_observer_residency_for_vram_mib 24576)"
[[ "${twin}" == "qwen2.5:14b" ]]
[[ "${vision}" == "qwen2.5vl:7b" ]]
[[ "${loaded}" == "2" ]]
[[ "${keep}" == "45s" ]]
[[ "${expected}" == "19456" ]]

IFS=$'\t' read -r twin vision loaded keep expected <<< "$(heirloom_observer_residency_for_vram_mib 8192)"
[[ "${twin}" == "qwen2.5:3b" ]]
[[ "${vision}" == "moondream" ]]
[[ "${loaded}" == "2" ]]

IFS=$'\t' read -r twin vision loaded keep expected <<< "$(heirloom_observer_residency_for_vram_mib 0)"
[[ "${twin}" == "qwen2.5:3b" ]]
[[ "${vision}" == "" ]]
[[ "${loaded}" == "1" ]]
echo "observer vision model table ok"
