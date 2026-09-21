# Heirloom Room — VR headset compatibility

**Updated 21 Sep 2026.** Official free software only. Heirloom does **not**
redistribute Meta, Sony, Pico, or Steam installers, and will never link to a
cracked copy of Virtual Desktop.

Primary runtime on PC: **OpenXR**. Fallback: **WebXR** in the browser (Quest
Browser, or Chrome/Edge riding the active OpenXR runtime). SteamVR is the
OpenXR bridge for Index, Vive, ALVR, Pico Connect, and PSVR2.

In the studio: **Rooms → VR setup coach** (`/rooms/vr`) and **Headset matrix**
(`/rooms/vr/matrix`). Sit → **Enter in VR** probes WebXR and sends you to the
coach when a runtime is missing.

Public Help copies (no login): `/support/vr` and `/support/vr/matrix`. Heirs
do not get Rooms; these Help pages are setup guidance only.

## Tiers

| Tier | Meaning | Headsets |
| --- | --- | --- |
| **A — First-class** | Official free PC path. OpenXR or WebXR. | Quest 2/3/3S/Pro, Valve Index, Vive / Index-class, WMR (deprecated/fragile) |
| **B — Official but fiddly** | Vendor software is free; hardware or an experimental runtime may be required. | Pico Neo 3/4/4 Ultra, PSVR2 + Sony PC adapter |
| **C — Guided workaround** | Community or browser. Extra steps, lower fidelity. | ALVR (Focus / YVR / PhoneVR / Monado), Apple Vision Pro, smartphone Cardboard |

## Matrix (headset × path)

Legend: **R** = recommended · **S** = simplest · **free** · **hw$** = paid hardware · **opt$** = paid optional polish · — = not a path

| Headset | Link USB | Air Link | ALVR | Pico Connect | Pico OpenXR | PSVR2 adapter | SteamVR | OpenXR | WebXR | Oasis (WMR) | Virtual Desktop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Quest 2/3/3S/Pro **A** | **R** free | free | free | — | — | — | free | free | **S** free | — | opt$ |
| Valve Index **A** | — | — | — | — | — | — | **R** free | **S** free | free | — | — |
| Vive / Index-class **A** | — | — | — | — | — | — | **R** free | **S** free | free | — | — |
| WMR (Reverb / Odyssey) **A*** | — | — | — | — | — | — | free | free | free | **R** free | — |
| Pico Neo 3/4/4 Ultra **B** | — | — | free | **R** free | free | — | — | — | **S** free | — | opt$ |
| PSVR2 **B** | — | — | — | — | — | **R** hw$ | free | free | free | — | — |
| ALVR others **C** | — | — | **R** free | — | — | — | free | — | free | — | — |
| Apple Vision Pro **C** | — | — | **R** free | — | — | — | — | — | **S** free | — | — |
| Phone / Cardboard **C** | — | — | — | — | — | — | — | — | **R** free | — | — |

\*WMR is first-class historically, **deprecated**. Microsoft removed Mixed Reality Portal in Windows 11 24H2. Treat Oasis as a community workaround.

## Official free downloads (deep links only)

| Software | Cost | Link |
| --- | --- | --- |
| Meta Horizon Link | Free | https://www.oculus.com/download_app/?id=1582076955407037 |
| Quest Link / Air Link help | Free | https://www.meta.com/help/quest/509273027107091/ |
| Steam | Free | https://store.steampowered.com/about/ |
| SteamVR | Free | https://store.steampowered.com/app/250820/SteamVR/ |
| ALVR releases (GitHub) | Free, OSS | https://github.com/alvr-org/ALVR/releases |
| ALVR on Meta store | Free | https://www.meta.com/experiences/alvr/7674846229245715/ |
| SideQuest | Free | https://sidequestvr.com/ |
| PICO Connect | Free | https://www.picoxr.com/software/pico-link |
| PlayStation VR2 App | Free | https://store.steampowered.com/app/2580190/PlayStationVR2_App/ |
| PSVR2 PC setup (Sony) | Docs | https://www.playstation.com/en-us/support/hardware/pc-ps-vr2-set-up/ |
| Oasis WMR driver | Free, community | https://store.steampowered.com/app/3824490/Oasis_Driver_for_Windows_Mixed_Reality/ |
| OpenXR (Khronos) | Standard | https://www.khronos.org/openxr/ |
| WebXR | Standard | https://immersiveweb.dev/ |
| PhoneVR | Free, OSS | https://github.com/PhoneVR-Developers/PhoneVR |
| Monado (Linux) | Free, OSS | https://monado.freedesktop.org/ |
| Virtual Desktop | **Paid, optional** | https://www.vrdesktop.net/ |

Virtual Desktop is polish, not a requirement. Do not pirate it.

## Path notes

### Quest 2 / 3 / 3S / Pro (Tier A)

1. **USB Link (recommended on PC):** Horizon Link + USB-C 3.2 (5 Gb/s). Headset Settings → Quest Link.
2. **Air Link:** same app, PC on Ethernet, headset on 5 GHz / 6 GHz, same LAN, not a guest SSID.
3. **WebXR (simplest):** open Heirloom Sit in **Quest Browser** and tap Enter in VR. No PC runtime.
4. **ALVR:** free wireless SteamVR. Meta store app on Quest 2/3/Pro; SideQuest for Quest 1.
5. SteamVR optional if you want the Steam overlay. OpenXR via Meta runtime or SteamVR.
6. Virtual Desktop: paid optional.

### Valve Index / Vive (Tier A)

SteamVR + OpenXR. SteamVR → Settings → OpenXR → Set SteamVR as OpenXR Runtime. DisplayPort + lighthouses.

### Windows Mixed Reality (Tier A, deprecated)

Official WMR-for-SteamVR is **gone** on Windows 11 24H2. Do not install old Mixed Reality Portal packages. Community **Oasis** driver (free on Steam) is the remaining path: NVIDIA or AMD RDNA, no Intel GPU. Fragile.

### Pico Neo 3 / 4 / 4 Ultra (Tier B)

1. **PICO Connect** (free) on PC + headset store app.
2. **Experimental OpenXR:** in the PICO Connect folder, run `add_runtime.bat` as Administrator (registers PicoStreamingXR). Undo with SteamVR → OpenXR.
3. **ALVR** via SideQuest.
4. Virtual Desktop: paid optional.

### PSVR2 (Tier B) — not ALVR

You need the **Sony PC adapter** (paid hardware, CFI-ZVP1). Software is free:

1. Steam → SteamVR → [PlayStation VR2 App](https://store.steampowered.com/app/2580190/PlayStationVR2_App/).
2. Adapter USB 3.0 Type-A **directly** into the PC (no hub).
3. **DisplayPort 1.4** from the adapter **directly** into the GPU. No USB-C DisplayPort, no HDMI converters.
4. Power the adapter, power the headset.
5. Bluetooth for Sense controllers (compatible USB adapter if the board has none).
6. Finish setup in the PSVR2 App (firmware lives there — keep it installed).

Sony docs: [set up](https://www.playstation.com/en-us/support/hardware/pc-ps-vr2-set-up/), [prepare](https://www.playstation.com/en-us/support/hardware/pc-prepare-ps-vr2/), [troubleshoot](https://www.playstation.com/en-us/support/hardware/pc-ps-vr2-troubleshoot/).

### ALVR others (Tier C)

Quest, Pico, Vive Focus, YVR, PhoneVR, experimental Android/Monado. SteamVR on a Windows or Linux PC. Sideload some clients with SideQuest. Match streamer and headset versions from [GitHub releases](https://github.com/alvr-org/ALVR/releases).

### Apple Vision Pro (Tier C)

ALVR App Store client exists. **macOS cannot host the ALVR streamer** — pair with a Windows (or Linux) PC on the same LAN. Safari WebXR is a limited fallback.

### Smartphone Cardboard (Tier C)

Open Sit in the phone browser, tap Enter in VR, drop the phone in a viewer. Lowest fidelity. No SteamVR.

## Fix OpenXR

1. HTTPS or localhost (WebXR requires a secure context).
2. Chrome / Edge / Quest Browser.
3. Headset awake; Link, SteamVR, Pico Connect, or PSVR2 App running.
4. One active runtime. Windows: `%LOCALAPPDATA%\openxr\1\active_runtime.json`.
5. After switching runtimes, fully quit the browser.
6. SteamVR → Settings → OpenXR is the safe reset if Pico's `add_runtime.bat` stole the slot.

The in-app **Fix OpenXR** panel (`/rooms/vr` → OpenXR) runs this check, including a filesystem probe on the API host.

## Wi-Fi (Air Link, ALVR, Pico Connect)

- Same subnet. Guest networks and AP isolation break discovery.
- PC on Ethernet. Headset on 5 GHz or Wi-Fi 6/6E.
- Disable adapter power saving. Pause VPNs.
- If Air Link stutters, use a Link cable.

## What Heirloom will not do

- Ship `.exe` / `.msi` / `.apk` for Meta, Sony, Pico, or Steam.
- Link to cracked Virtual Desktop or “full version” ALVR zips.
- Drive vendor sites, solve captchas, or read keys off a screenshot.

Native OpenXR in the WinUI Room document is still deferred. Until then, **Enter in VR** is WebXR on top of the active OpenXR runtime.
