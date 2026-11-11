# Heirloom Unbound — big update

Screens for Setup, Home, Writing, and Code are in the WinUI studio (dock and Assist menu), stacked on the engines from #62. Assist chat can call the new tools. Twin chat cannot. Encrypted backups (`SHA256SUMS`, `MANIFEST`, split `.tar.gpg`, full set then incrementals) restore with a passphrase that is not stored. A plain folder still works.

The work sits on pull request **#62**, which sits on **#60**.

The work sits on pull request **#60** (`cursor/unbound-observer-prompt-cap-8cea`). That pull request is not merged here. Its brain fallback, observer prompt cap, assist-live failure handling, gpt-oss search rewrite, observer compact, companion poll recovery, and `/run/heirloom/observer` spool stay as they are.

Twin routing is unchanged. `model_router.py` and `llm_provider.py` are not edited. The BIGDEAL brain at `http://192.168.0.60:11434` (`gpt-oss:120b`, strategy `single+odysseus_research`), Odysseus at `http://odysseus:7000` with its token file, and the box model as fallback all stay. When BIGDEAL is missing or slow, the box model still answers. On the new Windows PC, that local machine is the box.

## What shipped

**Engines (#62).** Owner-only HTTP routes and `StudioPolicy`. Heirs get 404.

**Screens (this follow-up).** WinUI documents Setup, Home, Writing, and Code, on the dock and the Assist menu. Companion `Ctrl+Alt+H` opens an approval card and does not paste until you approve. Assist chat can call the studio tools. Twin chat cannot.

| Area | What you can call now |
|---|---|
| Setup Center | `POST /api/setup/checklist`, `GET /api/setup/guides`, `POST /api/setup/secrets`, `POST /api/setup/restore/inventory`, `/plan`, `/apply`, `/inspect`, `/encrypted` |
| Smart home | `POST /api/smart-home/discover`, `POST /api/smart-home/scan`, `POST /api/smart-home/act`, `GET /api/smart-home/home-assistant` |
| Writing | `POST /api/writing/check`, `/rewrite`, `/paste`, `GET /api/writing/lookup` |
| Code | `POST /api/code/open`, `/hunks`, `/command`, `/coder`, `/context` |
| Assist tools | `GET /api/assist/tools`, `POST /api/assist/draft`, `/research`, `/mcp` |

Heirs and callers get **404** on these routes, not a permission error that admits the route exists.

### Setup Center

Checklist with a live status for hardware, install size (Small / Medium / Large / Dedicated), hearing, local talking mind, local voice, companion pairing, start with Windows, backup, and optional smart home, writing, and accounts.

Guided pages open the exact site and say what to click, for things that are not hosted chat models:

- Hugging Face download token: `https://huggingface.co/settings/tokens`
- Home Assistant long-lived token: `http://homeassistant.local:8123/profile/security` (or the discovered host)
- Resend (drafts only): `https://resend.com/api-keys`
- Hue, Kasa, Tapo, Shelly, Wemo, Meross, ecobee, Nest, Honeywell, LIFX, Govee, WiZ
- Ollama download, NVIDIA driver, Windows Update, firewall, startup apps
- LanguageTool's **download** page, for a copy you run on this PC
- DNS is explained and skipped for a home Twin Box. There is no registrar to send the family to.

Paste-and-test stores a key masked (`••••` plus the last four characters). Logs get `[redacted]`. A Home Assistant token is accepted only for a loopback, `.local`, or private address. Hosted chat keys (OpenAI, Gemini, Anthropic, ElevenLabs, and the rest) are refused. See the owner decision below.

Repair returns the next human step (resume hearing, start Ollama, paste the device token again). It does not shell out to the live box.

### Restore from the Linux Twin Box

Read-only inventory of a backup folder. A copy onto a destination you name. The source is not deleted and is not modified. Existing files at the destination are left in place.

Recognized layout, either a raw `/var/lib/heirloom` tree or a packed folder:

- `vault`, `owner` (including `odysseus.token` and `owner.pass`), `observer`, `presence`, `lab`, `lab-reports`
- Mongo **dumps** under `backups` (`.archive`, `.bson`, or a name containing `mongo`). Raw WiredTiger files and Ollama weights are not copied.
- Odysseus app data in `odysseus/` or `odysseus-app/`
- `box.env` (treated as a secret: name and size only in the inventory)
- `git-preserve/` — the uncommitted hotfix from `~/Heirloomunbound`

`git-preserve` is copied to `review/git-preserve/` on the new PC. It is **not** applied to a git checkout.

Writes under `/var/lib/heirloom` are refused, including when someone marks the job as the new PC. A destination that is the running data root also waits until the caller says this is the new machine, and even then a Linux live root is refused.

Secret file contents are not loaded into the inventory JSON.

### Smart home

Local-first. Reads are free. A change waits for Confirm the first time. After that, a per-device always-allow may cover ordinary on/off (a lamp, a lamp plug).

Always-allow does **not** cover:

- Turning off a fridge, freezer, sump, oxygen, medical device, furnace, water heater, well pump, smoke or CO detector, or CPAP
- Switching a thermostat off

Heat is clamped to **60–74°F**. Cooling is clamped to **68–78°F**. A request outside that range is brought inside it and the receipt says so.

Command builders (tested with a fake network, not the house):

- Shelly Gen2 `Switch.Set` on the LAN
- Hue local bridge (press the button; the account site is optional)
- Kasa on/off datagram (local XOR protocol, port 9999)
- WiZ `setPilot` JSON for UDP port 38899
- Home Assistant `POST /api/services/...` with a bearer token that is stripped from the receipt

Discovery classifies mDNS and SSDP records for Hue, Shelly, Matter, HomeKit, LIFX, Wemo, Kasa, WiZ, and Home Assistant. It does not probe the network by itself yet. Matter control in this pass is "commission on the LAN, then use Home Assistant." Nest, ecobee, Honeywell, Tapo, Meross, and Govee have guided pages; the reliable control path for those is Home Assistant until a local API is added.

Public internet hosts are refused. Device commands do not carry vault text.

Action receipts use the existing Assist receipt shape (`smart_home_read`, `smart_home_set`). Twin turns still do not get a receipt, and Twin does not receive these tools.

### Writing assistant

Offline rules for spelling, grammar, style, tone, and clarity, with spans the UI can underline and one-click fixes. Rewrites: shorter, friendlier, more formal. No hosted model.

Dictionary and thesaurus: a small lexicon shipped in the app (definition, synonyms, antonyms). A missing word says so instead of calling the network. Known typos (`recieve`, `teh`, and the usual set) are corrected. A missing or extra letter is suggested only when one dictionary word matches, so ordinary words are not underlined.

LanguageTool is accepted only at `127.0.0.1` or `localhost`. The public LanguageTool site is refused.

The same checker is for chat, drafts, notes, and code comments. Snake_case in a code comment is left alone.

System-wide helper contract: chord `Ctrl+Alt+H`, a proposal card, paste-back only after approve. The hotkey is not registered in this pass (that is a Windows Companion step and must not open extra windows on its own).

Writing is for the owner's words. It does not rewrite the Twin's voice.

### Code workspace

Open a project folder and list files. `.env`, tokens, `node_modules`, and `.git` are skipped. `/var/lib/heirloom` and any folder named vault or observer cannot be opened as a project, so memories are not packed into a coder prompt.

Edits are hunks. Accept or reject each one. Nothing is written to disk by the engine; it returns the new text.

Commands wait for Confirm and are not executed here. `rm -rf /`, format, `shutdown`, `diskpart`, `mkfs`, and a recursive delete of a drive are blocked even if someone confirms.

Coder model: local Ollama only. Preference order is `qwen3-coder`, `qwen2.5-coder`, `deepseek-coder`, `codellama`, `starcoder`. `gpt-4`, Claude, and Gemini tags are ignored. `gpt-oss:120b` is left for the twin and is not picked as the coder. If no coder tag is installed, the answer is to pull one. The twin brain is not reused.

Cursor (CLI or SDK) is reported as optional and **off**. Nothing is installed.

### Assist tools

Owner Assist only. Twin, heirs, and the heir portal get an empty tool list.

Tools: read or change a device, draft a message, web research, code edit, run a command, check or rewrite writing, a local MCP connector, a background plan. Drafts have `sent: false`. There is no send function. Web research and any new Odysseus hop strip private memories and vault paths before the text could leave. Remote MCP URLs are refused. A connector on this PC, or on `127.0.0.1`, is allowed, and its arguments are redacted the same way.

The live chat loop in `twin_runtime.py` is not wired to these tools yet, on purpose, so PR #60's BIGDEAL fallback is untouched. The routes above are what Assist calls until that wiring lands.

### Windows policy

`desktop/Heirloom/Services/StudioPolicy.cs` is included in the WinUI project and in `Heirloom.Tests`. It masks secrets, refuses hosted-model key ids, refuses `/var/lib/heirloom`, clamps thermostats, requires a second confirm for critical off, gates paste-back, picks a local coder, and blocks destructive commands.

## What the owner does by hand

Do this **before** the Linux Twin Box is wiped. This pull request will not do it.

1. Copy `/var/lib/heirloom` onto a drive. Include `vault`, `owner` (`odysseus.token`, `owner.pass`, the rest), `observer`, `presence`, `lab`, `lab-reports`, `backups` (the Mongo dump), and `box.env`. You do not need the `ollama` weight folder. Those models can be pulled again.
2. Copy the uncommitted hotfix in `~/Heirloomunbound` into `git-preserve/` beside that backup (the backup set already keeps a `git-preserve/` tree; keep it).
3. Copy Odysseus app data into `odysseus/` if it does not already live under the Heirloom tree.
4. On the new Windows 11 PC, install with the existing four-size Setup (`HeirloomUnboundSetup.exe`). SmartScreen is still unsigned: More info, then Run anyway.
5. Open restore, point it at that backup, and confirm this is the new PC. Do not point the destination at `/var/lib/heirloom`.
6. Read `review/git-preserve` and decide what to keep. It will not apply itself.
7. Optional, for the Code page later: `ollama pull qwen2.5-coder:7b` (or a `qwen3-coder` tag).
8. Optional, for the house: put lights and plugs on the home Wi-Fi. If you already use Home Assistant, open its profile security page and paste a long-lived token into Setup. The token stays on that PC.
9. Do not create OpenAI, Gemini, Anthropic, or ElevenLabs keys for this update. The twin does not use them.

## Owner decision — hosted chat models

Not shipped, and not stored.

Assist and the Code workspace could, later, call a hosted model with an owner key, a monthly cap, and a default of off. That would be a separate choice. It would not go through `model_router.py` or `llm_provider.py`. The twin would stay on Ollama.

Until that decision, Setup will not open those key pages and will not accept those keys. ElevenLabs remains the existing optional voice path in Studio models. This update does not add a new voice-key flow.

## Phases still ahead

### 1. Setup Center window

WinUI document: checklist, one row per step, status, a Repair button, and a guided card that opens the URL and then the masked paste box. Reuse the four install sizes and the current first-run hearing / Ollama / picture downloads (they already resume). Add GPU name from the companion probe, a firewall note, and start-with-Windows using the existing autostart service. No new Windows service and no UAC prompt unless the owner clicks a button that already asks.

### 2. Make the PC quieter and faster

Do this without rewriting the PR #60 brain path.

- Time startup: WinUI cold start, companion poll, Ollama keep-alive (already 30 minutes on the box).
- VRAM: one warm twin model. Do not also load a coder model until Code is opened. Unload it after.
- Log noise: companion log already rolls. Drop repeated "not ready" lines.
- Dead code and stale packages: a named pass, not a drive-by. Do not touch `gpu-fan-curve`.
- Windows 11: private-network firewall allow, path length, and the NVIDIA driver page when the probe sees a card and no driver.

### 3. Assist that finishes the job

Wire the new tools into Assist only (never Twin). Show progress lines. Keep Confirm in the document for device changes, commands, and paste-back. Background plans stay local. Web research and Odysseus keep using the privacy fence. Owner-private memories are never in those payloads. Email stays a draft until a later approval that still does not send by surprise. The existing email connector remains the only sender, and only after the approval card it already uses.

### 4. Code window

Monaco in a studio document: file tree, syntax highlight, chat beside it, hunks with accept and reject, a terminal that runs only confirmed commands, git status and commit. Agent mode uses `plan_agent`: read, propose hunks, run tests after confirm, report.

Why these pieces, and not a whole second product:

- **Monaco** is the editor. It is the same editing surface people already know, and it embeds.
- **Our hunk model** is the review step. Aider and OpenHands are good programs and bad guests: they bring their own agent loop, their own cloud defaults, and a second approval style.
- **Continue** is the closest IDE plugin and is still an IDE plugin. Heirloom needs one window for a family PC.
- **Open Interpreter** runs code too freely for this PC.
- **Cursor CLI / SDK** stays optional, off, and only if the owner already has an account. Heirloom does not log in for them.

Default coder tag: `qwen2.5-coder` or `qwen3-coder` via Ollama. No hosted coder.

### 5. Smart home, live

- mDNS and SSDP scan on the home LAN, plus a manual address when a device stays quiet.
- Matter commission through Home Assistant (already the bridge). A direct Matter controller only if the HA path is not enough.
- More local transports where the protocol is documented and testable: LIFX UDP, Tapo local, Shelly Gen1.
- Nest, ecobee, and Honeywell stay on the guided page plus Home Assistant. Do not store those cloud passwords.
- Persist always-allow next to the rest of the owner settings. Critical-off never becomes always-allow.
- Receipts on the Assist document.

### 6. Writing, in the windows

Underline the spans in chat, drafts, notes, and code comments. Hover or right-click for the lexicon. A lookup field and `Ctrl+Alt+H` in the Companion: rewrite the selection, show the card, paste only after approve. Grow the lexicon from a WordNet or Wiktionary dump that we can ship offline, still with no call to a public dictionary. LanguageTool only on loopback.

### 7. Polish

The studio shell is already the Adobe-style frame (menubar, dock, document window). The new documents should use that frame: large hit targets, short labels, one primary button per step, plain sentences. No badges, no streak counts, no extra modal for Confirm. Family members who are not programmers should be able to finish Setup, turn on a lamp, and check a paragraph without learning a vendor name.

## Building blocks left where they are

| Piece | Decision |
|---|---|
| Twin brain | Untouched. Local Ollama, BIGDEAL then box model. |
| Four-size Setup.exe | Untouched. Inno Setup still cannot be compiled from Linux. |
| First-run hearing / Ollama / picture | Untouched. Setup Center wraps them. |
| Assist vs Twin | Assist may be broadly useful. Twin stays first person, vault-grounded, no PC tools, no smart-home writes, no coder, no grammar rewrite of its voice. |
| Action receipts | Extended with labels. Twin still omits them. |
| Standing routines and Memory Studio | Unchanged. Heirs still do not get them. |
| gpu-fan-curve | Not touched. |

## Tests

- `backend/tests/test_setup_center.py` — guides, masked keys, restore copy, live-box refusal, git-preserve not applied
- `backend/tests/test_smart_home.py` — temperature clamp, critical off, LAN refusal, Shelly / Hue / Kasa / WiZ / Home Assistant builders, discovery
- `backend/tests/test_writing_assistant.py` — spelling, grammar, rewrites, lexicon, loopback-only LanguageTool, paste approval
- `backend/tests/test_code_and_assist.py` — local coder, vault refused, hunks, blocked commands, heir and twin tool fence, private text stripped
- `desktop/Heirloom.Tests/StudioPolicyTests.cs` — the same safety rules on the Windows side
- Existing receipt, owner-rail, brain-route, Odysseus, and llm-provider tests were run and still pass. The full `Heirloom.Tests` project passed (204 tests).
