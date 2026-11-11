# Engineering assessment

Date: 2026-11-11. Branch audited: `cursor/heirloom-studio-screens-83bd` (pull request #64), which includes #62 and #60. `main` is `dd34d9c`. This document answers the owner's ten questions from the code and from commands that ran in this Linux VM. It does not claim that WinUI, the installer, or a real GPU sitting works.

The breakdown in the owner's packet is mostly right about product shape and wrong in a few counts. `MainPage.xaml` is 2,916 lines, not about 2,800. `backend/routers/companion.py` is 2,111 lines. `backend/twin_runtime.py` is 1,282 lines. There are 56 Python files under `backend/routers/` and 268 Python files under `backend/`. FastAPI still reports version `0.3.0`. The desktop and the health payload still say `0.5.1`. There is no `tf-token-v1` string in Python. It lives in `desktop/Heirloom/Services/TwinCore.cs` as `Model = "tf-token-v1"`, and `STATUS.md` calls it a boost, not a memory.

## 1. What genuinely works

These ran and passed in this VM on 2026-11-11:

```text
cd backend
python -m pytest tests/test_setup_center.py tests/test_smart_home.py \
  tests/test_writing_assistant.py tests/test_code_and_assist.py \
  tests/test_backup_gpg.py tests/test_assist_receipt.py \
  tests/test_owner_rail.py tests/test_brain_route.py \
  tests/test_llm_provider.py tests/test_odysseus_client.py -q
```

Result: **85 passed, 2 skipped**.

```text
dotnet test desktop/Heirloom.Tests/Heirloom.Tests.csproj -c Release
```

Result: **208 passed, 0 failed**. The test project is `net8.0`. It compiles plain C# (BoxCore plus linked service files). It does **not** compile or launch the WinUI app.

What those tests actually cover:

- Twin vs Assist split in the owner-rail pure functions, and receipts omitted for Twin. Two tests in `test_owner_rail.py` skipped: desktop `ChatReq` needs `MONGO_URL`, and `twin_runtime` needs `emergentintegrations`. The heir-refusal tests that do not import those modules passed.
- Local provider selection in `llm_provider.py`: box mode refuses a cloud model and provider (`test_box_mode_uses_no_cloud_model_or_provider`). Odysseus URL checks. BIGDEAL fallback behavior covered by `test_brain_route.py`. `tests/test_model_router.py` was not part of this run.
- Setup checklist, guided pages, masked secrets, and a restore that refuses `/var/lib/heirloom`.
- A synthetic GPG backup: checksums, a wrong passphrase, and an incremental overlay. This is **not** the owner's real `twinbox-*.tar.gpg` files.
- Smart-home safety (temperature clamp, critical off, public hosts including a public IPv6, Home Assistant port), SSDP **parsing** with a fake socket. No live LAN scan ran.
- Writing rules, including `your welcome`, and short-fact redaction (`Mom` does not rewrite `Mombasa`).
- Code hunks applied at the reviewed line. Assist tools stay off Twin. Device changes from the model always wait for Confirm.

Also true from reading code, and consistent with those tests: connector mailbox passwords use Fernet (`backend/connector_secrets.py`) with `CONNECTOR_SECRET_KEY`. The device token path on Windows is written to go through `PasswordVault` in `CredentialStore.cs`. That WinRT call was not executed here.

## 2. What is implemented but unverified

Anything with a Windows window, a GPU, a microphone, a phone network, or the public website. In particular:

- The WinUI studio (`desktop/Heirloom/Heirloom.csproj`, `net8.0-windows10.0.26100.0`) was **not built**. Setup, Home, Writing, and Code XAML in #64 were not opened.
- `Heirloom.Companion` (WPF) was not built. `Ctrl+Alt+H` was not pressed. The copy-chord order is unit-tested. The key injection is not.
- Inno Setup (`HeirloomUnboundSetup.exe`) cannot be compiled on this VM.
- Live SSDP, Hue, Kasa, Shelly, WiZ, and Home Assistant were not contacted.
- The owner's real backup set on `D:\TwinBackup` and in Google Drive was not opened.
- Observer, Presence, Retell, Stripe, the Emergent site, and a real Ollama/`gpt-oss:120b` turn were not run.
- Layout PNGs attached to #64 are HTML renders, not `Heirloom.exe`.

`tf-token-v1` retrieval in `TwinCore.cs` was not executed. Neural embeddings are not in the product path.

## 3. What is architecturally weak

- Two deployment modes do different things with the same product. `HEIRLOOM_BOX=1` refuses cloud models. The website path still constructs Claude through `EMERGENT_LLM_KEY` in `twin_runtime.py` and `routers/twin.py`. A buyer on the website is not on the box.
- Two Windows clients remain: WinUI and the PySide6 tree under `backend/companion_desktop/`.
- Model choice for the Twin is in `model_router.py`. Assist coder choice is a separate function in `code_workspace.py`. Draft #51 adds a third router. They can drift.
- Assist tool policy is duplicated in Python (`assist_studio_tools.py`, `smart_home.py`) and C# (`StudioPolicy.cs`, `StudioScreens.cs`).
- `MainPage.xaml` (2,916 lines) still inlines almost every document. New windows in #64 are user controls, which is the right direction, and the page is still the shell.
- Retrieval is token overlap (`tf-token-v1`) plus archive text, not embeddings. That is a product limit, not a bug in the tests.
- The Linux box (systemd, Docker, Caddy, `heirloom-box`) and the Windows studio are not one runtime. #62/#64 restore a backup onto Windows. They do not replace observer, presence, or Caddy with Windows services.

## 4. What to consolidate

One source of truth, in this order, without a rewrite:

1. Twin routing stays `model_router.py` and `llm_provider.py`. Do not add a second twin router.
2. Assist permissions stay `tools_for_turn` plus `exec_studio_tool`. C# checks should call the same rules or be generated from them. Do not let the model pass `approved`.
3. BYO keys should use one seal (the milestone after this document), not a new store per vendor.
4. Keep WinUI as the Windows client. Do not grow PySide6.
5. Do not start a second memory database. Extend the vault and the heir query fence.

## 5. What is missing

Relative to the owner's directive, not relative to a competitor list:

- An evolving owner model for Assist (projects, recurring problems, preferences) that is not the Twin's biography and is not sent to heirs.
- Independent "build an app" work with an isolated workspace, tests, and a reviewable result.
- A capability registry so a new local model or tool is declared, not hard-wired into a rebuild.
- Verified Windows build and a sitting.
- Encrypted BYO API keys (plaintext today: `elevenlabs_api_key`, `d_id_api_key`, `fal_api_key`).
- Embeddings, a people index, and contradiction handling. Labeled as later in `STATUS.md`.
- A visible local-vs-cloud indicator on every surface.
- Heir audit log. Not found as a shipped owner view.
- Windows services for a Twin Box that is no longer Linux.

## 6. The biggest intelligence gain

Make retrieval and the "I don't remember" rule better before adding more Assist surfaces. A Twin that files less and recalls more accurately is the product. The next technical step inside that is local embeddings beside the existing full-text path, still behind the heir query fence, still local. That is larger than another window.

The biggest Assist gain that does not dilute the Twin is the owner's first addition: a separate, evolving model of how the owner works (projects, past fixes, preferences), used only by Assist.

## 7. What to do first

1. This assessment and the roadmap (this pull request). No product behavior change.
2. Encrypt the plaintext BYO keys and add `scripts/verify-windows.ps1` for the owner to run. Do not claim the script passed.
3. Owner runs that script on Windows and reports the log.
4. Only then land or restack #60 → #62 → #64, after the owner says so. This assessment does not merge them.

## 8. Serious security, privacy, and reliability risks

- **Plaintext BYO keys** in the user document: ElevenLabs, D-ID, fal.ai. `connector_secrets.py` says this in its own module docstring. OpenAI and Resend appear in the support-ticket redaction list. They are not saved as per-user fields in `routers/user_keys.py`.
- **Public live stream.** `backend/routers/live.py` states that `/twin/live/<handle>` has no auth. Anyone with the handle can watch. That is an impersonation surface.
- **Cloud path sends owner text to Anthropic** when `HEIRLOOM_BOX` is off. The box path refuses it. The website default is the cloud path.
- **Phone audio** goes through Retell when that line is enabled. Not re-tested here.
- **Observer and Presence** are lab features with screen, mic, and face embeddings. They are off unless installed. Heirs 404 on those routes in the code that was read. Not run here.
- **Restore** can copy a vault onto a destination the owner names. It refuses `/var/lib/heirloom` and, when `HEIRLOOM_BOX` is set, asks before writing into `HEIRLOOM_DATA_ROOT`. A wrong destination folder on a new PC would still receive files. The passphrase is not stored. The owner's real archives were not opened.
- **Short secrets.** Whole-word redaction is tested for `Mom` vs `Mombasa`. A fact that is also a normal word is still removed when it stands alone. That is intentional and can over-redact a query that uses the word for real.
- **Unsigned installer.** Documented in `desktop/installer/README.md`. Not rebuilt here.

## 9. What is realistic on the current hardware

The owner described two machines: BIGDEAL with an RTX PRO 6000 Blackwell 96 GB, and a Twin Box with an RTX 3090 24 GB and 32 GB RAM. This VM has neither. From the repo, not from a GPU run:

- The 3090 path in `box/README.md` is `qwen2.5:14b` plus `qwen2.5vl:7b`, not a 32B or 72B chat model, because vision has to fit.
- BIGDEAL is documented as `gpt-oss:120b` with `keep_alive` 30 minutes (#60). A missing BIGDEAL falls back to the box model. That fallback is covered by unit tests, not by a live 120B call in this VM.
- A coder model (`qwen2.5-coder` or `qwen3-coder`) should load only while Code is open. That unload policy is not implemented. Running it beside the twin on a 24 GB card is not realistic.
- Embeddings (`nomic-embed-text` or `bge`) fit on the 3090 beside the 14B only if one of the larger models is unloaded. That is an owner scheduling choice, not a measured result.

## 10. The best path to production quality

Prove the Windows app, encrypt the keys, then improve memory. Do not add a third client, a second twin router, or a cloud model inside `model_router.py`. Keep #60, #62, and #64 as the stack to land when the owner says so. Close nothing in this pass.

Production quality here means: a version that is not `0.5.1` everywhere, a Windows build the owner has run, keys that are not plaintext, a restore the owner has pointed at the real backup, and a Twin that still says it does not remember when the vault is empty. The outside plan's 0.6.0-beta bump is reasonable and was **not** done here, because a version bump touches every surface and should be its own change after the Windows script has been run.

## Architecture map

```text
Owner PC (BIGDEAL, Windows)                Twin Box (RTX 3090)
  WinUI studio  desktop/Heirloom             FastAPI  backend/server.py
  Companion tray  Heirloom.Companion         Mongo + local vault
  Ollama gpt-oss:120b (documented)           Ollama qwen2.5:14b fallback
        |  pinned HTTPS, poll                      ^
        +------------- companion audio/screen -----+
        |  LAN brain, Odysseus optional            |
        +------------------------------------------+

Website (Emergent, optional)
  React frontend, Stripe, Claude via EMERGENT_LLM_KEY
  Heir portal /heir/:token
  Public live /twin/live/<handle>

Twin identity: twin_runtime.py + model_router.py + llm_provider.py
  local only when HEIRLOOM_BOX=1
Assist identity: tools_for_turn role=assistant, exec_studio_tool
  heirs forced to twin; owner routes 404
Memory fence: memory_guard.py (query), owner_privacy.py (outbound redact)
Secrets today: Fernet for mailbox passwords; plaintext for BYO model-vendor keys
```

## Feature inventory

| Feature | Tag | Evidence |
|---|---|---|
| Box mode refuses a cloud model and provider | VERIFIED | `tests/test_llm_provider.py::test_box_mode_uses_no_cloud_model_or_provider` in the pytest command above. `tests/test_model_router.py` was not run |
| BIGDEAL URL and strategy parsing | VERIFIED | `tests/test_brain_route.py` in that same run |
| Odysseus URL rules, vault text not required for the client tests | VERIFIED | `tests/test_odysseus_client.py` in that same run |
| Owner rail and heir not offered Assist | VERIFIED for the pure functions | `tests/test_owner_rail.py` in that same run. Two tests in the file skipped (section 1) |
| Assist receipts, Twin omitted | VERIFIED | `tests/test_assist_receipt.py` |
| Setup checklist, masked key, live-root restore refusal | VERIFIED | `tests/test_setup_center.py` |
| Synthetic GPG full + incremental | VERIFIED | `tests/test_backup_gpg.py`. Real `D:\TwinBackup` archives not used |
| Smart-home clamp, critical off, IPv6, SSDP parse | VERIFIED | `tests/test_smart_home.py`. No packet left this VM |
| Writing rules and paste approval | VERIFIED | `tests/test_writing_assistant.py` |
| Hunk line placement, Assist tool fence, `Mom` vs `Mombasa` | VERIFIED | `tests/test_code_and_assist.py` |
| Plain C# policy and screen models | VERIFIED | `dotnet test` 208 passed. Not a WinUI build |
| WinUI windows, Monaco, hotkey injection, installer | UNVERIFIED | Code present. WinUI project not compiled |
| Live LAN devices, real GPU, mic, Retell, Stripe, website | UNVERIFIED | Not run |
| `tf-token-v1` retrieval quality | UNVERIFIED | Constant in `TwinCore.cs`. No retrieval test in the command above |
| Public live stream | UNVERIFIED as a running server | Code in `routers/live.py` says the watch half is unauthenticated. Not served here |
| Study Hall (#61) | UNVERIFIED | Separate PR. Not checked out. Not tested in this run |

## Security review

See section 8. The fence that is tested: heirs do not get Assist tools; private lines are stripped before research; `/var/lib/heirloom` is not a restore destination; mailbox passwords have a Fernet helper. The hole that is not fixed in this document: BYO API keys are plaintext. Fixing that is the next milestone, not this file.

## Tech debt

- Version `0.5.1` / API `0.3.0` while months of work sit on `main` and on the #60 stack.
- 20 open pull requests. Many target SHAs from July 2026 (`10298c4e`, `f6ae0d34`), which are not `main`.
- PySide6 fallback still in tree.
- Duplicate Assist policy in C# and Python.
- `MainPage.xaml` and `companion.py` are too large to change safely in one pass. Splitting them is justified and was **not** done here. A split of `companion.py` without a Windows run would be a guess.
- Rooms reconstruction is described in the breakdown as a mock. Not re-verified by running the web app.

## Open pull requests

Recommendations only. Nothing was closed or merged.

| PR | State | Recommendation |
|---|---|---|
| #60 Keep local turns in the context window | Open, base `main` | Keep. It is the base of the current stack. Land only when the owner says so. |
| #62 Setup, smart home, writing, code engines | Open, stacked on #60 | Keep. Do not retarget onto `main` by hand while #64 sits on it. |
| #64 Studio windows | Open, stacked on #62 | Keep. This assessment stacks on it. WinUI still unverified. |
| #61 Study Hall | Open, base `main` | Keep open and separate. It is a second app. Do not fold it into the twin router. Owner should decide whether panel keys for ChatGPT/Gemini are allowed. Not audited line by line in this pass. |
| #51 Assist model router | Draft, base is an October `main` | Supersede. #62/#64 already pick a local coder outside `model_router.py`. Do not merge #51 into twin routing. |
| #46 Autoinstall Bugbot fixes | Open, base October commit `4bde506` | Likely stale against today's `main`. Recommend the owner confirm the fixes are already on `main`, then close. Not closed here. |
| #1, #13 Cloud dev-environment docs | Drafts, July | Close as duplicates of each other and of current `AGENTS.md`. |
| #2, #3, #5, #6, #10, #11 | Drafts, July, base `10298c4e` | Close as superseded by `main`. Do not rebase them. |
| #7, #8, #9 | Drafts stacked on #6 | Close the stack with #6. Death-governance ideas can be rewritten later from `main` if the owner still wants them. |
| #12 Maestro / mobile / keyboard | Draft, base `conflict_150826_0017` | Do not merge. The base is a conflict branch. Mine for ideas only, then close. |
| #19, #20 Desktop 0.4 first-run | Drafts, August | Close. First-run on `main` and #64 has moved past 0.4.0. |

There is no open pull request #4, #14–#18, #21–#45, #47–#50, or #52–#59 in the open list returned on 2026-11-11.

## Build and test status

| Command | Result in this VM |
|---|---|
| pytest command in section 1 | 85 passed, 2 skipped |
| `dotnet test desktop/Heirloom.Tests/Heirloom.Tests.csproj -c Release` | 208 passed, 0 failed |
| `dotnet build desktop/Heirloom/Heirloom.csproj` | **Not run.** The project targets `net8.0-windows10.0.26100.0` and WinUI. This VM is Linux. |
| Inno Setup | **Not run.** |
| Companion WPF build | **Not run.** |

## Conflicts with the outside plans

Adopted where the repo agrees:

- Encrypt BYO keys. The code confirms they are plaintext. Next milestone.
- Do not put cloud keys into twin routing. Matches the owner's hard rule and the current `model_router.py`.
- A Windows smoke script the owner runs, because this VM cannot build WinUI. The outside note about a pre-release script on BIGDEAL is the right shape. The script is the next milestone, not a claim that it passed.
- Splitting `MainPage.xaml` and `companion.py` is real debt. It is **not** the first code change. A split without a Windows run can break the studio.
- `tf-token-v1` is real (`TwinCore.cs`). Embeddings are not in the product yet. The outside plan is right that this is the memory gap. It is phase 2 in the roadmap, after keys and a Windows build.
- Public `/twin/live/<handle>` is unauthenticated in `routers/live.py`. Hardening it is a product change (invite tokens). Listed as an owner decision because it changes who can watch.
- Version bump 0.5.1 → 0.6.0-beta is reasonable and **not done** in this pull request.

Rejected or not taken as fact:

- "About 860 Python tests" and "49 pages" were not counted by running the full pytest tree. Many tests need Mongo and `emergentintegrations`, which this VM does not have. Do not treat that count as verified.
- "Assist chat loop isn't wired" is **false on #64**. `twin_runtime.py` calls `execute_tool` with `role` and `private_texts`. Unit tests cover the fence. A live Claude tool-call was not run.
- Retiring PySide6 and closing PRs #1–#13 in the same change as a version bump is too wide. Recommendations are above. Nothing was closed.
- Pricing ($99–149, a subscription) is not in the owner's directive. The repo's own price was not re-verified against Stripe in this pass. Left as an owner decision.
- Nav change to hide Code, Home, and Writing is a product call. #64 just put them on the dock because the owner asked for those windows. Do not hide them in this pass.

### Owner decision: Twin Box OS

The outside review says keep the Twin Box on headless Linux and keep Windows as the studio client. The owner is planning to move that PC to Windows 11. Both are written down. This assessment does not choose. Restore onto Windows is implemented and unit-tested. The Linux box services are still the only box runtime in `box/`.
