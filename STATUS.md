# Heirloom Assist / Twin — living status

Last inspected: 20 Aug 2026, 05:40 local.

**Rule:** nothing is complete until it is checked in the running WinUI studio. A green `dotnet test` / publish is evidence, not done.

**Bar:** a Twin the creator would trust their children with as a true representation of themselves. Fluent is not filed.

## Live studio (this machine)

| Fact | Value |
|---|---|
| Process | **none** launched by this agent |
| Published bits | `desktop\dist\Heirloom-ready\Heirloom.exe` — Video studio **this pass** (do not use a locked `desktop\dist\Heirloom\Heirloom.exe`) |
| Tests | `desktop/Heirloom.Tests` Release: **98 passed** |
| Build | Release win-x64, **0 C# errors** (3 pre-existing PRI qualifier warnings) |

## Video studio (this pass)

Dock id stays `avatar` (Twin landmark). Window title is **Video studio**.

- Film presets: Message to my kids, Tell a life story, Answer this question on video, Memory video, Greeting, Scene from a picture
- Talking likeness: LatentSync 1.6 + cloned voice (sitting preferred). Ask still speaks in Mixer and does **not** re-lipsync each Twin answer
- Photographs: living still + voice when Wan / LTX / Hunyuan are not on disk. MiniMax Hailuo is named as not local
- Twin / Assist: `open video studio`, `make a video of that`, `make a video saying …` — in-document, not a toast. Heirs cannot make a new film
- Export: save-as mp4. No Explorer unless the owner picks the dialog

**Not complete until a sitting** on `desktop\dist\Heirloom-ready\Heirloom.exe`: open Video studio; Make film on Greeting; Export; Twin “make a video of that” after a real answer; heir cannot generate.

## Browser jobs (prior pass)

Assist parses these **without a local model** and names each step (`Opening browser…` → `Navigating to YouTube…` / `Searching Google for “…”…` → `Done — YouTube is open.`):

- Open a browser and go to YouTube
- Search YouTube for [query]
- Open Google and search for [query]
- Go to [website] (YouTube, github.com, Reddit, …)
- Open a new tab and go to YouTube
- Open YouTube and search for [query]
- Click / type / fill / scroll / go back / reload (Heirloom Edge window, not the everyday signed-in profile)

Usual-browser open for simple go/search (logged-in Gmail/YouTube). Playwright only when the job needs a click, type, or in-page navigation. Failures stay human (`Use this PC is off…`, `Could not open YouTube…`). “search for tax PDF” still finds files. “open notepad” / “open chrome” stay apps. Twin (owner, Use this PC) may open a URL as Did — not a filed memory and not a click-driver. Heirs cannot.

**Not complete until a sitting** on `desktop\dist\Heirloom-ready\Heirloom.exe` (quit the locked live process first): the six phrases above; notepad still not Google; PC control off named; Twin owner open YouTube does not invent a memory; heir cannot open.

## Grandmother-proof setup (prior pass)

Old overlay: four jargon steps (role, disk SKU, backend URL / tokens, vendor email) then a vendor coach. Whisper was never downloaded. Ollama was “install it yourself.”

New overlay: one **Get everything ready** button. Checklist of named facts (stories folder, hearing, talking mind, talking picture). Auto vault in Documents. No tokens, no model picker. Lands on Twin. Copied-voice guide is Settings-only.

**Not complete until a sitting** on the published exe: fresh `setup_complete` false, one click, human failures, Twin next steps.

## Master roadmap (hand-downable Twin)

Ranked by damage to authenticity and family trust. Execute in this order; do not skip to lipsync theater.

| # | Work | Why it matters | State |
|---|---|---|---|
| 0 | PTT actually holds | If voice capture dies on press, the archive never gets their voice | prior pass — code |
| 1 | Tight retrieve | Weak rows in PASSAGES make the Twin invent in first person | prior pass — code |
| 2 | Avatar studio honesty | One LatentSync take is a likeness, not a mouth for every Ask | prior pass — code |
| 3 | Identity chapters | Humor, speech, regrets, joys, family instructions were missing | prior pass — code |
| 4 | Export includes facts | A family copy that drops the fact index is not a gift | prior pass — code |
| 5 | Sit the running exe | PTT hold, Twin miss, Avatar generate | **open until sitting** |
| 6 | Grandmother-proof setup | If she cannot finish install, there is no Twin to sit | **this pass — code** |
| 7 | AI biographer follow-ups | Interviewer still does not branch from what was already filed | next |
| 8 | Per-answer lipsync | Only when the engine is local and the line is the one being spoken | next |
| 9 | Sealed letters + heir audit | Triggers, tokens, a log of what the Twin said to a child | next |
| 10 | Neural embeddings | tf-token-v1 is a boost, not a memory | later |

Do not rip out TwinPack, Ask-does-not-file, File this sitting, heir write-lock, or FTS retrieve.

## Highest impact (user sitting at the PC)

| # | Issue | User-facing failure | Code | Live sitting |
|---|---|---|---|---|
| 1 | Close X hides the window; restore was tray right-click only | Studio “quit” and never comes back | Left/double-click tray shows. Attach fail → close exits. | **open** |
| 2 | Assist job had no in-document working / error / empty / stop | Status caption only | Now line, Did, Confirm / Do not run / Stop in the document | **open** |
| 3 | Ollama probe shared a 10-minute HttpClient | “Thinking…” could stall | Probe 3s, generate 50s | **open** |
| 4 | Cloud / API errors were `null` | Offline read as “quiet” | `LastFailure` named | **open** |
| 5 | PTT ended on press / last WASAPI buffer dropped | Hold-to-talk captured nothing | CaptureLost ignored while pressed; wait for RecordingStopped; one EndHold; silent mic named | **open** |
| 6 | Twin retrieve fell back to last 400 rows; embed promoted unmatched speech | Generic / invented first person | No recent fallback; embed cannot promote unmatched; facts must match the question | **open** |
| 7 | Twin Ask auto-filed speech | Sitting talk treated as filed life | Ask does not file. **File this sitting** is explicit | **open** |
| 8 | Heir could rewrite the gift | Infer / file / abilities | Heir: vault write-locked, Grounded only | **open** |
| 9 | Cloud Twin ignored local vault pack | Fallback answered Mongo | `twin_pack` on chat | **open** |
| 10 | Setup was a token/key wizard; models were not actually fetched | Grandmother cannot finish alone | One Get everything ready; Whisper download; Ollama helper; Twin landing | **open** |

## What a live sitting must prove

1. Hold to talk: press, the gold bar moves, release, transcript appears. A click that steals capture must not stop the hold while the finger is down.
2. Silent mic or missing Whisper is named in the document.
3. Twin: old interview still cited (`kind#id`). Unfiled question → “I don't remember” and captures do not grow.
4. Twin Ask does not file. File this sitting does.
5. Avatar: Add photos / File sitting / Make live version names engine or writes generated.mp4. Twin well does not mouth a different line.
6. Export vault JSON contains `facts`.
7. Close X hides; left-click tray restores.
8. Getting started: one gold button, no tokens. After it finishes, Twin — not Assist, not the vendor coach.
9. Assist `open notepad` / `open visual studio code` without a Google search.
10. Assist `Open a browser and go to YouTube`, `Search YouTube for …`, `Open Google and search for …`, `Go to github.com`, `Open a new tab and go to YouTube` open the usual browser with Opening / Navigating / Done lines. `search for tax PDF` still finds files.

## Chrome / sitting UI

Second design pass (19 Aug 22:58) plus fidelity pass plus grandmother setup: Mixer/Settings overlines; gold is Ask / armed PTT / active window / Get everything ready; Twin likeness has no Movies transport; Avatar Stop; Interviewer has 13 chapters; first-run is one consumer button.

**Still open until a sitting on the published exe.**

## Not in this pass

- Twin click-driver / heirs driving the PC
- Cloud vector database / fine-tune
- Live lipsync on every Ask
- Toasts as the main status channel
- Killing or launching `Heirloom.exe` from this agent

## How an item moves to complete

1. Change is in `desktop\dist\Heirloom` (or Heirloom-ready if the live exe is locked).
2. That build is the running process.
3. The specific sitting above was done on that process.
