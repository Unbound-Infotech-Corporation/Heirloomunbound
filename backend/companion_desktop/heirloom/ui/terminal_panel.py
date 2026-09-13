"""Heirloom Unbound Terminal — live studio log + Send ticket."""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from heirloom import BUILD_ID, __version__, api, config, models
from heirloom.studio_log import SOURCES, get_log, info as log_info, studio_log_path, ticket as log_ticket
from heirloom.ticket_redact import build_snapshot, mailto_href, snapshot_json

from . import PALETTE


class TicketDialog(QDialog):
    """Solid archive dialog — no glass. Subject, intent, email, redacted bundle."""

    def __init__(self, parent: Optional[QWidget] = None, *, email: str = "", snapshot: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Send ticket — Heirloom Unbound")
        self.setModal(True)
        self.resize(520, 560)
        self._snapshot = snapshot or {}
        self.setStyleSheet(
            f"""
            QDialog {{
                background: #1C1A18;
                color: {PALETTE['text_primary']};
                border: 1px solid #36322E;
            }}
            QLabel {{ color: {PALETTE['text_secondary']}; }}
            QLineEdit, QTextEdit {{
                background: #121110;
                border: 1px solid #36322E;
                color: {PALETTE['text_primary']};
                padding: 8px;
                border-radius: 2px;
            }}
            QLineEdit:focus, QTextEdit:focus {{ border-color: #D4A373; }}
            QPushButton#primary {{
                background: #D4A373;
                color: #121110;
                border: none;
                padding: 10px 16px;
                font-weight: 600;
            }}
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        title = QLabel("Send a ticket")
        title.setStyleSheet(
            f"font-family: 'Cormorant Garamond', Garamond, serif; font-size: 26px; color: {PALETTE['text_primary']};"
        )
        hint = QLabel("We attach a redacted probe snapshot — never keys, journal text, or voice files.")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        form = QFormLayout()
        self.subject = QLineEdit()
        self.subject.setPlaceholderText("What broke?")
        self.subject.setText("Heirloom Unbound — studio help")
        self.intent = QTextEdit()
        self.intent.setPlaceholderText("What you were trying to do…")
        self.intent.setFixedHeight(90)
        self.email = QLineEdit()
        self.email.setPlaceholderText("you@example.com")
        self.email.setText(email)
        form.addRow("Subject", self.subject)
        form.addRow("Trying to", self.intent)
        form.addRow("Email", self.email)
        root.addLayout(form)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        btns = QHBoxLayout()
        send = QPushButton("Send ticket")
        send.setObjectName("primary")
        send.clicked.connect(self._send)
        copy = QPushButton("Copy bundle")
        copy.clicked.connect(self._copy)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        btns.addWidget(send)
        btns.addWidget(copy)
        btns.addStretch(1)
        btns.addWidget(cancel)
        root.addLayout(btns)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(snapshot_json(self._snapshot))
        self.status.setText("Redacted bundle copied.")

    def _send(self) -> None:
        subject = self.subject.text().strip() or "Heirloom Unbound ticket"
        message = self.intent.toPlainText().strip() or "No extra detail."
        email = self.email.text().strip()
        payload = {
            "subject": subject,
            "message": message,
            "email": email,
            "probe": self._snapshot.get("probe"),
            "model_map": self._snapshot.get("model_map"),
            "compute": self._snapshot.get("compute"),
            "log_lines": self._snapshot.get("log_tail") or [],
            "os": self._snapshot.get("os"),
            "build_id": self._snapshot.get("build_id"),
            "companion_version": self._snapshot.get("companion_version"),
        }
        self.status.setText("Sending…")

        def _ok(data: dict) -> None:
            tid = (data or {}).get("ticket_id") or "HU-????"
            queued = bool((data or {}).get("queued"))
            log_ticket("ticket", f"ticket {tid} queued" if queued else f"ticket {tid} saved (mailto fallback)")
            self.status.setText((data or {}).get("hint") or f"ticket {tid}")
            if not queued:
                href = (data or {}).get("mailto") or mailto_href(tid, subject, email, self._snapshot)
                webbrowser.open(href)

        def _err(msg: str) -> None:
            tid = "HU-OFFLINE"
            href = mailto_href(tid, subject, email, self._snapshot)
            QGuiApplication.clipboard().setText(snapshot_json(self._snapshot))
            log_ticket("ticket", f"ticket {tid} queued · offline mailto + copy bundle")
            self.status.setText(f"Offline — bundle copied. Opening mailto… ({msg[:80]})")
            webbrowser.open(href)

        api.post_async("/support/ticket", payload, on_ok=_ok, on_err=_err)


class TerminalPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paused = False
        self._level = ""
        self._source = ""
        self._chips: dict[str, QPushButton] = {}
        self._email = ""
        self._model_map: dict = {}
        self._probe: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        over = QLabel("HEIRLOOM UNBOUND · TERMINAL")
        over.setProperty("class", "overline")
        over.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-family: 'IBM Plex Mono', 'JetBrains Mono', monospace; "
            "font-size: 10px; letter-spacing: 2px;"
        )
        root.addWidget(over)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        for label, slot in (
            ("Pause", self.toggle_pause),
            ("Clear", self.clear_view),
            ("Copy", self.copy_visible),
            ("Send ticket", self.send_ticket),
            ("Reveal log folder", self.reveal_folder),
        ):
            btn = QPushButton(label)
            btn.setObjectName("toolbar")
            btn.setMinimumHeight(36)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        tools.addStretch(1)
        root.addLayout(tools)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Level"))
        for lvl in ("", "debug", "info", "warn", "error", "ticket"):
            chip = QPushButton(lvl or "all")
            chip.setCheckable(True)
            chip.setChecked(lvl == "")
            chip.setObjectName("chip")
            chip.clicked.connect(lambda _=False, value=lvl: self._set_level(value))
            self._chips[f"lvl:{lvl}"] = chip
            filters.addWidget(chip)
        filters.addSpacing(12)
        filters.addWidget(QLabel("Source"))
        for src in ("",) + SOURCES:
            chip = QPushButton(src or "all")
            chip.setCheckable(True)
            chip.setChecked(src == "")
            chip.setObjectName("chip")
            chip.clicked.connect(lambda _=False, value=src: self._set_source(value))
            self._chips[f"src:{src}"] = chip
            filters.addWidget(chip)
        filters.addStretch(1)
        root.addLayout(filters)

        self.view = QPlainTextEdit()
        self.view.setObjectName("terminal_log")
        self.view.setReadOnly(True)
        self.view.setPlaceholderText("Studio log…")
        root.addWidget(self.view, 1)

        cmd_row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("probe voice · probe all · status · copy last 200")
        self.cmd.returnPressed.connect(self._run_command)
        run = QPushButton("Run")
        run.setObjectName("toolbar")
        run.setMinimumHeight(32)
        run.clicked.connect(self._run_command)
        cmd_row.addWidget(self.cmd, 1)
        cmd_row.addWidget(run)
        root.addLayout(cmd_row)

        get_log().subscribe(self._on_record)
        self.reload()

    def set_context(self, *, email: str = "", model_map: dict | None = None, probe: dict | None = None) -> None:
        if email:
            self._email = email
        if model_map is not None:
            self._model_map = model_map
        if probe is not None:
            self._probe = probe

    def _on_record(self, rec: dict) -> None:
        if self._paused:
            return
        if self._level and rec.get("level") != self._level:
            return
        if self._source and rec.get("source") != self._source:
            return
        self.view.appendPlainText(get_log().format_line(rec))

    def _set_level(self, level: str) -> None:
        self._level = level
        for key, chip in self._chips.items():
            if key.startswith("lvl:"):
                chip.setChecked(key == f"lvl:{level}")
        self.reload()

    def _set_source(self, source: str) -> None:
        self._source = source
        for key, chip in self._chips.items():
            if key.startswith("src:"):
                chip.setChecked(key == f"src:{source}")
        self.reload()

    def reload(self) -> None:
        rows = get_log().snapshot(last=800, level=self._level, source=self._source)
        self.view.setPlainText("\n".join(get_log().format_line(r) for r in rows))

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        log_info("ui", "terminal paused" if self._paused else "terminal resumed")

    def clear_view(self) -> None:
        get_log().clear_ring()
        self.view.clear()
        log_info("ui", "terminal cleared (studio.log is append-only)")

    def copy_visible(self, last: int = 0) -> None:
        if last:
            text = "\n".join(get_log().format_line(r) for r in get_log().snapshot(last=last))
        else:
            text = self.view.toPlainText()
        QGuiApplication.clipboard().setText(text)
        log_info("ui", f"copied {len(text.splitlines())} log lines")

    def reveal_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(studio_log_path().parent)))

    def _snapshot(self) -> dict:
        settings = config.load_settings()
        probe = self._probe or models.full_probe()
        lines = [get_log().format_line(r) for r in get_log().snapshot(last=200)]
        return build_snapshot(
            build_id=BUILD_ID,
            companion_version=__version__,
            probe=probe,
            model_map=self._model_map or settings.get("studio_models") or {},
            compute=settings.get("studio_compute") or {},
            log_lines=lines,
        )

    def send_ticket(self) -> None:
        dlg = TicketDialog(self, email=self._email, snapshot=self._snapshot())
        dlg.exec()

    def _run_command(self) -> None:
        raw = self.cmd.text().strip().lower()
        self.cmd.clear()
        if not raw:
            return
        log_info("ui", f"$ {raw}")
        if raw in {"probe voice", "probe voices"}:
            probe = models.full_probe()
            self._probe = probe
            for key in ("voicebox", "qwen3_tts", "piper"):
                block = probe.get(key) or {}
                log_info("probe", f"{key}: {'ready' if block.get('ready') else 'down'} · {block.get('detail', '')}")
        elif raw in {"probe all", "probe"}:
            probe = models.full_probe()
            self._probe = probe
            log_info("probe", probe.get("detail") or "probed")
        elif raw == "status":
            probe = self._probe or models.full_probe()
            log_info("companion", f"status · {probe.get('detail')}")
        elif raw.startswith("copy last"):
            n = 200
            parts = raw.split()
            if parts[-1].isdigit():
                n = int(parts[-1])
            self.copy_visible(last=n)
        else:
            log_info("ui", "commands: probe voice · probe all · status · copy last 200")
