# Heirloom

Private digital archive + AI twin by **Unbound Infotech**.
One-time **$79 lifetime** purchase. Runs on **Emergent AI** (FastAPI + React + Mongo).

## Production

| | URL |
| --- | --- |
| App | https://heirloomunbound.com |
| Health | https://heirloomunbound.com/api/health |
| Buy | https://heirloomunbound.com/buy |

## Emergent relaunch (operator)

Full checklist: **[DEPLOY.md](./DEPLOY.md)** → section *Emergent relaunch checklist*.

Short path:

1. Sync this branch into the Emergent preview workspace (or merge to the branch Emergent deploys from).
2. In Emergent → backend env, set the production vars listed in `backend/.env.example` (especially Stripe live, Resend domain sender, `PUBLIC_*` URLs, `ENFORCE_PURCHASE=true`).
3. Restart backend (`sudo supervisorctl restart backend` or Emergent restart).
4. Confirm `GET /api/health` shows `"sale_ready": true`.
5. Smoke: login → Twin chat → companion download → Stripe test/live checkout.
6. Emergent UI → **Deploy** → promote preview to production / custom domain `heirloomunbound.com`.

## Local / agent layout

```
backend/     FastAPI app (uvicorn via supervisor on Emergent)
frontend/    React CRA (CRACO)
memory/      Product PRD history
DEPLOY.md    Ops runbook + Stripe + backups
```

## Docs

- [DEPLOY.md](./DEPLOY.md) — deploy, Stripe, backups, on-call
- [BASE44_INTEGRATION.md](./BASE44_INTEGRATION.md) — Unbound marketing site embed
- [auth_testing.md](./auth_testing.md) — seed sessions without Google
- [memory/PRD.md](./memory/PRD.md) — feature history
