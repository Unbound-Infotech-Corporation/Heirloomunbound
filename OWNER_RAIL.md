# Owner rail

Make Assist and Twin feel like a pairing teammate for the **owner** — decide sensible defaults, do the work, close the loop with a short result — without collapsing Assist vs Twin, and without giving heirs PC tools or a productivity posture.

This document is the roadmap. **Slice 2 is the only code shipped in the first pass** (prefs + prompt wiring). Slices 1, 3, and 4 are UI / follow-on rails.

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

## Usefulness gaps (why this rail exists)

Today the split is correct and still easy to feel unfinished:

- Assist can wait for menus instead of deciding a default and doing the job.
- Twin (owner) can stay a museum of the archive instead of a useful sitting (capture, remind, search, close).
- There is no persisted “how we work” for the owner, so every turn re-asks posture.
- Heir portal must never pick up owner pairing text if we add it.

Slice 2 bakes the posture into prefs + prompts. Later slices make the rails visible.

## Slices

### Slice 1 — Owner rails (UI chrome)

Not in this pass.

Dock / document chrome that makes **Assist = Do** and **Twin = Ask** obvious on the owner studio. Today pairing strip, gold verbs, and inspector copy. Must not collapse the two products or expose Assist to heirs.

### Slice 2 — How we work (prefs + prompts)

**This pass.**

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

### Slice 3 — Close-loop surfaces

Not in this pass.

Visible result of the last Do / Ask: short chips, last-did strip, Confirm-in-document polish. No dumped menus. Assist still confirms destructive tools in the document.

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
- [ ] Slice 1 UI rails (dock / Today strip) — deferred.
- [ ] Slice 3 close-loop chips — deferred.
- [ ] Slice 4 cross-session memory + full heir-fence audit pass — deferred.
- [ ] WinUI Settings → How we work — deferred (web Settings ships in Slice 2).

## Ship order

1. **Slice 2** — prefs + prompts (this document’s first code). Behavior changes even before chrome.
2. **Slice 1** — owner rails so the studio *looks* like the split it already is.
3. **Slice 3** — close-loop surfaces so a Do leaves a visible result.
4. **Slice 4** — remember + heir-fence audit once the prompts have settled.

Do not ship Slice 1/3/4 UI until Slice 2 is in and heir paths stay gift-only.
