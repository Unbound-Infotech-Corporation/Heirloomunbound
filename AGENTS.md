# AGENTS.md

## Cursor Cloud specific instructions

Digital Heirloom ("Heirloom") is a two-service app:

- **backend/** — FastAPI + MongoDB (Motor). Entrypoint `server.py` (`app`). ~180 API routes under `/api`. Auth is cookie/Bearer session tokens minted from Emergent-managed Google OAuth.
- **frontend/** — React 19 SPA built with CRA + CRACO (`craco start`), package manager **yarn** (Yarn 1). Talks to the backend via `REACT_APP_BACKEND_URL`.

### Services & how to run them (dev)

Run each in its own long-lived terminal. The update script only refreshes dependencies; it does NOT start services.

- **MongoDB** (required by the backend at import time): `mongod --dbpath /home/ubuntu/mongodb-data --bind_ip 127.0.0.1 --port 27017`. There is no systemd in the container, so start `mongod` directly (not `systemctl`/`service`). Data dir `/home/ubuntu/mongodb-data` persists in the snapshot.
- **Backend**: from `backend/`, `.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001 --reload`. Health check: `curl http://localhost:8001/api/` → `{"app":"digital-heirloom","status":"ok"}`. (There is no `/api/health` route despite the Sentry filter mentioning it.)
- **Frontend**: from `frontend/`, `BROWSER=none yarn start` (serves on `http://localhost:3000`, proxied to the backend via `REACT_APP_BACKEND_URL`).

### Environment files (gitignored — recreate if missing)

`.env` files are gitignored and are NOT committed; they persist in the environment snapshot. If missing on a fresh machine, recreate:

- `backend/.env`:
  ```
  MONGO_URL=mongodb://127.0.0.1:27017
  DB_NAME=test_database
  REACT_APP_BACKEND_URL=http://localhost:8001
  CORS_ORIGINS=http://localhost:3000
  PUBLIC_BACKEND_URL=http://localhost:8001
  EMERGENT_LLM_KEY=
  ```
- `frontend/.env`:
  ```
  REACT_APP_BACKEND_URL=http://localhost:8001
  PORT=3000
  ```

Only `MONGO_URL` and `DB_NAME` are required for the backend to import/boot. Integration keys are intentionally blank locally.

### Feature keys (most AI/paid features are inert without them)

`EMERGENT_LLM_KEY` powers the LLM Twin/interviewer/heir-chat (via the private `emergentintegrations` package). Also optional: `ELEVENLABS_API_KEY`, `FAL_KEY`/`D_ID_API_KEY` (avatar), `STRIPE_API_KEY`/`STRIPE_WEBHOOK_SECRET` (billing), `RESEND_API_KEY` (email), `SENTRY_DSN`. Endpoints that need a missing key return an error (usually 5xx) but do not block boot. CRUD flows (archive entries, letters, heirs, heir portal summary/letters/archive) work with no keys.

### Python dependencies (important gotcha)

Backend deps pin two Emergent-hosted packages not on public PyPI: `emergentintegrations` and a `litellm` wheel. Install requires the extra index:
`pip install -r backend/requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`
The venv lives at `backend/.venv`. `requirements.txt` also includes desktop-companion deps (PySide6, sounddevice) that are not needed to run the API but are installed for completeness.

### Auth for manual testing (no real Google login available)

Real login needs Emergent's external OAuth service + interactive Google, so seed a session directly in Mongo and use a Bearer token (see `auth_testing.md`):
```
mongosh --quiet --eval 'use("test_database"); const t="dev_"+Date.now(); const u="dev-"+Date.now(); db.users.insertOne({user_id:u,email:u+"@example.com",name:"Dev User",created_at:new Date().toISOString()}); db.user_sessions.insertOne({user_id:u,session_token:t,expires_at:new Date(Date.now()+7*864e5).toISOString(),created_at:new Date().toISOString()}); print(t);'
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/auth/me
```
The public **Heir Portal** (`/heir/:token`) needs no login: create+seal a letter and create+release an heir (`POST /api/heirs/{id}/release-now`) to get a `hr_tok_...` token, then open `/heir/<token>`.

### Tests & lint

- Backend tests in `backend/tests/` are **integration tests** that hit a live server at `REACT_APP_BACKEND_URL` using session tokens; many require the backend running + seeded users + real API keys, so they are not a hermetic unit suite. Run with `backend/.venv/bin/pytest` from `backend/`.
- No lint config is committed. `ruff`, `flake8`, `black`, `isort`, `mypy` are installed (dev deps); running them surfaces pre-existing findings that are not project-enforced. Frontend lint is CRA/eslint via `yarn start`/`yarn build`.
