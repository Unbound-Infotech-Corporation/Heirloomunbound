# Heirloom

## Cursor Cloud specific instructions

The dedicated Windows companion (`backend/companion_desktop/`) is the product that talks, listens, and uses the PC. The React app is the archive/control surface.

- Mixer volume is the **Heirloom WASAPI session**, not the system master. After changing desktop audio code, run `python backend/build_desktop_data.py` so the downloadable zip stays in sync.
- Studio persistence lives at `GET/PUT /api/studio/audio` and `GET/PUT /api/studio/models` plus `POST /api/studio/models/provision`. The companion applies `audio_settings` / `model_map` from `/api/companion/poll` and reports GPU/Ollama/Whisper via `POST /api/companion/runtime` (also copied to `users.companion_runtime_probe` for routing).
- **Twin brain routing:** `backend/model_router.py` resolves STT/twin/TTS from `studio_models` + the runtime probe. Voice on the dedicated PC prefers **local faster-whisper → local Ollama** when provisioned; cloud Claude/ElevenLabs remain fallbacks. Desktop endpoints: `POST /api/desktop/brain-pack`, `POST /api/desktop/chat/local-complete`.
- `say` commands and the legacy companion script call **`POST /api/desktop/speak`** (cloned voice) before OS TTS.
- Web chrome is an Adobe-style studio shell: app menubar + icon dock + floating document window (`AppLayout`, `StudioWindow`). Per-route dropdown menus live in `frontend/src/components/studio/menuDefinitions.js`. Reusable inspector panels use `StudioPanel`, `StudioFieldRow`, `StudioTabs`, `StudioWorkspace`, and `FeatureModelPanel` under `frontend/src/components/studio/`. **Model credentials** are configured per feature in `/models` (inline key + Test), not only on `/setup/keys`. API: `PATCH /api/studio/models/{feature_id}`, `POST .../test`, `POST .../provision`.
- `CONVEX_AGENT_MODE` is unrelated to this repo. Local auth for API tests is a seeded Mongo session Bearer token (see `backend/tests/conftest.py` / `auth_testing.md`).
- Standard lint/test/run commands are in `frontend/package.json` (`yarn start`, `yarn test` if present) and `backend/` (`uvicorn server:app --host 0.0.0.0 --port 8001 --reload`, `pytest`).
