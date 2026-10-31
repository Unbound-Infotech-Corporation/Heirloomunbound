# Odysseus on the Twin Box

Odysseus is a separate self-hosted AI workspace
([odysseus-dev/odysseus](https://github.com/odysseus-dev/odysseus), `main`).
Heirloom can ask it as an optional local brain. Nothing here calls a cloud model.

The compose service name is `odysseus`. Inside the container the app listens on
port **7000**. The published host port defaults to **7011**
(`http://192.168.0.110:7011` on the Twin Box). Containers on the shared
`heirloom-box` network use `http://odysseus:7000` after that service is
attached to the network.

## Installer

```bash
sudo bash box/install.sh --odysseus-url http://192.168.0.110:7011
```

That writes:

```text
HEIRLOOM_ODYSSEUS_URL=http://192.168.0.110:7011
HEIRLOOM_ODYSSEUS=1
HEIRLOOM_ODYSSEUS_TOKEN_FILE=/var/lib/heirloom/owner/odysseus.token
```

A public address is refused. The installer does not create the token and does
not print it. `HEIRLOOM_BRAIN_STRATEGY` stays unset, which means `single`.

From the API container, when Odysseus has joined `heirloom-box`:

```bash
sudo bash box/install.sh --odysseus-url http://odysseus:7000
```

## API token

Odysseus admin creates one integration token per caller. Tokens look like
`ody_...`. Heirloom sends `Authorization: Bearer` and only needs the `chat`
scope (the default profile).

1. Open Odysseus at `http://192.168.0.110:7011` and sign in as admin.
2. Create a token named `Heirloom` with scope `chat`. In the API that is
   `POST /api/tokens` as the admin session (form fields `name` and `scopes`).
   The raw token is returned once.
3. On the Twin Box, put that value on a single line in the token file. Do not
   commit it, do not put it in the URL, and do not paste it into a log:

```bash
sudo install -d -m 2750 -o root -g heirloom /var/lib/heirloom/owner
sudo touch /var/lib/heirloom/owner/odysseus.token
sudo chgrp heirloom /var/lib/heirloom/owner/odysseus.token
sudo chmod 0640 /var/lib/heirloom/owner/odysseus.token
# Then write the ody_ value as the only line of that file, as root.
```

`HEIRLOOM_ODYSSEUS_TOKEN` is a fallback when the file is empty. The file wins.
The Models page can store a copy for the owner; the file still wins, and the
API never returns the secret (`token_set` only).

## What Heirloom calls

- Ordinary drafts: `POST /api/v1/chat` with `{"message": "<the question>"}`.
  That route is the integration chat. It does not run shell tools.
- Current-info questions: `POST /api/research/start` (Deep Research through
  Odysseus's SearXNG), then `GET /api/research/status/{id}` and
  `POST /api/research/result-peek/{id}`.
- Odysseus `main` rejects API tokens on research start (`require_user` returns
  403). Heirloom then uses `/api/v1/chat` so the turn still finishes.
- The question is the only text sent. Owner memories are not included, for an
  owner turn or an heir turn.
- A short timeout and a failed call drop Odysseus. The local Ollama answer
  still returns.

## Strategy

`HEIRLOOM_BRAIN_STRATEGY` (or the owner control on the Models page):

| Value | Behavior |
|---|---|
| `single` | One Ollama. BIGDEAL `llama3.3:70b` when it answers, otherwise the box `qwen2.5:14b`. Default. |
| `single+odysseus_research` | That one model. Research questions also get Odysseus Deep Research notes. |
| `ensemble_synthesis` | Hard or owner questions fan out to BIGDEAL, the box, and Odysseus. The primary local model writes the answer. Simple chat stays one model. |
| `judge_pick_best` | The same fan-out. The primary model picks one draft, and that draft is the answer. |

Each answer records `strategy`, `contributors` (name, model, latency), and
`latency_ms` on `brain_meta` and under `brain.answer` in `GET /api/health`.

The owner turns Odysseus off from the WinUI Models page. Heirs do not see the
control.
