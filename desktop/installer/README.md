# Heirloom Unbound Setup

Mainstream Windows installer for **Heirloom Unbound**. Not a bat file only.

Product name: **Heirloom Unbound Setup**  
Output: `desktop/dist/HeirloomUnboundSetup.exe`

## Pages

1. Welcome
2. License + privacy (local models stay on this PC)
3. **Choose install size** — four cards
   - **Small** · 5–12 GB · Whisper + Piper + lite vault. Twin/TTS/avatar cloud Auto. No GPU.
   - **Medium** · 40–70 GB · Small + Ollama llama3.1 + one voice-clone path.
   - **Large** · 100–160 GB · Whisper large-v3, stronger twin + vision, Voicebox **and** Qwen3-TTS 1.7B, LatentSync.
   - **Dedicated PC** · 200 GB+ · Large plus machine role (consent, vault drive, start with Windows, optional power plan, warm engines).
4. Install directory (+ vault drive when Dedicated)
5. Ready
6. Progress (copies app bits, then runs `provision.bat`)
7. Finish → Launch Heirloom Unbound

Legacy ids still resolve: `lite`→Small, `full`→Medium, `max`→Large.

## Compile on Windows

1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php) (ISCC.exe).
2. Install the .NET 8 Windows App SDK workload (to publish WinUI).
3. From a Developer Command Prompt:

```bat
desktop\installer\Build-HeirloomUnbound-Setup.bat
```

Skip publish if `desktop\dist\Heirloom-ready\Heirloom.exe` already exists:

```bat
desktop\installer\Build-HeirloomUnbound-Setup.bat --skip-publish
```

Linux / Cursor Cloud agents **cannot** produce `Setup.exe`. They commit the `.iss`, bat, and in-app FirstRun / WinUI four-tier provision instead.

## Bootstrap

1. Copy Heirloom Unbound app bits into `Program Files\Heirloom Unbound` (or the per-user dir).
2. `provision.bat <profile> <vault> <consent> <appdir>` writes `%LOCALAPPDATA%\Heirloom\settings.json` `install_profile` and launches the app (or `python -m heirloom.provision_cli`).
3. Downloads resume via `.part` + HTTP Range. Voicebox / Qwen3-TTS / LatentSync failures coach and continue. Never Pinokio.

Dedicated PC also records start-with-Windows (Startup folder / HKCU Run), optional high-performance power plan **only with consent**, warm probes, standing routines / live listen toward on, and `Heirloom Unbound · Dedicated` branding text.

## SmartScreen

This Setup is **unsigned**. Windows will warn. Choose **More info → Run anyway**. The same honest note is in `backend/companion_desktop/Build-Heirloom-Exe.bat`. Reputation accumulates with installs.

## Headless provision (scriptable)

```bat
py -3 -m heirloom.provision_cli --profile small
py -3 -m heirloom.provision_cli --profile dedicated --vault D:\HeirloomVault --consent --start-with-windows
```

Companion first-run wizard (`backend/companion_desktop/heirloom/ui/setup_wizard.py`) and WinUI Getting started use the same four sizes.
