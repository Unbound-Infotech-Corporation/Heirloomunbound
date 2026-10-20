# Assist task router

Heirloom Unbound keeps two voices. **Assist** does work on this PC. **Twin** answers from the vault and does not get PC tools. This router is Assist only. Twin still resolves through `backend/model_router.py`.

The product name stays **Heirloom Unbound**. Local models are standalone installs (Ollama, a llama.cpp server, or pip). Pinokio is not a backend. Cloud is off until the owner turns it on, saves a key, and puts a `cloud` slot in a chain.

## What runs

Each Assist request is classified by rules, not by another model:

| Category | Examples |
| --- | --- |
| Code | refactor, migrate, rewrite, a source file |
| Reasoning | plan, tradeoff, architecture |
| Research | what is, look up, sources |
| Quick chat | short talk that is none of the above |
| Vision | an image, or words like screenshot |

Code wins over research and reasoning. An attached image is vision.

Auto walks the category chain and uses the first installed match. A spec matches an installed name when they are equal, or the installed name is `spec:tag`. `qwen3` does not match `qwen3-coder`. An unsized spec prefers the larger `Nb` tag.

If that model is missing or the call fails, the next slot runs and the badge says so. If the chain is exhausted, Assist stops. Nothing else is substituted, including the Twin model.

Manual picker is one model. It does not fall back. If second opinion would have run, the badge says it was skipped.

## Default chains

Local only. Cloud is never appended for you.

| Category | Order |
| --- | --- |
| Code | Ollama `qwen3-coder`, `deepseek-coder-v2`, `qwen2.5-coder`; llama.cpp `qwen3-coder`, `deepseek-coder` |
| Reasoning | Ollama `deepseek-r1`, `qwen3`; llama.cpp `deepseek-r1`; Ollama `llama3.1` |
| Research | Ollama `qwen3`, `llama3.1`; llama.cpp `qwen3` |
| Quick chat | Ollama `qwen2.5:3b`, `llama3.2:3b`; llama.cpp `qwen2.5-3b`; Ollama `llama3.2` |
| Vision | Ollama `qwen2.5vl`, `llava`; llama.cpp `llava` |

Ollama speaks OpenAI-compatible chat at `http://127.0.0.1:11434/v1`. llama.cpp server defaults to `http://127.0.0.1:8080/v1`.

## Second opinion

For risky code (delete, migrate, auth, secrets, payment, deploy, and the rest of the list in `assist_router.py`), Auto runs two different code models and a reasoning-chain judge. The reply is the judge's merge. Both drafts stay on the answer. If the judge fails, both drafts are still shown and the badge says the judge failed. Fewer than two code models is an error before any call.

`always` does this for every code request. `off` never does.

## Where the owner edits it

- Web Models Studio, Assist feature: picker, routing table, cloud opt-in, preview. `PUT /api/studio/models/assist-routes`, `PUT /api/studio/models/assist-cloud`, `POST /api/studio/models/assist/preview`.
- WinUI Models document: the same fields, stored in `%LOCALAPPDATA%\Heirloom\settings.json`. The first-run overlay still says **Get everything ready** and does not list model names. Dev models download when the owner provisions a size from Models, not during that overlay.

The badge on an Assist answer looks like `Assist · Code · ollama/qwen3-coder:30b`. A fallback, a judge, or a skipped second opinion is appended on that same line.

## Install sizes

| Size | Assist models pulled |
| --- | --- |
| Small | none (Assist feature is not provisioned; Ollama is not required) |
| Medium | `qwen2.5-coder:7b`, `qwen2.5:3b` |
| Large | Medium, plus `qwen2.5-coder:32b`, `deepseek-r1:14b`, `qwen2.5vl:7b` |
| Dedicated PC | Large, plus `qwen3-coder`, `deepseek-coder-v2`, `deepseek-r1:32b` |

On a Medium install the code chain's first names are absent, so the badge is a loud fallback to `qwen2.5-coder:7b`.

## Follow-ups

- Research answers that cite sources, instead of a plain local completion.
- An agentic coding loop that edits, runs tests, and retries on this PC.
- A live llama.cpp model probe on each plan (short timeout) so that chain is not always "not running".
- Keep the C# and Python chain tables in one generated source if they start to drift.
