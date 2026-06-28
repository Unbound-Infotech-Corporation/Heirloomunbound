"""Heirloom desktop — colour palette + Qt stylesheet.

Matches the web app's serif/quiet aesthetic: warm parchment background, the
soft `--accent` rose-gold, generous whitespace, no garish accents.
"""

# Mirrors the web app's CSS variables
PALETTE = {
    "bg_base": "#121110",
    "bg_surface": "#1d1b18",
    "bg_elevated": "#262320",
    "text_primary": "#f5efe6",
    "text_secondary": "#beb4a8",
    "text_muted": "#7e7468",
    "text_inverse": "#121110",
    "accent": "#d4a373",
    "accent_muted": "#3a2c1e",
    "border": "#3a342e",
    "error": "#c0635a",
    "ok": "#7da06f",
}

QSS = f"""
* {{
    color: {PALETTE['text_primary']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QMainWindow, QWidget#root {{
    background: {PALETTE['bg_base']};
}}

QWidget#sidebar, QWidget#quickcap, QWidget#titlebar {{
    background: {PALETTE['bg_surface']};
}}

QWidget#avatar_panel {{
    background: {PALETTE['bg_surface']};
    border-radius: 4px;
}}

QLabel#brand {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 22px;
    color: {PALETTE['text_primary']};
}}

QLabel.overline {{
    color: {PALETTE['text_muted']};
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
}}

QLabel.section-title {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 18px;
    color: {PALETTE['text_primary']};
}}

QLabel.muted {{
    color: {PALETTE['text_muted']};
}}

QPushButton {{
    background: transparent;
    color: {PALETTE['text_secondary']};
    border: 1px solid {PALETTE['border']};
    border-radius: 3px;
    padding: 7px 14px;
}}

QPushButton:hover {{
    color: {PALETTE['accent']};
    border-color: {PALETTE['accent']};
}}

QPushButton#primary {{
    background: {PALETTE['accent']};
    color: {PALETTE['text_inverse']};
    border: 1px solid {PALETTE['accent']};
}}

QPushButton#primary:hover {{
    background: #c79360;
}}

QPushButton#ghost {{
    border: none;
    color: {PALETTE['text_muted']};
}}

QPushButton#ghost:hover {{
    color: {PALETTE['accent']};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {PALETTE['bg_base']};
    border: 1px solid {PALETTE['border']};
    border-radius: 3px;
    padding: 8px 10px;
    selection-background-color: {PALETTE['accent_muted']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {PALETTE['accent']};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE['border']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PALETTE['accent']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QSplitter::handle {{
    background: {PALETTE['border']};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}

QFrame#bubble_user {{
    background: {PALETTE['accent_muted']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
}}

QFrame#bubble_assistant {{
    background: {PALETTE['bg_elevated']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
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
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
}}
"""
