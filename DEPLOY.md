# Heirloom — Deploy, Backup & Ops Runbook

Last reviewed: Aug 27, 2026 (desktop **0.5.0** — WinUI primary; see `EMERGENT_HANDOFF.md`).

## TL;DR

| Action | Where | Frequency |
| --- | --- | --- |
| Push code to production | Emergent web UI → "Deploy" | Per release |
| Run pre-deploy tests | `testing_agent_v3` in this app | Per release |
| Verify production health | https://voice-clone-hub-20.emergent.host | Per release + weekly |
| Check error logs | Emergent dashboard → logs | After every deploy + on customer complaints |
| MongoDB backup | Emergent infra (verify with support) | Daily — confirm SLO |
| Rotate API keys | Anthropic / ElevenLabs / D-ID / Stripe portals | Every 6 months |
| Re-run SEO audit | Semrush | Monthly |

## Environments

| Env | URL | Purpose |
| --- | --- | --- |
| Preview (dev) | `voice-clone-hub-20.preview.emergentagent.com` | Where the agent edits code. Auto-redeploys on every save. |
| Production | `voice-clone-hub-20.emergent.host` (or your custom domain) | What customers see. Manually promoted from preview. |

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
- To turn it on in checkout: set `automatic_tax: { enabled: true }` on the checkout session metadata. This is currently NOT in our code — add it to `billing.py` when you're ready.

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

0. **Read `EMERGENT_HANDOFF.md`** for the current desktop stamp (WinUI primary vs legacy PySide zip) before promoting.
1. **Run the testing agent in preview** until green. Open the latest `/app/test_reports/iteration_*.json` and confirm all critical paths pass.
2. **Manual smoke** in preview: log in, send a Twin message, queue a companion command, render a D-ID clip, complete a $1 Stripe test checkout.
3. **Click "Deploy" in the Emergent UI.** This promotes the preview build to production.
4. **Post-deploy verification** (within 5 min):
   - `curl https://voice-clone-hub-20.emergent.host/api/` — should return `{"app":"digital-heirloom","status":"ok"}`
   - Load the landing page in incognito — check OG image renders
   - Sign in as yourself in production — confirm no console errors
5. **If something is broken in production:** rollback from the Emergent dashboard before debugging. Never debug in production.

## Backup strategy

**MongoDB**: Emergent's managed Mongo offering does daily snapshots. Confirm with Emergent support what the retention window is and whether you have access to restore. For belt-and-suspenders, run a weekly `mongodump` exported to S3 or Google Drive (script below).

```bash
# Weekly Mongo backup — run from a worker, not from inside this container
mongodump --uri="$MONGO_URL" --archive=/tmp/heirloom-$(date +%F).gz --gzip
# Upload to a private bucket / your Drive — pick one
```

**Object storage** (photo uploads, voice samples): Currently stored on the local FS in the container. **This is fragile** — if the container is recreated, photo binaries are lost. Move to GCS / S3 before going to scale. See `integration_playbook_expert_v2` for the object-storage playbook.

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
- **GDPR data export** — there's no UI for export yet (future work). Manual export via mongoshell into a JSON file mailed to the user.
- **Account deletion** — user can self-serve from Settings → Danger Zone. The endpoint is `DELETE /api/auth/me?confirm=DELETE`.
- **Lost magic-link** — re-issue from the Stripe checkout fulfillment record (`db.checkout_sessions`).

## Trust pages

- `/privacy` — privacy policy
- `/terms` — terms of service
- `/refunds` — refund policy
- `/support` — contact info

Update these when you change a third-party processor, your jurisdiction, or pricing. Re-publish privacy policy with a new "Last updated" date and email a heads-up to existing customers if the change is material.
