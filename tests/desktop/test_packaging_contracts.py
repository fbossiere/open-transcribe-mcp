"""PKG-01, PKG-04 and PKG-06: what the package promises, checked without building it."""

import configparser
import re
import stat
from pathlib import Path
from xml.etree import ElementTree

import pytest

from open_transcribe.desktop.installation import ENGINE_NAME, PACKAGE_ROOT

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"
DESKTOP_ENTRY = PACKAGING / "desktop" / "open-transcribe-assistant.desktop"


def _entry() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[method-assign]
    parser.read(DESKTOP_ENTRY, encoding="utf-8")
    return parser


def test_the_desktop_entry_launches_an_absolute_path_without_a_shell() -> None:
    entry = _entry()["Desktop Entry"]
    assert entry["Exec"] == "/usr/bin/open-transcribe-assistant"
    assert entry["Terminal"] == "false"
    assert entry["Type"] == "Application"
    assert entry["StartupWMClass"] == "open-transcribe-assistant"
    assert "sh -c" not in entry["Exec"]


def test_the_desktop_entry_is_translated_and_claims_no_audio_files() -> None:
    entry = _entry()["Desktop Entry"]
    assert entry["Name[fr]"]
    assert entry["Comment[fr]"]
    # It configures a service. It does not open audio, and must not become a MIME handler.
    assert "MimeType" not in entry
    assert "audio/" not in DESKTOP_ENTRY.read_text(encoding="utf-8")


def test_the_application_identity_is_stable_and_matches_the_metainfo() -> None:
    metainfo = PACKAGING / "desktop" / "io.github.fbossiere.OpenTranscribeSetup.metainfo.xml"
    # A file from this repository, read by this repository's own test.
    tree = ElementTree.parse(metainfo)  # noqa: S314
    assert tree.findtext("id") == "io.github.fbossiere.OpenTranscribeSetup"
    assert tree.findtext("project_license") == "Apache-2.0"
    assert tree.find("launchable").text == "open-transcribe-assistant.desktop"  # type: ignore[union-attr]
    assert tree.findtext("provides/binary") == "open-transcribe-assistant"


def test_the_control_template_declares_an_architecture_and_an_honest_recommendation() -> None:
    control = (PACKAGING / "debian" / "control.in").read_text(encoding="utf-8")
    assert "Architecture: amd64" in control
    assert "Architecture: all" not in control
    assert "Recommends: gnome-keyring" in control
    # A recommendation is not a guarantee that the session exposes a usable keyring.
    assert "does not by itself prove" in control
    for field in ("Maintainer:", "Homepage:", "Installed-Size:", "Depends:", "Description:"):
        assert field in control


def test_maintainer_scripts_do_nothing_per_user_and_reach_no_network() -> None:
    forbidden = (
        "getent",
        "loginctl",
        "su ",
        "sudo",
        "curl",
        "wget",
        "pip install",
        "systemctl --user",
        "/home/",
        "secret-tool",
        "apt-get install",
    )
    for name in ("postinst", "prerm", "postrm"):
        script = PACKAGING / "debian" / name
        body = script.read_text(encoding="utf-8")
        assert body.startswith("#!/bin/sh")
        assert "set -e" in body
        assert stat.S_IMODE(script.stat().st_mode) & 0o111
        for term in forbidden:
            assert term not in body, f"{name} must not contain {term!r}"


def test_the_launcher_is_the_only_executable_meant_for_the_path() -> None:
    launcher = (PACKAGING / "debian" / "launcher").read_text(encoding="utf-8")
    assert "/opt/open-transcribe-assistant/open-transcribe-assistant" in launcher
    assert str(PACKAGE_ROOT) in launcher
    # The engine is launched by a client with its absolute path; it never goes on PATH.
    assert f"/usr/bin/{ENGINE_NAME}" not in launcher


def test_the_payload_checker_refuses_a_missing_or_leaky_package(tmp_path: Path) -> None:
    from scripts.check_deb_payload import check  # type: ignore[import-not-found]

    problems = check(tmp_path)
    assert any("missing required file" in problem for problem in problems)

    stage = tmp_path / "stage"
    (stage / "opt" / "open-transcribe-assistant").mkdir(parents=True)
    (stage / "DEBIAN").mkdir()
    (stage / "DEBIAN" / "control").write_text("Package: x\n", encoding="utf-8")
    (stage / "opt" / "open-transcribe-assistant" / ".env").write_text("K=v\n", encoding="utf-8")
    (stage / "opt" / "open-transcribe-assistant" / "settings.json").write_text(
        '{"cache": "/home/builder/.cache"}', encoding="utf-8"
    )
    problems = check(stage)
    assert any("build leftover" in problem for problem in problems)
    assert any("build-machine path" in problem for problem in problems)


def test_the_payload_checker_rejects_the_engine_on_the_path(tmp_path: Path) -> None:
    from scripts.check_deb_payload import check  # type: ignore[import-not-found]

    (tmp_path / "usr" / "bin").mkdir(parents=True)
    (tmp_path / "usr" / "bin" / "open-transcribe-mcp").write_text("#!/bin/sh\n", encoding="utf-8")
    assert any("must not be on PATH" in problem for problem in check(tmp_path))


def test_the_engine_bundle_excludes_the_interface() -> None:
    spec = (PACKAGING / "pyinstaller" / "engine.spec").read_text(encoding="utf-8")
    assert '"PySide6"' in spec
    assert '"open_transcribe.desktop.gui"' in spec
    # Dynamically loaded backends and package metadata must be named, not assumed.
    assert "keyring.backends.SecretService" in spec
    assert "copy_metadata" in spec


def test_both_bundles_are_built_from_one_version_in_one_run() -> None:
    script = (ROOT / "scripts" / "build_deb.sh").read_text(encoding="utf-8")
    assert "engine.spec" in script
    assert "assistant.spec" in script
    assert "--root-owner-group" in script
    assert "check_deb_payload.py" in script
    assert "sha256sum" in script
    assert re.search(r'VERSION="\$\(cd "\$ROOT".*pyproject\.toml', script)


def test_the_cleanup_units_are_harmless_without_the_package() -> None:
    service = (PACKAGING / "desktop" / "open-transcribe-cleanup.service").read_text("utf-8")
    assert "test -x /opt/open-transcribe-assistant/open-transcribe-mcp || exit 0" in service
    assert "PrivateNetwork=true" in service
    assert "cleanup-temporary-audio" in service
    timer = (PACKAGING / "desktop" / "open-transcribe-cleanup.timer").read_text("utf-8")
    assert "OnUnitActiveSec=5min" in timer


def test_the_cleanup_timer_is_never_installed_by_a_maintainer_script() -> None:
    for name in ("postinst", "prerm", "postrm"):
        body = (PACKAGING / "debian" / name).read_text(encoding="utf-8")
        assert "open-transcribe-cleanup" not in body


@pytest.mark.parametrize(
    "path",
    [
        "packaging/debian/copyright",
        "packaging/desktop/open-transcribe-assistant.svg",
        "scripts/generate_notices.py",
        "scripts/derive_deb_depends.py",
    ],
)
def test_release_inputs_are_present(path: str) -> None:
    assert (ROOT / path).is_file()
