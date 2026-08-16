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
- Scopes: `gmail.readonly` + `gmail.send` + `calendar.events` + `documents` + `spreadsheets` + `drive.file` + `youtube.readonly` + `webmasters.readonly`
  (plus openid/email/profile). Enable the Google Docs, Sheets, Drive, YouTube Data, and Search Console APIs on the project.
  Production needs Google app verification; until then the Connect button is fine in test/internal
  use. Existing Gmail users tap Connect Gmail again (or **Share Docs, Search & YouTube too**) to grant Docs.
- Optional `GOOGLE_REDIRECT_URI` override. Heirloom never stores the user's
  Gmail password — only OAuth tokens in `oauth_connections`. We only create files (`drive.file`),
  we do not browse the whole Drive. YouTube is list-only (no upload). Search Console is read-only.

### 9. Microsoft OAuth · Outlook · `MICROSOFT_CLIENT_ID` + `MICROSOFT_CLIENT_SECRET`
- Azure app registration → https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps
- Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/microsoft/callback`
- Scopes: `offline_access User.Read Mail.Read Mail.Send Calendars.ReadWrite`
- Optional `MICROSOFT_TENANT` (default `common`) and `MICROSOFT_REDIRECT_URI`.
- Same rule: sign-in happens on Microsoft's page. No Outlook password in Heirloom.

### 10. X (Twitter) OAuth · `TWITTER_CLIENT_ID` + `TWITTER_CLIENT_SECRET`
- Developer portal → https://developer.x.com/en/portal/dashboard
- Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/twitter/callback`
- Scopes: `tweet.read tweet.write users.read offline.access`. PKCE (S256) is used.
- Optional `TWITTER_REDIRECT_URI` (alias `X_*`). Sign-in on X's page. No password in Heirloom.

### 11. LinkedIn OAuth · `LINKEDIN_CLIENT_ID` + `LINKEDIN_CLIENT_SECRET`
- Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/linkedin/callback`
- Product: Sign In with LinkedIn using OpenID Connect + Share on LinkedIn.
- Scopes: `openid profile email w_member_social`.
- Optional `LINKEDIN_REDIRECT_URI`. Same rule: their page, never our password field.

### 12. Extra OAuth apps · Discord, Reddit, Pinterest, TikTok, WordPress, Slack, Notion, Dropbox, Mailchimp
Each is optional. Redirect URI: `{PUBLIC_BACKEND_URL}/api/oauth/{provider}/callback`.
Sign-in happens on their page. Heirloom never stores the user's password.

| App | Env vars | Notes |
|---|---|---|
| Discord | `DISCORD_CLIENT_ID` + `DISCORD_CLIENT_SECRET` | Scopes `identify webhook.incoming`. User picks a channel. |
| Reddit | `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Scopes `identity read submit history`. New Reddit apps may be gated. |
| Pinterest | `PINTEREST_CLIENT_ID` + `PINTEREST_CLIENT_SECRET` | Needs an `image_url` to pin. |
| TikTok | `TIKTOK_CLIENT_KEY` + `TIKTOK_CLIENT_SECRET` | List only. Publish needs a video file + app audit. |
| WordPress.com | `WORDPRESS_CLIENT_ID` + `WORDPRESS_CLIENT_SECRET` | Create post after confirm. |
| Slack | `SLACK_CLIENT_ID` + `SLACK_CLIENT_SECRET` | User scopes `chat:write,channels:read,...`. Store the **user** token. |
| Notion | `NOTION_CLIENT_ID` + `NOTION_CLIENT_SECRET` | User must share a page with the integration. |
| Dropbox | `DROPBOX_CLIENT_ID` + `DROPBOX_CLIENT_SECRET` | Uploads under `/Heirloom/`. |
| Mailchimp | `MAILCHIMP_CLIENT_ID` + `MAILCHIMP_CLIENT_SECRET` | Draft then send on confirm. Persist `api_endpoint` from metadata. |

Not wired (honest): Instagram / Facebook / Threads (Meta review), Bluesky (PAR+DPoP), WhatsApp Business API, Telegram bot tokens.

### 13. Sentry · `SENTRY_DSN` (low priority)
- Not really a "secret" — it's a public write endpoint token, but rotating is
  still good hygiene once a year.
- https://sentry.io → Settings → Client Keys (DSN) → generate new, deprecate old.

### 14. Emergent Universal Key · `EMERGENT_LLM_KEY`
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
