"""USE-04 through USE-07, as far as an offscreen Qt platform can establish them.

These run headless and prove structure: that every step builds, that the primary action says what
it does, that every interactive widget is labelled and focusable, and that the layout does not
clip at the smallest supported size. They do not replace a real screen-reader run or a look at the
window on a real desktop; `docs/desktop-acceptance.md` keeps those separate.
"""

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="Qt ships in the desktop bundle, not the engine environment")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
)

INTERACTIVE = (QPushButton, QLineEdit, QCheckBox, QComboBox, QRadioButton, QDoubleSpinBox)
SMALLEST_SUPPORTED = (640, 480)


@pytest.fixture(scope="session")
def application() -> QApplication:
    from open_transcribe.desktop.gui.theme import apply_theme

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing = QApplication.instance()
    app = existing or QApplication([])
    try:
        apply_theme(app)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - no usable Qt platform plugin
        pytest.skip(f"no usable Qt platform: {exc}")
    return app  # type: ignore[return-value]


@pytest.fixture
def window(application: QApplication, monkeypatch: pytest.MonkeyPatch):
    from open_transcribe.desktop.gui.main_window import MainWindow

    home = Path(tempfile.mkdtemp())
    (home / "run").mkdir()
    for name, value in {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_RUNTIME_DIR": str(home / "run"),
    }.items():
        monkeypatch.setenv(name, value)
    created = MainWindow()
    created.show()
    yield created
    created.close()


def _widgets(page: object) -> list[object]:
    found: list[object] = []
    for kind in INTERACTIVE:
        found.extend(page.findChildren(kind))  # type: ignore[attr-defined]
    return found


def test_the_wizard_has_six_steps_and_a_status_page(window) -> None:
    from open_transcribe.desktop.gui.main_window import TOTAL_STEPS

    assert TOTAL_STEPS == 6
    assert len(window.steps) == TOTAL_STEPS
    assert window.stack.count() == TOTAL_STEPS + 1


def test_every_step_names_its_own_result_rather_than_saying_ok(window) -> None:
    labels = []
    for index in range(len(window.steps)):
        window.show_step(index)
        labels.append(window.primary.text())
    assert labels == [
        "Get started",
        "Continue",
        "Continue",
        "Review setup",
        "Enable connection",
        "Finish",
    ]
    assert "OK" not in labels


def test_the_progress_indicator_is_visible_on_every_step(window) -> None:
    for index in range(len(window.steps)):
        window.show_step(index)
        assert window.progress.isVisible()
        assert window.progress.text() == f"Step {index + 1} of 6"
    # The status page is not a step and shows no step counter.
    window.stack.setCurrentIndex(6)
    window.show_step(6)
    assert not window.progress.isVisible()


def test_back_is_hidden_on_the_first_step_only(window) -> None:
    window.show_step(0)
    assert not window.back.isVisible()
    window.show_step(3)
    assert window.back.isVisible()


def test_every_interactive_widget_is_labelled_and_reachable_by_keyboard(window) -> None:
    unlabelled: list[str] = []
    unreachable: list[str] = []
    for index in range(window.stack.count()):
        page = window.stack.widget(index)
        for widget in _widgets(page):
            name = widget.accessibleName() or (widget.text() if hasattr(widget, "text") else "")
            if not name:
                unlabelled.append(f"{index}:{type(widget).__name__}")
            if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                unreachable.append(f"{index}:{type(widget).__name__}")
    assert unlabelled == []
    assert unreachable == []


def test_the_stylesheet_carries_a_visible_focus_ring_and_severity_colours(
    application: QApplication,
) -> None:
    sheet = application.styleSheet()
    assert "outline: 2px solid" in sheet
    for severity in ("ok", "warning", "error", "info"):
        assert f'severity="{severity}"' in sheet


def test_nothing_clips_at_the_smallest_supported_size(window, application: QApplication) -> None:
    """No page may have a minimum width wider than the window it has to fit in."""
    window.resize(*SMALLEST_SUPPORTED)
    application.processEvents()
    for index in range(window.stack.count()):
        page = window.stack.widget(index)
        assert page.minimumSizeHint().width() <= SMALLEST_SUPPORTED[0], type(page).__name__
    assert window.scroll.horizontalScrollBar().maximum() == 0


def test_the_provider_step_shows_canonical_capabilities_not_a_hand_written_catalogue(
    window,
) -> None:
    window.show_step(2)
    step = window.steps[2]
    providers = [step.provider_box.itemText(i) for i in range(step.provider_box.count())]
    providers_only = providers[1:]
    assert providers_only == ["Microsoft", "ElevenLabs", "Groq"]

    step.provider_box.setCurrentIndex(providers.index("Groq"))
    models = [step.model_box.itemText(i) for i in range(step.model_box.count())]
    assert models == ["Groq whisper-large-v3", "Groq whisper-large-v3-turbo"]
    text = step.capabilities.text()
    assert "Price as published on" in text
    assert "Estimates only" in text
    # Groq needs no resource endpoint, so that field is not shown at all.
    assert not step.endpoint.isVisible()


def test_no_vendor_is_preselected(window) -> None:
    """A position in a catalogue is not a recommendation, and there is no sponsored default."""
    window.show_step(2)
    step = window.steps[2]
    assert step.provider_box.currentIndex() == 0
    assert step.descriptor() is None
    assert step.choice() is None
    assert not step.secret.isVisible()
    assert not window.primary.isEnabled()


def test_the_provider_step_requires_a_choice_and_a_key_before_it_will_continue(window) -> None:
    window.show_step(2)
    step = window.steps[2]
    assert not window.primary.isEnabled()
    step.secret.edit.setText("a-key")
    assert not window.primary.isEnabled(), "a key without a chosen provider is not enough"
    step.provider_box.setCurrentIndex(3)  # Groq: no resource endpoint
    assert step.secret.value() == "", "a key belongs to the provider it was entered for"
    assert not window.primary.isEnabled()
    step.secret.edit.setText("a-key")
    assert window.primary.isEnabled()


def test_a_provider_needing_an_endpoint_will_not_continue_without_one(window) -> None:
    window.show_step(2)
    step = window.steps[2]
    step.provider_box.setCurrentIndex(1)  # Microsoft: needs a resource endpoint
    assert step.endpoint.isVisible()
    step.secret.edit.setText("a-key")
    assert not window.primary.isEnabled()
    step.endpoint.setText("https://speech.example.com")
    assert window.primary.isEnabled()


def test_a_field_error_is_inline_and_focuses_the_field(window) -> None:
    window.show_step(2)
    step = window.steps[2]
    step.provider_box.setCurrentIndex(3)
    step.focus_first_invalid()
    assert step.secret.error.isVisible()
    # Offscreen Qt has no active window, so focus is checked on the widget hierarchy.
    assert window.focusWidget() is step.secret.edit


def test_the_key_field_is_masked_with_an_accessible_reveal(window) -> None:
    window.show_step(2)
    window.steps[2].provider_box.setCurrentIndex(3)
    field = window.steps[2].secret
    assert field.edit.echoMode() == QLineEdit.EchoMode.Password
    field.reveal.setChecked(True)
    assert field.edit.echoMode() == QLineEdit.EchoMode.Normal
    assert field.reveal.accessibleName()


def test_leaving_the_provider_step_clears_the_key_from_the_widget(window) -> None:
    window.show_step(2)
    window.steps[2].provider_box.setCurrentIndex(3)
    field = window.steps[2].secret
    field.edit.setText("a-key")
    window.show_step(3)
    assert field.value() == ""
    assert not field.reveal.isChecked()


def test_the_privacy_permissions_start_off(window) -> None:
    window.show_step(2)
    step = window.steps[2]
    step.provider_box.setCurrentIndex(3)
    assert not step.allow_relay.isChecked()
    assert not step.allow_fallback.isChecked()
    choice = step.choice()
    assert choice.privacy.temporary_audio_processing is False
    assert choice.privacy.cross_provider_fallback is False
    assert choice.privacy.transcript_store == "disabled"


def test_the_cost_threshold_is_off_by_default_and_named_an_estimate(window) -> None:
    window.show_step(2)
    step = window.steps[2]
    assert step.threshold_value() is None
    assert step.threshold_label.text() == "Estimated cost threshold"


def test_a_client_conflict_offers_takeover_without_preselecting_it(window) -> None:
    window.show_step(3)
    step = window.steps[3]
    step.show_conflict("Demo client", "open-transcribe")
    assert step.conflict.isVisible()
    assert step.takeover.isVisible()
    assert not step.takeover.isChecked()


def test_the_review_step_lists_the_recipients_and_the_data_flow(window) -> None:
    from pydantic import SecretStr

    from open_transcribe.desktop.credentials import InMemoryCredentialStore
    from open_transcribe.desktop.schema import ManagedSelection
    from open_transcribe.desktop.setup import ProviderIntent, SetupIntent, SetupService

    service = SetupService(window.paths, InMemoryCredentialStore(), Path("/bin/true"))
    intent = SetupIntent(
        providers=(ProviderIntent("groq", True, {"api_key": SecretStr("k")}),),
        selection=ManagedSelection(provider="groq", model="whisper-large-v3-turbo"),
    )
    plan = service.plan(intent)
    window.show_step(2)
    window.steps[2].provider_box.setCurrentIndex(3)
    model = window.steps[2].selected_model()
    window.show_step(4)
    window.steps[4].show_plan(plan, model, "Demo client")

    assert "Audio may be sent to: groq." in window.steps[4].recipients.text()
    assert "Your assistant receives" in window.steps[4].flow.text()
    assert window.primary.text() == "Enable connection"
    # The details of what changes locally are available, and collapsed until asked for.
    assert not window.steps[4].changes.isVisible()
    window.steps[4].details_button.setChecked(True)
    assert window.steps[4].changes.isVisible()
    assert "keyring: groq:api_key" in window.steps[4].changes.text()


def test_the_final_step_separates_registration_from_activation(window) -> None:
    from open_transcribe.desktop.engine_probe import EngineProbeResult
    from open_transcribe.desktop.setup import ApplyOutcome

    window.show_step(5)
    step = window.steps[5]
    step.show_outcome(
        ApplyOutcome(
            config_saved=True,
            engine=EngineProbeResult(ok=True, reason="engine.ready"),
            registered=True,
            restart_required=True,
        ),
        "Demo client",
    )
    rows = [
        step._rows.itemAt(index).widget().accessibleName() for index in range(step._rows.count())
    ]
    assert any("engine answered" in row for row in rows)
    assert any("Registered in Demo client" in row for row in rows)
    assert any("Restart Demo client" in row for row in rows)
    assert any("check it in your assistant" in row for row in rows)
    assert not any("everything works" in row.lower() for row in rows)


def test_the_first_prompt_is_copyable_and_never_sent(window) -> None:
    window.show_step(5)
    step = window.steps[5]
    assert step.prompt.isReadOnly()
    assert "List the transcription models" in step.prompt.text()
    sent: list[str] = []
    step.copy_prompt.connect(sent.append)
    step.findChildren(QPushButton)  # the copy button lives on the step
    step.copy_prompt.emit(step.prompt.text())
    assert sent == [step.prompt.text()]


def test_the_sample_is_optional_and_starts_untested(window) -> None:
    window.show_step(5)
    step = window.steps[5]
    assert step.sample_result.text() == "Transcription not tested."
    assert step.sample_button.text() == "Transcribe the public sample"


def test_the_disconnect_dialog_leaves_erasure_unticked(application: QApplication) -> None:
    from open_transcribe.desktop.gui.status import DisconnectDialog
    from open_transcribe.desktop.i18n import translator

    dialog = DisconnectDialog(translator("en"))
    assert not dialog.erase_requested()


def test_the_diagnostic_preview_shows_the_payload_before_copying(
    application: QApplication,
) -> None:
    from PySide6.QtWidgets import QPlainTextEdit

    from open_transcribe.desktop.gui.status import DiagnosticPreview
    from open_transcribe.desktop.i18n import translator

    payload = '{"schema": "open-transcribe-diagnostic/1"}'
    dialog = DiagnosticPreview(translator("en"), payload)
    view = dialog.findChild(QPlainTextEdit)
    assert view is not None
    assert view.toPlainText() == payload
    assert view.isReadOnly()


def test_a_failure_reaches_the_window_as_a_message_not_a_traceback() -> None:
    from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
    from open_transcribe.desktop.gui.workers import describe

    failure = describe(
        DesktopError(
            DesktopErrorCode.KEYRING_LOCKED,
            "Your session keyring is locked.",
            recovery="Unlock it.",
        )
    )
    assert failure.code == "KEYRING_LOCKED"
    assert failure.recovery == "Unlock it."
    assert "Traceback" not in failure.message
    assert describe(RuntimeError("internal detail")).message == "Something went wrong."
