# Assist tools (`PcToolkit.RunAsync`)

Confirm in-document before: `shell`, `type_text`, `power` sleep/shutdown/restart, and `browse` click/type that buys, pays, deletes, or types a password.

| Tool | Job |
|---|---|
| `browse` | Open/search in the owner's default browser (YouTube, Gmail, Google). `goto` / `click` / `type` / `scroll` / `snapshot` / `close` use a separate Heirloom Edge window (not the everyday signed-in profile). |
| `open_url` / `open_app` | Launch site or app |
| `set_volume` | Heirloom WASAPI session 0–100 |
| `media` | playpause / next / previous / mute |
| `clipboard_get` / `clipboard_set` | Clipboard |
| `type_text` | Unicode into foreground window |
| `find_file` | Desktop, Documents, Downloads, vault (20 hits) |
| `list_dir` / `read_file` | Profile or vault only, 120KB cap |
| `write_note` / `search_vault` | Local vault |
| `shell` | cmd, 20s, stdout |
| `power` | lock / sleep / shutdown / restart |
| `screenshot` | JPEG + optional Ollama vision |
| `system_status` | Machine, Whisper, Ollama, optional nvidia-smi |
| `windows` | Visible titles |
| `fetch_url` | HTTP(S) text extract |
| `run_skill` | Vault webhook by name/trigger |

`CommandPoller` maps companion kinds onto this toolkit, including `browse`. Screenshot still uploads via poller. Heir mode denies PC and screen.

Simple “open a browser and go to YouTube / Search YouTube for … / Open Google and search for … / go to github.com / open a new tab and go to …” must not wait on a local model — Assist parses them directly and names each step (Opening browser…, Navigating…, Done). Twin (owner, Use this PC on) may open a URL the same way; clicks stay Assist. Heirs inherit Twin, not the copilot.

**Video studio** (dock id `avatar`, window title Video studio) is not a PcToolkit tool. Assist / Twin phrases `open video studio`, `make a video of that`, `make a video saying …` open the Film pane. Talking likeness is LatentSync 1.6 + cloned voice. Photographs hold when Wan/LTX/Hunyuan are not on disk. MiniMax Hailuo is not local. Heirs cannot make a new film.
