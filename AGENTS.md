# Heirloom

## Cursor Cloud specific instructions

The dedicated Windows companion (`backend/companion_desktop/`) is the product that talks, listens, and uses the PC. The React app is the archive/control surface.

- Mixer volume is the **Heirloom WASAPI session**, not the system master. After changing desktop audio code, run `python backend/build_desktop_data.py` so the downloadable zip stays in sync.
- Studio persistence lives at `GET/PUT /api/studio/audio` and `GET/PUT /api/studio/models` plus `POST /api/studio/models/provision`. The companion applies `audio_settings` / `model_map` from `/api/companion/poll` and reports GPU/Ollama/Whisper via `POST /api/companion/runtime`.
- Web chrome is an MDI-style studio (`AppLayout` dock + per-feature window menus). Public routes (landing, login, heir portal) stay outside that shell.
- `CONVEX_AGENT_MODE` is unrelated to this repo. Local auth for API tests is a seeded Mongo session Bearer token (see `backend/tests/conftest.py` / `auth_testing.md`).
- Standard lint/test/run commands are in `frontend/package.json` (`yarn start`, `yarn test` if present) and `backend/` (`uvicorn server:app --host 0.0.0.0 --port 8001 --reload`, `pytest`).
