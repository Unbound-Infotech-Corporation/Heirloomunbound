# Phone app (Android + iOS)

The Heirloom phone app (`mobile/`, Expo / React Native) is a remote for the buyer's own box.
It pairs with one box and talks only to it. The Twin's brain (local model), memory, speech
recognition (local Whisper) and voice (local Chatterbox) all stay on the box.

## What it does

| Screen | Box endpoint | Runs on the box |
|---|---|---|
| Pair (scan QR or type code) | `POST /api/mobile/pair/claim` | issues a phone token |
| Chat | `POST /api/desktop/chat` (Bearer phone token, mode `twin`) | local model, grounded |
| Talk | `POST /api/companion/voice` (recorded audio) | local Whisper → Twin |
| Spoken replies | `GET /api/mobile/speak.wav?text=` | local Chatterbox |
| Unpair | forgets the token; owner can revoke on the box | — |

A phone token can only chat and talk as the Twin (`client_chat_mode` maps `phone_*` devices to
`twin` mode: no PC control, no assistant tools). It cannot list or pair devices.

## Pairing

1. On the computer, sign in as the owner and open **/phone-app** → **Show pairing code**.
   The box makes an 8-character code (no look-alike letters), good for **one use and 10
   minutes**. At most 3 open codes per owner; 10 wrong guesses per 10 minutes per address
   are refused. Only a hash of the code is stored.
2. In the app, scan the QR (`heirloom://pair?box=…&code=…&pin=…`) or type the box address and code.
3. The box returns a phone token (`mob_…`), kept in the phone's secure storage
   (Keychain / Android Keystore via `expo-secure-store`).
4. The owner sees paired phones on **/phone-app** and can **Remove** one; its token stops
   working at once.

## Connection security

- The app talks **https** to the box (Caddy with the box's own CA). Plain http is only
  accepted for a private LAN address, and Android builds disallow cleartext anyway.
- **Trust the box CA once on the phone.** Download it from `https://<box>/api/box/ca`
  (also `/var/lib/heirloom/caddy/caddy/pki/authorities/local/root.crt`):
  - iPhone: open the file → Settings → Profile Downloaded → Install, then
    Settings → General → About → Certificate Trust Settings → enable it.
  - Android: Settings → Security → Encryption & credentials → Install a certificate → CA.
    The app's network config (`mobile/plugins/withBoxCa.js`) trusts user CAs for this app only.
- **Pinning.** The QR carries the SHA-256 of the box CA's public key (`HEIRLOOM_TLS_SPKI_PIN`,
  or computed from `HEIRLOOM_CADDY_ROOT`). The app pins it with
  `react-native-ssl-public-key-pinning` (OkHttp on Android, TrustKit on iOS), so another CA on the
  phone cannot impersonate the box. Pinning is native: it works in development and production
  builds, not in Expo Go.
- Away from home, reach the box the same way the Windows app does (e.g. Tailscale); set
  `HEIRLOOM_PHONE_BOX_URL` so the QR carries that address.

## Building

```bash
cd mobile
npm ci
npm test && npm run typecheck
npm run export                      # JS bundles for Android + iOS (CI does this)
npx expo prebuild                   # android/ + ios/ (generated, not committed)
npx expo run:android                # or open ios/ in Xcode; or eas build
```

App ids: `com.unboundinfotech.heirloom.companion` (both platforms). Store signing, icons and
listing text are still to do before a public release.

## Testing against a real box without touching its data

`backend/mobile_mock_check.py` builds a minimal API (mobile, desktop, companion, twilio routers)
on 127.0.0.1 against a **throwaway database** (`DB_NAME` must start with `hl_mock_`), makes a fake
owner, pairs a fake phone, chats, renders the voice, sends it back through Whisper, simulates an
SMS and a call (Twilio mock mode), revokes the phone and drops the database:

```bash
docker run --rm --network heirloom-box --env-file /var/lib/heirloom/box.env \
  -e DB_NAME=hl_mock_$(date +%s) -e TWILIO_MODE=mock -e HEIRLOOM_VOICE_URL=http://chatterbox:8010/speak \
  -v $PWD/backend:/bench -w /bench box-api python -m mobile_mock_check
```
