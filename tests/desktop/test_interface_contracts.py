"""Interface-layer guarantees that can be checked without a display: strings and import hygiene."""

import string
import subprocess
import sys
from pathlib import Path

import pytest

from open_transcribe.desktop.i18n import (
    _CATALOGUE,
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    resolve_locale,
    translator,
)

GUI_PACKAGE = "open_transcribe.desktop.gui"


def test_both_locales_ship_the_same_keys() -> None:
    english = set(_CATALOGUE["en"])
    for locale in SUPPORTED_LOCALES:
        assert set(_CATALOGUE[locale]) == english, locale


def test_every_placeholder_is_named_and_present_in_both_locales() -> None:
    """Translated strings are never assembled by concatenation, so placeholders must match."""
    for key, english in _CATALOGUE["en"].items():
        expected = {name for _, name, _, _ in string.Formatter().parse(english) if name}
        assert all(not name.isdigit() for name in expected), key
        for locale in SUPPORTED_LOCALES:
            actual = {
                name for _, name, _, _ in string.Formatter().parse(_CATALOGUE[locale][key]) if name
            }
            assert actual == expected, f"{locale}:{key}"


def test_a_missing_key_returns_its_identifier_rather_than_a_blank_label() -> None:
    assert translator("en")("no.such.key") == "no.such.key"


def test_the_session_locale_is_used_and_an_override_wins() -> None:
    assert resolve_locale("system", {"LANG": "fr_FR.UTF-8"}) == "fr"
    assert resolve_locale("system", {"LANG": "de_DE.UTF-8"}) == DEFAULT_LOCALE
    assert resolve_locale("en", {"LANG": "fr_FR.UTF-8"}) == "en"
    assert resolve_locale("system", {}) == DEFAULT_LOCALE


def test_the_plain_data_flow_explanation_is_the_one_the_specification_fixes() -> None:
    body = translator("en")("welcome.body")
    assert "runs on this computer" in body
    assert "does not keep a transcript history by default" in body


def test_the_cost_control_is_never_labelled_a_spending_cap() -> None:
    t = translator("en")
    assert t("cost.threshold") == "Estimated cost threshold"
    assert "not a billing cap" in t("cost.threshold.help")
    for locale in SUPPORTED_LOCALES:
        catalogue = _CATALOGUE[locale]
        assert not any(
            "maximum spend" in value.lower() or "plafond de dépense" in value.lower()
            for value in catalogue.values()
        )


def test_no_string_claims_a_single_overall_success() -> None:
    """There is no one green badge; verification is reported dimension by dimension."""
    for locale in SUPPORTED_LOCALES:
        for value in _CATALOGUE[locale].values():
            assert "everything works" not in value.lower()
            assert "tout fonctionne" not in value.lower()


def test_the_engine_startup_path_never_imports_the_interface() -> None:
    """A headless engine must start where Qt is not installed at all."""
    probe = (
        "import sys;"
        "import open_transcribe.cli as cli;"
        "cli.build_parser();"
        "import open_transcribe.desktop.stdio;"
        "import open_transcribe.desktop.runtime;"
        "leaked = sorted(n for n in sys.modules "
        f"if n.startswith('PySide6') or n.startswith({GUI_PACKAGE!r}));"
        "print(leaked)"
    )
    result = subprocess.run(  # noqa: S603 - this interpreter, a literal program
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout


def test_the_interface_package_is_importable_only_where_qt_is(tmp_path: Path) -> None:
    """The modules exist, and their absence of Qt is the reason they are never eagerly imported."""
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 is part of the desktop bundle, not the engine environment")
    from open_transcribe.desktop.gui import main_window, status, steps, widgets, workers

    assert main_window.TOTAL_STEPS == 6
    assert widgets.SEVERITY_MARK["error"] == "✕"
    assert steps.Step is not None
    assert status.StatusPage is not None
    assert workers.describe(ValueError("x")).code == "INTERNAL_ERROR"


def test_the_severity_marks_never_rely_on_colour_alone() -> None:
    source = Path("src/open_transcribe/desktop/gui/widgets.py").read_text(encoding="utf-8")
    assert "SEVERITY_MARK" in source
    for mark in ("✓", "•", "!", "✕"):
        assert mark in source
