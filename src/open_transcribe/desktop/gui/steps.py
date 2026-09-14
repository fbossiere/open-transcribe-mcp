"""The six first-run steps.

Each step states what it needs, validates locally, and hands a typed intent fragment back to the
window. No step performs a side effect of its own except the ones its own primary action names.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from open_transcribe.desktop.clients.base import ClientAdapter, SupportStatus
from open_transcribe.desktop.diagnostics import DiagnosticReport
from open_transcribe.desktop.gui.widgets import (
    SecretField,
    StatusRow,
    announce,
    body_label,
    heading_label,
)
from open_transcribe.desktop.i18n import Translator
from open_transcribe.desktop.providers import ProviderSetupDescriptor
from open_transcribe.desktop.schema import ManagedPrivacy
from open_transcribe.desktop.setup import ApplyOutcome, SetupPlan
from open_transcribe.domain.capabilities import ModelDescriptor


class Step(QWidget):
    """A step in the wizard. `ready` drives the window's single primary action."""

    ready = Signal(bool)

    def __init__(self, translate: Translator) -> None:
        super().__init__()
        self.t = translate
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(12)

    def action_label(self) -> str:
        return self.t("nav.continue")

    def activate(self) -> None:
        """Called each time the step is shown, including after a restart."""

    def deactivate(self) -> None:
        """Called when leaving. Steps holding sensitive input clear it here."""


class WelcomeStep(Step):
    def __init__(self, translate: Translator) -> None:
        super().__init__(translate)
        self.column.addWidget(heading_label(self.t("welcome.title")))
        self.column.addWidget(body_label(self.t("welcome.body")))
        note = body_label(self.t("welcome.no_account"))
        note.setProperty("muted", True)
        self.column.addWidget(note)
        self.column.addStretch(1)

    def action_label(self) -> str:
        return self.t("welcome.action")

    def activate(self) -> None:
        self.ready.emit(True)


class ChecksStep(Step):
    """Step 2: what this computer provides, with one recovery action per problem."""

    recheck = Signal()

    def __init__(self, translate: Translator) -> None:
        super().__init__(translate)
        self.column.addWidget(heading_label(self.t("checks.title")))
        self.column.addWidget(body_label(self.t("checks.subtitle")))
        self._rows = QVBoxLayout()
        self.column.addLayout(self._rows)
        self.column.addStretch(1)
        self._blocking: tuple[str, ...] = (
            "keyring.backend",
            "engine.installed",
            "platform.privilege",
        )

    def show_report(self, report: DiagnosticReport) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()
        blocked = False
        for check in report.checks:
            if check.check_id == "config.load":
                continue
            action = None
            if check.severity.value in {"warning", "error"}:
                action = (self.t("status.check"), self.recheck.emit)
            self._rows.addWidget(
                StatusRow(check.title, check.severity.value, check.recovery, action)
            )
            if check.check_id in self._blocking and check.severity.value == "error":
                blocked = True
        # An undetected client is not a blocker: the manual path always exists.
        self.ready.emit(not blocked)
        announce(self, report.worst.value)


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    descriptor: ProviderSetupDescriptor
    secrets: dict[str, str]
    endpoint: str | None
    api_version: str | None
    model: ModelDescriptor | None
    privacy: ManagedPrivacy


class ProviderStep(Step):
    """Step 3: the provider, its credentials, its capabilities, and the relevant permissions."""

    open_link = Signal(str)

    def __init__(
        self,
        translate: Translator,
        descriptors: tuple[ProviderSetupDescriptor, ...],
        models_for: Callable[[str], list[ModelDescriptor]],
    ) -> None:
        super().__init__(translate)
        self._descriptors = descriptors
        self._models_for = models_for
        self.column.addWidget(heading_label(self.t("provider.title")))
        self.column.addWidget(body_label(self.t("provider.subtitle")))

        self.provider_box = QComboBox()
        self.provider_box.setAccessibleName(self.t("provider.title"))
        # No vendor is preselected: the first provider is the user's choice, and a catalogue
        # position is not a recommendation.
        self.provider_box.addItem(self.t("provider.choose"), None)
        for descriptor in descriptors:
            self.provider_box.addItem(descriptor.display_name, descriptor.provider_id)
        self.provider_box.currentIndexChanged.connect(self._provider_changed)
        self.column.addWidget(self.provider_box)

        self.model_box = QComboBox()
        self.model_box.setAccessibleName(self.t("review.provider"))
        self.model_box.currentIndexChanged.connect(self._model_changed)
        self.column.addWidget(self.model_box)

        self.capabilities = body_label("")
        self.capabilities.setProperty("muted", True)
        self.column.addWidget(self.capabilities)

        self.secret = SecretField(
            self.t("provider.api_key"), self.t("provider.reveal"), self.t("provider.api_key.help")
        )
        self.secret.edit.textChanged.connect(self._validate)
        self.column.addWidget(self.secret)

        self.endpoint_label = QLabel(self.t("provider.microsoft.endpoint"))
        self.endpoint = QLineEdit()
        self.endpoint.setAccessibleName(self.t("provider.microsoft.endpoint"))
        self.endpoint.setPlaceholderText("https://")
        self.endpoint_label.setBuddy(self.endpoint)
        self.endpoint.textChanged.connect(self._validate)
        self.endpoint_error = body_label("")
        self.endpoint_error.setProperty("severity", "error")
        self.endpoint_error.hide()
        for widget in (self.endpoint_label, self.endpoint, self.endpoint_error):
            self.column.addWidget(widget)

        self.console = QPushButton(self.t("provider.open_console"))
        self.console.clicked.connect(self._open_console)
        self.column.addWidget(self.console)

        self.privacy_group = QGroupBox(self.t("privacy.title"))
        privacy_layout = QVBoxLayout(self.privacy_group)
        self.relay_note = body_label(self.t("provider.relay_warning"))
        self.relay_note.setProperty("severity", "warning")
        self.relay_note.hide()
        privacy_layout.addWidget(self.relay_note)
        self.allow_relay = QCheckBox(self.t("privacy.temporary_audio"))
        self.allow_relay.setChecked(False)
        privacy_layout.addWidget(self.allow_relay)
        relay_help = body_label(self.t("privacy.temporary_audio.help", minutes=60))
        relay_help.setProperty("muted", True)
        privacy_layout.addWidget(relay_help)
        caveat = body_label(self.t("privacy.temporary_audio.caveat"))
        caveat.setProperty("muted", True)
        privacy_layout.addWidget(caveat)
        self.allow_fallback = QCheckBox(self.t("privacy.fallback"))
        self.allow_fallback.setChecked(False)
        privacy_layout.addWidget(self.allow_fallback)
        fallback_help = body_label(self.t("privacy.fallback.help"))
        fallback_help.setProperty("muted", True)
        privacy_layout.addWidget(fallback_help)
        privacy_layout.addWidget(body_label(self.t("privacy.history")))
        self.column.addWidget(self.privacy_group)

        self.threshold_label = QLabel(self.t("cost.threshold"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 1000.0)
        self.threshold.setDecimals(2)
        self.threshold.setSpecialValueText(self.t("review.off"))
        self.threshold.setAccessibleName(self.t("cost.threshold"))
        self.threshold_label.setBuddy(self.threshold)
        threshold_help = body_label(self.t("cost.threshold.help"))
        threshold_help.setProperty("muted", True)
        for threshold_widget in (self.threshold_label, self.threshold, threshold_help):
            self.column.addWidget(threshold_widget)

        self.column.addStretch(1)
        self._provider_changed()

    # -- behaviour ------------------------------------------------------------------

    def descriptor(self) -> ProviderSetupDescriptor | None:
        index = self.provider_box.currentIndex() - 1
        return self._descriptors[index] if 0 <= index < len(self._descriptors) else None

    def selected_model(self) -> ModelDescriptor | None:
        model = self.model_box.currentData()
        return model if isinstance(model, ModelDescriptor) else None

    def _provider_changed(self) -> None:
        descriptor = self.descriptor()
        # A key belongs to the provider it was issued for. Changing provider clears it rather
        # than carrying it over, so one provider's key can never be sent to another.
        self.secret.clear_secret()
        self.secret.clear_error()
        self.model_box.setVisible(descriptor is not None)
        self.secret.setVisible(descriptor is not None)
        self.console.setVisible(descriptor is not None)
        self.privacy_group.setVisible(descriptor is not None)
        if descriptor is None:
            self.endpoint_label.hide()
            self.endpoint.hide()
            self.endpoint_error.hide()
            self.model_box.clear()
            self.capabilities.setText("")
            self.ready.emit(False)
            return
        needs_endpoint = any(field.kind == "https_url" for field in descriptor.fields)
        for widget in (self.endpoint_label, self.endpoint):
            widget.setVisible(needs_endpoint)
        if not needs_endpoint:
            self.endpoint_error.hide()
        self.model_box.clear()
        for model in self._models_for(descriptor.provider_id):
            self.model_box.addItem(model.display_name, model)
        self._model_changed()

    def _model_changed(self) -> None:
        model = self.selected_model()
        if model is None:
            self.capabilities.setText("")
            return
        self.capabilities.setText(self._describe(model))
        # Relay is only relevant when the model cannot fetch a URL itself.
        self.relay_note.setVisible(not model.supports_url_input)
        self._validate()

    def _describe(self, model: ModelDescriptor) -> str:
        lines = [f"{model.display_name} — {model.lifecycle.value}"]
        if model.languages == "dynamic":
            lines.append(self.t("provider.languages.dynamic"))
        else:
            lines.append(", ".join(sorted(model.languages)[:12]))
        if model.supports_diarization:
            lines.append(self.t("provider.diarization"))
        timestamps = ", ".join(sorted(mode.value for mode in model.timestamp_modes))
        lines.append(f"timestamps: {timestamps or self.t('provider.unknown')}")
        if model.pricing is not None:
            lines.append(self.t("provider.pricing", date=model.pricing.valid_from.isoformat()))
        else:
            lines.append(self.t("provider.pricing.unknown"))
        return "\n".join(lines)

    def _open_console(self) -> None:
        """Opening a provider's website is an explicit user action, taken in their own browser."""
        from PySide6.QtCore import QUrl

        descriptor = self.descriptor()
        if descriptor is not None:
            QDesktopServices.openUrl(QUrl(descriptor.account_url))

    def _validate(self) -> None:
        self.secret.clear_error()
        self.endpoint_error.hide()
        valid = (
            self.descriptor() is not None
            and bool(self.secret.value())
            and self.selected_model() is not None
        )
        if self.endpoint.isVisible():
            valid = valid and self.endpoint.text().strip().startswith("https://")
        self.ready.emit(valid)

    def focus_first_invalid(self) -> None:
        if self.descriptor() is None:
            self.provider_box.setFocus(Qt.FocusReason.OtherFocusReason)
            announce(self.provider_box, self.t("provider.choose"))
            return
        if not self.secret.value():
            self.secret.show_error(self.t("provider.api_key.help"))
            return
        if self.endpoint.isVisible() and not self.endpoint.text().strip().startswith("https://"):
            self.endpoint_error.setText(self.t("provider.microsoft.endpoint.help"))
            self.endpoint_error.show()
            announce(self.endpoint, self.endpoint_error.text())
            self.endpoint.setFocus(Qt.FocusReason.OtherFocusReason)

    def choice(self) -> ProviderChoice | None:
        descriptor = self.descriptor()
        if descriptor is None:
            return None
        model = self.selected_model()
        needs_relay = model is not None and not model.supports_url_input
        return ProviderChoice(
            descriptor=descriptor,
            secrets={"api_key": self.secret.value()},
            endpoint=self.endpoint.text().strip() or None if self.endpoint.isVisible() else None,
            api_version=None,
            model=model,
            privacy=ManagedPrivacy(
                temporary_audio_processing=self.allow_relay.isChecked() and needs_relay,
                cross_provider_fallback=self.allow_fallback.isChecked(),
            ),
        )

    def threshold_value(self) -> float | None:
        value = self.threshold.value()
        return value if value > 0 else None

    def deactivate(self) -> None:
        self.secret.clear_secret()


class ClientStep(Step):
    """Step 4: which assistant, and nothing changed yet."""

    def __init__(self, translate: Translator, adapters: list[ClientAdapter]) -> None:
        super().__init__(translate)
        self._adapters = adapters
        self.column.addWidget(heading_label(self.t("client.title")))
        self.column.addWidget(body_label(self.t("client.subtitle")))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, adapter in enumerate(adapters):
            button = QRadioButton(adapter.display_name)
            button.setAccessibleName(adapter.display_name)
            self._group.addButton(button, index)
            self.column.addWidget(button)
            if adapter.support_status is SupportStatus.UNTESTED:
                note = body_label(self.t("client.untested", client=adapter.display_name))
                note.setProperty("muted", True)
                self.column.addWidget(note)
            if adapter.support_status is SupportStatus.MANUAL_ONLY:
                note = body_label(self.t("client.manual"))
                note.setProperty("muted", True)
                self.column.addWidget(note)
            if index == 0:
                button.setChecked(True)
        self.takeover = QCheckBox(self.t("client.takeover"))
        self.takeover.setChecked(False)
        self.takeover.hide()
        self.column.addWidget(self.takeover)
        self.conflict = body_label("")
        self.conflict.setProperty("severity", "warning")
        self.conflict.hide()
        self.column.addWidget(self.conflict)
        self.column.addStretch(1)

    def action_label(self) -> str:
        return self.t("client.action")

    def activate(self) -> None:
        self.ready.emit(bool(self._adapters))

    def selected(self) -> ClientAdapter | None:
        index = self._group.checkedId()
        return self._adapters[index] if 0 <= index < len(self._adapters) else None

    def show_conflict(self, client: str, name: str) -> None:
        """A conflict offers an explicit takeover; it is never pre-selected."""
        self.conflict.setText(self.t("client.conflict", client=client, name=name))
        self.conflict.show()
        self.takeover.setChecked(False)
        self.takeover.show()
        announce(self.conflict, self.conflict.text())


class ReviewStep(Step):
    """Step 5: exactly what Enable connection authorizes."""

    def __init__(self, translate: Translator) -> None:
        super().__init__(translate)
        self.column.addWidget(heading_label(self.t("review.title")))
        card = QFrame()
        card.setObjectName("card")
        self._grid = QGridLayout(card)
        self._grid.setColumnStretch(1, 1)
        self.column.addWidget(card)
        self.flow = body_label(self.t("review.flow"))
        self.column.addWidget(self.flow)
        self.delivery = body_label("")
        self.column.addWidget(self.delivery)
        self.recipients = body_label("")
        self.column.addWidget(self.recipients)
        self.changes = body_label("")
        self.changes.setProperty("muted", True)
        self.changes.hide()
        self.details_button = QPushButton(self.t("review.changes"))
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.changes.setVisible)
        self.column.addWidget(self.details_button)
        self.column.addWidget(self.changes)
        self.column.addStretch(1)

    def action_label(self) -> str:
        return self.t("review.action")

    def show_plan(self, plan: SetupPlan, model: ModelDescriptor | None, client: str) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()
        privacy = plan.config.privacy
        on, off = self.t("review.on"), self.t("review.off")
        rows = [
            (self.t("review.provider"), model.display_name if model else ""),
            (self.t("review.assistant"), client),
            (self.t("review.fallback"), on if privacy.cross_provider_fallback else off),
            (self.t("review.history"), off),
            (
                self.t("review.temporary_audio"),
                on if privacy.temporary_audio_processing else off,
            ),
            (self.t("review.keys"), self.t("review.keys.value")),
        ]
        for row, (name, value) in enumerate(rows):
            self._grid.addWidget(QLabel(name), row, 0)
            self._grid.addWidget(body_label(value), row, 1)

        if model is not None and model.supports_url_input:
            self.delivery.setText(self.t("review.passthrough"))
        elif privacy.temporary_audio_processing:
            self.delivery.setText(self.t("review.relay", minutes=60))
        else:
            self.delivery.setText("")
        self.recipients.setText(
            self.t("review.recipients", providers=", ".join(plan.provider_recipients))
        )
        actions = [
            f"{action.kind}: {action.target}"
            for action in (plan.registration_plan.actions if plan.registration_plan else ())
        ]
        credentials = [f"keyring: {item}" for item in plan.new_credentials]
        self.changes.setText(
            "\n".join([*credentials, f"config: {plan.config.installation_id}", *actions])
        )
        self.ready.emit(True)


class FinishStep(Step):
    """Step 6: what was verified, what was not, and one copyable first prompt."""

    confirmed = Signal(bool)
    run_sample = Signal()
    copy_prompt = Signal(str)

    def __init__(self, translate: Translator) -> None:
        super().__init__(translate)
        self.column.addWidget(heading_label(self.t("finish.title")))
        self._rows = QVBoxLayout()
        self.column.addLayout(self._rows)

        self.confirm = QCheckBox(self.t("finish.confirm"))
        self.confirm.toggled.connect(self.confirmed.emit)
        self.column.addWidget(self.confirm)

        self.column.addWidget(heading_label(self.t("finish.prompt_label"), level=2))
        prompt_row = QVBoxLayout()
        self.prompt = QLineEdit(self.t("finish.prompt"))
        self.prompt.setReadOnly(True)
        self.prompt.setAccessibleName(self.t("finish.prompt_label"))
        prompt_row.addWidget(self.prompt)
        copy = QPushButton(self.t("finish.copy"))
        copy.clicked.connect(lambda: self.copy_prompt.emit(self.prompt.text()))
        prompt_row.addWidget(copy)
        self.column.addLayout(prompt_row)

        self.column.addWidget(heading_label(self.t("sample.title"), level=2))
        self.column.addWidget(body_label(self.t("sample.description")))
        self.sample_cost = body_label("")
        self.column.addWidget(self.sample_cost)
        self.sample_button = QPushButton(self.t("sample.run"))
        self.sample_button.clicked.connect(self.run_sample.emit)
        self.column.addWidget(self.sample_button)
        self.sample_result = body_label(self.t("sample.not_tested"))
        self.column.addWidget(self.sample_result)
        self.column.addStretch(1)

    def action_label(self) -> str:
        return self.t("finish.action")

    def show_outcome(self, outcome: ApplyOutcome, client: str) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()
        engine_ok = outcome.engine is not None and outcome.engine.ok
        self._rows.addWidget(
            StatusRow(
                self.t("finish.engine_ready") if engine_ok else self.t("finish.engine_failed"),
                "ok" if engine_ok else "error",
            )
        )
        if outcome.registered:
            self._rows.addWidget(StatusRow(self.t("finish.registered", client=client), "ok"))
            if outcome.restart_required:
                self._rows.addWidget(StatusRow(self.t("finish.restart", client=client), "info"))
            # Registration is not activation, and is never presented as though it were.
            self._rows.addWidget(StatusRow(self.t("finish.unverified"), "info"))
        elif outcome.failure is not None:
            self._rows.addWidget(
                StatusRow(outcome.failure.message, "error", outcome.failure.recovery)
            )
        self.sample_button.setEnabled(engine_ok)
        self.ready.emit(True)

    def show_sample_plan(self, text: str) -> None:
        self.sample_cost.setText(text)

    def show_sample_result(self, text: str, severity: str) -> None:
        self.sample_result.setText(text)
        self.sample_result.setProperty("severity", severity)
        announce(self.sample_result, text)
