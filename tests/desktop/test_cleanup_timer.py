"""§11 and §13: the cleanup timer is installed only with the opt-in, and removed with it."""

import stat
from pathlib import Path

import pytest

from open_transcribe.desktop.cleanup_timer import SERVICE_NAME, TIMER_NAME, CleanupTimer
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.installation import current_installation

_FAKE_SYSTEMCTL = """#!/bin/sh
printf '%s\\n' "$*" >>"$FAKE_SYSTEMCTL_LOG"
exit "${FAKE_SYSTEMCTL_STATUS:-0}"
"""


@pytest.fixture
def systemctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "systemctl"
    path.write_text(_FAKE_SYSTEMCTL, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_SYSTEMCTL_LOG", str(tmp_path / "calls.log"))
    return path


@pytest.fixture
def timer(tmp_path: Path, systemctl: Path) -> CleanupTimer:
    return CleanupTimer(
        unit_dir=tmp_path / "systemd" / "user",
        installation=current_installation(),
        systemctl=systemctl,
    )


def calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_it_installs_and_starts_only_its_own_units(timer: CleanupTimer, tmp_path: Path) -> None:
    assert not timer.installed
    timer.install()
    assert timer.installed
    assert (timer.unit_dir / TIMER_NAME).is_file()
    assert (timer.unit_dir / SERVICE_NAME).is_file()
    assert calls(tmp_path) == ["--user daemon-reload", f"--user enable --now {TIMER_NAME}"]


def test_the_installed_service_cannot_run_without_the_packaged_engine(
    timer: CleanupTimer,
) -> None:
    timer.install()
    service = (timer.unit_dir / SERVICE_NAME).read_text(encoding="utf-8")
    assert "test -x /opt/open-transcribe-assistant/open-transcribe-mcp || exit 0" in service
    assert "PrivateNetwork=true" in service
    # It sweeps; it is not a transcription service.
    assert "cleanup-temporary-audio" in service
    assert "serve" not in service


def test_removal_takes_only_the_units_it_wrote(timer: CleanupTimer, tmp_path: Path) -> None:
    unrelated = timer.unit_dir
    timer.install()
    unrelated.joinpath("someone-elses.timer").write_text("[Timer]\n", encoding="utf-8")

    assert timer.remove() is True
    assert not timer.installed
    assert not (timer.unit_dir / TIMER_NAME).exists()
    assert not (timer.unit_dir / SERVICE_NAME).exists()
    assert (unrelated / "someone-elses.timer").exists()
    assert f"--user disable --now {TIMER_NAME}" in calls(tmp_path)


def test_removing_a_timer_that_is_not_there_is_not_a_failure(timer: CleanupTimer) -> None:
    assert timer.remove() is True


def test_a_refusing_systemctl_is_reported_rather_than_assumed(
    timer: CleanupTimer, monkeypatch: pytest.MonkeyPatch
) -> None:
    timer.install()
    monkeypatch.setenv("FAKE_SYSTEMCTL_STATUS", "1")
    assert timer.remove() is False
    # The unit files are still cleared, so nothing keeps firing on the user's behalf.
    assert not (timer.unit_dir / TIMER_NAME).exists()


def test_a_session_without_systemd_cannot_offer_the_permission(tmp_path: Path) -> None:
    """If the expiry mechanism is unavailable, relay stays unavailable."""
    without = CleanupTimer(
        unit_dir=tmp_path / "units", installation=current_installation(), systemctl=None
    )
    assert not without.available
    with pytest.raises(DesktopError) as caught:
        without.install()
    assert caught.value.code is DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE
    assert caught.value.recovery is not None


def test_it_finds_its_units_beside_the_packaged_application(timer: CleanupTimer) -> None:
    for name in (TIMER_NAME, SERVICE_NAME):
        assert timer._packaged_unit(name).is_file()


def test_a_missing_unit_source_is_an_actionable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from open_transcribe.desktop import cleanup_timer as module
    from open_transcribe.desktop.installation import Installation

    # Neither the packaged layout nor the repository copy is present.
    monkeypatch.setattr(module, "_repository_unit", lambda name: tmp_path / "absent" / name)
    nowhere = CleanupTimer(
        unit_dir=tmp_path / "units",
        installation=Installation(
            root=tmp_path / "absent",
            engine=tmp_path / "absent" / "engine",
            assistant=tmp_path / "absent" / "assistant",
            config_dir=tmp_path / "absent" / "config",
            packaged=False,
        ),
        systemctl=Path("/bin/true"),
    )
    with pytest.raises(DesktopError) as caught:
        nowhere._packaged_unit(TIMER_NAME)
    assert caught.value.code is DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE
