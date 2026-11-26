# Model tiers: which local model each buyer's hardware gets

Heirloom picks its chat model from the GPU it finds on first run
(`backend/model_tiers.py`, mirrored in `box/lib/models.sh` for a box without
Python). Every model here is open-weight, Apache-2.0, and runs in Ollama on
the buyer's own machine. No cloud model is ever chosen; `HEIRLOOM_MODEL_OVERRIDE`
refuses cloud tags.

## The table

| Tier | GPU memory | Example cards | Model | Fallback | Context | Measured VRAM | Voice |
|---|---|---|---|---|---|---|---|
| xl | 30 GB+ | RTX 5090, RTX PRO | **gemma4:26b** | gemma4:12b | 16k | 18.0 GB | on GPU |
| large | 22 GB+ | RTX 3090/4090, RX 7900 XTX | **gemma4:12b** | gemma4:e4b | 16k | 8.4 GB | on GPU |
| medium | 15 GB+ | 4060 Ti 16G, 4070 Ti S, 4080, RX 7800 XT | **gemma4:12b** | qwen3.5:4b | 16k | 8.4 GB | on GPU |
| small | 11 GB+ | 3060 12G, 4070, RX 6700 XT | **qwen3.5:4b** | gemma4:e2b | 16k | 4.6 GB | on GPU |
| compact | 7 GB+ | 3060 Ti, 4060, RX 7600 | **qwen3.5:4b** | gemma4:e2b | 8k | 4.4 GB | on CPU |
| cpu | none / under 4 GB | any | **gemma4:e4b** (16 GB+ RAM) | gemma4:e2b | 8k | — | on CPU |

"Measured VRAM" is the nvidia-smi delta with the model loaded at the tier's
context, measured beside the running Chatterbox voice model (5.2 GB) on an RTX
3090 (gemma4) or RTX 5090 (qwen3.5:4b). The picker adds 5,248 MiB for voice
plus 512 MiB headroom on tiers with voice on the GPU; if the model would not
fit it takes the fallback. AMD cards (ROCm) use the same table.

Override: `HEIRLOOM_MODEL_OVERRIDE=<ollama tag>` (box.env or the PC's
environment). On a box: `sudo heirloom-box model` shows the pick,
`sudo heirloom-box model auto` (or `model <tag>`) pulls, tests, backs up
box.env, and switches. An upgrade never changes the model or the context.

## How the models were scored (November 2026)

Twenty open models went through four checks. All runs were local (BIGDEAL
RTX 5090 and the Twin Box RTX 3090), thinking turned off (`think:false`, or
`reasoning_effort:"none"` on Ollama's /v1 API, which ignores `think`).

1. **Direct bench** (`python -m model_bench`): 21 chat tasks, 12 tool-call
   cases, 7 JSON-schema extractions, and Heirloom's own grounding calls
   (turn classifier, claim verifier, card-only answers and declines).
   Quality = 40 grounding + 30 chat + 18 tools + 12 JSON.
2. **Judged open answers** (`python -m model_bench_open`): 8 everyday asks,
   graded 1–10 by the other local models (never by their own family),
   centred per judge.
3. **Full pipeline** (`python -m model_bench_pipeline`): the real
   `eval-grounding` suite (52 turns: recall, declines, reminders, time zones,
   how-to help, desktop turns) through a side API on the same box image.
4. **Speed and memory**: time to first token, tokens/s, VRAM by context, and
   CPU-only speed on 8 threads.

### Direct bench (RTX 5090)

| Model | Quality | Grounding | Chat /21 | Tools /12 | JSON /7 | TTFT s | tok/s | Judged |
|---|---|---|---|---|---|---|---|---|
| gemma4:26b | **96.6** | 95.8 | 21 | 12 | 6 | 0.08 | 256 | 9.09 |
| mistral-small3.2:24b | 93.6 | 100 | 20 | 11 | 5 | 0.05 | 96 | 8.71 |
| gemma4:31b | 93.4 | 100 | 20 | 12 | 4 | 0.18 | 135 | 8.91 |
| gemma4:e4b | 92.6 | 100 | 17 | 12 | 6 | 0.10 | 293 | 8.72 |
| qwen3.5:4b | 92.2 | 100 | 19 | 11 | 5 | 0.15 | 183 | 8.31 |
| gemma4:12b | 92.0 | 100 | 19 | 12 | 4 | 0.12 | 193 | 8.97 |
| qwen3:14b | 91.9 | 100 | 20 | 11 | 4 | 0.11 | 127 | 8.81 |
| qwen3:32b | 91.9 | 100 | 20 | 11 | 4 | 0.10 | 32 | 8.56 |
| qwen2.5:14b (old default) | 91.7 | 100 | 20 | 12 | 3 | 0.05 | 128 | 8.44 |
| qwen3.5:9b | 90.8 | 100 | 18 | 11 | 5 | 0.11 | 139 | 8.94 |
| qwen3.8:27b | 90.6 | 95.8 | 18 | 12 | 5 | 0.21 | 121 | 9.38 |
| qwen3:8b | 88.8 | 95.8 | 19 | 11 | 4 | 0.05 | 204 | — |
| ministral-3:14b | 87.9 | 100 | 19 | 7 | 6 | 0.05 | 129 | 8.67 |
| ministral-3:8b | 87.4 | 100 | 17 | 12 | 3 | 0.09 | 172 | — |
| gemma4:e2b | 86.1 | 99.5 | 15 | 12 | 4 | 0.14 | 285 | 8.66 |
| qwen3.6:35b-a3b | 83.6 | 62.5 | 20 | 12 | 7 | 0.11 | 203 | — |
| llama3.2:3b | 82.2 | 82.8 | 18 | 11 | 4 | 0.04 | 378 | — |
| ministral-3:3b | 80.7 | 79.2 | 18 | 11 | 4 | 0.08 | 314 | — |
| qwen3.5:2b | 74.1 | 62.5 | 18 | 11 | 4 | 0.10 | 263 | — |
| gpt-oss:20b | 66.5 | 51.7 | 19 | 9 | 3 | 0.11 | 252 | — |

### Full eval-grounding pipeline

| Model | Where | Result | Median / p90 / max per turn |
|---|---|---|---|
| gemma4:26b | 5090 | **PASS** | 0.2 / 1.4 / 8.7 s |
| gemma4:12b | 3090 | **PASS** | 0.3 / 2.9 / 20 s (cold load) |
| qwen2.5:14b | 3090 | PASS | 0.1 / 2.0 s |
| qwen3.5:9b | 3090 | 1 miss ("What's 15% of 80?" → "12." is right but under the 12-character helpful bar) | 0.2 / 2.4 / 14.8 s |
| qwen3.5:4b | 5090 | 1 miss (declined the trout how-to) | 0.2 / 0.9 / 1.3 s |
| gemma4:e4b | 3090 | 2 misses (trout decline; birthday note 1 of 3) | — |
| gemma4:e2b | 5090 | 2 misses (trout and printer how-to declined) | 0.1 / 0.7 / 0.8 s |
| mistral-small3.2:24b | 3090 | 3 misses (blocks ordinary chat as "no memory") | — |
| qwen3.8:27b | 3090 | 4 misses, and 15% spilled to CPU | 1.0 / 7.5 / 21.7 s |

### CPU only (8 threads)

gemma4:e2b 27.9 tok/s · gemma4:e4b 20.1 · llama3.2:3b 16.0 · qwen3.5:4b 10.2 · qwen3.5:9b 5.5

### VRAM beside voice on a 24 GB RTX 3090 (voice + desktop already 5.8 GB)

gemma4:26b 18.0 GB at 16k (spills 26% to CPU: does not fit) · mistral-small3.2 15.4 GB ·
qwen2.5:14b 9.7 GB (16k) / 11.3 GB (32k) · gemma4:12b 8.4 GB · qwen3.5:9b 6.2 GB · gemma4:e4b 4.5 GB.
`ollama ps` under-reports gemma4's size, so these are nvidia-smi deltas.

## Why these picks

- **xl, gemma4:26b**: best direct score, perfect chat, passes the pipeline, 256 tok/s.
- **large and medium, gemma4:12b**: passes the pipeline on the 3090 and leaves
  room for voice and Observer. The 24 GB card cannot hold gemma4:26b beside
  voice, qwen3.8:27b spills and misses 4 pipeline cases, and mistral-small3.2
  over-blocks ordinary chat.
- **small and compact, qwen3.5:4b**: the fewest pipeline misses of the models
  that fit in 5.5 GB, 100 grounding, 183 tok/s.
- **cpu, gemma4:e4b**: twice qwen3.5:4b's CPU speed at the same grounding score.
- Known gap: the smallest models sometimes decline a how-to question as if it
  were a missing memory. The multi-tier test suite (step 5) tracks it.

## Re-running

    # on a box (side container; the live API is not touched)
    sudo heirloom-box bench-models gemma4:12b qwen3.5:4b
    sudo heirloom-box bench-pipeline gemma4:12b
    # anywhere with Python and an Ollama
    python -m model_bench gemma4:12b --ollama http://127.0.0.1:11434 --out direct.jsonl
    python -m model_bench gemma4:e4b --cpu-speed
