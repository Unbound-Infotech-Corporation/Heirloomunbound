# Heirloom companion (Android + iOS)

A small Expo app that pairs with the buyer's own Heirloom box and talks to the Twin.
It only ever talks to that box: chat goes to `/api/desktop/chat`, voice is transcribed by the
box's local Whisper (`/api/companion/voice`), and replies are spoken by the box's local voice
(`/api/mobile/speak.wav`). No cloud AI, no other server.

- **Pair**: scan the QR from the box (or type the address and the 8-character code). The QR
  carries the box's TLS key pin; the app pins it (dev/production builds).
- **Chat / Talk**: type, or tap Talk, speak, tap Stop. Voice on/off toggles spoken replies.
- **Unpair**: forgets the token on the phone. The owner can also revoke a phone on the box.

```bash
npm install
npm test            # jest: QR parsing + API client
npm run typecheck
npm run export      # bundles Android + iOS JS (no native build needed)
npx expo prebuild   # native projects, then build with Android Studio / Xcode or EAS
```

Pinning, the camera and the microphone are native modules, so use a development build
(`npx expo run:android|ios` or `eas build --profile development`), not Expo Go.
Setup and security details: [docs/MOBILE.md](../docs/MOBILE.md).
