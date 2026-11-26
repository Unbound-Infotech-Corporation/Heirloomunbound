# Life story: guided interview and memory imports

The fastest way for a new owner to teach their twin who they are. Page: **/life-story**
(new owners land there right after the short onboarding form; "Do this later" goes to Today).

Everything runs on the owner's machine with the local model. Nothing becomes part of the
twin until the owner approves it.

## Interview
- **Short** (22 questions, about 28 minutes) or **Full** (38 questions, about 48 minutes,
  up to 12 follow-ups, so about an hour at most). Eleven chapters: where you come from, parents
  and family, school, leaving home, work, love, children, hard times, joys, beliefs, legacy.
  Questions are written for any buyer (no assumed spouse, children, or religion).
- Answer by voice (local Whisper via `/api/memory-loop/transcribe`) or typing. "Read questions
  aloud" uses only the browser's on-device voices; if there are none it stays silent.
- Skip a question or a whole chapter; stop and resume any time (one active session per owner).
- After a substantial answer the local model may ask **one** follow-up. It is kept only if it is
  a single question that shares words with the answer and names no person or place the owner
  did not say. Otherwise the interview moves on.
- Answers under three content words make no card.

## Imports
| Kind | Accepted | What becomes the story |
|---|---|---|
| Photo | jpg/png/webp/gif/heic + caption | the caption (or the caption already in the photo's EXIF), date from EXIF; photo saved to Photos |
| Letter / document | .txt .md .docx .pdf .html | about 1,200-character passages, up to 20; a letter written by someone else is kept word for word as "A letter to me from NAME: …" |
| Messages | WhatsApp .txt export, Facebook/Instagram .json, CSV with sender + text | the owner's **own** messages, one passage per day, richest 25 days; other people are listed by name only |

Message imports ask "which one is you?" first. Imports draft in the background; the page shows progress.

## Review and grounding
Every answer and import is a **pending** memory card (title, when, people, story in their words;
the model's draft falls back to the owner's exact words if it adds anything). On Review cards the
owner edits, approves (one or many), or discards. Approving does exactly what the Record page does:
the card becomes `approved`, an owner-private vault entry is added, and only then can
`grounding_for_turn` cite it. Pending cards never answer; heirs never see owner-private cards.

Grounding now loads approved cards only, so hundreds of pending import cards cannot push approved
ones out, and card embeddings are cached per card text so a 100-card life story does not re-embed
every turn.

## API (owner session)
`GET /api/life-story/plan` · `POST|GET /api/life-story/interview` · `POST /api/life-story/interview/answer|skip|finish` ·
`POST /api/life-story/import/messages/preview` · `POST /api/life-story/import/messages|document|photo` ·
`GET /api/life-story/imports` · `GET /api/life-story/cards?status=pending` · `PATCH /api/life-story/cards/{id}` ·
`POST /api/life-story/cards/approve|discard`

## Checking a model
`python -m model_bench_life_story MODEL [--ollama URL]` runs the real endpoints as a throwaway user
with a made-up persona (interview, chat export, letter, photo, approve, recall, decline) and deletes
every row it made.
