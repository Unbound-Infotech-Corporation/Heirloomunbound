# Secret Rotation Playbook — Heirloom

The `backend/.env` file currently ships live third-party credentials so the
Emergent deploy pipeline can read them. That is a known trade-off — but it
means anyone with repo/backup access can read those keys.

This document is your rotate-and-migrate checklist. Follow it once, then keep
`backend/.env` in git for the deploy pipeline going forward but with the
values replaced from the deploy secret store at boot time (via `emergent
secrets` or an equivalent CI step).

## Order (least → most disruptive)

Do these in order — if something breaks, you'll know which key.

### 1. Stripe · `STRIPE_API_KEY`
- Dashboard → https://dashboard.stripe.com/apikeys
- **Roll** the current key. Stripe supports a 12-hour grace period; keep
  processing traffic on the old key during the swap.
- Paste the new key into your deploy secret store (**not** `.env`).
- Redeploy. Verify a test payment session still creates.

### 2. Resend · `RESEND_API_KEY`
- Dashboard → https://resend.com/api-keys
- Create a new key (name it `heirloom-prod-2026-02`), then delete the old one.
- Paste new value into deploy secret store.
- Redeploy. Verify a magic-link email delivers.

### 3. ElevenLabs · `ELEVENLABS_API_KEY`
- Dashboard → https://elevenlabs.io/app/settings/api-keys
- Rotate. Only one key can be active at a time — expect ~30s downtime for
  voice-cloning between "revoke old" and "deploy new."
- Redeploy. Trigger a `/api/voice/synthesize` request to verify.

### 4. D-ID · `D_ID_API_KEY`
- Dashboard → https://studio.d-id.com/account-settings
- Generate a new key. D-ID also supports having two keys active.
- Redeploy. Trigger an avatar clip generation to verify.

### 5. Fal.ai · `FAL_KEY`
- Dashboard → https://fal.ai/dashboard/keys
- Create new, revoke old.
- Redeploy. Verify an image restore / generate request works.

### 6. GitHub OAuth · `GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET`
- Settings → https://github.com/settings/developers → your OAuth app
- Only the **client secret** can be rotated; the client_id is public.
- Generate a new client secret; put it in the deploy secret store.
- Deploy, verify a fresh Heirloom "link GitHub" flow, then delete the old secret.

### 7. Spotify OAuth · `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`
- Dashboard → https://developer.spotify.com/dashboard → your app → Settings
- "Reset client secret" — this immediately invalidates the old one.
- Put new value in secret store, redeploy.
- Expect anyone already linked to be forced to re-authorise.

### 8. Google OAuth · Gmail · `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET`
- Cloud Console → https://console.cloud.google.com/apis/credentials
- OAuth client type: Web application.
- Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/google/callback`
- Scopes: `gmail.readonly` + `gmail.send` (plus openid/email/profile). Production
  needs Google app verification; until then the Connect button is fine in
  test/internal use.
- Optional `GOOGLE_REDIRECT_URI` override. Heirloom never stores the user's
  Gmail password — only OAuth tokens in `oauth_connections`.

### 9. Microsoft OAuth · Outlook · `MICROSOFT_CLIENT_ID` + `MICROSOFT_CLIENT_SECRET`
- Azure app registration → https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps
- Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/microsoft/callback`
- Scopes: `offline_access User.Read Mail.Read Mail.Send`
- Optional `MICROSOFT_TENANT` (default `common`) and `MICROSOFT_REDIRECT_URI`.
- Same rule: sign-in happens on Microsoft's page. No Outlook password in Heirloom.

### 10. Sentry · `SENTRY_DSN` (low priority)
- Not really a "secret" — it's a public write endpoint token, but rotating is
  still good hygiene once a year.
- https://sentry.io → Settings → Client Keys (DSN) → generate new, deprecate old.

### 9. Emergent Universal Key · `EMERGENT_LLM_KEY`
- Managed by Emergent — if you suspect compromise, contact support to rotate.
- The `.env` value is populated by the deploy pipeline; no manual step needed.

## Verifying the migration

After rotating everything:

```bash
# 1. Confirm no real key remains in backend/.env
$ grep -E "^(STRIPE|RESEND|ELEVENLABS|D_ID|FAL|GITHUB_CLIENT_SECRET|SPOTIFY_CLIENT_SECRET)_" backend/.env
# All values should now be `${SECRET_NAME}` placeholders or `<paste-in-deploy>`

# 2. Confirm the deploy pod actually reads them from the secret store
$ curl -s $PUBLIC_BACKEND_URL/api/ping
# → 200 OK

# 3. Trigger one endpoint per vendor to prove the keys resolved:
#    - Stripe: /api/billing/checkout
#    - Resend: /api/email/test
#    - ElevenLabs: /api/voice/list-voices
#    - D-ID: /api/avatar/list
#    - Fal: /api/photo-story/generate (any generation)
#    - GitHub / Spotify / Gmail / Outlook OAuth: click "Connect" in Settings
```

## Ongoing hygiene

- **Never** paste a live key into a github issue, PR description, or chat.
- Rotate secrets every 6 months as a scheduled ops task.
- If a key is ever suspected leaked, revoke first, patch later. Every provider
  above has one-click revoke in the dashboard.
- Consider a `pre-commit` hook that greps `.env` for anything matching
  `sk_live_`, `re_`, `xi-`, etc. and blocks commits.

_Generated during Phase 39 (Feb 2026) security-audit response._
