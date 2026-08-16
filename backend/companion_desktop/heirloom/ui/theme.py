"""Theme system for the Heirloom desktop.

Design goal: every color, radius and spacing token lives here. Widgets never
reach for a raw hex — they read `PALETTE` (mutable) or use QSS classes so that
`apply_theme()` truly reloads the whole app.

Contract:
    * PALETTE is a mutable module-level dict. It ALWAYS has the same keys.
    * Curated themes live in THEMES.
    * A "custom" theme is stored under the special key "custom" and is
      merged over the "amber_library" base so unknown keys never break.
    * `apply_theme(app, name, custom=None)` mutates PALETTE in place and
      re-applies the generated QSS to the QApplication + all top-level windows.
    * The QSS is derived from PALETTE via `build_qss()`; call it after any
      palette mutation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtWidgets import QApplication, QWidget

# ------------------------------------------------------------------
# Curated palettes
# ------------------------------------------------------------------
# All palettes share the same key set. The visual language matches the
# HTML mockup the owner supplied: deep-ink canvas, warm amber accent,
# high-contrast parchment text, subtle borders.
_KEYS = (
    "bg_base",       # window canvas
    "bg_surface",    # elevated card / panel
    "bg_elevated",   # extra-lifted (menus, tooltips)
    "bg_glass",      # semi-opaque over Mica
    "bg_glass_high", # slightly denser glass for panels
    "text_primary",  # main copy
    "text_secondary",# body support
    "text_muted",    # metadata / overlines
    "text_inverse",  # text on top of accent
    "accent",        # brand color
    "accent_hover",
    "accent_muted",  # low-alpha accent tint background
    "accent_deep",   # deep accent background — twin bubble, badges
    "border",
    "border_soft",   # hairline / rgba border for dark surfaces
    "user_bubble",   # user chat bubble bg
    "twin_bubble",   # twin chat bubble bg
    "error",
    "ok",
)

THEMES: Dict[str, Dict[str, str]] = {
    # 1) The mockup the owner supplied. This is the new default — deeper
    #    canvas + brighter amber + higher-contrast body copy than the old
    #    dim palette.
    "amber_library": {
        "bg_base":       "#0f0e0c",
        "bg_surface":    "#1a1712",
        "bg_elevated":   "#22201c",
        "bg_glass":      "rgba(26, 23, 18, 0.78)",
        "bg_glass_high": "rgba(34, 32, 28, 0.86)",
        "text_primary":  "#f3ede4",
        "text_secondary":"#c9c0b2",
        "text_muted":    "#a39a8c",
        "text_inverse":  "#1a1712",
        "accent":        "#e8a95c",
        "accent_hover":  "#f0b968",
        "accent_muted":  "rgba(232, 169, 92, 0.14)",
        "accent_deep":   "#3a2a1a",
        "border":        "#2a2723",
        "border_soft":   "rgba(243, 237, 228, 0.08)",
        "user_bubble":   "#2a2723",
        "twin_bubble":   "#3a2a1a",
        "error":         "#c0635a",
        "ok":            "#7da06f",
    },
    # 2) Cool graphite — feels like Linear / Cursor
    "slate_pro": {
        "bg_base":       "#0d1117",
        "bg_surface":    "#161b22",
        "bg_elevated":   "#1c2129",
        "bg_glass":      "rgba(22, 27, 34, 0.80)",
        "bg_glass_high": "rgba(28, 33, 41, 0.88)",
        "text_primary":  "#e6edf3",
        "text_secondary":"#c3ccd6",
        "text_muted":    "#8b98a5",
        "text_inverse":  "#0d1117",
        "accent":        "#5b9dff",
        "accent_hover":  "#79b0ff",
        "accent_muted":  "rgba(91, 157, 255, 0.14)",
        "accent_deep":   "#1c3a66",
        "border":        "#2a2f37",
        "border_soft":   "rgba(230, 237, 243, 0.08)",
        "user_bubble":   "#22272e",
        "twin_bubble":   "#1c3a66",
        "error":         "#f47067",
        "ok":            "#66c07f",
    },
    # 3) Warm parchment on charcoal — feels like Obsidian / Craft
    "ivory_library": {
        "bg_base":       "#1a1815",
        "bg_surface":    "#25221e",
        "bg_elevated":   "#2f2b26",
        "bg_glass":      "rgba(37, 34, 30, 0.82)",
        "bg_glass_high": "rgba(47, 43, 38, 0.88)",
        "text_primary":  "#faf3e6",
        "text_secondary":"#d6cdba",
        "text_muted":    "#a89e88",
        "text_inverse":  "#1a1815",
        "accent":        "#c9884d",
        "accent_hover":  "#d99a5f",
        "accent_muted":  "rgba(201, 136, 77, 0.14)",
        "accent_deep":   "#4a341e",
        "border":        "#3a342c",
        "border_soft":   "rgba(250, 243, 230, 0.08)",
        "user_bubble":   "#332e28",
        "twin_bubble":   "#4a341e",
        "error":         "#c0635a",
        "ok":            "#7da06f",
    },
    # 4) Cool blue-gray — feels like JetBrains / iA Writer night mode
    "nordic_mist": {
        "bg_base":       "#0f141a",
        "bg_surface":    "#181f28",
        "bg_elevated":   "#1f2833",
        "bg_glass":      "rgba(24, 31, 40, 0.80)",
        "bg_glass_high": "rgba(31, 40, 51, 0.86)",
        "text_primary":  "#e5edf5",
        "text_secondary":"#b8c4d3",
        "text_muted":    "#7a8797",
        "text_inverse":  "#0f141a",
        "accent":        "#88c0d0",
        "accent_hover":  "#a4d0dd",
        "accent_muted":  "rgba(136, 192, 208, 0.14)",
        "accent_deep":   "#2c4a56",
        "border":        "#2a3441",
        "border_soft":   "rgba(229, 237, 245, 0.08)",
        "user_bubble":   "#232c37",
        "twin_bubble":   "#2c4a56",
        "error":         "#bf616a",
        "ok":            "#a3be8c",
    },
    # 5) Painted playroom — cream wood on a walnut table. Optional toy look.
    "playroom": {
        "bg_base":       "#2a1c12",
        "bg_surface":    "#f4e8c8",
        "bg_elevated":   "#fff6d8",
        "bg_glass":      "rgba(244, 232, 200, 0.92)",
        "bg_glass_high": "rgba(255, 246, 216, 0.94)",
        "text_primary":  "#3a2418",
        "text_secondary":"#5c4030",
        "text_muted":    "#8a6a4a",
        "text_inverse":  "#fff8e8",
        "accent":        "#e24a3a",
        "accent_hover":  "#f05a48",
        "accent_muted":  "rgba(226, 74, 58, 0.16)",
        "accent_deep":   "#c9a227",
        "border":        "#d4b88a",
        "border_soft":   "rgba(58, 36, 24, 0.14)",
        "user_bubble":   "#ffe8a0",
        "twin_bubble":   "#ffd4c8",
        "error":         "#c0392b",
        "ok":            "#3d9a4a",
    },
}

DEFAULT_THEME = "amber_library"

# The live palette. Mutated by apply_theme(). Widgets should READ from this
# but understand that inline `setStyleSheet(f"color: {PALETTE['x']}")` calls
# will only refresh on window rebuild — prefer QSS classes for live-swap.
PALETTE: Dict[str, str] = dict(THEMES[DEFAULT_THEME])


def resolve(name: str, custom: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return a full palette dict for the given theme name.

    * `name == "custom"` merges `custom` on top of the amber base so the caller
      can supply just {accent, bg_base, text_primary} and everything else
      still resolves.
    * Unknown names silently fall back to the default — keeps a broken
      settings file from crashing the app.
    """
    if name == "custom":
        base = dict(THEMES[DEFAULT_THEME])
        for k, v in (custom or {}).items():
            if k in _KEYS and isinstance(v, str) and v.strip():
                base[k] = v.strip()
        return base
    return dict(THEMES.get(name, THEMES[DEFAULT_THEME]))


def build_qss(p: Dict[str, str]) -> str:
    """Generate the app-wide stylesheet from a palette dict.

    All widget styling goes through this so a theme change only needs one
    `app.setStyleSheet(build_qss(...))` call to update every widget that
    isn't holding its own inline stylesheet.
    """
    return f"""
* {{
    color: {p['text_primary']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QWidget#root {{ background: transparent; }}
QMainWindow {{ background: transparent; }}

QWidget#card {{
    background: {p['bg_glass']};
    border-radius: 12px;
    border: 1px solid {p['border_soft']};
}}

QWidget#titlebar {{
    background: transparent;
    border-bottom: 1px solid {p['border_soft']};
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}

QWidget#sidebar {{
    background: {p['bg_glass_high']};
    border-right: 1px solid {p['border_soft']};
}}

QWidget#quickcap {{
    background: {p['bg_glass_high']};
    border-left: 1px solid {p['border_soft']};
}}

QWidget#avatar_panel {{
    background: {p['bg_glass']};
    border-radius: 10px;
    border: 1px solid {p['border']};
}}

QWidget#statuspill {{
    background: {p['accent_deep']};
    border: 1px solid {p['border']};
    border-radius: 14px;
}}

QLabel#brand {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 22px;
    color: {p['text_primary']};
}}

QLabel[class="overline"] {{
    color: {p['text_muted']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 11px;
    letter-spacing: 0.05em;
}}

QLabel[class="section-title"] {{
    font-family: 'Cormorant Garamond', 'Garamond', serif;
    font-size: 20px;
    color: {p['text_primary']};
}}

QLabel[class="muted"] {{ color: {p['text_muted']}; }}
QLabel[class="secondary"] {{ color: {p['text_secondary']}; }}

QPushButton {{
    background: transparent;
    color: {p['text_secondary']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 8px 14px;
}}
QPushButton:hover {{
    color: {p['accent']};
    border-color: {p['accent']};
    background: {p['accent_muted']};
}}
QPushButton:pressed {{
    background: {p['accent_muted']};
    padding: 9px 14px 7px 14px;
}}

QPushButton#primary {{
    background: {p['accent']};
    color: {p['text_inverse']};
    border: 1px solid {p['accent']};
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton#primary:hover {{
    background: {p['accent_hover']};
    border-color: {p['accent_hover']};
}}

QPushButton#ghost {{
    border: none;
    color: {p['text_muted']};
    padding: 6px 10px;
}}
QPushButton#ghost:hover {{ color: {p['accent']}; background: transparent; }}

QPushButton#kbdhint {{
    color: {p['text_muted']};
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 4px 10px;
    font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
    font-size: 10px;
    letter-spacing: 1.5px;
}}
QPushButton#kbdhint:hover {{ color: {p['accent']}; border-color: {p['accent']}; }}

QPushButton#ptt {{
    background: {p['accent_deep']};
    color: {p['accent']};
    border: 1px solid {p['accent']};
    border-radius: 20px;
    padding: 6px 16px;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.02em;
}}
QPushButton#ptt:hover {{ background: {p['accent_muted']}; }}
QPushButton#ptt:pressed {{ background: {p['accent']}; color: {p['text_inverse']}; }}

QPushButton#titleicon {{
    background: transparent;
    color: {p['text_muted']};
    border: none;
    border-radius: 6px;
    font-size: 15px;
}}
QPushButton#titleicon:hover {{ color: {p['accent']}; background: {p['accent_muted']}; }}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 9px 12px;
    selection-background-color: {p['accent_deep']};
    color: {p['text_primary']};
}}
QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {{
    color: {p['text_muted']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {p['accent']};
    background: {p['bg_elevated']};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    selection-background-color: {p['accent_deep']};
    color: {p['text_primary']};
    padding: 4px;
}}

QScrollArea {{ border: none; background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {p['border']}; border-radius: 4px; min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSplitter::handle {{ background: {p['border_soft']}; }}
QSplitter::handle:hover {{ background: {p['accent']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* Chat bubbles — asymmetric tails per the owner's mockup */
QFrame#bubble_user {{
    background: #c45c38;
    border: 2px solid #3a2418;
    border-radius: 12px;
    border-bottom-right-radius: 2px;
}}
QFrame#bubble_assistant {{
    background: #f4e8c8;
    border: 2px solid #3a2418;
    border-radius: 12px;
    border-bottom-left-radius: 2px;
}}
QFrame#flat_user, QFrame#flat_assistant {{
    background: transparent;
    border: none;
    border-left: 2px solid {p['border']};
    border-radius: 0;
}}
QFrame#flat_user {{ border-left-color: {p['accent']}; }}

QLabel#role {{
    color: {p['text_muted']};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: lowercase;
}}
QLabel[class="chat-body"] {{
    color: {p['text_primary']};
    font-size: 14px;
    line-height: 1.55;
}}

/* Recent-memories card — matches the owner's mockup exactly */
QFrame#memory_row {{
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame#memory_row:hover {{
    border-color: {p['accent']};
    background: {p['bg_elevated']};
}}
QLabel[class="memory-kind"] {{
    color: {p['accent']};
    font-size: 10px;
    letter-spacing: 0.04em;
}}
QLabel[class="memory-title"] {{
    color: {p['text_primary']};
    font-size: 13px;
}}
QLabel[class="memory-preview"] {{
    color: {p['text_secondary']};
    font-size: 12px;
}}

QMenu {{
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px;
    color: {p['text_primary']};
}}
QMenu::item {{
    padding: 7px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {p['accent_deep']};
    color: {p['accent']};
}}
QMenu::separator {{
    height: 1px;
    background: {p['border_soft']};
    margin: 4px 8px;
}}

QToolTip {{
    background: {p['bg_elevated']};
    color: {p['text_primary']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
}}

/* Settings dialog polish */
QDialog {{ background: {p['bg_base']}; }}
QLabel {{ color: {p['text_primary']}; }}
QCheckBox, QRadioButton {{
    color: {p['text_primary']};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {p['border']};
    border-radius: 3px;
    background: {p['bg_surface']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p['accent']};
    border-color: {p['accent']};
}}
QRadioButton::indicator {{ border-radius: 8px; }}

QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: 8px;
    background: {p['bg_surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p['text_muted']};
    padding: 8px 16px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {p['accent']};
    background: {p['bg_surface']};
    border-color: {p['border']};
    border-bottom-color: {p['bg_surface']};
}}
QTabBar::tab:hover:!selected {{ color: {p['text_primary']}; }}

QGroupBox {{
    color: {p['text_primary']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p['text_muted']};
    font-size: 11px;
    letter-spacing: 0.04em;
}}

QProgressBar {{
    background: {p['bg_surface']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    text-align: center;
    color: {p['text_primary']};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 5px; }}
"""


def apply_theme(app: QApplication, name: str, custom: Optional[Dict[str, str]] = None) -> str:
    """Load `name` (or resolve custom) into PALETTE and push QSS everywhere.

    Returns the final QSS so callers can also set it on frameless children
    that don't inherit from the app (Qt menus opened via native context).
    """
    resolved = resolve(name, custom)
    PALETTE.clear()
    PALETTE.update(resolved)
    qss = build_qss(resolved)
    app.setStyleSheet(qss)
    # Force every top-level to repaint — a couple of widgets cache pens/brushes
    for w in app.topLevelWidgets():
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
        # Recursively re-polish so QSS attribute selectors pick up new PALETTE
        for child in w.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)
    return qss


def current_qss() -> str:
    """The current stylesheet — used when constructing detached menus."""
    return build_qss(PALETTE)


# Public: the theme names in the order the settings dialog should show them.
THEME_ORDER = ["amber_library", "slate_pro", "ivory_library", "nordic_mist", "playroom"]
THEME_LABELS: Dict[str, str] = {
    "amber_library":  "Amber Library",
    "slate_pro":      "Slate Pro",
    "ivory_library":  "Ivory Library",
    "nordic_mist":    "Nordic Mist",
    "playroom":       "Playroom",
}


# Convenience: which palette keys the "Custom" picker exposes to the user.
# Keeping this list short — dumping 19 pickers on someone is worse than 4.
CUSTOMIZABLE_KEYS = [
    ("accent",       "Accent color"),
    ("bg_base",      "Background"),
    ("bg_surface",   "Surface"),
    ("text_primary", "Text color"),
]


# Legacy re-export: some widgets still `from . import PALETTE` — keep it.
def _legacy_getitem(k: str) -> str:  # pragma: no cover — safety net only
    return PALETTE[k]


# --- one-time backwards compat aliases used by very old palettes ---
# Older files may still ask for `bg_base` / etc. and we already handle that.
# No more shims needed since all keys are in _KEYS.

Any  # noqa: B018 — silence "imported but unused" (used in type hints above)
