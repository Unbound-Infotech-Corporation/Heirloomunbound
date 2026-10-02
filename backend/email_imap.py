"""IMAP/SMTP mailbox. TLS required. Timeouts are strict. No network in tests.

``send_message`` is for the approval executor only. Drafts are an IMAP append.
"""
from __future__ import annotations

import imaplib
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_default
from typing import Any, Callable, Optional

from mail_provider import (
    MAIL_TIMEOUT_SECONDS,
    MailAccessError,
    MailDraft,
    MailMessage,
    MailThreadSummary,
    extract_address,
    redact_text,
)

ImapFactory = Callable[[str, int, float, str], Any]
SmtpFactory = Callable[[str, int, float, str], Any]


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    security: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    username: str
    password: str

    def public(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "security": self.security,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_security": self.smtp_security,
            "username": self.username,
        }


def _host_ok(value: str) -> bool:
    return bool(value) and " " not in value and "/" not in value and "@" not in value and len(value) <= 253


def parse_imap_config(data: dict[str, Any]) -> ImapConfig:
    security = str(data.get("security") or "ssl").strip().lower()
    smtp_security = str(data.get("smtp_security") or "ssl").strip().lower()
    if security not in {"ssl", "starttls"} or smtp_security not in {"ssl", "starttls"}:
        raise MailAccessError("TLS is required.")
    host = str(data.get("host") or "").strip()
    smtp_host = str(data.get("smtp_host") or host).strip()
    if not _host_ok(host) or not _host_ok(smtp_host):
        raise MailAccessError("Mail host is required.")
    try:
        port = int(data.get("port") or (993 if security == "ssl" else 143))
        smtp_port = int(data.get("smtp_port") or (465 if smtp_security == "ssl" else 587))
    except (TypeError, ValueError) as exc:
        raise MailAccessError("Mail port is invalid.") from exc
    if not (1 <= port <= 65535) or not (1 <= smtp_port <= 65535):
        raise MailAccessError("Mail port is invalid.")
    username = str(data.get("username") or "").strip()
    password = str(data.get("app_password") or data.get("password") or "")
    if not username or len(username) > 254:
        raise MailAccessError("Username is required.")
    if not password.strip() or len(password) > 256:
        raise MailAccessError("App password is required.")
    return ImapConfig(
        host=host,
        port=port,
        security=security,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_security=smtp_security,
        username=username,
        password=password,
    )


def _header(message: Any, name: str) -> str:
    value = message.get(name) or ""
    return str(value).strip()


def _body_text(message: Any) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return str(part.get_content() or "")
                except Exception:  # noqa: BLE001
                    continue
        return ""
    try:
        return str(message.get_content() or "")
    except Exception:  # noqa: BLE001
        return ""


def message_from_bytes(raw: bytes, *, thread_id: str) -> MailMessage:
    parsed = BytesParser(policy=email_default).parsebytes(raw or b"")
    subject = _header(parsed, "Subject")
    sender = _header(parsed, "From")
    mid = _header(parsed, "Message-ID") or thread_id
    return MailMessage(
        thread_id=mid,
        subject=subject,
        sender=sender,
        to=_header(parsed, "To"),
        date=_header(parsed, "Date"),
        body=_body_text(parsed),
        unread=True,
    )


def default_imap_factory(host: str, port: int, timeout: float, security: str) -> Any:
    if security == "ssl":
        return imaplib.IMAP4_SSL(host, port, timeout=timeout)
    if security == "starttls":
        client = imaplib.IMAP4(host, port, timeout=timeout)
        client.starttls()
        return client
    raise MailAccessError("TLS is required.")


def default_smtp_factory(host: str, port: int, timeout: float, security: str) -> Any:
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=timeout)
    if security == "starttls":
        client = smtplib.SMTP(host, port, timeout=timeout)
        client.ehlo()
        client.starttls()
        client.ehlo()
        return client
    raise MailAccessError("TLS is required.")


class ImapSmtpProvider:
    """Stdlib IMAP and SMTP. Factories are injected in tests so nothing dials out."""

    provider_id = "imap"
    enabled = True

    def __init__(
        self,
        config: ImapConfig,
        *,
        imap_factory: Optional[ImapFactory] = None,
        smtp_factory: Optional[SmtpFactory] = None,
        timeout: float = MAIL_TIMEOUT_SECONDS,
    ) -> None:
        if config.security not in {"ssl", "starttls"} or config.smtp_security not in {"ssl", "starttls"}:
            raise MailAccessError("TLS is required.")
        self.config = config
        self.timeout = float(timeout)
        self._imap_factory = imap_factory or default_imap_factory
        self._smtp_factory = smtp_factory or default_smtp_factory
        self._sent: set[str] = set()
        self._draft_seq = 0

    def _fail(self, exc: Exception) -> MailAccessError:
        return MailAccessError(redact_text(
            f"Couldn't reach the mailbox. {exc}",
            [self.config.password],
        ))

    def _login_imap(self) -> Any:
        try:
            client = self._imap_factory(
                self.config.host, self.config.port, self.timeout, self.config.security
            )
            client.login(self.config.username, self.config.password)
            return client
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None

    def _close(self, client: Any) -> None:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            return

    def list_threads(self, *, limit: int = 10) -> list[MailThreadSummary]:
        client = self._login_imap()
        try:
            client.select("INBOX", readonly=True)
            _typ, data = client.search(None, "ALL")
            blob = data[0] if data and data[0] else b""
            ids = [piece for piece in blob.split() if piece]
            chosen = ids[-max(1, limit):]
            rows: list[MailThreadSummary] = []
            for num in reversed(chosen):
                _typ, fetched = client.fetch(num, "(BODY.PEEK[HEADER])")
                raw = _payload_bytes(fetched)
                message = message_from_bytes(raw, thread_id=num.decode("ascii", "ignore") or "imap")
                rows.append(MailThreadSummary(
                    thread_id=message.thread_id,
                    subject=message.subject,
                    sender=message.sender,
                    date=message.date,
                    unread=True,
                ))
            return rows
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        finally:
            self._close(client)

    def get_thread(self, thread_id: str) -> list[MailMessage]:
        client = self._login_imap()
        try:
            client.select("INBOX", readonly=True)
            wanted = (thread_id or "").replace('"', "").strip()
            _typ, data = client.search(None, "HEADER", "Message-ID", f'"{wanted}"')
            blob = data[0] if data and data[0] else b""
            ids = [piece for piece in blob.split() if piece]
            if not ids and thread_id.isdigit():
                ids = [thread_id.encode("ascii")]
            messages: list[MailMessage] = []
            for num in ids[:5]:
                _typ, fetched = client.fetch(num, "(BODY.PEEK[])")
                raw = _payload_bytes(fetched)
                messages.append(message_from_bytes(raw, thread_id=thread_id))
            return messages
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        finally:
            self._close(client)

    def create_draft(
        self, *, to: str, subject: str, body: str, thread_id: str = ""
    ) -> MailDraft:
        client = self._login_imap()
        try:
            mime = _mime(self.config.username, to, subject, body)
            payload = mime.as_bytes()
            last: Exception | None = None
            for folder in ("Drafts", "[Gmail]/Drafts"):
                try:
                    client.append(folder, "\\Draft", None, payload)
                    last = None
                    break
                except Exception as exc:  # noqa: BLE001 — try the other drafts folder
                    last = exc
            if last is not None:
                raise last
            self._draft_seq += 1
            return MailDraft(
                draft_id=f"imap_draft_{self._draft_seq}",
                to=to,
                subject=subject,
                body=body,
                thread_id=thread_id,
            )
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        finally:
            self._close(client)

    def send_message(
        self, *, to: str, subject: str, body: str, approval_id: str
    ) -> dict[str, Any]:
        """Called only after an approval. The same approval id sends once."""
        if not (approval_id or "").strip():
            raise MailAccessError("A send needs an approval.")
        if approval_id in self._sent:
            return {"ok": True, "idempotent": True, "approval_id": approval_id}
        try:
            client = self._smtp_factory(
                self.config.smtp_host,
                self.config.smtp_port,
                self.timeout,
                self.config.smtp_security,
            )
            client.login(self.config.username, self.config.password)
            client.send_message(_mime(self.config.username, to, subject, body))
            try:
                client.quit()
            except Exception:  # noqa: BLE001
                pass
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        self._sent.add(approval_id)
        return {"ok": True, "idempotent": False, "approval_id": approval_id}

    def test_connection(self) -> dict[str, Any]:
        imap = self._login_imap()
        self._close(imap)
        try:
            smtp = self._smtp_factory(
                self.config.smtp_host,
                self.config.smtp_port,
                self.timeout,
                self.config.smtp_security,
            )
            smtp.login(self.config.username, self.config.password)
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass
        except MailAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc) from None
        return {"ok": True, "detail": "Signed in. Nothing was sent."}


def _mime(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body or "")
    return message


def _payload_bytes(fetched: Any) -> bytes:
    if not fetched:
        return b""
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return b""


def address_of(message: MailMessage) -> str:
    return extract_address(message.sender)
