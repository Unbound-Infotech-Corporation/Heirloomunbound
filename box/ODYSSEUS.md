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

The live path does not wait on Deep Research.

- Fast search, owner turns only: the BIGDEAL model rewrites the question into
  one search query. Heirloom then `POST /api/search` with `{"query": "..."}`
  and the `ody_` token. That route is Odysseus's SearXNG lookup and returns
  `context` plus `sources`. If it is missing, Heirloom uses
  `POST /api/v1/chat` with `use_web: true`. The primary model answers from
  those notes. The search leg is capped at about 10 seconds.
- Deep Research (`POST /api/research/start`) runs only when
  `HEIRLOOM_ODYSSEUS_DEEP_RESEARCH=1` or the Models page toggle is on. It is a
  background job. The reply does not wait for the report.
- Heirs and callers never call Odysseus.
- The question or the search query is the only text sent. Vault memories stay
  on the local Ollama prompt.
- A timeout or a down host drops Odysseus. The local answer still returns.

## Strategy

`HEIRLOOM_BRAIN_STRATEGY` defaults to `single`. `HEIRLOOM_BRAIN_MODEL` defaults
to `gpt-oss:120b` (`think` `low`, `num_predict` 2500). `qwen3:32b` with
thinking off is the alternate when the 96GB card leaves.

| Value | Behavior |
|---|---|
| `single` | One Ollama. BIGDEAL when it answers, otherwise the box `qwen2.5:14b`. Default. |
| `single+odysseus_research` | Owner turns that need current information. Fast search, then the primary model answers. Not used for heirs or callers. |
| `ensemble_synthesis` | Experimental and off. Set `HEIRLOOM_BRAIN_ENSEMBLE=1` to try it on owner turns. Heir and caller turns never fan out. |
| `judge_pick_best` | Owner turns only. The primary model picks one draft. |

Each answer records `strategy`, `contributors` (name, model, latency), and
`latency_ms` on `brain_meta` and under `brain.answer` in `GET /api/health`.

The owner turns Odysseus off from the WinUI Models page. Heirs do not see the
control.
