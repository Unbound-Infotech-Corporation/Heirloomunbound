"""Mailbox provider interface and the email assignment step.

``list_threads``, ``get_thread``, and ``create_draft`` run without an approval.
``send_message`` is called only by ``EmailSendConnector.execute``, which the
approval executor uses after the owner approves.

Inbound mail is untrusted data. It cannot create a send, a tool call, or an
approval. Those come only from the owner's own assignment text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence

from assignments import (
    ProposedAction,
    StepDraft,
    normalize_action_kind,
    outbound_kind_in_text,
)
from email_intent import (
    DRAFT_REPLY,
    NOT_CONNECTED_REPLY,
    SUMMARIZE_THREAD,
    TRIAGE_EMAIL,
    email_assignment_intent,
)

MAIL_TIMEOUT_SECONDS = 15
MAX_THREADS = 8
MAX_DRAFTS = 3
QUOTE_CHARS = 160

_SECRET_ASSIGN = re.compile(
    r"(?i)\b(password|passwd|app_password|secret|token|api_key)\b\s*[:=]\s*\S+"
)
_REPLY_TARGET = re.compile(
    r"draft\s+(?:a\s+)?repl(?:y|ies)\s+to\s+(.+)",
    re.IGNORECASE,
)
_SEND_TAIL = re.compile(r"\b(?:and|&)\s+send\b", re.IGNORECASE)
_STOP = frozenset({
    "the", "and", "for", "about", "with", "this", "that", "from", "your",
    "reply", "draft", "send", "please", "thread", "email", "inbox",
})


class MailAccessError(RuntimeError):
    """A mailbox failure whose message is already safe to show and log."""


def redact_text(text: str, secrets: Sequence[str] = ()) -> str:
    """Drop passwords and assignment-log secrets. Keep the sentence short."""
    out = text or ""
    for secret in secrets:
        if secret and len(secret) >= 3:
            out = out.replace(secret, "[redacted]")
    out = _SECRET_ASSIGN.sub(lambda match: f"{match.group(1)}=[redacted]", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:240]


def extract_address(value: str) -> str:
    raw = value or ""
    match = re.search(r"<([^<>@\s]+@[^<>\s]+)>", raw)
    if match:
        return match.group(1).strip()
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
    return match.group(0) if match else ""


@dataclass
class MailMessage:
    thread_id: str
    subject: str
    sender: str
    to: str = ""
    date: str = ""
    body: str = ""
    unread: bool = True


@dataclass
class MailDraft:
    draft_id: str
    to: str
    subject: str
    body: str
    thread_id: str = ""


@dataclass
class MailThreadSummary:
    thread_id: str
    subject: str
    sender: str
    date: str = ""
    unread: bool = True


class MailProvider(Protocol):
    def list_threads(self, *, limit: int = 10) -> list[MailThreadSummary]: ...

    def get_thread(self, thread_id: str) -> list[MailMessage]: ...

    def create_draft(
        self, *, to: str, subject: str, body: str, thread_id: str = ""
    ) -> MailDraft: ...

    def send_message(
        self, *, to: str, subject: str, body: str, approval_id: str
    ) -> dict[str, Any]: ...


def summary_of(message: MailMessage) -> MailThreadSummary:
    return MailThreadSummary(
        thread_id=message.thread_id,
        subject=message.subject,
        sender=message.sender,
        date=message.date,
        unread=message.unread,
    )


def short_line(message: MailMessage | MailThreadSummary) -> str:
    sender = (getattr(message, "sender", "") or "").strip()[:80]
    subject = (getattr(message, "subject", "") or "").strip()[:80]
    line = f"{sender}: {subject}".strip(": ")
    return redact_text(line) or "A message"


def owner_wants_send(title: str, goal: str) -> bool:
    """True only when the owner's own words ask to send. Never the mail."""
    return outbound_kind_in_text(f"{title}\n{goal}") == "send"


def label_for(message: MailMessage) -> tuple[str, str]:
    """Priority from headers. The body is not a command channel."""
    sender = (message.sender or "").lower()
    subject = (message.subject or "").lower()
    if any(token in sender for token in ("noreply", "no-reply", "newsletter", "notifications@")):
        return "later", "low"
    if "unsubscribe" in subject:
        return "later", "low"
    if message.unread and "?" in (message.subject or ""):
        return "reply", "high"
    return "review", "normal"


def reply_target(text: str) -> str:
    match = _REPLY_TARGET.search(text or "")
    if not match:
        return ""
    tail = _SEND_TAIL.split(match.group(1), maxsplit=1)[0]
    return tail.strip(" .,:;")[:200]


def match_messages(messages: Sequence[MailMessage], query: str) -> list[MailMessage]:
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9@.]{3,}", query or "")
        if token.lower() not in _STOP
    ]
    if not tokens:
        return []
    found: list[MailMessage] = []
    for message in messages:
        hay = f"{message.sender} {message.subject}".lower()
        if any(token in hay for token in tokens):
            found.append(message)
    return found


def draft_reply_text(message: MailMessage) -> str:
    """Our words. The inbound body is not copied in."""
    subject = redact_text((message.subject or "your note").strip())[:120] or "your note"
    return f"Thanks for writing about {subject}.\n\nI will follow up shortly.\n"


def reply_subject(subject: str) -> str:
    clean = (subject or "your note").strip()
    if clean.lower().startswith("re:"):
        return clean[:200]
    return f"Re: {clean}"[:200]


def untrusted_quote(body: str) -> str:
    text = re.sub(r"\s+", " ", body or "").strip()
    if not text:
        return ""
    return redact_text(text)[:QUOTE_CHARS]


def actions_from_untrusted_mail(body: str) -> list[Any]:
    """Inbound mail is data. It never yields a send, tool call, or approval."""
    _ = body
    return []


class FakeMailProvider:
    """In-memory mailbox. No network."""

    provider_id = "fake"
    enabled = True

    def __init__(self, messages: Optional[Sequence[MailMessage]] = None) -> None:
        self.messages = list(messages or [])
        self.drafts: list[MailDraft] = []
        self.sends: list[dict[str, Any]] = []
        self._sent: set[str] = set()
        self._seq = 0

    def list_threads(self, *, limit: int = 10) -> list[MailThreadSummary]:
        return [summary_of(message) for message in self.messages[:limit]]

    def get_thread(self, thread_id: str) -> list[MailMessage]:
        return [message for message in self.messages if message.thread_id == thread_id]

    def create_draft(
        self, *, to: str, subject: str, body: str, thread_id: str = ""
    ) -> MailDraft:
        self._seq += 1
        draft = MailDraft(
            draft_id=f"draft_{self._seq}",
            to=to,
            subject=subject,
            body=body,
            thread_id=thread_id,
        )
        self.drafts.append(draft)
        return draft

    def send_message(
        self, *, to: str, subject: str, body: str, approval_id: str
    ) -> dict[str, Any]:
        if not (approval_id or "").strip():
            raise MailAccessError("A send needs an approval.")
        if approval_id in self._sent:
            return {"ok": True, "idempotent": True, "approval_id": approval_id}
        self._sent.add(approval_id)
        self.sends.append({
            "to": to,
            "subject": subject,
            "body": body,
            "approval_id": approval_id,
        })
        return {"ok": True, "idempotent": False, "approval_id": approval_id}

    def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "detail": "Signed in. Nothing was sent."}


class EmailSendConnector:
    """``Connector`` implementation. ``execute`` is the only send path."""

    def __init__(self, provider: MailProvider) -> None:
        self.provider = provider
        self.calls: list[str] = []

    def execute(self, action: Any) -> dict[str, Any]:
        kind = normalize_action_kind(getattr(action, "action_kind", "") or "")
        if kind != "send":
            raise MailAccessError("This connector only sends approved email.")
        payload = dict(getattr(action, "payload", None) or {})
        channel = str(payload.get("channel") or "email")
        if channel != "email":
            raise MailAccessError("This connector only sends email.")
        to = str(payload.get("to") or "").strip()
        subject = str(payload.get("subject") or "").strip()
        body = str(payload.get("body") or "")
        approval_id = str(getattr(action, "approval_id", "") or "")
        if not to or not subject:
            raise MailAccessError("The approval is missing a recipient or subject.")
        result = self.provider.send_message(
            to=to,
            subject=subject,
            body=body,
            approval_id=approval_id,
        )
        self.calls.append(approval_id)
        return result


class RefusingConnector:
    """Email approval with no mailbox. Does not pretend the send happened."""

    def __init__(self, message: str = NOT_CONNECTED_REPLY) -> None:
        self.message = message

    def execute(self, action: Any) -> dict[str, Any]:
        _ = action
        raise MailAccessError(self.message)


@dataclass
class _Loaded:
    messages: list[MailMessage] = field(default_factory=list)


def _load(provider: MailProvider, *, limit: int = MAX_THREADS) -> list[MailMessage]:
    summaries = provider.list_threads(limit=limit)
    loaded: list[MailMessage] = []
    for summary in summaries:
        thread = provider.get_thread(summary.thread_id)
        if thread:
            loaded.extend(thread)
        else:
            loaded.append(MailMessage(
                thread_id=summary.thread_id,
                subject=summary.subject,
                sender=summary.sender,
                date=summary.date,
                unread=summary.unread,
            ))
    return loaded


def _propose(message: MailMessage, body: str, *, title: str, goal: str) -> Optional[ProposedAction]:
    if not owner_wants_send(title, goal):
        return None
    if actions_from_untrusted_mail(message.body):
        return None
    to = extract_address(message.sender) or extract_address(message.to)
    if not to:
        return None
    subject = reply_subject(message.subject)
    return ProposedAction(
        action_kind="send",
        summary=f"Send reply to {to}: {subject[:80]}",
        payload={
            "channel": "email",
            "to": to,
            "subject": subject,
            "body": body,
            "thread_id": message.thread_id,
        },
    )


class EmailAssignmentExecutor:
    """Reads and drafts through the mailbox. Never calls ``send_message``."""

    def __init__(self, provider: Optional[MailProvider]) -> None:
        self.provider = provider

    async def draft(self, assignment: Mapping[str, Any]) -> StepDraft:
        preset = str(assignment.get("preset") or "")
        if preset not in {TRIAGE_EMAIL, SUMMARIZE_THREAD, DRAFT_REPLY}:
            preset = email_assignment_intent(
                f"{assignment.get('title') or ''}\n{assignment.get('goal') or ''}"
            ) or TRIAGE_EMAIL
        if self.provider is None:
            return StepDraft(
                summary=NOT_CONNECTED_REPLY,
                artifact_name="mailbox.md",
                artifact_kind="summary",
                artifact_text=NOT_CONNECTED_REPLY,
                proposed=None,
            )
        try:
            if preset == SUMMARIZE_THREAD:
                return self._summarize(assignment)
            if preset == DRAFT_REPLY:
                return self._draft_reply(assignment)
            return self._triage(assignment)
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001 — never leak a password or body
            raise MailAccessError(redact_text(f"Couldn't read the mailbox. {type(exc).__name__}")) from None

    def _triage(self, assignment: Mapping[str, Any]) -> StepDraft:
        assert self.provider is not None
        messages = _load(self.provider)
        title = str(assignment.get("title") or "")
        goal = str(assignment.get("goal") or "")
        lines = ["# Triage", ""]
        drafts = 0
        proposed: Optional[ProposedAction] = None
        for message in messages:
            label, priority = label_for(message)
            lines.append(f"- {priority} · {label} · {short_line(message)}")
            quote = untrusted_quote(message.body)
            if quote:
                lines.append(f"  Quoted mail (untrusted): {quote}")
            if label != "reply" or drafts >= MAX_DRAFTS:
                continue
            body = draft_reply_text(message)
            to = extract_address(message.sender)
            if not to:
                continue
            self.provider.create_draft(
                to=to,
                subject=reply_subject(message.subject),
                body=body,
                thread_id=message.thread_id,
            )
            drafts += 1
            lines.append(f"  Draft saved to {to}. Not sent.")
            if proposed is None:
                proposed = _propose(message, body, title=title, goal=goal)
        if not messages:
            lines.append("The inbox had nothing to triage.")
        summary = f"Triaged {len(messages)} thread{'s' if len(messages) != 1 else ''}."
        if proposed:
            summary = f"{summary} Held one reply for approval."
        return StepDraft(
            summary=summary,
            artifact_name="triage.md",
            artifact_kind="summary",
            artifact_text="\n".join(lines).strip(),
            proposed=proposed,
            note=" ".join(short_line(message) for message in messages[:4]),
        )

    def _summarize(self, assignment: Mapping[str, Any]) -> StepDraft:
        assert self.provider is not None
        messages = _load(self.provider)
        goal = str(assignment.get("goal") or "")
        chosen = match_messages(messages, goal) or (messages[:1] if messages else [])
        if not chosen:
            return StepDraft(
                summary="No thread to summarize.",
                artifact_name="thread.md",
                artifact_kind="summary",
                artifact_text="No thread to summarize.",
                proposed=None,
            )
        message = chosen[0]
        quote = untrusted_quote(message.body)
        text = "\n".join([
            f"# {message.subject or 'Thread'}",
            "",
            short_line(message),
            f"Quoted mail (untrusted): {quote}" if quote else "No body.",
            "",
            "I didn't send anything. Ask me to draft a reply if you want one held for approval.",
        ])
        return StepDraft(
            summary=f"Summarized {short_line(message)}.",
            artifact_name="thread.md",
            artifact_kind="summary",
            artifact_text=text.strip(),
            proposed=None,
            note=short_line(message),
        )

    def _draft_reply(self, assignment: Mapping[str, Any]) -> StepDraft:
        assert self.provider is not None
        messages = _load(self.provider)
        title = str(assignment.get("title") or "")
        goal = str(assignment.get("goal") or "")
        target = reply_target(f"{title}\n{goal}") or goal
        chosen = match_messages(messages, target)
        if not chosen:
            return StepDraft(
                summary="No matching thread to draft against.",
                artifact_name="reply.md",
                artifact_kind="draft",
                artifact_text="No matching thread. Nothing was drafted or sent.",
                proposed=None,
            )
        message = chosen[0]
        body = draft_reply_text(message)
        to = extract_address(message.sender)
        subject = reply_subject(message.subject)
        if to:
            self.provider.create_draft(to=to, subject=subject, body=body, thread_id=message.thread_id)
        proposed = _propose(message, body, title=title, goal=goal) if to else None
        summary = f"Drafted a reply to {to or 'the sender'}."
        if proposed:
            summary = f"{summary} Held it for approval."
        artifact = "\n".join([
            f"To: {to}",
            f"Subject: {subject}",
            "",
            body.strip(),
        ])
        return StepDraft(
            summary=summary,
            artifact_name="reply.md",
            artifact_kind="draft",
            artifact_text=artifact,
            proposed=proposed,
            note=short_line(message),
        )
