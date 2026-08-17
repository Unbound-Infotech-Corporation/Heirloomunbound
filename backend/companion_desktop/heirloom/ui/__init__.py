"""Heirloom desktop — colour palette + Qt stylesheet.

Elite mode: everything on this canvas assumes a frameless window sitting on
Windows 11 Mica. The root bg is transparent so the OS tint bleeds through;
panels get their own semi-opaque surfaces layered on top. On Win10 (no
Mica) the QSS falls back cleanly because the palette values still resolve
to a valid solid dark theme.
"""

# Palette (warm serif · dark parchment)
PALETTE = {
    "bg_base": "#121110",
    "bg_surface": "#1d1b18",
    "bg_elevated": "#262320",
    # Semi-transparent surface variants used when Mica is active
    "bg_glass": "rgba(24, 22, 20, 0.72)",
    "bg_glass_high": "rgba(35, 32, 28, 0.78)",
    "text_primary": "#f5efe6",
    "text_secondary": "#beb4a8",
    "text_muted": "#7e7468",
    "text_inverse": "#121110",
    "accent": "#d4a373",
    "accent_hover": "#c79360",
    "accent_muted": "#3a2c1e",
    "border": "#3a342e",
    "border_soft": "rgba(255, 245, 230, 0.06)",
    "error": "#c0635a",
    "ok": "#7da06f",
}

QSS = f"""
* {{
    color: {PALETTE['text_primary']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

/* Root — transparent so Mica shows through */
QWidget#root {{ background: transparent; }}
QMainWindow {{ background: transparent; }}

/* Bordered card that wraps everything on top of Mica */
QWidget#card {{
    background: {PALETTE['bg_glass']};
    border-radius: 12px;
    border: 1px solid {PALETTE['border_soft']};
}}

/* Panels sit on the glass */
QWidget#titlebar {{
    background: transparent;
    border-bottom: 1px solid {PALETTE['border_soft']};
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}

QWidget#sidebar {{
    background: rgba(255, 245, 230, 0.02);
    border-right: 1px solid {PALETTE['border_soft']};
}}

QWidget#quickcap {{
    background: rgba(255, 245, 230, 0.02);
    border-left: 1px solid {PALETTE['border_soft']};
}}

QWidget#avatar_panel {{
    background: rgba(255, 245, 230, 0.02);
    border-radius: 4px;
}}

QWidget#statuspill {{
    background: rgba(255, 245, 230, 0.03);
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 14px;
}}

/* Typography helpers */
QLabel#brand {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 22px;
    color: {PALETTE['text_primary']};
}}

QLabel.overline, QLabel[class="overline"] {{
    color: {PALETTE['text_muted']};
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 9px;
    letter-spacing: 3px;
}}

QLabel.section-title {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 18px;
    color: {PALETTE['text_primary']};
}}

QLabel.muted {{ color: {PALETTE['text_muted']}; }}

/* Buttons */
QPushButton {{
    background: transparent;
    color: {PALETTE['text_secondary']};
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 6px;
    padding: 8px 14px;
}}

QPushButton:hover {{
    color: {PALETTE['accent']};
    border-color: {PALETTE['accent']};
    background: rgba(212, 163, 115, 0.06);
}}

QPushButton:pressed {{
    background: rgba(212, 163, 115, 0.14);
    padding: 9px 14px 7px 14px;  /* nudge to feel pressable */
}}

QPushButton#primary {{
    background: {PALETTE['accent']};
    color: {PALETTE['text_inverse']};
    border: 1px solid {PALETTE['accent']};
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton#primary:hover {{
    background: {PALETTE['accent_hover']};
    border-color: {PALETTE['accent_hover']};
}}

QPushButton#ghost {{
    border: none;
    color: {PALETTE['text_muted']};
    padding: 6px 10px;
}}
QPushButton#ghost:hover {{
    color: {PALETTE['accent']};
    background: transparent;
}}

/* Titlebar controls */
QPushButton#kbdhint {{
    color: {PALETTE['text_muted']};
    background: rgba(255, 245, 230, 0.03);
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 6px;
    padding: 4px 10px;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 1.5px;
}}
QPushButton#kbdhint:hover {{
    color: {PALETTE['accent']};
    border-color: {PALETTE['accent']};
}}

QPushButton#ptt {{
    background: rgba(212, 163, 115, 0.14);
    color: {PALETTE['accent']};
    border: 1px solid {PALETTE['accent']};
    border-radius: 6px;
    padding: 6px 16px;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 2px;
}}
QPushButton#ptt:hover {{ background: rgba(212, 163, 115, 0.28); }}
QPushButton#ptt:pressed {{
    background: {PALETTE['accent']};
    color: {PALETTE['text_inverse']};
}}

QPushButton#titleicon {{
    background: transparent;
    color: {PALETTE['text_muted']};
    border: none;
    border-radius: 6px;
    font-size: 15px;
}}
QPushButton#titleicon:hover {{
    color: {PALETTE['accent']};
    background: rgba(255, 245, 230, 0.05);
}}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 6px;
    padding: 9px 12px;
    selection-background-color: {PALETTE['accent_muted']};
    color: {PALETTE['text_primary']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {PALETTE['accent']};
    background: rgba(0, 0, 0, 0.36);
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {PALETTE['bg_surface']};
    border: 1px solid {PALETTE['border']};
    selection-background-color: {PALETTE['accent_muted']};
}}

/* Scroll areas */
QScrollArea {{ border: none; background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 245, 230, 0.06);
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {PALETTE['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: rgba(255, 245, 230, 0.06); border-radius: 4px; min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Splitter — hairline that fades on hover */
QSplitter::handle {{ background: {PALETTE['border_soft']}; }}
QSplitter::handle:hover {{ background: {PALETTE['accent']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* Conversation bubbles / flat rows */
QFrame#bubble_user {{
    background: rgba(212, 163, 115, 0.18);
    border: 1px solid rgba(212, 163, 115, 0.32);
    border-radius: 14px;
}}
QFrame#bubble_assistant {{
    background: rgba(255, 245, 230, 0.04);
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 14px;
}}
QFrame#flat_user, QFrame#flat_assistant {{
    background: transparent;
    border: none;
    border-left: 2px solid {PALETTE['border']};
    border-radius: 0;
}}
QFrame#flat_user {{ border-left-color: {PALETTE['accent']}; }}

QLabel#role {{
    color: {PALETTE['text_muted']};
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 9px;
    letter-spacing: 2px;
    text-transform: uppercase;
}}

/* Menu (tray + context) */
QMenu {{
    background: {PALETTE['bg_surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 6px;
    color: {PALETTE['text_primary']};
}}
QMenu::item {{
    padding: 7px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: rgba(212, 163, 115, 0.18);
    color: {PALETTE['accent']};
}}
QMenu::separator {{
    height: 1px;
    background: {PALETTE['border_soft']};
    margin: 4px 8px;
}}

QToolTip {{
    background: {PALETTE['bg_elevated']};
    color: {PALETTE['text_primary']};
    border: 1px solid {PALETTE['border']};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 11px;
}}

/* Photoshop-style MDI */
QMdiArea {{
    background: #1a1917;
    border: none;
}}
QMdiSubWindow {{
    background: {PALETTE['bg_surface']};
    border: 1px solid {PALETTE['border']};
    color: {PALETTE['text_primary']};
}}
QMdiSubWindow:title {{
    background: #2a2724;
}}
QWidget#mdi_body {{
    background: {PALETTE['bg_surface']};
}}
QMenuBar {{
    background: #2a2724;
    color: {PALETTE['text_secondary']};
    border-bottom: 1px solid {PALETTE['border_soft']};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: rgba(212, 163, 115, 0.18);
    color: {PALETTE['accent']};
}}
QGroupBox {{
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 8px 8px 8px;
    color: {PALETTE['text_secondary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {PALETTE['text_muted']};
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 1px;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(255, 245, 230, 0.08);
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -5px 0;
    background: {PALETTE['accent']};
    border-radius: 6px;
}}
QProgressBar {{
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid {PALETTE['border_soft']};
    border-radius: 4px;
    text-align: center;
    color: {PALETTE['text_muted']};
    height: 16px;
}}
QProgressBar::chunk {{
    background: {PALETTE['accent']};
}}
QCheckBox {{
    color: {PALETTE['text_secondary']};
    spacing: 8px;
}}
"""
