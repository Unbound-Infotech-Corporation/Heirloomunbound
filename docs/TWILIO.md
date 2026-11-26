# Optional: call or text the Twin (Twilio)

Family can call or text a phone number and reach the Twin. This is **off by default** and
needs the buyer's own Twilio account and number. Nothing in Heirloom buys a number or creates
an account.

Twilio only carries the call. Everything else stays on the box:

| Step | Where |
|---|---|
| Who may call/text (owner, allowlist, unknown callers) | box: `phone_policy.decide_inbound` with the owner's phone settings |
| Speech → text | box: local Whisper on the recorded turn |
| Reply | box: the Twin (`run_twin_turn`, `local_only=True`, grounded, family persona) |
| Text → speech | box: local Chatterbox; Twilio just `<Play>`s the wav |

No Twilio speech recognition (`<Gather input="speech">`) and no Twilio text-to-speech (`<Say>`)
are used. If the box voice is down, the call says nothing rather than fall back to a cloud voice.
Live recordings are downloaded from `https://*.twilio.com` only and then **deleted** on Twilio.
Every call and text starts with "I'm an AI…" (turn off with `HEIRLOOM_AI_DISCLOSURE=0`).

## Modes (`TWILIO_MODE`)

- `off` (default): `/api/twilio/*` refuses everything.
- `mock`: no account. Requests must come from the box itself (loopback) with
  `X-Heirloom-Mock: 1`. Try it:

  ```bash
  python -m twilio_bridge simulate-sms  +15555550100 "Hi, it's me"   --api http://127.0.0.1:8001
  python -m twilio_bridge simulate-call +15555550100 /path/turn.wav   --api http://127.0.0.1:8001
  ```
- `live`: every webhook must carry a valid `X-Twilio-Signature` (HMAC-SHA1 with the auth token).

## Settings (`/var/lib/heirloom/box.env`)

```
TWILIO_MODE=off
TWILIO_ACCOUNT_SID=REPLACE_ME
TWILIO_AUTH_TOKEN=REPLACE_ME
TWILIO_PHONE_NUMBER=REPLACE_ME
HEIRLOOM_PUBLIC_URL=REPLACE_ME      # https address that forwards /api/twilio/* to the box
HEIRLOOM_VOICE_URL=http://chatterbox:8010/speak
```

Live mode stays "not ready" (`GET /api/twilio/status`, owner only) while any value is still
`REPLACE_ME` or the public URL is not https. The status never shows the auth token.

## Going live (buyer's own steps)

1. Create a Twilio account and buy a number in the Twilio console (their cost, their choice).
2. Expose only `/api/twilio/*` over https (e.g. Tailscale Funnel or a Cloudflare Tunnel) and put
   that address in `HEIRLOOM_PUBLIC_URL`.
3. In the number's settings: **A message comes in** → `POST {HEIRLOOM_PUBLIC_URL}/api/twilio/sms`;
   **A call comes in** → `POST {HEIRLOOM_PUBLIC_URL}/api/twilio/voice`.
4. Fill in the SID, token and number, set `TWILIO_MODE=live`, restart the API.
5. In the owner's phone settings, turn answering on and add family numbers to the allowlist.

## Endpoints

| Path | Use |
|---|---|
| `POST /api/twilio/sms` | text in → TwiML `<Message>` |
| `POST /api/twilio/voice` | call starts → greeting `<Play>` + `<Record>` |
| `POST /api/twilio/voice/turn` | recording → Whisper → Twin → `<Play>` + next `<Record>`; silence: one re-prompt, then goodbye |
| `GET /api/twilio/audio/{id}.wav` | reply clips (random ids, 1 hour) |
| `GET /api/twilio/status` | owner: mode, readiness, webhook paths |
