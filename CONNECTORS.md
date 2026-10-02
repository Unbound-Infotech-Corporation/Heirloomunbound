# Connectors

The first connector is **email**. It plugs into the Assignments approval spine (`ConnectorAction` / `decide_approval`). Calendar, Slack, and real Gmail OAuth are not in this build.

Heirs, callers, and the heir surface never see connectors, mail, or tokens. Routes use the owner session and `connectors_allowed`, the same fence as assignments.

## Model

One document per owner and provider in `connectors`:

| Field | Notes |
|---|---|
| `connector_id` | `con_…` |
| `user_id` | Owner. |
| `provider` | `imap` in this build. `gmail` is listed and refused. |
| `status` | `connected` after a successful sign-in. Disconnect deletes the row. |
| `scopes` | `mail.read`, `mail.draft`, `mail.send`. Send is still approval-gated. |
| `account`, `host`, ports, security | Not secrets. The owner can see which mailbox is connected. |
| `secret` | Fernet ciphertext of the app password. Never returned by the API. |
| `created_at`, `updated_at` | ISO timestamps. Reconnecting keeps `created_at`. |

There is no existing encrypted store. ElevenLabs and the other BYO keys are plain fields on the user document. Connector passwords do not follow that. Set `CONNECTOR_SECRET_KEY` to a Fernet key or a long passphrase before connecting. Without it, connect returns 503 and nothing is stored.

## API

Owner session only.

- `GET /api/connectors` — list, secrets stripped
- `GET /api/connectors/status` — list plus the provider catalog
- `POST /api/connectors/test` — IMAP and SMTP sign-in. Does not save and does not send.
- `POST /api/connectors/connect` — test, then store
- `POST /api/connectors/disconnect` — `{ "provider": "imap" }`

## Providers

`MailProvider` is `list_threads`, `get_thread`, `create_draft`, and `send_message`.

| Method | Approval |
|---|---|
| `list_threads`, `get_thread`, `create_draft` | No. Presets and the test connection use these. |
| `send_message` | Yes. Only `EmailSendConnector.execute`, which `decide_approval` calls after the owner approves. |

### IMAP / SMTP

Stdlib `imaplib` and `smtplib`. Any host that speaks IMAP and SMTP with an app password. TLS is required (`ssl` on 993/465, or `starttls` on 143/587). Sockets time out at 15 seconds. Drafts are appended to `Drafts`, then `[Gmail]/Drafts`. Tests inject fake sessions and do not open a socket.

### Gmail OAuth

`GmailOAuthProvider.enabled` is false. Every method raises. The status payload says it is not enabled.

To turn it on later, the owner would register a Google Cloud OAuth client and set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`, with scopes `gmail.readonly` and `gmail.compose`, and a redirect URL owned by this server (same shape as Spotify). That flow is not started here. A Gmail token would still not bypass Approvals.

## Assignments

`Triage email` lists recent threads, writes a short triage (label and priority from headers), and saves draft replies as artifacts. `Summarize thread` writes one summary. `draft a reply to …` from Sit opens a draft assignment through the same router handoff as “assign” / “in the background”.

If nothing is connected, the Twin says: “No email is connected. Connect one in Settings > Connectors.” It does not invent a mailbox.

A reply is sent only when the **owner’s** title or goal asks to send. The Approval payload is the exact `to`, `subject`, and `body`. `autonomy=act` does not skip that. Approve runs `send_message` once; a second approve is a no-op because the approval is already `approved`. The provider also ignores a repeated approval id in the same process. Decline and expire are final. A crash after the server accepts the message and before that row is saved can retry; that window is the same as the approval spine.

Inbound mail is untrusted. A body that says `ACTION: send` or names another recipient is quoted as text. It cannot create a tool call, an approval, or a send, and it cannot change who a draft is addressed to.

The assignment log keeps short sender and subject lines. Passwords, tokens, and message bodies are not written there or into error text.

## How to add a provider

1. Implement `list_threads`, `get_thread`, `create_draft`, and `send_message` (the last one only from `EmailSendConnector` or the equivalent approval executor).
2. Mark `enabled` false until the owner can configure it without a half-working flow.
3. Store secrets with `seal_secret`. Put only the public row in `public_connector`.
4. Teach `connector_for_approval` which payload `channel` maps to it. Do not call the provider from the assignment step for sends.
5. Add a fake for unit tests. No live network.

## Not built

- Real Gmail OAuth (no consent screen, no token exchange)
- Calendar, Slack
- Routines, per-Clone memory, Clone-to-Clone messaging
- A sweeper that expires old approvals on a clock
- WinUI connect form (session client can list `/connectors`; the screen is web Settings)
- Browser click-through of the settings form in this change
