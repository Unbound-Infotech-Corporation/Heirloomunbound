# Local skills: calendar, email, files, notes, web search

Every skill is **off until the owner turns it on** (Abilities page). Each runs
on the buyer's own machine through the local model; nothing here calls a cloud
model. Only the owner can use them: heirs, phone callers, and the heir portal
never see these tools.

| Skill | Tools the local model can call | What leaves the machine |
|---|---|---|
| Calendar | `calendar_upcoming`, `calendar_draft_event` | Read-only calendar API calls to Google or Microsoft |
| Email | `email_search`, `email_draft` | Mail API reads and draft creation; **never a send** |
| File Search | `search_files` | Nothing; the index is an SQLite file on the box/PC |
| Notes | `save_note`, `search_notes` | Nothing |
| Reminders | `set_reminder`, `list_reminders` (always on) | Nothing |
| Web & Weather | `web_search`, `web_fetch`, `get_weather` | The query (private words removed) or the public URL |

## How the local model calls tools

`backend/local_tools.py` gives the box's Ollama model the owner's enabled tools
through `/api/chat` `tools`, but only on a turn that plainly asks for one
("what's on my calendar tomorrow", "draft a reply to Karen's email"), and only
the two or three tools that match. A question about the owner's life never
sees a tool, so the approved-memory grounding is unchanged. Small models that
write the call as JSON text instead of `tool_calls` are understood too.

Every tool result goes back to the model fenced, with a note that it is data
and not an instruction (mail bodies are untrusted). Identical repeat calls run
once; after four rounds the model must answer without tools. The final reply
still goes through the claim check; what a tool returned this turn counts as
evidence, so "your dentist is at 9" is kept while an invented life claim is not.

Live check (`python -m model_bench_tools TAG`, 10 real requests with canned tool data):

| Model (tier) | Right | Median turn |
|---|---|---|
| gemma4:26b (xl) | 10/10 | 0.5 s |
| gemma4:12b (large, medium) | 10/10 | 0.6 s |
| qwen3.5:4b (small, compact) | 10/10 | 0.6 s |
| gemma4:e4b (cpu) | see PR | 0.3 s |
| gemma4:e2b (cpu, low RAM) | 10/10 | 0.3 s |

## Calendar and email accounts

OAuth 2 with PKCE. Tokens are sealed with the box's `CONNECTOR_SECRET_KEY`
before they reach Mongo and never reach the browser. The grants are the whole
permission:

- **Google:** `gmail.readonly`, `gmail.compose` (drafts; Google has no
  drafts-only scope, and Heirloom never calls send), `calendar.readonly`.
- **Microsoft:** `Mail.Read`, `Mail.ReadWrite` (drafts), `Calendars.Read`,
  `offline_access`. No `Mail.Send`.

A token that comes back with a send or calendar-write grant is refused. Event
"drafts" stay on the box as `.ics` files the owner opens to add; Heirloom never
writes their calendar.

Setup for a buyer (or the installer, step 4):

1. Google Cloud console → OAuth client (Web), redirect
   `https://<box>/api/local-skills/oauth/google/callback`. Set
   `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
2. Microsoft Entra → app registration (personal + work accounts), redirect
   `https://<box>/api/local-skills/oauth/microsoft/callback`, public client.
   Set `MS_OAUTH_CLIENT_ID`.
3. `HEIRLOOM_OAUTH_REDIRECT_BASE=https://<box>` (a PC install uses
   `http://127.0.0.1:8001`).
4. Abilities → Calendar or Email → Link.

## File Search

Abilities → File Search → add a folder. On a Twin Box, copy documents into
`/var/lib/heirloom/files` (mounted read-only into the API) and add that path.
Text, Markdown, CSV, HTML, PDF and Word files are read; other files are found
by name. Dot-folders, keys, wallets, password stores, `.env` files and
databases are never opened, and system or Heirloom data folders cannot be
added. `python file_index.py add|remove|reindex|search|status` works from a shell.

## Web search privacy

`web_search` is owner-only. Before a query leaves the machine,
`backend/web_privacy.py` removes self-references ("my", "mom", "grandpa") and
any name or rare word from this turn's private memory text. A query with
nothing public left is not sent. Set `HEIRLOOM_SEARXNG_URL` to use a SearXNG
on the LAN (the Twin Box's Odysseus stack runs one) instead of DuckDuckGo.
`web_fetch` reads public pages only: LAN addresses, the box's own services,
and redirects into them are refused.

## API (owner session only)

`GET /api/local-skills/status` · `POST /api/local-skills/oauth/{google|microsoft}/start` ·
`DELETE /api/local-skills/oauth/{provider}` · `POST /api/local-skills/files/roots` ·
`POST /api/local-skills/files/roots/remove` · `POST /api/local-skills/files/reindex` ·
`GET /api/local-skills/calendar/drafts` · `GET /api/local-skills/calendar/drafts/{id}.ics` ·
`GET|DELETE /api/local-skills/notes`
