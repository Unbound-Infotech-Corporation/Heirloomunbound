"""First-launch wizard for the dedicated PC.

Walks disk budget, vendor email, official cloud sign-up (user completes
robot checks), local model download, and phone pairing. Does not automate
third-party account creation.
"""
from __future__ import annotations

import shutil
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..models import provision
from ..vault import vault_root
from . import PALETTE, QSS

PAGES = ("welcome", "space", "email", "cloud", "phone", "finish")


def _free_gb(path) -> Optional[float]:
    try:
        usage = shutil.disk_usage(path)
        return usage.free / (1024 ** 3)
    except Exception:
        return None


class _ProvisionThread(QThread):
    line = Signal(str)
    done = Signal(dict)

    def __init__(self, features: list[str], parent=None):
        super().__init__(parent)
        self._features = features

    def run(self) -> None:
        def note(msg: str) -> None:
            self.line.emit(msg)

        try:
            probe = provision(self._features, progress=note)
            self.done.emit(probe if isinstance(probe, dict) else {"log": [str(probe)]})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class FirstRunWizard(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(QSS)
        self.setWindowTitle("Heirloom · First-run setup")
        self.setModal(True)
        self.resize(720, 640)
        self._page = 0
        self._email = ""
        self._profile = "full"
        self._phone_feats = ["twin", "capture", "journal", "reminders"]
        self._pair_code = ""
        self._prov: Optional[_ProvisionThread] = None
        self._payload: dict = {}
        self._coach = None
        self._build()
        api.get_async("/studio/first-run", on_ok=self._on_loaded, on_err=lambda m: None)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        over = QLabel("FIRST USE · THIS PC")
        over.setProperty("class", "overline")
        title = QLabel("Set up Heirloom once")
        title.setObjectName("brand")
        root.addWidget(over)
        root.addWidget(title)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_space())
        self.stack.addWidget(self._page_email())
        self.stack.addWidget(self._page_cloud())
        self.stack.addWidget(self._page_phone())
        self.stack.addWidget(self._page_finish())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        skip = QPushButton("Finish later")
        skip.setObjectName("ghost")
        skip.clicked.connect(self._skip)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._back)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self._next)
        nav.addWidget(skip)
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        root.addLayout(nav)
        self._sync_nav()

    def _body(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 13px;")
        return lab

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        free = _free_gb(vault_root())
        free_txt = f"{free:.0f} GB free on this drive." if free is not None else "Could not read free disk."
        lay.addWidget(self._body(
            "Full power (local Whisper, Ollama twin, Piper, vault) uses about "
            f"20–50 GB. {free_txt}\n\n"
            "We run as much as possible on this PC for privacy and speed.\n\n"
            "Cloud vendors (ElevenLabs, D-ID, fal) require you to create the account "
            "and complete any 'not a robot' checks. Heirloom opens the official page "
            "and stores the API key you paste. It cannot sign up on those sites for you."
        ))
        lay.addStretch(1)
        return w

    def _page_space(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body("How much of this machine should Heirloom use?"))
        self._space_group = QButtonGroup(self)
        self._space_full = QRadioButton("Full local (recommended) · 20–35 GB · Whisper + Ollama llama3.1")
        self._space_max = QRadioButton("Maximum · 40–50 GB · also llava vision + keep every recording")
        self._space_lite = QRadioButton("Lite · 3–8 GB · Whisper only, cloud twin fallback")
        self._space_full.setChecked(True)
        for i, btn in enumerate((self._space_lite, self._space_full, self._space_max)):
            self._space_group.addButton(btn, i)
            lay.addWidget(btn)
        lay.addStretch(1)
        return w

    def _page_email(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body(
            "Email you will use on ElevenLabs / D-ID / fal. Use this same address when "
            "those sites ask you to sign up."
        ))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("you@example.com")
        lay.addWidget(self.email_input)
        lay.addStretch(1)
        return w

    def _page_cloud(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body(
            "Pop out a stay-on-top guide. It opens their sign-up page, then your inbox, "
            "then their API keys page, and pauses with what to click and paste. "
            "You click Create account and I'm not a robot — Heirloom cannot drive their site."
        ))
        self._cloud_status = QLabel("")
        self._cloud_status.setWordWrap(True)
        lay.addWidget(self._cloud_status)
        guide = QPushButton("Pop out the guide")
        guide.setObjectName("primary")
        guide.clicked.connect(self._start_coach)
        lay.addWidget(guide)
        lay.addStretch(1)
        return w

    def _page_phone(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body(
            "Pair your phone with the same Heirloom login. Inference stays on this PC."
        ))
        self._feat_boxes: dict[str, QCheckBox] = {}
        for fid, label in (
            ("twin", "Talk to twin"),
            ("capture", "Quick capture"),
            ("journal", "Voice journal"),
            ("reminders", "Reminders"),
        ):
            box = QCheckBox(label)
            box.setChecked(fid in self._phone_feats)
            self._feat_boxes[fid] = box
            lay.addWidget(box)
        gen = QPushButton("Generate pairing code")
        gen.setObjectName("primary")
        gen.clicked.connect(self._make_pair)
        lay.addWidget(gen)
        self.pair_label = QLabel("No code yet.")
        self.pair_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pair_label.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 28px; font-family: 'JetBrains Mono', monospace;"
        )
        lay.addWidget(self.pair_label)
        self.pair_url = QLabel("")
        self.pair_url.setWordWrap(True)
        self.pair_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.pair_url)
        lay.addStretch(1)
        return w

    def _page_finish(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body(
            "Finish downloads local models for your disk profile, then every feature is "
            "a dropdown in Models. Keep this window open while files download."
        ))
        self.finish_log = QLabel("Waiting to start…")
        self.finish_log.setWordWrap(True)
        lay.addWidget(self.finish_log)
        lay.addStretch(1)
        return w

    def _sync_nav(self) -> None:
        self.back_btn.setEnabled(self._page > 0)
        last = self._page >= len(PAGES) - 1
        self.next_btn.setText("Finish & download" if last else "Next")

    def _profile_id(self) -> str:
        checked = self._space_group.checkedId()
        return {0: "lite", 1: "full", 2: "max"}.get(checked, "full")

    def _collect_phone(self) -> list[str]:
        return [fid for fid, box in self._feat_boxes.items() if box.isChecked()]

    def _persist(self, extra: Optional[dict] = None) -> None:
        body = {
            "space_profile": self._profile_id(),
            "vendor_email": self.email_input.text().strip(),
            "prefer_local": True,
            "phone_features": self._collect_phone(),
        }
        if extra:
            body.update(extra)
        api.put_async("/studio/first-run", body)

    def _on_loaded(self, data: dict) -> None:
        self._payload = data or {}
        settings = (data or {}).get("settings") or {}
        email = settings.get("vendor_email") or ""
        if email:
            self.email_input.setText(email)

    def _start_coach(self) -> None:
        self._persist()
        email = self.email_input.text().strip().lower()
        if email:
            QApplication.clipboard().setText(email)
        payload = self._payload or {}
        keys = payload.get("keys") or {}
        handoffs = []
        for hid, h in (payload.get("handoffs") or {}).items():
            item = dict(h or {})
            item["already_saved"] = bool(keys.get(hid))
            handoffs.append(item)
        if not handoffs:
            self._cloud_status.setText("Could not load vendor guide yet. Go Back and Next to retry.")
            return
        from .vendor_coach import VendorCoachWindow

        self._coach = VendorCoachWindow(
            handoffs,
            email=email,
            parent=self,
            on_saved=lambda: api.get_async("/studio/first-run", on_ok=self._on_loaded),
        )
        self._coach.show()
        self._cloud_status.setText(
            "Guide is pinned on top. Follow it while you use the browser. "
            "You click Create account and I'm not a robot."
        )

    def _make_pair(self) -> None:
        self._persist()
        api.post_async(
            "/studio/first-run/pair",
            {},
            on_ok=self._on_pair,
            on_err=lambda m: QMessageBox.warning(self, "Pairing", m),
        )

    def _on_pair(self, data: dict) -> None:
        self._pair_code = data.get("code") or ""
        self.pair_label.setText(self._pair_code or "—")
        self.pair_url.setText(data.get("url") or "")

    def _back(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.stack.setCurrentIndex(self._page)
            self._sync_nav()

    def _next(self) -> None:
        if self._page < len(PAGES) - 1:
            self._persist()
            self._page += 1
            self.stack.setCurrentIndex(self._page)
            self._sync_nav()
            return
        self._finish()

    def _skip(self) -> None:
        s = config.load_settings()
        s["setup_skipped"] = True
        config.save_settings(s)
        self.reject()

    def _finish(self) -> None:
        self._persist()
        api.post_async(
            "/studio/first-run/complete",
            {},
            on_ok=self._on_complete_ok,
            on_err=lambda m: QMessageBox.warning(self, "Setup", m),
        )

    def _on_complete_ok(self, data: dict) -> None:
        features = ((data or {}).get("space_profile") or {}).get("provision_features") or [
            "stt",
            "tts",
            "twin",
        ]
        self.finish_log.setText("Downloading local models…")
        self._prov = _ProvisionThread(list(features), self)
        self._prov.line.connect(lambda m: self.finish_log.setText(m))
        self._prov.done.connect(self._on_provisioned)
        self._prov.start()

    def _on_provisioned(self, probe: dict) -> None:
        s = config.load_settings()
        s["setup_complete"] = True
        s["setup_skipped"] = False
        config.save_settings(s)
        err = probe.get("error")
        if err:
            QMessageBox.warning(self, "Models", f"Setup saved, but a download failed:\n{err}")
        self.accept()
