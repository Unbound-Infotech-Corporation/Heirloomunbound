# Owner rail

Make Assist and Twin feel like a pairing teammate for the **owner** — decide sensible defaults, do the work, close the loop with a short result — without collapsing Assist vs Twin, and without giving heirs PC tools or a productivity posture.

This document is the roadmap. **Slice 2** (prefs + prompts) shipped first. **Slice 1** is the owner teammate chat (this pass). Slices 3 and 4 remain follow-on rails.

## Goal

Owner sessions should feel like sitting with someone who already knows how you work:

1. Decide a sensible default.
2. Do the job (or wait in-document when Confirm is required).
3. Report what happened in one to three sentences.

Heir and released sessions stay a **gift voice**. They do not inherit pairing style, act-by-default, or PC abilities.

## Assist vs Twin

| | Assist | Twin |
|---|---|---|
| Who it is | Copilot on this PC. Works **for** the owner. Never first-person as them. | Grounded first-person from the vault. A continuation of a filed life. |
| Gold verb | **Do** | **Ask** |
| Tools | May use `pc_control`, `screen_vision`, `terminal`, plus archive / reminder tools. | Archive, remind, capture. **No** `pc_control` / `screen_vision` / `terminal`. |
| Confirm | Destructive / paid / password / power / shell waits **in-document**. No MessageBox. | Does not invent PC actions. If the owner needs the computer, say so plainly so Assist can Do. |
| Owner sitting | Pair like a teammate. Prefer tools. Close the loop. | Be useful in their voice: capture, remind, search the archive, close loops. Never invent biography. |
| Heir / released | Not offered. Heirs inherit Twin, not the copilot. | Existing gift voice. No pairing / productivity block. No file, invent, or PC actions. |

Do not invent PC actions in Twin prompts. Do not speak as the owner from Assist.

The owner **Sit** surface is one composer. It does not collapse the products: each turn is classified to Assist, Twin, or both. Quiet chips (`Do` / `As you` / `Do + As you`) show which leg ran. Heirs never see Sit / owner mode.

## Usefulness gaps (why this rail exists)

Today the split is correct and still easy to feel unfinished:

- Assist can wait for menus instead of deciding a default and doing the job.
- Twin (owner) can stay a museum of the archive instead of a useful sitting (capture, remind, search, close).
- There is no persisted “how we work” for the owner, so every turn re-asks posture.
- Heir portal must never pick up owner pairing text if we add it.

Slice 2 bakes the posture into prefs + prompts. Slice 1 makes one owner chat that routes without a mode picker.

## Slices

### Slice 1 — Owner rails (one teammate chat)

**This pass.** Heuristic v1 (keyword / intent). Optional cheap LLM later.

| Surface | Status |
|---|---|
| Classifier `classify_owner_turn` → `assist` \| `twin` \| `both` | Done |
| `POST /api/desktop/chat` `mode=owner` | Done |
| `GET/POST /api/owner/conversation` + `/api/owner/chat` (session auth) | Done |
| Response `rail` / `rail_chip` / `rail_legs` | Done (`Do` / `As you` / `Do + As you`) |
| Web `/owner` — one composer + quiet chip | Done. `/twin` stays Twin-only. |
| Both-leg order | Twin / memory first, then Assist. One persisted receipt. |
| Heir fence | `resolve_chat_mode` forces twin when `audience` is heir/caller or `heir_surface`. Portal never calls owner rail. |
| PC tools | `tools_for_turn` / `tools_for_owner_leg` — only the Assist leg. |
| WinUI Owner document | **Follow-up.** Assist + Twin docks stay. Glossary has Sit. Native document would be a second chrome pass. |

Heuristics (v1):

- **Do / Assist** — open/launch a named app or the browser, screen, volume, sleep/shutdown/restart, find file, clipboard, terminal/command, type/click, “on this PC”.
- **As you / Twin** — remember/recall (not “remember to &lt;do&gt;” alone), file/capture, what did I, remind me, growing up / family / archive.
- **Both** — both signals, or “remember to &lt;do&gt;”.
- Unclear → Twin (safer; no PC tools).
- “Open up about …” is Ask, not Do.

### Slice 2 — How we work (prefs + prompts)

**Shipped.**

Owner prefs on the existing user document (`GET /api/auth/me`, `PUT /api/auth/me/preferences`):

| Pref | Values | Default |
|---|---|---|
| `pairing_style` | `teammate` \| `wait` \| `proactive` | `teammate` |
| `act_default` | bool | `true` |
| `close_loop` | bool | `true` |
| `remember_prefs` | bool | `true` |

Prompt deltas:

- **Assist** (`build_assistant_system`): pair like a teammate; decide defaults; do the job; report in 1–3 sentences; don’t dump menus; if Confirm is needed, say what you’ll do and wait in-document; prefer tools; never speak as the owner.
- **Twin** (`build_twin_system` / `compile_twin_prompt`): `audience=owner` — useful in their voice; if they need the computer, say so so Assist can Do; never invent biography. `audience=heir` (and caller) — keep the gift voice; no pairing productivity block.

Audience is threaded through desktop and web twin chat so the heir portal cannot receive owner pairing instructions.

WinUI Settings **How we work** is deferred if the XAML surface is crowded; web Settings exposes the prefs. Local Assist planner copy still encodes the default teammate / act / close-loop posture.

### Memory Studio v1 (web)

**Shipped on web.** Owner-only page at `/memory` (Memory Studio) consolidates what the Twin holds — no invented biography, no second store:

| Section | Source |
|---|---|
| What I hold onto | `GET/DELETE /api/memory/facts` — removable identity facts with provenance (`kind`, `source_entry_id`) |
| How we work | `GET /api/auth/me` + `PUT /api/auth/me/preferences` — same pairing prefs as Settings |
| Safe topics | same preferences API — fence still applies to heir chats |

Nav from Sit, Twin, Settings, Portrait, and the studio dock. Heirs never see this page: `/heir/:token` stays outside `AppLayout`, and the portal does not call `/memory/facts` or owner preferences.

WinUI Memory document is **deferred** (same as Settings → How we work). Assist vs Twin split is unchanged.

### Slice 3 — Close-loop surfaces

Not in this pass.

Visible result of the last Do / Ask: last-did strip, Confirm-in-document polish. No dumped menus. Assist still confirms destructive tools in the document. Slice 1 chips are the first quiet receipt.

### Slice 4 — Memory of work + heir fence audit

Not in this pass.

Remember working style across owner sessions when `remember_prefs` is on. Audit every heir / released / caller path so pairing text and PC tools cannot leak. Heir portal stays gift voice.

## Acceptance criteria

- [x] Owner prefs live on the existing user / preferences API (no second store).
- [x] Assist system prompt encodes act / close-loop teammate behavior.
- [x] Owner Twin prompt includes pairing usefulness; heir / caller Twin does not.
- [x] Heir portal compiles with `audience=heir` and cannot receive owner pairing text.
- [x] Assist vs Twin roles are unchanged (no PC tools on Twin; Assist never first-person as the owner).
- [x] Confirm-in-document for destructive Assist tools is unchanged.
- [x] Slice 1 owner Sit (web + `mode=owner`) with heuristic routing and chips.
- [x] Heir / caller cannot enter `mode=owner`; PC tools only on the Assist leg.
- [ ] Slice 1 WinUI Owner document — deferred (Assist + Twin docks remain).
- [ ] Slice 3 close-loop strip beyond chips — deferred.
- [ ] Slice 4 cross-session memory + full heir-fence audit pass — deferred.
- [ ] WinUI Settings → How we work — deferred (web Settings ships in Slice 2).
- [x] Memory Studio v1 on web (`/memory`) — facts, pairing, fence; heirs excluded.
- [ ] WinUI Memory Studio document — deferred (web `/memory` is the owner edit surface).

## Ship order

1. **Slice 2** — prefs + prompts (shipped).
2. **Slice 1** — owner Sit so one composer routes Do vs Ask (this pass).
3. **Slice 3** — close-loop surfaces so a Do leaves a visible result.
4. **Slice 4** — remember + heir-fence audit once the prompts have settled.

Do not give heirs owner mode, pairing productivity, or PC tools.
