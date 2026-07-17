Heirloom Desktop
================

A professional Windows desktop app for your AI Twin — the same brain as the
web twin, running beside you on your PC.

QUICK START
-----------
1. Double-click `Heirloom.bat`.
2. First run installs Python deps in %LOCALAPPDATA%\Heirloom — takes ~60 seconds.
3. The app opens. Your device token is already baked in — no sign-in needed.

WHAT'S INSIDE
-------------
- Full twin brain: archive search, long-term memory, music, smart-home skills,
  and PC control tools (open apps, volume, screenshot vision, system status…).
  Text chat and push-to-talk both use the same tool-calling runtime as the web.
- A resizable avatar panel (D-ID talking head or animated waveform — toggle in
  the top-right of the avatar panel).
- A chat thread with your twin — bubble or flat layout; tool chips show when
  the twin uses a capability.
- A quick-capture journal on the right.
- A recent-memories sidebar on the left.
- Push-to-talk: hold Ctrl+Space anywhere in the app to speak; release to send
  (titlebar button is also hold-to-talk).
- Local Vault with Full / Partial / Lite tiers — every chat turn grows your twin.
- System tray icon: closing the window minimises to tray; right-click for
  Quit / Pop-out / Push-to-talk.
- Command palette: Ctrl+K.

OBS / STREAMING
---------------
Click "Pop out for OBS ↗" on the avatar panel to detach the twin into its own
borderless, transparent, always-on-top window. In OBS, add a Window Capture
source and pick "Heirloom Twin — Broadcast".

REQUIREMENTS
------------
- Windows 10 or 11
- Python 3.10+ (if missing, the launcher will open the install page for you)
- A working microphone (for push-to-talk)
- Internet — the twin runs in the cloud

TROUBLESHOOTING
---------------
- Status says "account inactive"? Your account was refunded — contact support.
- Status says "auth failed"? Re-download Heirloom Desktop from the Companion page.
- Status says "offline"? Check internet; the poller retries automatically.
- No sound when twin speaks? Check default playback device. The D-ID render
  bundles audio inside the MP4 — Windows volume mixer should show Heirloom.
- Reminder "say" commands: spoken via Windows SAPI when the twin queues them.
- Mic not working? Settings → Privacy → Microphone → allow desktop apps.
- App didn't open? Check %LOCALAPPDATA%\Heirloom for error logs.

VOICE CLONING
-------------
In Waveform avatar mode, Heirloom calls your ElevenLabs cloned voice so the
twin speaks aloud. Configure your voice in the web app: Settings → Voice clone
→ paste your ElevenLabs API key and pick the voice id (clone one in
ElevenLabs first if you haven't). The desktop app picks it up automatically
on next launch — no restart needed.

If no voice is configured, Waveform mode just pulses silently (no error).
D-ID mode is unaffected — it always speaks because the talking-head MP4
already has voice baked in.

BUILDING A STANDALONE .EXE (Optional)
-------------------------------------
To produce a `Heirloom.exe` that doesn't need Python installed on the
target machine:

  1. On a Windows machine with Python 3.10+ installed,
  2. Double-click `Build-Heirloom-Exe.bat`.
  3. Wait ~3-5 minutes. Output: `dist\Heirloom\Heirloom.exe`.
  4. Zip the entire `dist\Heirloom\` folder and share it.

First launch on a new PC will show a SmartScreen warning (the exe isn't
code-signed). Click "More info" -> "Run anyway". After ~5-10 successful
installs, SmartScreen reputation builds up and the warning disappears.

DATA
----
Settings live at %LOCALAPPDATA%\Heirloom\settings.json. The device token is
baked into the heirloom\config.py inside the install — revoke it any time
from your account's Settings → Devices page on the web.

— Unbound Infotech Corporation
