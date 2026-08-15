Heirloom Desktop
================

A professional Windows desktop app for your AI Twin.

QUICK START
-----------
1. Double-click `Heirloom.bat`.
2. First run sets Heirloom up — about a minute. Leave the window open.
   If Python is missing, Heirloom installs it (via winget). If a Python
   installer window appears instead, tick "Add python.exe to PATH", finish
   it, then double-click Heirloom.bat again.
3. The app opens already signed in. Then go to Twin → Avatar Studio in
   your browser: add a photo, tick the box, tap Set up my twin.

If Windows shows a blue "Windows protected your PC" box: More info, then
Run anyway. That is the one click we cannot skip for you.

Lost the zip? Open Local PC in your account and tap Download again on this
computer. You do not need a new pairing.

Logs: %LOCALAPPDATA%\Heirloom\setup.log

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
  Quit / Talk in a small window / Pop-out / Push-to-talk.

SMALL TALK WINDOW
-----------------
Click "Talk in a small window" on the twin's face, in the tray, or in the
command palette (Ctrl+K). The big Heirloom window hides. A small always-on-top
card stays on your screen with the twin's face, a short chat, and hold-to-speak.
Ask it to do tasks the same way as in the full window. Click "Full window" to
bring Heirloom back, or close the small card — Heirloom stays in the tray.

LOOK AT MY SCREEN
-----------------
Click "Look at my screen" (or say it out loud). The twin takes a picture of
this computer, helps with whatever is on it — a game, a sentence, a movie —
then deletes the picture. It does not keep what it saw. The Heirloom app must
be open. Fullscreen games work best with this look; if a game is exclusive
fullscreen and the picture is black, switch that game to borderless window.

OBS / STREAMING
---------------
Click "Pop out for OBS ↗" on the avatar panel to detach the twin into its own
borderless, transparent, always-on-top window (face only, no chat). In OBS, add
a Window Capture source and pick "Heirloom Twin — Broadcast".

REQUIREMENTS
------------
- Windows 10 or 11
- Python 3.10+ (Heirloom.bat installs it if missing; if a download page
  opens, tick "Add python.exe to PATH")
- A working microphone (for push-to-talk)
- Internet — the twin runs in the cloud

TROUBLESHOOTING
---------------
- No sound when twin speaks? Check default playback device. The D-ID render
  bundles audio inside the MP4 — Windows volume mixer should show Heirloom.
- Mic not working? Settings → Privacy → Microphone → allow desktop apps.
- App didn't open? Open %LOCALAPPDATA%\Heirloom\setup.log. Then Local PC →
  Download again. Unzip over the old folder and double-click Heirloom.bat.

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
