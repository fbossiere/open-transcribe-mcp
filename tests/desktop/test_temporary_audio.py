"""SEC-07 and SEC-08: the relay area's ownership, bounds, cleanup, and recovery."""

import json
import os
import stat
import time
from pathlib import Path

import pytest

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.tempaudio import TemporaryAudioArea


@pytest.fixture
def area(desktop_paths: DesktopPaths) -> TemporaryAudioArea:
    created = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir, ttl_seconds=3600)
    created.prepare()
    return created


def _claim(area: TemporaryAudioArea, path: str) -> Path:
    return area.root / f"{Path(path).name.removesuffix('.audio')}.meta"


def test_a_session_without_a_runtime_directory_cannot_relay() -> None:
    with pytest.raises(DesktopError) as caught:
        TemporaryAudioArea.for_runtime_dir(None)
    assert caught.value.code is DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE


def test_the_ttl_is_capped_at_the_documented_maximum(desktop_paths: DesktopPaths) -> None:
    created = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir, ttl_seconds=999_999)
    assert created.ttl_seconds == 3600


def test_files_are_private_unpredictable_and_exclusive(area: TemporaryAudioArea) -> None:
    first = Path(area.create_file())
    second = Path(area.create_file())
    assert first != second
    assert len(first.stem) == 32
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE(area.root.stat().st_mode) == 0o700


def test_release_removes_the_file_and_its_claim(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    area.release(path)
    assert not Path(path).exists()
    assert not _claim(area, path).exists()


def test_release_ignores_a_path_outside_the_area(area: TemporaryAudioArea, tmp_path: Path) -> None:
    outsider = tmp_path / "someone-elses.audio"
    outsider.write_bytes(b"x")
    area.release(outsider)
    assert outsider.exists()


def test_a_live_owner_keeps_its_unexpired_file(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    report = area.sweep()
    assert report.removed == 0
    assert report.retained == 1
    assert Path(path).exists()


def test_an_expired_file_is_reclaimed_even_from_a_live_owner(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    claim_path = _claim(area, path)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["expires_at"] = time.time() - 1
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    assert area.sweep().removed == 1
    assert not Path(path).exists()


def test_a_dead_owner_leaves_a_file_reclaimable(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    claim_path = _claim(area, path)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["pid"] = 999_999_999
    claim["pid_start_ticks"] = 1
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    assert area.sweep().removed == 1


def test_a_recycled_pid_does_not_protect_an_abandoned_file(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    claim_path = _claim(area, path)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["pid"] = os.getpid()
    claim["pid_start_ticks"] = (claim.get("pid_start_ticks") or 0) + 1
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    assert area.sweep().removed == 1


def test_a_reboot_invalidates_every_claim(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    claim_path = _claim(area, path)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["boot_id"] = "a-previous-boot"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    assert area.sweep().removed == 1


def test_a_file_without_a_claim_is_abandoned(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    _claim(area, path).unlink()
    assert area.sweep().removed == 1


def test_an_orphaned_claim_is_removed(area: TemporaryAudioArea) -> None:
    path = area.create_file()
    Path(path).unlink()
    area.sweep()
    assert not _claim(area, path).exists()


def test_a_symlink_planted_in_the_area_is_never_followed(
    area: TemporaryAudioArea, tmp_path: Path
) -> None:
    target = tmp_path / "precious"
    target.write_text("keep me", encoding="utf-8")
    (area.root / "deadbeef.audio").symlink_to(target)
    area.sweep()
    assert target.read_text(encoding="utf-8") == "keep me"


def test_purge_clears_everything_this_installation_owns(area: TemporaryAudioArea) -> None:
    area.create_file()
    area.create_file()
    report = area.purge()
    assert report.removed == 2
    assert area.total_bytes() == 0


def test_the_aggregate_bound_refuses_a_new_relay(desktop_paths: DesktopPaths) -> None:
    small = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir)
    small = TemporaryAudioArea(root=small.root, ttl_seconds=3600, max_total_bytes=8)
    path = Path(small.create_file())
    path.write_bytes(b"0123456789")
    with pytest.raises(DesktopError) as caught:
        small.create_file()
    assert caught.value.code is DesktopErrorCode.TEMP_AUDIO_UNAVAILABLE


def test_the_next_session_reclaims_crash_residue(desktop_paths: DesktopPaths) -> None:
    first = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir, ttl_seconds=60)
    first.prepare()
    path = first.create_file()
    claim_path = first.root / f"{Path(path).stem}.meta"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["boot_id"] = "crashed-boot"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    # A later session sweeps before it reuses the area.
    second = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir, ttl_seconds=60)
    second.create_file()
    assert not Path(path).exists()
