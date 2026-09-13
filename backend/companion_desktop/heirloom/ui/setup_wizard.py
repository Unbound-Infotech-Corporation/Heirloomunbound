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
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..models import provision
from ..space_profiles import recommend_profile, space_profile
from ..vendor_handoffs import local_handoffs, provision_features
from ..vault import vault_root
from . import PALETTE, QSS

PAGES = ("welcome", "space", "dedicated", "email", "phone", "finish", "cloud")
_RADIO_ORDER = ("small", "medium", "large", "dedicated")


def _free_gb(path) -> Optional[float]:
    try:
        usage = shutil.disk_usage(path)
        return usage.free / (1024 ** 3)
    except Exception:
        return None


class _ProvisionThread(QThread):
    line = Signal(str)
    done = Signal(dict)

    def __init__(self, features: list[str], profile_id: str = "medium", parent=None):
        super().__init__(parent)
        self._features = features
        self._profile_id = profile_id

    def run(self) -> None:
        def note(msg: str) -> None:
            self.line.emit(msg)

        try:
            probe = provision(self._features, progress=note, profile_id=self._profile_id)
            self.done.emit(probe if isinstance(probe, dict) else {"log": [str(probe)]})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class FirstRunWizard(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(QSS)
        self.setWindowTitle("Heirloom Unbound · First-run setup")
        self.setModal(True)
        self.resize(760, 680)
        self._page = 0
        self._email = ""
        self._profile = "medium"
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
        over = QLabel("HEIRLOOM UNBOUND · FIRST USE")
        over.setProperty("class", "overline")
        title = QLabel("Set up Heirloom Unbound once")
        title.setObjectName("brand")
        root.addWidget(over)
        root.addWidget(title)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_space())
        self.stack.addWidget(self._page_dedicated())
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
        rec = recommend_profile(free) if free is not None else "medium"
        rec_label = space_profile(rec)["label"]
        free_txt = f"{free:.0f} GB free on this drive." if free is not None else "Could not read free disk."
        lay.addWidget(self._body(
            "Heirloom Unbound Setup feels like a studio installer: pick an install "
            f"size, then we download models onto this PC. {free_txt} Suggested: {rec_label}.\n\n"
            "Small (~5–12 GB) works without a GPU. Large is 100–160 GB of local goods. "
            "Dedicated PC consecrates this machine for the twin.\n\n"
            "Local models stay on this computer. Cloud vendors (ElevenLabs, D-ID, fal) "
            "come after downloads. You click Create account and I'm not a robot — "
            "Heirloom Unbound cannot sign up on those sites or read keys off the screen."
        ))
        lay.addStretch(1)
        return w

    def _page_space(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body("Choose an Heirloom Unbound install size. Downloads resume if they pause."))
        self._space_group = QButtonGroup(self)
        radios = {
            "small": "Small · 5–12 GB · Whisper + Piper + lite vault. Twin/TTS/avatar stay cloud Auto. No GPU.",
            "medium": "Medium · 40–70 GB · Small + Ollama llama3.1 + one voice-clone path (Qwen3-TTS 0.6B or Voicebox).",
            "large": "Large · 100–160 GB · Whisper large-v3, stronger twin + vision, Voicebox AND Qwen3-TTS 1.7B, LatentSync.",
            "dedicated": "Dedicated PC · 200 GB+ · Everything in Large, plus this machine exists for Heirloom Unbound.",
        }
        self._space_btns: dict[str, QRadioButton] = {}
        for i, pid in enumerate(_RADIO_ORDER):
            btn = QRadioButton(radios[pid])
            btn.setWordWrap(True)
            if pid == "medium":
                btn.setChecked(True)
            self._space_group.addButton(btn, i)
            self._space_btns[pid] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        return w

    def _page_dedicated(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._body(
            "This PC exists for Heirloom Unbound. The twin lives here: models stay "
            "warm, the vault prefers a second disk, and Windows can start Heirloom "
            "Unbound when you sign in. You can still turn live listen off later."
        ))
        self._ded_consent = QCheckBox("This PC exists for Heirloom Unbound")
        self._ded_consent.setChecked(True)
        lay.addWidget(self._ded_consent)

        lay.addWidget(self._body("Vault / data drive (a second disk is recommended)."))
        drive_row = QHBoxLayout()
        self._vault_drive = QLineEdit()
        self._vault_drive.setPlaceholderText(str(vault_root()))
        browse = QPushButton("Browse…")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._browse_vault)
        drive_row.addWidget(self._vault_drive, 1)
        drive_row.addWidget(browse)
        lay.addLayout(drive_row)

        self._ded_startup = QCheckBox("Start Heirloom Unbound with Windows (this user)")
        self._ded_startup.setChecked(True)
        lay.addWidget(self._ded_startup)
        lay.addWidget(self._body(
            "Optional always-on service: Task Scheduler can keep Heirloom Unbound "
            "warm when nobody is signed in. Setup does not install a Windows service."
        ))
        self._ded_power = QCheckBox("Apply the high-performance power plan (I consent — do not silently fight IT policy)")
        self._ded_power.setChecked(False)
        lay.addWidget(self._ded_power)
        self._ded_warm = QCheckBox("Warm Ollama, Voicebox, Qwen3-TTS, and LatentSync listeners")
        self._ded_warm.setChecked(True)
        lay.addWidget(self._ded_warm)
        self._ded_listen = QCheckBox("Default standing routines and live room listen toward on (still togglable)")
        self._ded_listen.setChecked(True)
        lay.addWidget(self._ded_listen)
        self._ded_brand = QCheckBox("Optional desktop / lock mark: Heirloom Unbound · Dedicated")
        self._ded_brand.setChecked(False)
        lay.addWidget(self._ded_brand)
        lay.addWidget(self._body("Overnight maintenance will re-check models so this dedicated PC stays current."))
        lay.addStretch(1)
        return w

    def _browse_vault(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Heirloom Unbound vault drive", self._vault_drive.text() or str(vault_root()))
        if picked:
            self._vault_drive.setText(picked)

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
            "Download local models for your Heirloom Unbound install size. "
            "Partial downloads resume. An engine that fails gets a coach line — "
            "Setup does not abort unless the app itself cannot be written."
        ))
        self.finish_log = QPlainTextEdit()
        self.finish_log.setReadOnly(True)
        self.finish_log.setPlainText("Waiting to start…")
        self.finish_log.setStyleSheet(
            f"font-family: 'JetBrains Mono', 'Cascadia Mono', Consolas, monospace; "
            f"font-size: 12px; color: {PALETTE['text_secondary']}; "
            f"background: {PALETTE['bg_elevated']};"
        )
        lay.addWidget(self.finish_log, 1)
        lay.addStretch(1)
        return w

    def _log_line(self, msg: str) -> None:
        cur = self.finish_log.toPlainText().strip()
        if cur in {"", "Waiting to start…"}:
            self.finish_log.setPlainText(msg)
        else:
            self.finish_log.appendPlainText(msg)
        self.finish_log.verticalScrollBar().setValue(self.finish_log.verticalScrollBar().maximum())

    def _page_visible(self, page_id: str) -> bool:
        if page_id == "dedicated":
            return self._profile_id() == "dedicated"
        return True

    def _step(self, delta: int) -> None:
        idx = self._page
        while True:
            idx += delta
            if idx < 0 or idx >= len(PAGES):
                return
            if self._page_visible(PAGES[idx]):
                self._page = idx
                self.stack.setCurrentIndex(self._page)
                self._sync_nav()
                if PAGES[self._page] == "cloud":
                    self._start_coach()
                return

    def _sync_nav(self) -> None:
        page_id = PAGES[self._page]
        self.back_btn.setEnabled(self._page > 0 and not self._downloading)
        self.next_btn.setEnabled(not self._downloading)
        if page_id == "dedicated":
            self.next_btn.setText("Consecrate this PC")
        elif page_id == "finish" and not self._provisioned:
            self.next_btn.setText("Download models")
        elif page_id == "cloud":
            self.next_btn.setText("Done")
        else:
            self.next_btn.setText("Next")

    def _profile_id(self) -> str:
        checked = self._space_group.checkedId()
        if 0 <= checked < len(_RADIO_ORDER):
            return _RADIO_ORDER[checked]
        return "medium"

    def _collect_phone(self) -> list[str]:
        return [fid for fid, box in self._feat_boxes.items() if box.isChecked()]

    def _persist(self, extra: Optional[dict] = None) -> None:
        pid = self._profile_id()
        body = {
            "space_profile": pid,
            "install_profile": pid,
            "vendor_email": self.email_input.text().strip(),
            "prefer_local": True,
            "phone_features": self._collect_phone(),
        }
        if pid == "dedicated" and hasattr(self, "_ded_consent"):
            body.update(
                {
                    "dedicated_consent": self._ded_consent.isChecked(),
                    "vault_drive": self._vault_drive.text().strip(),
                    "start_with_windows": self._ded_startup.isChecked(),
                    "power_plan_consent": self._ded_power.isChecked(),
                    "warm_engines": self._ded_warm.isChecked(),
                    "live_listen_default": self._ded_listen.isChecked(),
                    "branding_dedicated": self._ded_brand.isChecked(),
                }
            )
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

    def _on_load_err(self, _msg: str) -> None:
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
            self._step(-1)

    def _next(self) -> None:
        page_id = PAGES[self._page]
        if page_id == "dedicated" and not self._ded_consent.isChecked():
            QMessageBox.information(
                self,
                "Heirloom Unbound",
                "Dedicated PC needs the consent that this computer exists for Heirloom Unbound.",
            )
            return
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
        if page_id == "dedicated":
            self._apply_dedicated()
        self._step(1)

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

    def _apply_dedicated(self) -> None:
        try:
            from ..dedicated import apply_machine_role

            apply_machine_role(
                consent=self._ded_consent.isChecked(),
                vault_drive=self._vault_drive.text().strip(),
                start_with_windows=self._ded_startup.isChecked(),
                power_plan_consent=self._ded_power.isChecked(),
                warm_engines=self._ded_warm.isChecked(),
                live_listen=self._ded_listen.isChecked(),
                branding=self._ded_brand.isChecked(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Dedicated PC", str(exc))

    def _complete_missing(self, _msg: str) -> None:
        """Local models still install when /api/studio/first-run is not on this cloud."""
        self._cloud_offline = True
        self._log_line("Cloud has no first-run API yet. Downloading local models on this PC anyway…")
        self._on_complete_ok(
            {"space_profile": {"provision_features": provision_features(self._profile_id())}}
        )


    def _on_complete_ok(self, data: dict) -> None:
        pid = self._profile_id()
        features = ((data or {}).get("space_profile") or {}).get("provision_features") or provision_features(pid)
        self._log_line(f"Downloading Heirloom Unbound · {space_profile(pid)['label']}…")
        self._prov = _ProvisionThread(list(features), pid, self)
        self._prov.line.connect(self._log_line)
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
            self._log_line(f"coach: {err}")
        else:
            self._log_line("Models ready. Opening the vendor guide…")
        if self._profile_id() == "dedicated":
            s = config.load_settings()
            s["install_profile"] = "dedicated"
            config.save_settings(s)
            self._log_line("install_profile: dedicated")
        self._goto_page("cloud")

    def _complete_setup(self) -> None:
        self._persist({"complete": True})
        s = config.load_settings()
        s["setup_complete"] = True
        s["setup_skipped"] = False
        pid = self._profile_id()
        s["space_profile"] = pid
        s["install_profile"] = pid
        if pid == "dedicated":
            s["machine_role"] = "dedicated"
        config.save_settings(s)
        self.accept()
