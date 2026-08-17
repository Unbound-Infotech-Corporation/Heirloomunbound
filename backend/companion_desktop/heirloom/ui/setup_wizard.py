"""First-launch wizard for the dedicated PC.

Walks disk budget, vendor email, phone pairing, then local model download.
After models are in, a stay-on-top vendor guide watches the screen (same
path as twin see_screen) while the human clicks robot / verify. Does not
automate third-party account creation or scrape API keys.
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
from ..vendor_handoffs import local_handoffs, provision_features
from ..vault import vault_root
from . import PALETTE, QSS

PAGES = ("welcome", "space", "email", "phone", "finish", "cloud")


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
        self._provisioned = False
        self._downloading = False
        self._cloud_offline = False
        self._build()
        api.get_async("/studio/first-run", on_ok=self._on_loaded, on_err=self._on_load_err)

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
        self.stack.addWidget(self._page_phone())
        self.stack.addWidget(self._page_finish())
        self.stack.addWidget(self._page_cloud())
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
            "Cloud vendors (ElevenLabs, D-ID, fal) come after local models download, "
            "so screen vision is ready. Heirloom opens official pages and watches the "
            "screen. You click Create account and I'm not a robot — it cannot sign up "
            "on those sites or read keys off the screen."
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
            "Local models are installed. A stay-on-top guide opens their sign-up page, "
            "then your inbox, then API keys, and watches the screen to move on. "
            "You click Create account and I'm not a robot — Heirloom cannot drive their site "
            "or copy keys from the screenshot."
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
            "Download local models for your disk profile first. After that, the vendor "
            "guide can watch the screen. Keep this window open while files download."
        ))
        self.finish_log = QLabel("Waiting to start…")
        self.finish_log.setWordWrap(True)
        lay.addWidget(self.finish_log)
        lay.addStretch(1)
        return w

    def _sync_nav(self) -> None:
        page_id = PAGES[self._page]
        self.back_btn.setEnabled(self._page > 0 and not self._downloading)
        self.next_btn.setEnabled(not self._downloading)
        if page_id == "finish" and not self._provisioned:
            self.next_btn.setText("Download models")
        elif page_id == "cloud":
            self.next_btn.setText("Done")
        else:
            self.next_btn.setText("Next")

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
        self._cloud_offline = False
        self._payload = data or {}
        settings = (data or {}).get("settings") or {}
        email = settings.get("vendor_email") or ""
        if email:
            self.email_input.setText(email)

    def _on_load_err(self, msg: str) -> None:
        if api.is_not_found_error(msg):
            self._cloud_offline = True

    def _coach_handoffs(self, email: str) -> list[dict]:
        payload = self._payload or {}
        keys = payload.get("keys") or {}
        handoffs = []
        raw = payload.get("handoffs") or {}
        if isinstance(raw, dict):
            items = raw.items()
        elif isinstance(raw, list):
            items = ((h.get("id"), h) for h in raw if isinstance(h, dict))
        else:
            items = ()
        for hid, h in items:
            item = dict(h or {})
            item["id"] = item.get("id") or hid
            item["already_saved"] = bool(keys.get(hid) or keys.get(item.get("id")))
            handoffs.append(item)
        if handoffs:
            return handoffs
        return local_handoffs(email)

    def _start_coach(self) -> None:
        if self._coach is not None and self._coach.isVisible():
            self._coach.raise_()
            self._coach.activateWindow()
            return
        self._persist()
        email = self.email_input.text().strip().lower()
        if email:
            QApplication.clipboard().setText(email)
        handoffs = self._coach_handoffs(email)
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
        if self._cloud_offline:
            self._cloud_status.setText(
                "Guide is pinned on top. This cloud is an older Heirloom — "
                "screen watch and phone pairing wait for a server deploy. "
                "You still click Create account and I'm not a robot."
            )
        else:
            self._cloud_status.setText(
                "Guide is pinned on top and watching the screen. "
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
        page_id = PAGES[self._page]
        if page_id == "finish":
            if self._provisioned:
                self._goto_page("cloud")
                return
            self._start_download()
            return
        if page_id == "cloud":
            self._complete_setup()
            return
        self._persist()
        self._page += 1
        self.stack.setCurrentIndex(self._page)
        self._sync_nav()
        if PAGES[self._page] == "cloud":
            self._start_coach()

    def _goto_page(self, page_id: str) -> None:
        if page_id not in PAGES:
            return
        self._page = PAGES.index(page_id)
        self.stack.setCurrentIndex(self._page)
        self._sync_nav()
        if page_id == "cloud":
            self._start_coach()

    def _skip(self) -> None:
        s = config.load_settings()
        s["setup_skipped"] = True
        config.save_settings(s)
        self.reject()

    def _start_download(self) -> None:
        self._persist()
        self._downloading = True
        self._sync_nav()
        api.post_async(
            "/studio/first-run/complete",
            {},
            on_ok=self._on_complete_ok,
            on_err=self._complete_missing,
        )

    def _complete_missing(self, msg: str) -> None:
        """Fall back to local-only when this cloud has no /api/studio/first-run."""
        if not api.is_not_found_error(msg):
            self._download_err(msg)
            return
        self._cloud_offline = True
        self.finish_log.setText(
            "Cloud has no first-run API yet. Downloading local models on this PC anyway…"
        )
        self._on_complete_ok(
            {"space_profile": {"provision_features": provision_features(self._profile_id())}}
        )

    def _download_err(self, msg: str) -> None:
        self._downloading = False
        self._sync_nav()
        QMessageBox.warning(self, "Setup", msg)

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
        self._downloading = False
        self._provisioned = True
        err = probe.get("error")
        if err:
            QMessageBox.warning(
                self,
                "Models",
                f"A download failed:\n{err}\n\nThe vendor guide still opens. "
                "Screen watch uses cloud vision when local llava is missing.",
            )
        else:
            self.finish_log.setText("Models ready. Opening the vendor guide…")
        self._goto_page("cloud")

    def _complete_setup(self) -> None:
        self._persist({"complete": True})
        s = config.load_settings()
        s["setup_complete"] = True
        s["setup_skipped"] = False
        config.save_settings(s)
        self.accept()
