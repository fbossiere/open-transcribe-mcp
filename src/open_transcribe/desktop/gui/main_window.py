"""The window: navigation, the single primary action per step, and the background work.

Nothing blocking runs here. Every provider call, keyring operation, engine handshake, and client
registration is handed to a worker, and what comes back is shown as what it actually established.
"""

from typing import Any

from pydantic import SecretStr
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from open_transcribe.desktop.clients.registry import build_adapters
from open_transcribe.desktop.credentials import SecretServiceCredentialStore
from open_transcribe.desktop.diagnostics import run_diagnostics
from open_transcribe.desktop.errors import DesktopError
from open_transcribe.desktop.gui.status import DiagnosticPreview, DisconnectDialog, StatusPage
from open_transcribe.desktop.gui.steps import (
    ChecksStep,
    ClientStep,
    FinishStep,
    ProviderStep,
    ReviewStep,
    Step,
    WelcomeStep,
)
from open_transcribe.desktop.gui.theme import CONTENT_WIDTH
from open_transcribe.desktop.gui.widgets import BusyBar, announce, body_label, heading_label
from open_transcribe.desktop.gui.workers import TaskFailure, run_async
from open_transcribe.desktop.i18n import translator
from open_transcribe.desktop.installation import current_installation
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.providers import DESCRIPTORS, CheckOutcome, check_credential
from open_transcribe.desktop.schema import ManagedLimits, ManagedSelection
from open_transcribe.desktop.setup import ProviderIntent, SetupIntent, SetupPlan, SetupService
from open_transcribe.domain.capabilities import ModelDescriptor

TOTAL_STEPS = 6


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.paths = DesktopPaths.resolve()
        self.installation = current_installation()
        self.t = translator(self._saved_locale())
        self.setWindowTitle(self.t("app.name"))
        self.resize(920, 640)
        self.setMinimumSize(640, 480)

        self._service: SetupService | None = None
        self._plan: SetupPlan | None = None
        self._intent: SetupIntent | None = None
        self._task: Any = None

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        header = QHBoxLayout()
        self.title = heading_label(self.t("app.name"))
        header.addWidget(self.title, 1)
        self.progress = body_label("")
        self.progress.setProperty("muted", True)
        header.addWidget(self.progress)
        outer.addLayout(header)

        # Navigation stays visible while the content scrolls.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        self.stack.setMaximumWidth(CONTENT_WIDTH)
        self.scroll.setWidget(self.stack)
        outer.addWidget(self.scroll, 1)

        self.busy = BusyBar()
        outer.addWidget(self.busy)

        footer = QHBoxLayout()
        self.back = QPushButton(self.t("nav.back"))
        self.back.clicked.connect(self.go_back)
        footer.addWidget(self.back)
        footer.addStretch(1)
        self.cancel = QPushButton(self.t("nav.cancel"))
        self.cancel.clicked.connect(self.close)
        footer.addWidget(self.cancel)
        self.primary = QPushButton("")
        self.primary.setDefault(True)
        self.primary.clicked.connect(self.advance)
        footer.addWidget(self.primary)
        outer.addLayout(footer)

        self._build_pages()
        self._start()

    # -- construction ---------------------------------------------------------------

    def _saved_locale(self) -> str:
        try:
            config = _read_config(self.paths)
        except DesktopError:
            return "system"
        return config.locale if config else "system"

    def _build_pages(self) -> None:
        adapters = build_adapters(self.installation.config_dir)
        self.steps: list[Step] = [
            WelcomeStep(self.t),
            ChecksStep(self.t),
            ProviderStep(self.t, DESCRIPTORS, self._models_for),
            ClientStep(self.t, adapters),
            ReviewStep(self.t),
            FinishStep(self.t),
        ]
        for step in self.steps:
            step.ready.connect(self.primary.setEnabled)
            self.stack.addWidget(step)
        self.status = StatusPage(self.t)
        self.status.check_requested.connect(self.refresh_status)
        self.status.providers_requested.connect(lambda: self.show_step(2))
        self.status.repair_requested.connect(self.repair)
        self.status.diagnostic_requested.connect(self.copy_diagnostic)
        self.status.disconnect_requested.connect(self.disconnect_client)
        self.stack.addWidget(self.status)

        self.steps[1].recheck.connect(self.run_checks)  # type: ignore[attr-defined]
        self.steps[5].run_sample.connect(self.transcribe_sample)  # type: ignore[attr-defined]
        self.steps[5].copy_prompt.connect(self.copy_text)  # type: ignore[attr-defined]

    def _models_for(self, provider_id: str) -> list[ModelDescriptor]:
        """Canonical descriptors from the bundled engine, not a hand-written catalogue."""
        from open_transcribe.providers.registry import ProviderRegistry
        from open_transcribe.settings import ExplicitSettings

        settings = ExplicitSettings(
            transport="stdio",
            security={"auth_mode": "none"},
            config_dir=self.installation.config_dir,
        )
        return [
            model
            for model in ProviderRegistry.from_settings(settings).list_models()
            if model.provider == provider_id
        ]

    def _start(self) -> None:
        try:
            config = _read_config(self.paths)
        except DesktopError as exc:
            config = None
            self._show_failure(TaskFailure(exc.message, exc.recovery, exc.code.value))
        # A restart resumes from what was actually saved, never from what was last attempted.
        self.show_step(TOTAL_STEPS if config is not None else 0)
        if config is not None:
            self.refresh_status()

    # -- navigation -----------------------------------------------------------------

    def show_step(self, index: int) -> None:
        current = self.stack.currentWidget()
        if isinstance(current, Step):
            current.deactivate()
        self.stack.setCurrentIndex(index)
        widget = self.stack.currentWidget()
        self.back.setVisible(0 < index < TOTAL_STEPS)
        self.primary.setVisible(index < TOTAL_STEPS)
        self.progress.setVisible(index < TOTAL_STEPS)
        if index < TOTAL_STEPS:
            self.progress.setText(self.t("nav.step", current=index + 1, total=TOTAL_STEPS))
        if isinstance(widget, Step):
            self.primary.setText(widget.action_label())
            self.primary.setEnabled(False)
            widget.activate()
            if index == 1:
                self.run_checks()
        self.scroll.verticalScrollBar().setValue(0)

    def go_back(self) -> None:
        self.show_step(max(self.stack.currentIndex() - 1, 0))

    def advance(self) -> None:
        index = self.stack.currentIndex()
        if index == 2:
            self.prepare_provider()
        elif index == 3:
            self.prepare_review()
        elif index == 4:
            self.enable_connection()
        elif index == 5:
            self.show_step(TOTAL_STEPS)
            self.refresh_status()
        else:
            self.show_step(index + 1)

    # -- background work ------------------------------------------------------------

    def _busy(self, message_key: str, work: Any, done: Any) -> None:
        self.primary.setEnabled(False)
        task = run_async(work, lambda result: self._finish(done, result), self._busy_failed)
        self._task = task
        self.busy.start(self.t(message_key), self.t("nav.cancel"), task.cancel)

    def _finish(self, done: Any, result: Any) -> None:
        self.busy.stop()
        done(result)

    def _busy_failed(self, failure: TaskFailure) -> None:
        self.busy.stop()
        self.primary.setEnabled(True)
        self._show_failure(failure)

    def _show_failure(self, failure: TaskFailure) -> None:
        announce(self, failure.message)
        self.title.setText(failure.message)
        self.title.setProperty("severity", "error")

    def run_checks(self) -> None:
        self._busy(
            "busy.verifying_engine",
            lambda: run_diagnostics(self.paths.config_file, paths=self.paths),
            self.steps[1].show_report,  # type: ignore[attr-defined]
        )

    def prepare_provider(self) -> None:
        step = self.steps[2]
        choice = step.choice()  # type: ignore[attr-defined]
        if choice is None or not choice.secrets.get("api_key"):
            step.focus_first_invalid()  # type: ignore[attr-defined]
            return
        descriptor = choice.descriptor
        secret = SecretStr(choice.secrets["api_key"])
        base_url = choice.endpoint or _default_base_url(descriptor.provider_id)

        async def check() -> Any:
            return await check_credential(descriptor, _managed_stub(), secret, base_url=base_url)

        def work() -> Any:
            import asyncio

            return asyncio.run(check())

        self._busy("busy.checking_key", work, self._provider_checked)

    def _provider_checked(self, result: Any) -> None:
        # A check that cannot authenticate is reported as untested, never as passed.
        announce(self, self.t(result.message_key))
        if result.outcome is CheckOutcome.FAILED:
            field = self.steps[2].secret  # type: ignore[attr-defined]
            field.show_error(self.t(result.message_key))
            self.primary.setEnabled(True)
            return
        self._check_outcome = result.outcome
        self.show_step(3)

    def prepare_review(self) -> None:
        step_provider = self.steps[2]
        step_client = self.steps[3]
        choice = step_provider.choice()  # type: ignore[attr-defined]
        if choice is None:
            return
        adapter = step_client.selected()  # type: ignore[attr-defined]
        model = choice.model
        threshold = step_provider.threshold_value()  # type: ignore[attr-defined]
        intent = SetupIntent(
            providers=(
                ProviderIntent(
                    provider_id=choice.descriptor.provider_id,
                    enabled=True,
                    secrets={"api_key": SecretStr(choice.secrets["api_key"])},
                    endpoint=choice.endpoint,
                    api_version=choice.api_version,
                    check_outcome=getattr(self, "_check_outcome", CheckOutcome.NOT_TESTED),
                ),
            ),
            selection=ManagedSelection(
                provider=choice.descriptor.provider_id,
                model=model.model if model else None,
            ),
            privacy=choice.privacy,
            limits=ManagedLimits(estimated_cost_threshold_usd=threshold),
            adapter=adapter,
            takeover=step_client.takeover.isChecked(),  # type: ignore[attr-defined]
            locale=self.t.locale,
        )
        self._intent = intent
        try:
            plan = self.service().plan(intent)
        except DesktopError as exc:
            self._show_failure(TaskFailure(exc.message, exc.recovery, exc.code.value))
            return
        if plan.registration_plan is not None and plan.registration_plan.blocked:
            conflict = plan.registration_plan.conflicts[0]
            step_client.show_conflict(  # type: ignore[attr-defined]
                plan.registration_plan.target_description, conflict.name
            )
            return
        self._plan = plan
        self.steps[4].show_plan(  # type: ignore[attr-defined]
            plan, model, adapter.display_name if adapter else ""
        )
        self.show_step(4)

    def enable_connection(self) -> None:
        plan, intent = self._plan, self._intent
        if plan is None or intent is None:
            return
        service = self.service()
        self._busy("busy.registering", lambda: service.apply(plan, intent), self._applied)

    def _applied(self, outcome: Any) -> None:
        adapter = self._intent.adapter if self._intent else None
        self.steps[5].show_outcome(  # type: ignore[attr-defined]
            outcome, adapter.display_name if adapter else ""
        )
        model = self.steps[2].selected_model()  # type: ignore[attr-defined]
        if model is not None:
            from open_transcribe.desktop.sample import plan_sample

            sample_plan = plan_sample(model)
            text = (
                self.t(
                    "sample.cost",
                    amount=sample_plan.estimated_cost_usd,
                    date=sample_plan.pricing_valid_from,
                )
                if sample_plan.cost_is_known
                else self.t("sample.cost.unknown")
            )
            self.steps[5].show_sample_plan(text)  # type: ignore[attr-defined]
        # Sensitive input is not kept past the step that needed it.
        self.steps[2].deactivate()
        self.show_step(5)

    def transcribe_sample(self) -> None:
        """The sample is a separate, explicitly requested action, never part of enabling."""
        model = self.steps[2].selected_model()  # type: ignore[attr-defined]
        if model is None:
            return
        from open_transcribe.desktop.sample import message_key_for, sample_request, summarize

        service = self.service()

        def work() -> Any:
            import asyncio

            from open_transcribe.desktop.runtime import build_managed_runtime
            from open_transcribe.server import create_service

            runtime = build_managed_runtime(service.paths.config_file)
            transcription = create_service(runtime.settings, runtime.policy)
            response = asyncio.run(transcription.transcribe(sample_request(model)))
            return summarize(response.model_dump(mode="json"))

        finish_step = self.steps[5]

        def done(result: Any) -> None:
            finish_step.show_sample_result(result.text_preview, "ok")  # type: ignore[attr-defined]

        def failed(failure: TaskFailure) -> None:
            self.busy.stop()
            finish_step.show_sample_result(  # type: ignore[attr-defined]
                self.t(message_key_for(failure.code or "")), "error"
            )

        self.primary.setEnabled(False)
        task = run_async(work, lambda result: self._finish(done, result), failed)
        self.busy.start(self.t("busy.transcribing"), self.t("nav.cancel"), task.cancel)
        # Cancelling here stops waiting, not the provider; the step says so.
        finish_step.show_sample_result(  # type: ignore[attr-defined]
            self.t("sample.cancelled"), "info"
        )

    # -- status page ----------------------------------------------------------------

    def service(self) -> SetupService:
        if self._service is None:
            from open_transcribe.desktop.cleanup_timer import CleanupTimer

            self._service = SetupService(
                self.paths,
                SecretServiceCredentialStore(),
                self.installation.engine,
                application_version=self.installation.version,
                cleanup_timer=CleanupTimer.for_user(self.installation),
            )
        return self._service

    def refresh_status(self) -> None:
        def work() -> Any:
            return _read_config(self.paths), run_diagnostics(
                self.paths.config_file, paths=self.paths, check_engine=True
            )

        self._busy(
            "busy.verifying_engine",
            work,
            lambda result: self.status.show_state(result[0], result[1]),
        )

    def repair(self) -> None:
        """Repair reconciles; it does not reinstall everything by default."""
        plan, intent = self._plan, self._intent
        if plan is None or intent is None:
            self.refresh_status()
            return
        self.enable_connection()

    def copy_diagnostic(self) -> None:
        import json

        report = run_diagnostics(self.paths.config_file, paths=self.paths)
        payload = json.dumps(report.to_export(), indent=2, sort_keys=True)
        dialog = DiagnosticPreview(self.t, payload, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.copy_text(payload)

    def copy_text(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        announce(self, self.t("finish.copied"))

    def disconnect_client(self) -> None:
        dialog = DisconnectDialog(self.t, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        service = self.service()
        adapter = self._intent.adapter if self._intent else None
        erase = dialog.erase_requested()

        def work() -> Any:
            outcome = service.disconnect(adapter)
            if erase:
                return service.erase(temporary_audio=self._temporary_audio())
            return outcome

        self._busy("busy.registering", work, lambda _: self.refresh_status())

    def _temporary_audio(self) -> Any:
        """The runtime area to purge, when this installation had one at all."""
        from open_transcribe.desktop.tempaudio import TemporaryAudioArea

        try:
            return TemporaryAudioArea.for_runtime_dir(self.paths.runtime_dir)
        except DesktopError:
            return None


def _read_config(paths: DesktopPaths) -> Any:
    from open_transcribe.desktop.errors import DesktopErrorCode
    from open_transcribe.desktop.store import load_managed_config

    try:
        return load_managed_config(paths.config_file)
    except DesktopError as exc:
        if exc.code is DesktopErrorCode.CONFIG_MISSING:
            return None
        raise


def _default_base_url(provider_id: str) -> str:
    from open_transcribe.settings import ElevenLabsSettings, GroqSettings

    if provider_id == "groq":
        return str(GroqSettings().base_url).rstrip("/")
    if provider_id == "elevenlabs":
        return str(ElevenLabsSettings().base_url).rstrip("/")
    return ""


def _managed_stub() -> Any:
    from open_transcribe.desktop.schema import ManagedProvider

    return ManagedProvider()
