#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=box/lib/models.sh
source "${ROOT}/lib/models.sh"

[[ "$(heirloom_model_for_vram_mib 0)" == "qwen2.5:3b" ]]
[[ "$(heirloom_model_for_vram_mib 4096)" == "qwen2.5:3b" ]]
[[ "$(heirloom_model_for_vram_mib 8191)" == "qwen2.5:3b" ]]
[[ "$(heirloom_model_for_vram_mib 8192)" == "qwen2.5:7b" ]]
[[ "$(heirloom_model_for_vram_mib 12287)" == "qwen2.5:7b" ]]
[[ "$(heirloom_model_for_vram_mib 12288)" == "qwen2.5:14b" ]]
[[ "$(heirloom_model_for_vram_mib 20480)" == "qwen2.5:32b" ]]
[[ "$(heirloom_model_for_vram_mib 40960)" == "qwen2.5:72b" ]]
[[ "$(heirloom_model_for_vram_mib none)" == "qwen2.5:3b" ]]
echo "vram model table ok"
