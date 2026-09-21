# Unbound Phase 1 — Heirloom Room + clones under the twin

Product directions from owner C L. This pass ships a **real scaffold**, not vapor:
working owner-only UI, data models, mock reconstruction, and chat routing that
extends Assist / Sit / Twin instead of forking a second product.

## What shipped (Phase 1)

### A) Heirloom Room

Rooms live in their own studio section (`/rooms`), not Archive. Archive is
filed memory. A Room is a **place** you capture so you can sit with the twin
there later.

- Mongo `rooms`: `room_id`, `user_id`, `name`, `capture_status`
  (`pending` / `processing` / `ready` / `failed`), `assets[]`, `scene`, `job`,
  timestamps. Owner-gated (`get_current_user`). Refunded accounts 403.
- Capture: instructions to film from many angles; upload video or stills via
  the same object store as photos (`storage.put_object`). If storage is down,
  metadata is still recorded so the mock path can proceed.
- Reconstruction: `POST /api/rooms/{id}/reconstruct` with `backend=mock`
  marks the room **ready** and attaches a placeholder **glTF 2.0** volume
  (inline positions/indices). No paid photogrammetry / NeRF / splat API is
  called. `job.vendor` is an optional integration point only.
- Viewer: `/rooms/:id/sit` draws the placeholder room (orbit) with a Twin
  conversation overlay. **Enter VR** is a WebXR stub (`navigator.xr`).
  Deep-link: `/twin?room=`.

### B) Clones under the twin

Personas stay **tone/modes** of the same twin. **Clones** are named
specialist agents the owner adds under that twin — **who speaks this
turn**, with a tools allowlist. Twin = the person / heirloom identity.
Clones ≠ Assist (the PC copilot), though a PC clone may *route as* Assist.

- Mongo `twin_assistants` (internal): `clone_id` / `assistant_id` alias,
  `name`, `slug`, `role`, `tools_allowlist`, `enabled`,
  `speak_as` (`specialist` | `assist`).
- Public API: `GET/POST /api/clones`, `PATCH/DELETE /api/clones/{clone_id}`.
  JSON uses `clone_id` (and `assistants` as a response alias).
- Seeded clones: Research, Archive, Letters, PC.
- Owner can add / rename / disable in Settings (and Sit / Twin pickers).
- Chat: pick a chip or `@Research …`. Twin remains the person. PC
  clones route as **Assist** (never first-person as the owner, never
  on heir/caller). Twin-side clones never receive PC tools.
- Wired on `POST /api/twin/message`, `POST /api/owner/chat`,
  `POST /api/desktop/chat` (`clone_id`; `assistant_id` accepted as alias).

### Trust fences (unchanged)

- Heirs inherit Twin, not Assist, not Rooms, not Clones.
- Portal (`/heir/:token`) has no links to `/rooms` or `/clones`.
- Stripe / billing / refund 403 paths untouched.

## Try it locally

Backend:

```bash
cd backend
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

Frontend (needs `REACT_APP_BACKEND_URL` pointing at that API):

```bash
cd frontend
yarn start
```

Auth: seeded Mongo session Bearer token — see `backend/tests/conftest.py`
and `auth_testing.md`.

In the studio:

1. **Rooms** in the dock → name a room → upload a still or video (optional) →
   **Build stand-in scene** → **Sit in this room**. Talk in the overlay;
   switch Twin / Research / PC.
2. **Sit** (`/owner`) or **Talk to twin** — clone chips under the
   composer, or type `@Research look this up`.
3. **Settings** → Clones under the twin — add, rename, disable.

Tests:

```bash
cd backend && python -m pytest tests/test_rooms.py tests/test_assistants.py tests/test_heir_guards.py tests/test_owner_rail.py -q
cd frontend && CI=true yarn test --watchAll=false --testPathPattern='(rooms|assistants|memoryStudio)'
```

WinUI Rooms / Clones documents are **deferred** (same as Memory Studio
and Sit Owner document). Native chat already accepts `clone_id` on
`POST /api/desktop/chat`.

## Phase 2 (not this PR)

- Real reconstruction vendor: photogrammetry, NeRF, or Gaussian splat.
  Swap `job.backend` / `job.vendor`; keep the Room document. Preferred
  export remains glTF; splat may sit beside it as `scene.splat_url`.
- Quest / headset packaging: sideload or App Lab wrapper around the WebXR
  viewer; seated tracking; spatial audio of the cloned voice.
- Capture from phone companion (existing phone pair) into the same Room.
- Heir-enter-a-released-room (gift a place, not just a voice) — only after
  an explicit owner release, never by default.
- Full tool parity per clone (letters CRUD, archive file, PC Confirm
  receipts already on Assist).
- WinUI Rooms document + Clones list in Settings.

Hypothesis confirmed for Phase 1: **Owner rail + Assist** are the extension
points for clones; **Rooms** are a new section (not Archive).
