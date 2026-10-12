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
echo "observer vision model table ok"
