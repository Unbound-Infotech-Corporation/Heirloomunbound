# AGENTS.md

## Cursor Cloud specific instructions

This repo is the **Heirloom / Digital Heirloom — AI Twin** product (Emergent platform app): a
**FastAPI** backend (`backend/`), a **React 19 / CRACO** frontend (`frontend/`), and a **MongoDB**
datastore. A PySide6 Windows desktop companion lives in `backend/companion_desktop/` but is a
separate distributable, not part of the server-side dev loop.

The Cloud Agent update script already installs code dependencies (backend venv + `pip`, frontend
`yarn`). The notes below cover the non-obvious parts of running/testing the stack.

### Services & how to run them (dev mode)

Three processes are needed for end-to-end work. Start them in this order:

1. **MongoDB** (required, must be started manually — it is not a code dependency and has no
   auto-start):
   ```
   mongod --dbpath /home/ubuntu/mongo-data --logpath /home/ubuntu/mongo-log/mongod.log --bind_ip 127.0.0.1 --fork
   ```
   Verify: `mongosh --quiet --eval "db.runCommand({ping:1})"`.
2. **Backend** (FastAPI, port 8001): from `backend/`:
   ```
   .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
   ```
   Health check: `curl http://localhost:8001/api/` → `{"app":"digital-heirloom","status":"ok"}`.
   All routes are under `/api`. On startup it ensures Mongo indexes and starts a background
   sealed-letter delivery loop.
3. **Frontend** (React/CRACO dev server, port 3000): from `frontend/`:
   ```
   BROWSER=none yarn start
   ```

Run long-lived services under `tmux` so they survive between tool calls.

### Environment files (gitignored — must exist locally)

Neither `.env` is committed (both are gitignored). The update script recreates them if missing.
If you need to author them manually:

- `backend/.env`: `MONGO_URL=mongodb://localhost:27017`, `DB_NAME=test_database`,
  `EMERGENT_LLM_KEY=` (empty ok), `CORS_ORIGINS=http://localhost:3000`,
  `REACT_APP_BACKEND_URL=http://localhost:8001` (the test `conftest.py` reads this file).
- `frontend/.env`: `REACT_APP_BACKEND_URL=http://localhost:8001`.

`backend/deps.py` hard-requires `MONGO_URL` and `DB_NAME` at import — the backend will not start
without them.

### Authentication for local testing (no Google OAuth available)

Login normally uses Emergent-managed Google OAuth, which is unavailable locally. Bypass it by
seeding a user + session directly in Mongo (see `auth_testing.md`), then either:
- call the API with `Authorization: Bearer <session_token>`, or
- in the browser, set the cookie via DevTools console: `document.cookie="session_token=<token>;path=/"`
  then navigate to `/today`. (Cookies are domain-scoped to `localhost`, so a cookie set on
  `:3000` is sent to the backend on `:8001`.)

New accounts are forced through a 7-step onboarding wizard at `/onboarding` before `/today` and other
protected routes load. Onboarding is form-only (no AI) and seeds the user's archive.

### AI / third-party features need external keys

Core AI features (Twin chat, Biographer/interviewer, Whisper transcription, letter "assist",
photo storytelling, object storage for uploads) call the Emergent LLM proxy via `EMERGENT_LLM_KEY`.
Without that key these endpoints return **500** and object storage logs "disabled" — this is
expected in a keyless dev env, and the rest of the app (auth, archive, letters, heirs, dashboard,
onboarding, etc.) works fine. Stripe / ElevenLabs / D-ID / fal.ai / Resend / Spotify / GitHub are
all optional and degrade gracefully when their keys are unset.

### Lint / test / build

- **Lint**: there is no committed lint config. Backend has `ruff`/`flake8`/`black` in the venv
  (`.venv/bin/ruff check .` runs but reports pre-existing findings). The frontend has no `lint`
  npm script; ESLint runs automatically inside the CRA/webpack build during `yarn start` / `yarn build`.
- **Tests**: backend tests in `backend/tests/` are **integration tests** that hit a *running*
  backend at `REACT_APP_BACKEND_URL` and rely on session tokens seeded in Mongo. Run e.g.
  `cd backend && REACT_APP_BACKEND_URL=http://localhost:8001 .venv/bin/python -m pytest tests/test_iteration28_letters.py -v`.
  Some test files hardcode `/app/...` paths and specific tokens (Emergent CI conventions); AI-backed
  assertions fail without `EMERGENT_LLM_KEY`.
- **Build (frontend prod)**: `cd frontend && yarn build` (not needed for dev).

### Legacy Continuity (posthumous twin)

- Web page: `/legacy` — readiness score, death-watch, Inheritance Package download.
- API: `/api/legacy/*` (status, check-in, settings, export, heartbeat, export-device).
- Heir portal twin now uses the same personality + memory pack + safe-topic fence as the
  owner twin (`twin_prompt.py`). Optional `/heir-portal/{token}/twin/speak` for cloned voice.
- Windows companion (`backend/companion_desktop/`): death-watch heartbeat, Inheritance Package
  export, Family Kiosk mode, Windows Autostart, fixed `say` TTS. After editing the desktop
  package, re-run `backend/build_desktop_data.py` so `companion_desktop_data.py` stays in sync.
- Inactivity release for heirs uses the freshest of heir check-in, owner legacy check-in, and
  companion `last_seen` — so a running Windows twin prevents false releases.

### Gotchas

- Python here is 3.12; backend deps live in `backend/.venv`. `emergentintegrations` (imported at
  module load in most routers) is **not** on PyPI — install it with
  `--extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/` (the update script does this).
- `redis` is in `requirements.txt` but not actually required (live sessions use an in-memory bus).
