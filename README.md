# Here are your Instructions

## Unbound Phase 1

Heirloom Room + named **Clones** under the twin. Product note, Phase 2, and how to try it locally: [`UNBOUND.md`](UNBOUND.md).

## VR setup (testers)

Rooms sit uses **OpenXR on PC** (via WebXR in Chrome/Edge) and **WebXR** in the Quest browser. Native WinUI OpenXR viewing is still deferred.

1. Sign in, open **Rooms**, **or** open the public Help copy at `/support/vr` (no login).
2. **VR setup coach** (`/rooms/vr` or `/support/vr`) — pick your headset, follow the illustrated checklist. Downloads are official and free (Meta Horizon Link, SteamVR, ALVR GitHub releases, PICO Connect, PlayStation VR2 App). Virtual Desktop is paid optional — skip it unless you own it.
3. **Headset matrix** (`/rooms/vr/matrix` or `/support/vr/matrix`) or [`docs/vr-compatibility.md`](docs/vr-compatibility.md).
4. Build a stand-in scene, **Sit in this room**, press **Enter in VR**. If no runtime is present, the button tells you why and links the coach.
5. **Fix OpenXR** on the coach runs a secure-context + WebXR + `active_runtime.json` self-check.

### Which headsets are first-class vs guided workaround

- **Tier A (first-class):** Quest 2/3/3S/Pro (Link / Air Link / WebXR / ALVR), Valve Index, Vive / Index-class SteamVR. WMR is listed here historically but **deprecated** (Oasis community driver after Windows 11 24H2).
- **Tier B (official but fiddly):** Pico Neo 3/4/4 Ultra (PICO Connect + experimental `add_runtime.bat` OpenXR), PSVR2 (Sony **PC adapter** + free Steam PSVR2 App — not ALVR).
- **Tier C (guided workaround):** ALVR for Vive Focus / YVR / PhoneVR / experimental Android-Monado; Apple Vision Pro (ALVR store client, **no macOS host**); smartphone Cardboard / browser WebXR (lowest fidelity).

Do not sideload cracked Virtual Desktop. Heirloom does not ship vendor `.exe` / `.apk` files.
