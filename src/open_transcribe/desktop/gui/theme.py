"""Presentation rules expressed against the system palette.

The window follows the desktop's light or dark palette rather than imposing its own. Only the
severity accents and a readable content column are set here, so the application looks native and
keeps its contrast in both themes.
"""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

CONTENT_WIDTH = 720
"""A readable measure. The window grows; the text column does not."""

_STYLE = """
QLabel[heading="1"] {{ font-size: 20px; font-weight: 600; }}
QLabel[heading="2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[muted="true"] {{ color: {muted}; }}
QLabel[severity="ok"] {{ color: {ok}; }}
QLabel[severity="warning"] {{ color: {warning}; }}
QLabel[severity="error"] {{ color: {error}; }}
QLabel[severity="info"] {{ color: {muted}; }}
QFrame#card {{ border: 1px solid {line}; border-radius: 8px; }}
QPushButton {{ padding: 6px 14px; }}
QPushButton:focus, QLineEdit:focus, QCheckBox:focus, QComboBox:focus {{
    outline: 2px solid {focus};
}}
"""


def apply_theme(application: QApplication) -> None:
    palette = application.palette()
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    application.setStyleSheet(
        _STYLE.format(
            muted=palette.color(QPalette.ColorRole.PlaceholderText).name(),
            ok="#1f7a3d" if not dark else "#61c97f",
            warning="#8a5a00" if not dark else "#e0a23c",
            error="#a1202a" if not dark else "#f0787f",
            line=palette.color(QPalette.ColorRole.Mid).name(),
            focus=palette.color(QPalette.ColorRole.Highlight).name(),
        )
    )
