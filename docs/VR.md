# VR in the Heirloom Room

Owner only. Heirs stay on the flat Twin. Product version stays **0.5.1**. FastAPI stays **0.3.0**.

VR renders on the owner's Windows PC. The Twin Box (headless Ubuntu) is the backend: chat, speech, and Observer notes. It does not drive the visor.

## The switch

The Room always opens on the normal screen.

- VR is off until the owner turns it on.
- The preference is saved per owner (`studio_vr` on the account, and `heirloom.vr.<user id>` in the browser). WinUI stores `vr_mode` and `vr_gaze` in `%LOCALAPPDATA%\Heirloom\settings.json`.
- A connected headset does not enter VR, including when the saved preference is already on.
- Turning the Room switch from off to on is the click that starts WebXR.
- If the preference was already on, the page still shows the flat Room and an **Enter headset** button. That click is the gesture.
- **Leave headset**, or turning VR off, ends the WebXR session and returns to the flat Room.
- The Settings page saves the same switches. It does not start a session.
- The VR setup coach's **Try Enter in VR** is a runtime check. It does not turn Room VR mode on.
- WinUI Twin and Settings show the same switches. The native window has no WebXR session, so it only saves the preference and, when a device token is present, `PUT /api/studio/vr`. It does not launch SteamVR, a browser, or `Heirloom.exe`. The headset view is the browser Room on this PC.

Eye tracking is a second switch, also default off. Turning it on does not start VR.

## PSVR2 on Windows

The owner's headset is PlayStation VR2 with Sony's official PC adapter (CFI-ZVP1). That combination works only on **Windows**, through **SteamVR**. It does not run on the Twin Box.

1. Use a Windows PC with DisplayPort 1.4 on the GPU, a USB 3 port, and Bluetooth for the Sense controllers.
2. Install Steam, then SteamVR, then the [PlayStation VR2 App](https://store.steampowered.com/app/2580190/PlayStationVR2_App/) (app id 2580190).
3. Plug the adapter's USB-A 3.0 cable directly into the PC (no hub). Plug DisplayPort 1.4 directly into the GPU. Do not use a USB-C DisplayPort cable or an HDMI converter.
4. Power the adapter, then the headset.
5. Finish the play area and firmware in the PlayStation VR2 App. Leave that app installed.
6. SteamVR is the OpenXR runtime. Chrome or Edge on this PC uses it for WebXR.

Headset matrix and the longer cable checklist: `docs/vr-compatibility.md`.

### Eye tracking on PSVR2

The headset has eye cameras when it is connected to a PlayStation 5. Sony's PC adapter and the PlayStation VR2 App do not expose eye tracking to PC applications. SteamVR does not currently offer the OpenXR extension `XR_EXT_eye_gaze_interaction` for this headset. WebXR in Chrome and Edge does not surface that extension to the page either. HDR and headset haptics are also PlayStation 5 features.

Heirloom requests a `gaze` reference space only after the owner opts in, and only as an optional probe. It is not a required session feature, so a refusal does not cancel VR. When gaze is missing, the Room continues and no attention note is sent.

If a future runtime advertises gaze anyway, the page may use it. The data that leaves the browser is still the aggregated summary below, not a raw stream.

## Talking to the Twin Box

On the Windows PC, point the studio at the box. The backend URL is configurable (WinUI Settings, or the web app's API base). Example: `https://<box-ip>/`.

WebXR needs a secure context. The box terminates HTTPS with Caddy's internal certificate authority. Trust that CA on Windows before the Room will enter VR against the box:

1. On the box, the root is `/var/lib/heirloom/caddy/caddy/pki/authorities/local/root.crt`.
2. Copy `root.crt` to the Windows PC.
3. Install it under Trusted Root Certification Authorities for the current user (or the computer).
4. Open `https://<box-ip>/` and confirm the browser shows a trusted padlock.

`localhost` is also a secure context when the API is on the same machine. Do not drop TLS to satisfy WebXR.

In the headset the Twin is a simple seated block about 1.6 m in front of the owner (local floor, negative Z). There is no scanned face and no third-party face mesh.

Push-to-talk:

- Controller trigger or grip (WebXR gamepad buttons 0 and 1).
- Keyboard Space or V, when focus is not in a text field.

Speech uses the existing account route `POST /api/voice/transcribe` with `save_to_archive=false`, so the line is not filed as a journal. The reply is the existing Twin chat (`POST /api/twin/message`). Spoken audio is `POST /api/voice/speak`, played with a Web Audio panner at the Twin's seat. If playback fails, the text reply still appears in the Room.

The companion's local faster-whisper path (`POST /api/companion/voice`, device token) is unchanged. This browser sitting uses the account voice route.

## Eye-tracking notes

Default off. Separate from the VR switch.

When gaze data exists, the page totals which coarse area was looked at and for how long:

- twin
- the twin's seat
- room
- floor
- elsewhere

Dwells under 400 ms are dropped. On leaving VR, one summary is posted to `POST /api/observer/vr-gaze`. The stored note is `source=vr_gaze`. Raw origin, direction, quaternion, and pupil samples are discarded before the request is built, and the server drops them again.

The note is written only when the owner opted in, Observer is on, and Observer is not paused. Heirs receive 404. The note does not enter the Twin prompt. It stays out of heir-visible notes even after "That's me".

## Later

VR for heirs is a later slice. A native OpenXR view inside the WinUI window is still deferred. A likeness in the headset waits until a commercially usable mesh exists.
