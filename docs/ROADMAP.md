# Roadmap

Date: 2026-11-11. This is the prioritized list after `docs/ENGINEERING-ASSESSMENT.md`. Each item is one bounded change. Acceptance criteria say what must be true. "Verified" means a command ran in the VM that made the change, or a Windows log the owner pastes back. Do not mark a Windows item verified from Linux.

The stack to preserve is #60, then #62, then #64. This roadmap does not merge them.

## Now

### A1. Encrypt BYO API keys

**Why.** `elevenlabs_api_key`, `d_id_api_key`, and `fal_api_key` are plaintext user fields. Mailbox passwords are already Fernet. The owner asked for this as milestone 1.

**Work.** One helper. Fernet from `HEIRLOOM_BYO_KEY` in the environment, not in Mongo. Prefix sealed values so a migration can tell them from legacy plaintext. Encrypt existing plaintext in place. Readers decrypt. Writes refuse to store a new plaintext key when the env key is missing. Desktop stores the same secrets in Credential Locker (`PasswordVault`) when the Windows app saves them. Never log the key. Do not add these keys to `model_router.py` or `llm_provider.py`.

**Acceptance.**

- pytest shows a plaintext value becomes a sealed value, round-trips, and the plaintext is absent from the sealed string and from log lines.
- A second run of the migration does not double-encrypt.
- A missing `HEIRLOOM_BYO_KEY` does not wipe a stored key.
- `scripts/verify-windows.ps1` exists. The author says they did not run it.

### A2. Owner runs the Windows smoke script

**Why.** Nothing in A1 or in #64 proves the WinUI app builds.

**Work.** On the Windows PC, run `scripts/verify-windows.ps1`. Paste the summary back. Do not treat a Linux `dotnet test` as this step.

**Acceptance.** The script prints pass or fail for `dotnet build` of `desktop/Heirloom/Heirloom.csproj` and `dotnet test` of `desktop/Heirloom.Tests`. The owner, not an agent, is the witness.

## Next, still stabilization

### A3. Land the #60 stack only after A2

**Why.** #60 fixes real prompt-size failures. #62 and #64 add setup, home, writing, and code. They are unverified as a running WinUI app.

**Work.** After A2 is green, the owner decides whether to merge #60, then #62, then #64. Agents do not merge.

**Acceptance.** Each PR's CI is green on its own head. No file in `model_router.py` or `llm_provider.py` gains a hosted-LLM provider.

### A4. One version stamp

**Why.** API says `0.3.0`. Desktop and health say `0.5.1`.

**Work.** A single change that sets the user-facing version in `Heirloom.csproj`, the health payload, and the FastAPI app version. Do not rename the product.

**Acceptance.** One string is used in those three places. Existing tests that assert a feature flag still pass. No claim about the website until it is deployed.

### A5. Stale pull requests

**Why.** Twenty open PRs hide the product. The assessment lists which ones look superseded.

**Work.** The owner closes the July drafts and #12, #19, #20, and #46 if they agree. Agents do not close them.

**Acceptance.** The open list is the #60 stack, #61, and anything the owner explicitly keeps.

## Intelligence, after the above

### B1. Assist owner model (owner addition 1)

**Why.** Assist should remember projects, recurring problems, and how the owner likes to work, without becoming the Twin.

**Work.** A new owner-only store, separate from vault facts. Fields: project, problem, what worked, preference. Provenance is "owner said" or "Assist inferred," never a silent promotion to biography. Heir routes 404. The Twin prompt does not receive this store. Assist may read it. Outbound tools redact it the same way as vault lines.

**Acceptance.** pytest: an heir cannot read it; a Twin system prompt built for an heir or for the owner Twin does not contain a project note; an Assist turn can. A note marked inferred is not returned as a verified fact.

### B2. Capability registry (owner addition 3)

**Why.** New local models and tools should be declared, not patched into `MainPage.xaml` and `abilities.py` by hand.

**Work.** One registry file or module: id, kind (`model` or `tool`), local-only flag, permission (`read`, `confirm`, `critical`), and whether Twin may see it. Assist tools and coder tags register here. Twin routing does not. Loading a registry entry does not require a new installer.

**Acceptance.** A test registers a fake local tool and sees it on an Assist turn and not on a Twin turn. A hosted-LLM entry is rejected. No rebuild of WinUI is required for the Python registry test.

### B3. Independent build-an-app (owner addition 2)

**Why.** "Build an app that does X" needs a workspace that is not the vault and not the Heirloom repo.

**Work.** Assist creates a folder outside the vault and outside `/var/lib/heirloom`, writes files, proposes a test command, and runs it only after Confirm. The result is a reviewable diff or a folder listing plus the test output. No publish, no deploy, no cloud model.

**Acceptance.** pytest uses a temp directory. A command on the blocklist does not run. The vault is not a legal workspace. The test output is returned only after a simulated confirm.

### B4. Local embeddings beside tf-token-v1

**Why.** Retrieval quality is the Twin. `TwinCore.cs` still says `tf-token-v1`.

**Work.** Add an optional local embedding path (Ollama), keep the current scorer as fallback, and keep the heir query fence. Do not send vault text to a hosted embedder. Do not delete `tf-token-v1` until the new path is measured.

**Acceptance.** A unit test with a fake embedder ranks a filed sentence above an unrelated one, and returns a miss when nothing is close. Heir queries still exclude owner-private rows. No WinUI claim.

## Later

### C1. Visible local vs cloud

A single indicator, fed by `box_mode()` and whether a turn used a cloud provider. Off on the box. Honest on the website. Acceptance: a test of the indicator function, not a screenshot, until Windows or the site is run.

### C2. Live-stream invites

`routers/live.py` documents a public watch URL. Changing that is an owner decision because people may already use the handle.

### C3. Split MainPage and companion.py

After A2, move one document at a time out of `MainPage.xaml`. One router module at a time out of `companion.py`. Acceptance for each slice: the Windows script still passes, run by the owner.

### C4. Heir audit log

Owner-only list of what the Twin said to an heir. Heir cannot call it. Acceptance: pytest 404 for an heir and a row for an owner.

### C5. PySide6

Stop adding features there. Remove it only after the owner confirms no install still depends on the Emergent zip.

## Owner decisions this roadmap will not make

1. Twin Box stays Linux, or that PC becomes Windows 11. Restore exists either way. The service runtime does not.
2. Whether hosted models are ever allowed for Assist or Code. Default in this roadmap: no, and not inside twin routing.
3. Whether Study Hall (#61) is in the product.
4. Whether the public live-stream URL stays public.
5. Price and packaging.
6. Closing the stale pull requests listed in the assessment.
7. The `HEIRLOOM_BYO_KEY` value. The owner sets it. It is not committed.
