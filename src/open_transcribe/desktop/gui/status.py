"""The returning-user status page.

Every claim carries how it was established and when. A remembered success is shown as a
remembered success, and a configuration change invalidates the evidence it affected.
"""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from open_transcribe.desktop.diagnostics import DiagnosticReport
from open_transcribe.desktop.gui.widgets import StatusRow, body_label, heading_label
from open_transcribe.desktop.i18n import Translator
from open_transcribe.desktop.schema import ManagedConfig


class StatusPage(QWidget):
    check_requested = Signal()
    providers_requested = Signal()
    repair_requested = Signal()
    diagnostic_requested = Signal()
    updates_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, translate: Translator) -> None:
        super().__init__()
        self.t = translate
        column = QVBoxLayout(self)
        column.setSpacing(12)
        column.addWidget(heading_label(self.t("status.title")))
        self.summary = QGridLayout()
        column.addLayout(self.summary)
        self._rows = QVBoxLayout()
        column.addLayout(self._rows)
        self.checked_at = body_label(self.t("status.never_checked"))
        self.checked_at.setProperty("muted", True)
        column.addWidget(self.checked_at)
        self.staleness = body_label(self.t("status.stale"))
        self.staleness.setProperty("muted", True)
        column.addWidget(self.staleness)
        column.addWidget(body_label(self.t("status.revocation")))

        # A grid rather than a row: six buttons in one row would give the page a minimum width
        # wider than a 1280 x 720 window at 200% scaling, and the page would clip instead of wrap.
        actions = QGridLayout()
        for index, (label, signal) in enumerate(
            (
                (self.t("status.check"), self.check_requested),
                (self.t("status.providers"), self.providers_requested),
                (self.t("status.repair"), self.repair_requested),
                (self.t("status.diagnostic"), self.diagnostic_requested),
                (self.t("status.updates"), self.updates_requested),
                (self.t("status.disconnect"), self.disconnect_requested),
            )
        ):
            button = QPushButton(label)
            button.setAccessibleName(label)
            button.clicked.connect(signal.emit)
            actions.addWidget(button, index // 3, index % 3)
        column.addLayout(actions)
        column.addStretch(1)

    def show_state(self, config: ManagedConfig | None, report: DiagnosticReport) -> None:
        while self.summary.count():
            item = self.summary.takeAt(0)
            if (widget := item.widget()) is not None:
                widget.deleteLater()
        rows = [
            ("Version", report.application_version),
            (
                self.t("review.provider"),
                ", ".join(sorted(config.enabled_providers)) if config else "",
            ),
            (
                self.t("review.assistant"),
                config.client.display_name if config and config.client else "",
            ),
            (
                self.t("review.temporary_audio"),
                self.t("review.on")
                if config and config.privacy.temporary_audio_processing
                else self.t("review.off"),
            ),
            (
                self.t("review.fallback"),
                self.t("review.on")
                if config and config.privacy.cross_provider_fallback
                else self.t("review.off"),
            ),
        ]
        for index, (name, value) in enumerate(rows):
            self.summary.addWidget(body_label(name), index, 0)
            self.summary.addWidget(body_label(value), index, 1)

        while self._rows.count():
            item = self._rows.takeAt(0)
            if (widget := item.widget()) is not None:
                widget.deleteLater()
        for check in report.checks:
            self._rows.addWidget(StatusRow(check.title, check.severity.value, check.recovery))
        self.checked_at.setText(
            self.t("status.last_checked", when=report.generated_at.strftime("%Y-%m-%d %H:%M"))
        )


class DiagnosticPreview(QDialog):
    """Copy diagnostic always previews the allowlisted export before anything is copied."""

    def __init__(self, translate: Translator, payload: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate("status.diagnostic"))
        column = QVBoxLayout(self)
        column.addWidget(body_label(translate("diagnostic.preview")))
        view = QPlainTextEdit(payload)
        view.setReadOnly(True)
        view.setAccessibleName(translate("status.diagnostic"))
        column.addWidget(view)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(translate("finish.copy"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)


class DisconnectDialog(QDialog):
    """One focused confirmation that names what will be erased, with erasure unticked."""

    def __init__(self, translate: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate("status.disconnect"))
        column = QVBoxLayout(self)
        column.addWidget(body_label(translate("status.erase.confirm")))
        self.erase = QCheckBox(translate("status.erase"))
        self.erase.setChecked(False)
        column.addWidget(self.erase)
        column.addWidget(body_label(translate("status.revocation")))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(translate("status.disconnect"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    def erase_requested(self) -> bool:
        return self.erase.isChecked()


def connect_action(button: QPushButton, handler: Callable[[], None]) -> None:
    button.clicked.connect(handler)
