"""The visual system: one palette, one stylesheet, and the product mark.

The window follows the desktop's light or dark preference and then states every colour it uses,
so contrast is a property of this file rather than of whichever GTK theme happens to be
installed. Severity is always carried by a text mark as well as by colour; the colours here only
reinforce what the words already say.
"""

from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication

CONTENT_WIDTH = 720
"""A readable measure. The window grows; the text column does not."""

ICON_SIZES: Final = (16, 20, 24, 32, 40, 48, 64, 128, 256)
"""The sizes a desktop, a task bar and a window decoration may ask for."""

BRAND_GROUND: Final = "#14343f"
BRAND_MARK: Final = "#7fd1c1"

LIGHT: Final = {
    "bg": "#f2f6f6",
    "surface": "#ffffff",
    "field": "#ffffff",
    "text": "#14262b",
    "muted": "#54656a",
    "border": "#d2dedf",
    "accent": "#0b6057",
    "primary": "#0e5a52",
    "on_primary": "#ffffff",
    "hover": "#e5eeed",
    "focus": "#0b6057",
    "note": "#e6f1ef",
    "ok": "#1f7a3d",
    "warning": "#8a5a00",
    "error": "#a1202a",
}

DARK: Final = {
    "bg": "#121a1d",
    "surface": "#1c2529",
    "field": "#161f22",
    "text": "#edf4f3",
    "muted": "#a6bab9",
    "border": "#324449",
    "accent": "#7fd1c1",
    "primary": "#7fd1c1",
    "on_primary": "#0b2b27",
    "hover": "#253338",
    "focus": "#a5e2d5",
    "note": "#1d3235",
    "ok": "#61c97f",
    "warning": "#e0a23c",
    "error": "#f0787f",
}

_detected_dark: bool | None = None


def icon_pixmap(size: int) -> QPixmap:
    """Draw the product mark at one resolution, without a runtime asset.

    The same five bars as `packaging/desktop/open-transcribe-assistant.svg`, so the window icon
    and the packaged icon cannot drift apart.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 64, size / 64)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BRAND_GROUND))
    painter.drawRoundedRect(QRectF(0, 0, 64, 64), 14, 14)
    pen = QPen(QColor(BRAND_MARK), 3.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for x, top, bottom in ((17, 24, 40), (25, 18, 46), (33, 26, 38), (41, 21, 43), (49, 28, 36)):
        painter.drawPolyline(QPolygonF([QPointF(x, top), QPointF(x, bottom)]))
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """The window icon, drawn at every resolution the desktop may ask for."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(icon_pixmap(size))
    return icon


_STYLE = """
QWidget {{ color: {text}; font-size: 11pt; }}
QMainWindow, QWidget#shell, QWidget#header, QWidget#page, QScrollArea,
QScrollArea > QWidget > QWidget {{ background: {bg}; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 13pt; font-weight: 700; }}
QLabel[heading="1"] {{ font-size: 19pt; font-weight: 700; }}
QLabel[heading="2"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[muted="true"] {{ color: {muted}; }}
QLabel[severity="ok"] {{ color: {ok}; }}
QLabel[severity="warning"] {{ color: {warning}; }}
QLabel[severity="error"] {{ color: {error}; }}
QLabel[severity="info"] {{ color: {muted}; }}

QWidget#footer {{ border-top: 1px solid {border}; background: {bg}; }}
QFrame#segment {{ background: {border}; border: none; border-radius: 2px; }}
QFrame#segment[reached="true"] {{ background: {accent}; }}

QFrame#card, QWidget#statusRow {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
}}
QGroupBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
    margin-top: 10px; padding: 14px 14px 6px 14px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}

QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {hover}; }}
QPushButton#primary {{
    background: {primary}; color: {on_primary}; border: 2px solid {primary}; padding: 7px 20px;
}}
QPushButton#primary:hover {{ border-color: {text}; }}
QPushButton:disabled, QPushButton#primary:disabled {{
    color: {muted}; background: {bg}; border-color: {border};
}}
QPushButton#disclosure {{
    background: transparent; border: 1px solid transparent; color: {accent};
    text-align: left; padding: 6px 4px;
}}
QPushButton#disclosure:hover {{ background: {hover}; }}

QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {field}; border: 1px solid {border}; border-radius: 8px; padding: 8px;
    min-height: 20px; selection-background-color: {primary}; selection-color: {on_primary};
}}
QProgressBar {{ border: 1px solid {border}; border-radius: 6px; background: {field}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}

QPushButton:focus, QLineEdit:focus, QCheckBox:focus, QRadioButton:focus, QComboBox:focus,
QDoubleSpinBox:focus, QGroupBox:focus {{
    outline: 2px solid {focus};
    border-color: {focus};
}}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


def colors(dark: bool) -> dict[str, str]:
    return dict(DARK if dark else LIGHT)


def is_dark(application: QApplication) -> bool:
    """The desktop's preference, read once.

    Applying the theme overwrites the palette this answer comes from, so the first reading is
    the one that counts: a second call must not decide the desktop turned light.
    """
    global _detected_dark
    if _detected_dark is None:
        window = application.palette().color(QPalette.ColorRole.Window)
        _detected_dark = window.lightness() < 128
    return _detected_dark


def apply_theme(application: QApplication, *, dark: bool | None = None) -> None:
    palette_colors = colors(is_dark(application) if dark is None else dark)
    # Fusion honours the palette below on every desktop. A platform style may ignore parts of
    # it, which is how a check box or a radio button ends up drawn in a colour nothing here
    # chose — invisible against the surface it sits on.
    application.setStyle("Fusion")
    palette = application.palette()
    for role, key in (
        (QPalette.ColorRole.Window, "bg"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "field"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.Button, "surface"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
        (QPalette.ColorRole.Mid, "border"),
        (QPalette.ColorRole.Highlight, "primary"),
        (QPalette.ColorRole.HighlightedText, "on_primary"),
    ):
        palette.setColor(role, QColor(palette_colors[key]))
    application.setPalette(palette)
    application.setStyleSheet(_STYLE.format(**palette_colors))
