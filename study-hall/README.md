# Heirloom Study Hall

A local reading room whose only job is to make the Heirloom twin better. It is its own app: its own folder, its own launcher, and it is not part of the marketing site.

Study Hall reads articles, papers, course pages, docs, RSS feeds, and PDFs. A small panel of local models critiques what is actually useful. You file a lesson card, or you don't. Filed lessons become cited study notes the twin can see. Ideas that would change the twin's behavior wait in a queue. Accepting an idea writes a receipt. It does not change code.

## Run it

From this folder:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open the address `python run.py` prints. It prefers http://127.0.0.1:8788 and moves to the next free port if that one is taken. The Windows launcher opens that address for you.

The first screen has two actions: read the included sample, or open the library. Paste a link, type a topic (Wikipedia and arXiv, when their robots.txt allows it), or add a PDF.

**Run the panel** uses whatever local models answered. **Practice panel** is the same room with scripted readers, for when Ollama is not running. A practice card is labeled. Nothing is filed until you press **File into the twin**.

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File study-hall\install-windows.ps1
```

The default folder is `G:\HeirloomStudyHall`. Pass `-Destination` to put it somewhere else. The script does not ask for administrator rights and does not download models.

Then:

```powershell
G:\HeirloomStudyHall\Start-DedicatedOllama.ps1
G:\HeirloomStudyHall\Start-StudyHall.ps1
```

`Start-DedicatedOllama.ps1` serves on `127.0.0.1:11435` with models in `G:\HeirloomStudyHall\ollama-models`. It leaves the main Ollama on port 11434 alone. If 11435 is already answering, it does nothing.

## Models

Discovery asks both endpoints, plus a local OpenAI-compatible server on port 8080 if you have one (llama.cpp, a Hugging Face server, and similar).

| Host | Address | Used for |
| --- | --- | --- |
| study | http://127.0.0.1:11435 | The default panel and embeddings |
| main | http://127.0.0.1:11434 | Also discovered. Fallback moderator only |

Default readers, all on the study instance: `phi4:14b`, `mistral-small3.2:24b`, `gemma3:27b`.

Moderator: `llama3.1:8b` on the study instance. If that model is missing, `qwen3:8b` on the main instance. Embeddings prefer `mxbai-embed-large`, then `nomic-embed-text`. Those models do not sit on the panel.

Other installed models (deepseek-r1, qwen3:30b, llama3.3:70b, gpt-oss:120b, and the rest) show up in Models and are not in the default mix, so Study Hall does not load the twin's large models unless you edit `config.json`.

A paid cloud API is never required. Optional OpenAI-compatible endpoints can be added under `cloud` in `config.json`. Keys stay in that file.

## What filing does

Approved lessons are written to `data/knowledge/approved.json` with the source URL, title, date, and citations. On the Windows install that file is `G:\HeirloomStudyHall\data\knowledge\approved.json`. The twin reads the first of these that exists:

- `HEIRLOOM_STUDY_KNOWLEDGE`
- `HEIRLOOM_STUDY_HALL\knowledge\approved.json`
- `HEIRLOOM_DATA_ROOT\study-hall\knowledge\approved.json`
- `G:\HeirloomStudyHall\data\knowledge\approved.json`
- `~\.heirloom\study-hall\knowledge\approved.json`

The note is appended to the twin prompt only when the question actually overlaps it. The block says the note is research, not a memory of the owner's life, and it does not override a grounded "I don't remember." Empty or unrelated lessons change nothing.

Study lessons are not written into `memory_facts`. Those rows are identity claims about the person, they are wiped when the archive is rebuilt, and the prompt presents them as biography. Putting a paper in that shelf would weaken grounding. `model_router.py` and `llm_provider.py` are unchanged. Study Hall talks to Ollama itself.

## Research chat and Automate

The ask box is on every screen. “Find the best current research on long-term memory”, “look into how grief counselors talk about legacy letters”, and “ignore crypto sources” become missions, queries, or blocks. Questions about what has been read are answered from the library, with the source named.

**Become a better AI assistant** is a standing mission and it starts running. It looks at memory, personalization, grief-aware talk, voice UX, tool safety, grounding, evaluation, prompts, trust, and public discussions (including r/LocalLLaMA, r/MachineLearning, and Hacker News). Lesson cards from it are tagged assistant craft. Ideas land in the queue. You still file them.

Automate keeps going until you press Pause or Stop, in the Automate view or in the chat. Pages per hour and lead depth only slow it. An empty frontier is seeded again from the mission queries and watched communities. State is on disk, so a restart resumes a mission that was running. Errors back off and retry. `Enable-StudyHallLogin.ps1` (also the checkbox in Automate) adds a hidden Startup shortcut on Windows.

**Live Room** is the main view while a mission is running. The right side is the page being read, with the passage that matched and the reason it was followed. The left side is the panel talking about that page. The stream is server-sent events at `/api/live/stream`.

## Manners

- `robots.txt` is read first. If it cannot be read, the page is not fetched. A disallow is respected.
- One host is contacted at most every 1.5 seconds, or slower when the site asks for a crawl delay.
- Login walls and short pages that say "subscribe to continue" keep a citation and drop the body. There is no paywall bypass.
- Metadata hosts are refused.

## Tests

```bash
cd study-hall
.venv/bin/pytest
```

Covers ingestion (HTML, RSS, PDF, robots, rate limit, paywall, topics), the panel and moderator with mocked models, and the approval gate (a draft is not filed, filing writes provenance and a receipt, a second file is a no-op, accepting an idea does not change a sentinel copy of twin code).
