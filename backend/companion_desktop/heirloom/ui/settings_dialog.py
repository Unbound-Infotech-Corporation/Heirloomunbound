"""Settings dialog — vault folder, tier, schedule, manual maintenance trigger.

Opened from the titlebar gear button. Reads + writes config.save_settings.
The "Run maintenance now" button calls Maintenance.run_async() and streams
status into a log panel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..maintenance import Maintenance
from ..vault import Vault, vault_root
from . import PALETTE, QSS


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n} B"


class SettingsDialog(QDialog):
    """Modal for vault / tier / schedule. Emits `changed` if anything was saved."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(QSS)
        self.setWindowTitle("Heirloom · Settings")
        self.setModal(True)
        self.resize(620, 640)
        self._settings = config.load_settings()
        self._maint = Maintenance(self)
        self._maint.progress.connect(self._on_progress)
        self._maint.completed.connect(self._on_completed)
        self._maint.finished.connect(self._on_finished)
        self._maint.error.connect(self._on_error)

        self._build()
        self._refresh_storage()

    # ------------ UI ------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        overline = QLabel("LOCAL VAULT")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        title = QLabel("Your archive, on your disk")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family: 'Cormorant Garamond', serif; font-size: 22px;"
        )
        sub = QLabel(
            "Everything you say to your twin is captured here first. Once a day "
            "(or on demand), a compaction job extracts the durable bits and "
            "uploads them to your twin's permanent knowledge."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 12px;")
        root.addWidget(overline)
        root.addWidget(title)
        root.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        # Folder picker
        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit(str(vault_root()))
        self.folder_input.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_input, 1)
        folder_row.addWidget(browse)
        folder_wrap = QWidget()
        folder_wrap.setLayout(folder_row)
        form.addRow(_label("Vault folder"), folder_wrap)

        # Tier
        self.tier = QComboBox()
        self.tier.addItem("Full · keep every turn + audio forever", "full")
        self.tier.addItem("Partial · keep audio 30 days, transcripts forever (recommended)", "partial")
        self.tier.addItem("Lite · keep only daily summaries + extracted facts", "lite")
        idx = max(0, [self.tier.itemData(i) for i in range(self.tier.count())].index(
            self._settings.get("storage_tier", "partial")
        )) if self._settings.get("storage_tier", "partial") in ("full", "partial", "lite") else 1
        self.tier.setCurrentIndex(idx)
        form.addRow(_label("Storage tier"), self.tier)

        # Schedule
        self.schedule = QComboBox()
        self.schedule.addItem("At quit (recommended)", "on_quit")
        self.schedule.addItem("Daily at 3 AM (background)", "midnight")
        self.schedule.addItem("Manual only", "manual")
        cur_sched = self._settings.get("maintenance_schedule", "on_quit")
        for i in range(self.schedule.count()):
            if self.schedule.itemData(i) == cur_sched:
                self.schedule.setCurrentIndex(i)
                break
        form.addRow(_label("Maintenance schedule"), self.schedule)
        root.addLayout(form)

        # Storage indicator
        usage_box = QFrame()
        usage_box.setStyleSheet(
            f"background: {PALETTE['bg_surface']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 4px;"
        )
        ub = QVBoxLayout(usage_box)
        ub.setContentsMargins(14, 12, 14, 12)
        ub.setSpacing(6)
        self.usage_label = QLabel("…")
        self.usage_label.setStyleSheet(f"color: {PALETTE['text_primary']}; font-size: 13px;")
        self.usage_bar = QProgressBar()
        self.usage_bar.setMaximum(100)
        self.usage_bar.setFixedHeight(6)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setStyleSheet(
            f"QProgressBar {{ background: {PALETTE['bg_base']}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {PALETTE['accent']}; border-radius: 3px; }}"
        )
        self.last_compaction_label = QLabel("Last compaction: never")
        self.last_compaction_label.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px;"
        )
        ub.addWidget(self.usage_label)
        ub.addWidget(self.usage_bar)
        ub.addWidget(self.last_compaction_label)
        root.addWidget(usage_box)

        # Actions
        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run maintenance now")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run_now)
        actions.addWidget(self.run_btn)

        save_btn = QPushButton("Save changes")
        save_btn.clicked.connect(self._save_changes)
        actions.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        # Log panel
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Maintenance log will appear here…")
        self.log.setMinimumHeight(140)
        self.log.setStyleSheet(
            f"background: {PALETTE['bg_base']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 3px; font-family: 'IBM Plex Mono', Consolas, monospace;"
            " font-size: 11px;"
        )
        root.addWidget(self.log, 1)

    # ------------ Actions ------------
    def _pick_folder(self) -> None:
        new = QFileDialog.getExistingDirectory(
            self, "Pick your vault folder", str(vault_root())
        )
        if new:
            self.folder_input.setText(new)

    def _save_changes(self) -> None:
        s = config.load_settings()
        s["vault_folder"] = self.folder_input.text().strip() or None
        s["storage_tier"] = self.tier.currentData()
        s["maintenance_schedule"] = self.schedule.currentData()
        config.save_settings(s)
        self._settings = s
        self.log.appendPlainText("⚙  Settings saved.")
        self._refresh_storage()
        self.changed.emit()

    def _run_now(self) -> None:
        self.run_btn.setEnabled(False)
        self.log.appendPlainText("▶  Starting maintenance…")
        # Save first so the worker reads the current tier
        self._save_changes()
        self._maint.run_async()

    def _on_progress(self, msg: str) -> None:
        self.log.appendPlainText(f"·  {msg}")

    def _on_completed(self, payload: dict) -> None:
        self.log.appendPlainText(
            f"✓  {payload['date']} — {payload['turns_seen']} turns → "
            f"{payload['facts_uploaded']} new facts learned "
            f"({payload['facts_skipped']} already known)"
        )

    def _on_finished(self, done: int, failed: int) -> None:
        self.log.appendPlainText(f"⏹  Done. {done} day(s) compacted, {failed} failed.")
        self.run_btn.setEnabled(True)
        # Persist last-run timestamp
        s = config.load_settings()
        from datetime import datetime, timezone
        s["last_maintenance_at"] = datetime.now(timezone.utc).isoformat()
        config.save_settings(s)
        self._refresh_storage()

    def _on_error(self, msg: str) -> None:
        self.log.appendPlainText(f"✗  Error: {msg}")
        self.run_btn.setEnabled(True)

    def _refresh_storage(self) -> None:
        try:
            v = Vault()
            usage = v.storage_usage()
        except Exception as exc:  # noqa: BLE001
            self.usage_label.setText(f"Vault unavailable: {exc}")
            return
        self.usage_label.setText(
            f"{_human_bytes(usage['bytes'])} across {usage['files']} files · "
            f"{usage['turns']} turns · {usage['compactions']} compactions"
        )
        # Pseudo-progress: cap at 1GB visually
        pct = min(100, int(usage["bytes"] / (1024 * 1024 * 10)))
        self.usage_bar.setValue(pct)
        last = v.last_compaction()
        if last:
            self.last_compaction_label.setText(
                f"Last compaction: {last['date']} ({last['turns_seen']} turns, "
                f"{last['facts_extracted']} facts learned)"
            )
        else:
            self.last_compaction_label.setText("Last compaction: never")

        # Also fetch cloud-side fact count
        def _on_status(d):
            facts_v = (d or {}).get("facts_from_vault", 0)
            total = (d or {}).get("total_facts", 0)
            self.last_compaction_label.setText(
                self.last_compaction_label.text()
                + f"  ·  cloud has {facts_v}/{total} facts about you"
            )
        api.get_async("/vault/status", on_ok=_on_status, on_err=lambda _m: None)


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {PALETTE['text_muted']}; letter-spacing: 2px;"
        " font-size: 10px; text-transform: uppercase;"
    )
    return lbl
