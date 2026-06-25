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
- ✅ Sidebar app shell (9 nav routes)
- ✅ Dashboard with stats, completeness % (non-linear heuristic), suggested next topics
- ✅ Archive CRUD (memory / story / value / advice / quote / chapter / voice / import)
- ✅ AI Interviewer with streaming Claude responses + seed questions + save-turn-as-entry
- ✅ Voice journal: MediaRecorder → Whisper STT → archive entry
- ✅ Talk-to-Twin chat: streaming Claude, grounded in archive + skills, optional TTS playback per message
- ✅ Social/text import with Claude-powered extraction into structured entries
- ✅ Skills (webhooks): create / list / edit / invoke / delete, with live test invocation
- ✅ Heirs management
- ✅ Settings page with roadmap
- ✅ Multi-user isolation verified

## Backend test results (iteration_1.json)
- 50 / 50 pytest cases pass. Zero critical issues.
- Minor cosmetic notes (POST returning 200 vs 201) — not blocking.
- Voice STT success path not exercised (no audio sample in test env); 400 empty-audio guard verified.

## Prioritized backlog (next phases)

### P0 — Live-use capability (the "actually use the computer" pillar)
- **Local PC companion (Python, distributable)** that:
  - Holds an always-on mic, hot-word detect, streams audio to `/api/voice/transcribe` and `/api/twin/message`.
  - Exposes a local HTTP bridge so cloud-hosted Heirloom can hit it via ngrok / Tailscale Funnel.
  - Optional OS-control plugins (run shell commands, open apps, mouse/keyboard via pyautogui).
- **Home Assistant pre-baked skill templates** in the Skills UI ("Hue lights", "Spotify", "OBS scene").

### P1 — Personality fidelity
- **ElevenLabs voice cloning** — record 1-min sample → twin literally sounds like the user (requires user-supplied ElevenLabs key).
- **Photo + caption uploads** (object storage integration).
- **Long-conversation memory compaction** — summarize old turns so Claude context never overflows.

### P2 — Legacy & community
- Heir release workflow: scheduled email + access link when "release_on" hits.
- Discord bot (text channels) for passive personality capture.
- Family-tree graph linking memories to people.
- Export full archive as PDF "memoir" + JSON.

## Known limitations (transparent to user)
- Cloud-hosted: cannot directly control local devices without a webhook endpoint or local companion.
- Discord voice channel listening is not feasible via Discord's API — replaced with chat log import.
- Always-on "in the room" mic requires the local companion (P0 next).
