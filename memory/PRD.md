# Heirloom — Digital AI Twin (PRD)

## Original Problem Statement
> "I want to build an app that can make a AI Twin of me. One that i can have running in the background and just speak to when i enter the room. There should be a way to share my facebook and other social media pages with it so it can build a personality profile of me and a way for me to let it listen to me when i speak on Discord so that it gets to know more details about my personality.. i have a beefy computer with a 5090 so it shouldnt be too much of a stress on my hardware."

Follow-up (deciding intent):
> "the end goal is to use the AI twin and develop a massive amount of information on my personality so that when i die, the ai twin can be used by my son or relatives to have something of myself to still speak to when they want."

Follow-up (broader ambition):
> "i would like to be able to have the Ai twin actually use the computer that will be dedicated for it. Like i want to connect it to appliances in the house that have bluetooth or network connectivity and be able to tell the ai twin to complete tasks and actually have it do it."

## Core requirements
- Private archive of one person's voice, memories, beliefs, advice, stories — built slowly over years.
- A digital twin that responds in the user's voice, grounded in the archive, for the user's heirs to speak with after they pass.
- Capture surfaces: an AI interviewer, voice journal, social/text import, structured archive CRUD.
- Skills system: webhook-based commands the twin can invoke (Home Assistant, IFTTT, local scripts).
- Heirs: trusted contacts who one day inherit access.

## User personas
1. **Owner / archivist** — primary user, builds and maintains their archive over time.
2. **Heir** (future) — son / family / partner who eventually sits with the twin.

## Tech architecture (v1, what shipped)
- **Frontend**: React 19 + react-router 7 + Tailwind + shadcn/ui + framer-motion (Cormorant Garamond serif + Manrope sans + IBM Plex Mono).
- **Backend**: FastAPI 0.110 + Motor (Mongo) with a clean `/api/*` router structure.
- **LLM**: Claude Sonnet 4.6 via `emergentintegrations` (`EMERGENT_LLM_KEY`) — streaming SSE for both interviewer and twin.
- **Voice**: OpenAI Whisper STT + OpenAI TTS (voice=onyx) via the same key.
- **Auth**: Emergent-managed Google Auth → `/api/auth/session` + httpOnly `session_token` cookie (7-day expiry).
- **Storage**: MongoDB (`test_database`) — collections: users, user_sessions, entries, conversations, imports, skills, heirs.

## What's been implemented (Feb 25, 2026)
- ✅ Landing page + Google login + Auth callback (Emergent Auth playbook followed verbatim)
- ✅ Sidebar app shell (11 nav routes)
- ✅ Dashboard with stats, completeness % (non-linear heuristic), suggested next topics
- ✅ Archive CRUD (memory / story / value / advice / quote / chapter / voice / import)
- ✅ AI Interviewer with streaming Claude responses + seed questions + save-turn-as-entry
- ✅ Voice journal: MediaRecorder → Whisper STT → archive entry
- ✅ Talk-to-Twin chat: streaming Claude, grounded in archive + skills, optional TTS playback (falls back to OpenAI TTS if no voice clone)
- ✅ Social/text import with Claude-powered extraction into structured entries
- ✅ Skills (webhooks): create / list / edit / invoke / delete, with live test invocation
- ✅ Heirs management
- ✅ Settings page with ElevenLabs voice config + clone-your-own-voice
- ✅ Multi-user isolation verified

### Phase 2 — Feb 25, 2026
- ✅ **Photos**: Emergent object storage integration, upload with caption + taken_at, blob-fetch with Bearer/?auth query, soft-delete
- ✅ **ElevenLabs voice clone**: per-user API key override + app default fallback, list voices, set voice, Instant Voice Clone from samples, TTS via cloned voice. Twin chat falls back to OpenAI TTS automatically.
- ✅ **Local PC Companion v1**: device-token auth, command queue (shell / open_url / open_app / say), pull/poll architecture, voice passthrough (companion uploads audio → Whisper → Twin → reply + skill invocations), downloadable Python script with token + backend URL baked in, device revocation.

### Phase 3 — Feb 26, 2026 (this update)
- ✅ **Windows installer experience**: New `/api/companion/windows-package` returns a `.zip` containing `Heirloom.bat` (one-click launcher that installs deps + runs the script — no terminal needed), `Build-Exe.bat` (PyInstaller one-shot to produce a standalone `HeirloomCompanion.exe`), `heirloom_companion.py` (with system-tray icon support via pystray that degrades gracefully if missing), and `README.txt`. The Companion page now shows two download buttons: Windows package (primary) and `.py` only (Mac/Linux).
- ✅ **Wake-word mode** (push-to-talk OR "Hey Twin"): companion supports `--wake-word` / `--ptt` flags + `HEIRLOOM_WAKE_WORD` env var, using `openwakeword` (falls back to PTT automatically if not installed).
- ✅ **Sealed Letters**: full CRUD at `/api/letters` with three triggers — `on_release`, `on_date`, `on_age`. Letters can be sealed (locked from edits) and unsealed before delivery. Cannot be deleted after delivery.
- ✅ **Heir Release workflow**: extended Heirs with `release_on` date trigger and `inactivity_days` trigger. Owner endpoints: `/heirs/check-in` resets inactivity clock, `/heirs/check-releases` sweeps + mints tokens, `/heirs/<id>/release-now` manual override, `/heirs/<id>/revoke-release`, `/heirs/<id>/release-link`. Release tokens are never exposed in the list endpoint.
- ✅ **Public Heir Portal** at `/heir/<token>` (no auth, just the token): standalone page (no AppLayout) with four tabs — Welcome (heir.note + counts), Letters (only unlocked + auto-marks delivered on first read), Archive (read-only browse), Talk to them (real Claude chat grounded in owner's archive). Auto-rejects invalid/revoked tokens with a friendly error screen.

### Phase 4 — Feb 26, 2026 (research-driven feature pack)
Researched competitor matrix (HereAfter AI, Eternos, Replika 2026, Personal AI, StoryFile, Project December) and closed five real gaps:
- ✅ **Structured Personality Profile** (`/personality` page) — Claude auto-extracts Big Five (OCEAN with per-trait reasons), top values, voice tone description + signature phrases, life themes, key relationships, and a 3-4 sentence portrait summary. Cached for 7 days or until archive entry count changes. Manual refresh button. Closes the "what does my twin know about me?" gap that all competitors expose.
- ✅ **Proactive Daily Nudges** (`/api/nudges/today` + Today dashboard widget) — Claude generates a personal, archive-grounded nudge each UTC day: title, body, action_prompt. Idempotent per (user_id, date). User can act on it (deep-links to /interviewer pre-filled) or dismiss. History endpoint preserves them. Replika 2026 parity.
- ✅ **Ask-the-Archive Q&A** (`/api/archive/ask` + Library Ask toggle) — StoryFile-style cited answers. Keyword-scored retrieval over up to 400 entries, top 12 fed to Claude, returns answer + citation cards with snippets.
- ✅ **Safe-Topic Fence** (Settings → safe-topic-fence) — owner adds topics to politely decline. Applied to `_build_twin_system` so both `/twin/chat` AND the public heir portal respect the fence.
- ✅ **TTS language preference** scaffold (`/api/auth/me/preferences` accepts `tts_language`) — wiring ready for ElevenLabs Multilingual v2 selector.

### Phase 5 — Feb 26, 2026 (long-term memory + music control)
- ✅ **Long-term memory architecture** (`routers/memory.py`): identity facts (stable claims auto-extracted from the archive via Claude, cached, refresh when archive grows by 5+ entries) AND episodic summaries (twin auto-summarises a conversation after 12+ messages and stores it). Both are injected into the twin's system prompt BEFORE the per-turn archive excerpts — the twin no longer dumps the whole archive each turn.
- ✅ **What I Hold Onto** UI on `/personality` — each fact is removable (X button), instantly stops appearing in the twin's prompt. Closes the Vellum/OpenClaw/Replika-2026 memory gap.
- ✅ **Music control via the twin**: `routers/music.py` with 9 deep-link providers (YouTube Music, YouTube, Spotify, Apple Music, Amazon Music, Tidal, Deezer, Pandora, SoundCloud) + deterministic intent detection (`play X`, `put on X`, `queue up X`, `play song X`, `play music video of X`) that short-circuits before the LLM. When triggered, queues an `open_url` command on the user's active companion PC so playback opens in their browser/app. Twin replies with an inline music chip rendered on the chat page. User picks default provider in Settings.

## Backend test results
- iteration_11.json: 18/18 backend tests pass. Memory facts, episodes, caching, multi-user isolation, music regex (10/10 cases), companion command queue, twin SSE short-circuit (<3s, no Claude) — all green.

## Prioritized backlog (next phases)

### P1 — Polish on existing pillars
- **Companion TTS playback with cloned voice**: stream the twin's reply audio back to the on-PC speaker (currently uses local OS TTS — `say`/`espeak`/SAPI). Wire to ElevenLabs for in-room presence.
- **Email notifications**: when an heir is released, auto-email them the portal link (currently the owner must copy the link manually).
- **Long-conversation memory compaction** — summarize old turns so Claude context never overflows.
- **Photo linking** — attach photos to archive entries so the Twin can reference them by description.

### P2 — Legacy & community
- Discord bot (text channels) for passive personality capture.
- Family-tree graph linking memories to people.
- Export full archive as PDF "memoir" + JSON.

## Known limitations (transparent to user)
- Cloud-hosted: cannot directly control local devices without a webhook endpoint or local companion.
- Discord voice channel listening is not feasible via Discord's API — replaced with chat log import.
- Always-on "in the room" mic requires the local companion (P0 next).
