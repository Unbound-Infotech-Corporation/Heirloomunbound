# Heirloom — Deploy, Backup & Ops Runbook

Last reviewed: Jul 17, 2026.

## Emergent relaunch checklist

Use this when bringing Heirloom back online for sale on Emergent.

### A. Code → Emergent preview

1. Merge / sync the latest ship branch into the Emergent workspace (this repo’s relaunch branch includes competitive gaps, Death Governance, Simple Setup, Settings tabs, sale gate, and health checks).
2. Confirm preview boots: landing loads, `/api/` returns `{"app":"digital-heirloom","status":"ok"}`.
3. Run the Emergent testing agent until green (or `pytest backend/tests/test_health_sale_ready.py -q` for the relaunch unit checks).

### B. Production env on Emergent

Set these in the Emergent backend env UI (see `backend/.env.example`):

| Var | Production value |
| --- | --- |
| `PUBLIC_BACKEND_URL` | `https://heirloomunbound.com` |
| `PUBLIC_FRONTEND_URL` | `https://heirloomunbound.com` |
| `CORS_ORIGINS` | `https://heirloomunbound.com` |
| `REACT_APP_BACKEND_URL` | `https://heirloomunbound.com` (frontend build) |
| `STRIPE_API_KEY` | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` |
| `STRIPE_PAYMENT_LINK_URL` | live Payment Link URL |
| `STRIPE_PAYMENT_LINK_ID` | matching `plink_...` |
| `RESEND_API_KEY` | live Resend key |
| `SENDER_EMAIL` | verified domain sender (not `onboarding@resend.dev`) |
| `ENFORCE_PURCHASE` | `true` when you are ready to sell |
| `EMERGENT_LLM_KEY` | Profile → Universal Key |

Then `sudo supervisorctl restart backend` (or Emergent restart).

### C. Stripe + email (money path)

1. Stripe Dashboard → **LIVE** mode.
2. Webhooks → Add endpoint → URL from `GET https://heirloomunbound.com/api/billing/webhook-info` → events listed there → paste signing secret as `STRIPE_WEBHOOK_SECRET`.
3. Enable **Customer emails → Successful payments**.
4. Resend → verify sending domain → set `SENDER_EMAIL`.
5. Confirm `GET /api/health` returns `"sale_ready": true`.

### D. Deploy to production

1. Emergent web UI → **Deploy** (promotes preview → production / custom domain).
2. Within 5 minutes:
   - `curl https://heirloomunbound.com/api/health`
   - Incognito load of landing + OG image
   - Google sign-in as yourself
   - Twin message + companion download smoke
   - One real or $1 live checkout if keys are live
3. If broken: **rollback** from Emergent dashboard first; debug in preview.

### E. After go-live

- Point Base44 / Unbound marketing CTAs at `https://heirloomunbound.com` (see `BASE44_INTEGRATION.md`).
- Confirm custom domain DNS (apex + www) on Emergent.
- Weekly: check Emergent logs + `/api/health`.
- Grant free access: `db.users.update_one({email: "..."}, {$set: {is_tester: true}})` or `{purchased_lifetime: true}`.

---

## TL;DR

| Action | Where | Frequency |
| --- | --- | --- |
| Push code to production | Emergent web UI → "Deploy" | Per release |
| Run pre-deploy tests | Emergent testing agent / pytest | Per release |
| Verify production health | https://heirloomunbound.com/api/health | Per release + weekly |
| Check error logs | Emergent dashboard → logs | After every deploy + on customer complaints |
| MongoDB backup | Emergent infra (verify with support) | Daily — confirm SLO |
| Rotate API keys | Anthropic / ElevenLabs / D-ID / Stripe portals | Every 6 months |
| Re-run SEO audit | Semrush | Monthly |

## Environments

| Env | URL | Purpose |
| --- | --- | --- |
| Preview (dev) | `*.preview.emergentagent.com` | Where the agent edits code. Auto-redeploys on every save. |
| Production | **https://heirloomunbound.com** | What customers see. Custom domain on Emergent (www → apex). |
| Fallback Emergent host | `*.emergent.host` | Platform default if custom domain is not yet attached. |

### Production env vars Emergent must set

| Var | Value |
| --- | --- |
| `PUBLIC_BACKEND_URL` | `https://heirloomunbound.com` |
| `PUBLIC_FRONTEND_URL` | `https://heirloomunbound.com` |
| `CORS_ORIGINS` | `https://heirloomunbound.com` (optional if `PUBLIC_BACKEND_URL` is set — CORS derives from it) |
| `REACT_APP_BACKEND_URL` | `https://heirloomunbound.com` (frontend build) |
| `ENFORCE_PURCHASE` | `true` for sale mode (leave unset on preview) |

Post-deploy smoke: `curl https://heirloomunbound.com/api/` → `{"app":"digital-heirloom","status":"ok",...}`.

Deep readiness: `curl https://heirloomunbound.com/api/health` → look for `"sale_ready": true`.

## Sale gate (`ENFORCE_PURCHASE`)

When `ENFORCE_PURCHASE=true`:

- Authenticated API calls (except auth, billing, health, webhooks, public heir/live links) require `purchased_lifetime`, `is_tester`, or `is_admin` on the user.
- The React shell redirects unpaid signed-in users to `/buy`.
- Refunded accounts (`account_status=refunded`) get 403.

Leave the flag **unset** on preview so demos and testing agents keep working. Grant staff access with:

```js
db.users.update_one({ email: "you@example.com" }, { $set: { is_tester: true } })
```

## Stripe — production setup

Before you accept real money, do these 4 things in the Stripe Dashboard. Each step takes ~2 min.

### 1. Switch to LIVE mode
Top-left toggle in stripe.com dashboard → **Activate your account** → fill business details, bank info, ID. Once approved you get an `sk_live_...` key under **Developers → API keys**. Replace `STRIPE_API_KEY` in backend `.env` and `sudo supervisorctl restart backend`.

### 2. Register the webhook
- **Developers → Webhooks → Add endpoint**
- **Endpoint URL**: get the right one from `GET /api/billing/webhook-info` (paste the `webhook_url` value — it will be `https://YOUR_PROD_DOMAIN/api/webhook/stripe`)
- **Events to send** (paste exactly these four):
  - `checkout.session.completed`
  - `charge.refunded`
  - `charge.dispute.created`
  - `charge.dispute.funds_withdrawn`
- Save → copy the **Signing secret** (`whsec_...`) → paste into backend `.env` as `STRIPE_WEBHOOK_SECRET`. The emergent integration library already uses it via the `webhook_url` constructor.

### 3. Enable Stripe Tax (recommended if selling outside one state/country)
- **Settings → Tax → Enable Stripe Tax** → add your business address.
- Stripe Tax automatically charges the right VAT / sales tax based on the buyer's location.
- For Payment Link checkout, enable tax in the Stripe Payment Link settings. Programmatic Checkout sessions use the Emergent Stripe wrapper — prefer Payment Link for tax until the wrapper exposes `automatic_tax`.

### 4. Receipts
Stripe automatically emails a receipt to the buyer's email when Receipts are enabled in **Settings → Customer emails → "Successful payments"**. Toggle that on. We also send our own welcome email via Resend (`email_service.send_magic_link_email`) — both arrive, the Stripe receipt is the formal one.

## Refund / dispute behaviour

When Stripe sends `charge.refunded`, `charge.dispute.created`, or `charge.dispute.funds_withdrawn`:
- The user's `users.account_status` becomes `"refunded"`.
- Every companion device is revoked (won't get commands; poll returns 403).
- Active sessions are deleted (forced re-login).
- The archive is preserved (in case the refund was a mistake — you can manually re-activate via `db.users.update_one({user_id: ..}, {$unset: {account_status: ""}})`).

If you want the archive auto-deleted on refund, change `_revoke_access_for_event` in `routers/fulfillment.py`.

## How to deploy

1. **Run the testing agent in preview** until green. Open the latest `/app/test_reports/iteration_*.json` and confirm all critical paths pass.
2. **Manual smoke** in preview: log in, send a Twin message, queue a companion command, render a D-ID clip, complete a $1 Stripe test checkout.
3. **Click "Deploy" in the Emergent UI.** This promotes the preview build to production.
4. **Post-deploy verification** (within 5 min):
   - `curl https://heirloomunbound.com/api/health` — should report `status` ok/degraded and list any missing sale checks
   - Load https://heirloomunbound.com in incognito — check OG image renders
   - Sign in as yourself in production — confirm no console errors
5. **If something is broken in production:** rollback from the Emergent dashboard before debugging. Never debug in production.

## Backup strategy

**MongoDB**: Emergent's managed Mongo offering does daily snapshots. Confirm with Emergent support what the retention window is and whether you have access to restore. For belt-and-suspenders, run a weekly `mongodump` exported to S3 or Google Drive (script below).

```bash
# Weekly Mongo backup — run from a worker, not from inside this container
mongodump --uri="$MONGO_URL" --archive=/tmp/heirloom-$(date +%F).gz --gzip
# Upload to a private bucket / your Drive — pick one
```

**Object storage** (photo uploads, voice samples): Prefer Emergent object store (`storage.py`). Local FS alone is fragile if the container is recreated — confirm object-store init succeeds in startup logs before scale.

## API key rotation

Rotate the following every 6 months (or immediately if you suspect a leak):

- `EMERGENT_LLM_KEY` — covers Claude + Whisper, in Profile → Universal Key.
- `ELEVENLABS_API_KEY` — at elevenlabs.io/app → API Keys.
- `D_ID_API_KEY` — at d-id.com → Account → API Key.
- `STRIPE_API_KEY` — at stripe.com → Developers → API keys. **Use the LIVE key once you start selling.**

After rotating: update the value in the backend `.env` file via the Emergent web UI, then run `sudo supervisorctl restart backend` (or wait for the platform auto-restart). Verify the integrations still work via the testing agent.

## Companion auto-update

The Windows companion polls `/api/companion/poll` every few seconds. The poll response includes a `script_version` field (currently `COMPANION_SCRIPT_VERSION` in `routers/companion.py`). When you change the embedded `_build_companion_script` output:

1. Bump the version constant.
2. Deploy. Companions will see the new version, re-download `/api/companion/public-script`, and restart on next poll.

Customers don't need to re-run the installer.

## Cost guardrails

| Service | Risk | Mitigation |
| --- | --- | --- |
| D-ID renders | High per-render cost | Encourage users to bring their own key via Settings (already wired). Add per-user monthly cap if abuse appears. |
| ElevenLabs TTS | Character usage | Users can connect their own ElevenLabs key in Settings. |
| Claude (Emergent LLM key) | Token usage | Profile → Universal Key → set monthly budget + auto-topup. |
| Stripe | None | Stripe charges only on successful checkout — no abuse vector. |

## On call

| Severity | Definition | Response time |
| --- | --- | --- |
| **P0** | Production is down or new sign-ups are broken | ≤ 1 hour |
| **P1** | A core feature (Twin, Library, Heirs) is broken for >10% of users | ≤ 24 hours |
| **P2** | Cosmetic, single-user, or a third-party provider blip | ≤ 1 week |

When you get a P0/P1: post in `support@heirloom.app` acknowledgement, roll back from Emergent dashboard if recent deploy, then diagnose in preview.

## Customer support

- **Refund requests** — `mailto:support@heirloom.app`. Stripe refund: stripe.com → Payments → find the payment → Refund. Then send the user a confirmation.
- **GDPR data export** — Settings → Connections includes archive export; otherwise manual mongosh JSON.
- **Account deletion** — user can self-serve from Settings → Danger Zone. The endpoint is `DELETE /api/auth/me?confirm=DELETE`.
- **Lost magic-link** — re-issue from the Stripe checkout fulfillment record (`db.checkout_sessions` / `db.payment_transactions`).

## Trust pages

- `/privacy` — privacy policy
- `/terms` — terms of service
- `/refunds` — refund policy
- `/support` — contact info

Update these when you change a third-party processor, your jurisdiction, or pricing. Re-publish privacy policy with a new "Last updated" date and email a heads-up to existing customers if the change is material.
