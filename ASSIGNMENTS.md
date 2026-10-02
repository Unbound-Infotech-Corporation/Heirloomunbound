# Assignments v1

The Twin owns a workspace on this PC and takes **Assignments**: scoped jobs it or a Clone does in the background and reports back on. This is how the main bot hands real work to a Clone.

Heirs and callers never see assignments or approvals. The routes use the owner session (`get_current_user`) and `assignments_allowed` (the same owner/heir fence as Sit).

## Model

Stored on `assignments`, scoped by `user_id`:

| Field | Notes |
|---|---|
| `assignment_id` | `asn_…` |
| `title`, `goal`, `scope` | Scope is free text: what the job may touch. |
| `status` | See below. |
| `autonomy` | `draft` or `act`. Presets always start as `draft`. |
| `clone_id` | Optional. Null means the Twin. |
| `artifacts` | `{name, kind, text, ref}` |
| `log` | `{ts, line}`, capped at 20. |
| `tasks` | Optional checklist `{task_id, text, done}`. Not a separate product. |
| `created_at`, `updated_at` | ISO timestamps. |

## Statuses

Legal moves live in one function, `assert_transition` (`backend/assignments.py`):

| From | To |
|---|---|
| `queued` | `running`, `cancelled` |
| `running` | `needs_approval`, `done`, `failed`, `cancelled` |
| `needs_approval` | `done`, `cancelled`, `failed` |
| `done`, `failed`, `cancelled` | nowhere |

Creating an assignment queues it and runs one step. A draft or summary with no outbound action finishes as `done`. An outbound proposal moves the job to `needs_approval`.

## Approvals

Anything that would go out as the owner, or change something outside Heirloom, creates an Approval and does **not** run:

| Field | Notes |
|---|---|
| `approval_id` | `apr_…` |
| `assignment_id` | The job that proposed it. |
| `action_kind` | `send`, `post`, `delete`, `spend` (aliases like `send_email` normalize to `send`). |
| `summary` | One line. |
| `payload` | Exactly what would be sent or changed. |
| `status` | `pending`, `approved`, `declined`, `expired`. |
| `decided_at` | Set when the owner decides, or when cancel expires it. |

Rules:

- Nothing external executes until the owner approves.
- Clone `autonomy=ask` (default) means every external effect needs an approval.
- Clone `autonomy=act`, and assignment `autonomy=act`, may read, draft, summarize, and write artifacts without asking.
- `act` does **not** bypass send, post, delete, or spend.
- Approve executes once. A second approve is a no-op (`idempotent`, connector not called again).
- Decline and expire are final. They are not retried. Cancel expires a still-pending approval.

## Presets

Triage email, Summarize thread, and Blank. A preset prefills title, goal, scope, and autonomy (`draft`).

Triage email and Summarize thread read the owner's IMAP connector (see `CONNECTORS.md`). Triage lists recent threads, proposes a label and priority from the headers, and saves draft replies as artifacts. Summarize writes one thread note. Neither sends. A reply is sent only when the owner's own words ask to send, and that becomes an Approval whose payload is the exact To, Subject, and Body. If no mailbox is connected, the step says so and points at Settings > Connectors. It does not invent mail. Text inside a message cannot start a send.

## Router handoff

The default Sit turn still answers in chat. A turn opens an assignment only when the text (or a Clone handoff remainder) matches a conservative cue:

- `assign` / `assignment`
- `in the background`
- `while I'm away`
- `check my email` / `check my inbox` (Triage email)
- `summarize the thread` / `summarize my inbox` (Summarize thread)
- `draft a reply to …` (a draft assignment; send only if the owner asked to send)

The reply is one receipt line with the id and `/assignments/{id}`. The chat model is not called for that turn. Heir surfaces never enter this path.

## API

Owner session only.

- `GET/POST /api/assignments`
- `GET/PATCH /api/assignments/{id}`
- `POST /api/assignments/{id}/cancel`
- `POST /api/assignments/{id}/tasks`
- `POST /api/assignments/{id}/tasks/{task_id}/toggle`
- `POST /api/assignments/{id}/step` — one more step while queued or running
- `GET /api/approvals` — pending by default; `status=all` plus `assignment_id` for a job
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/decline`

`run_assignment_step(assignment)` is the runner. The v1 executor calls the same `LlmChat` path Twin turns use (`assignment_chat.py`). If the key is missing or the call fails, it writes a local draft instead of sending. A proposed outbound action becomes an Approval.

`ConnectorAction` is what an approved send hands to a connector. `InMemoryConnector` still records non-email sends once per `approval_id`. Email sends use `EmailSendConnector`, which calls `send_message` only from `decide_approval`. See `CONNECTORS.md`.

## Web

`/assignments` lists jobs. `/assignments/new` offers the three presets and shows whether IMAP is connected. The detail page shows status, log, artifacts, tasks, and an Approval card (the payload, including To / Subject / Body, Approve, Decline). The same card appears inline in Sit when an assignment needs approval. Settings has a Connectors section for the app password.

## WinUI

`AssignmentCore` holds the same transition, preset, and approval rules, with tests in `desktop/Heirloom.Tests`. `HeirloomApiClient` can list assignments, list pending approvals, approve or decline, and read connector status on the owner session. A native Assignments list and a native connect form are **not** in this build.

## Not built

- Calendar or Slack connectors. Email (IMAP/SMTP) is in `CONNECTORS.md`. Gmail OAuth is not enabled.
- Routines or scheduling
- Per-Clone memory
- Clone-to-Clone messaging
- WinUI Assignments document
- A sweeper that expires old approvals on a clock (cancel expires a pending approval; `expire` exists on the pure function)
