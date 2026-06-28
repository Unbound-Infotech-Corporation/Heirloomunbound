Heirloom Desktop
================

A professional Windows desktop app for your AI Twin.

QUICK START
-----------
1. Double-click `Heirloom.bat`.
2. First run installs Python deps in %LOCALAPPDATA%\Heirloom — takes ~60 seconds.
3. The app opens. Your device token is already baked in — no sign-in needed.

WHAT'S INSIDE
-------------
- A resizable avatar panel (D-ID talking head or animated waveform — toggle in
  the top-right of the avatar panel).
- A chat thread with your twin — bubble or flat layout, toggle in the top-right
  of the conversation panel.
- A quick-capture journal on the right.
- A recent-memories sidebar on the left.
- Push-to-talk: hold Ctrl+Space anywhere in the app to speak; release to send.
- System tray icon: closing the window minimises to tray; right-click for
  Quit / Pop-out / Push-to-talk.

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
- No sound when twin speaks? Check default playback device. The D-ID render
  bundles audio inside the MP4 — Windows volume mixer should show Heirloom.
- Mic not working? Settings → Privacy → Microphone → allow desktop apps.
- App didn't open? Check %LOCALAPPDATA%\Heirloom for error logs.

DATA
----
Settings live at %LOCALAPPDATA%\Heirloom\settings.json. The device token is
baked into the heirloom\config.py inside the install — revoke it any time
from your account's Settings → Devices page on the web.

— Unbound Infotech Corporation
