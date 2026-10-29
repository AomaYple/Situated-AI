from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import save_archive
from tools.save_archive import SaveArchive, candidate_is_better, parse_date, read_game_date


def _save(path: Path, date: str, payload: bytes = b"body", campaign: str = "test-campaign") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"SAV0100\nmeta_data={\n game_date="
        + date.encode()
        + b'\n}\nplaythrough_id="'
        + campaign.encode()
        + b'"\n'
        + payload
    )


def test_parse_game_date_and_nearest_candidate() -> None:
    assert parse_date("1856.1.1") == (1856, 1, 1)
    assert candidate_is_better("1856.2.1", None, "1856.1.1")
    assert candidate_is_better("1856.1.1", "1856.2.1", "1856.1.1")
    assert not candidate_is_better("1856.3.1", "1856.2.1", "1856.1.1")


def test_read_date_only_reads_header(tmp_path: Path) -> None:
    path = tmp_path / "autosave.v3"
    _save(path, "1836.1.1", b"x" * 100000)
    assert read_game_date(path) == "1836.1.1"


def test_archive_keeps_nearest_candidate_and_writes_hash(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    output = tmp_path / "out"
    path = userdir / "save games/autosave.v3"
    _save(path, "1856.2.1", b"first")
    collector = SaveArchive(
        userdir, output, ("1856.1.1",), stable_seconds=0, poll_seconds=0.5, window_months=12
    )
    collector.poll()
    collector.poll()
    row = collector.state["1856.1.1"]
    assert row["candidate"]["actual_date"] == "1856.2.1"
    assert Path(output / "candidates" / row["candidate"]["path"]).stat().st_size > 0
    _save(path, "1856.1.1", b"second")
    collector.poll()
    collector.poll()
    assert collector.state["1856.1.1"]["candidate"]["actual_date"] == "1856.1.1"
    assert collector.state["1856.1.1"]["status"] == "complete"
    files = list((output / "candidates").glob("*.v3"))
    assert len(files) == 1
    assert hashlib.sha256(files[0].read_bytes()).hexdigest() == row["candidate"]["sha256"]
    assert path.read_bytes() == files[0].read_bytes()


def test_explicit_baseline_is_copied_without_text_parsing(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    source = tmp_path / "cloud" / "opening.v3"
    source.parent.mkdir()
    source.write_bytes(b"SAV0105\x00PK compressed opening save")
    collector = SaveArchive(
        userdir,
        tmp_path / "out",
        ("1836.1.1",),
        stable_seconds=0,
        baselines=(("1836.1.1", source),),
    )
    row = collector.state["1836.1.1"]
    assert row["status"] == "complete"
    assert row["candidate"]["format"].startswith("原始用户指定")
    assert (
        tmp_path / "out" / "candidates" / row["candidate"]["path"]
    ).read_bytes() == source.read_bytes()


def test_target_stays_pending_until_nearby_window_has_passed(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    path = userdir / "save games/autosave.v3"
    _save(path, "1856.2.1")
    collector = SaveArchive(
        userdir,
        tmp_path / "out",
        ("1856.1.1",),
        stable_seconds=0,
        window_months=12,
    )
    collector.poll()
    collector.poll()
    assert collector.state["1856.1.1"]["status"] == "pending"
    collector._finalize_passed_targets(1857 * 12 + 1)
    assert collector.state["1856.1.1"]["status"] == "complete"


@pytest.mark.parametrize(
    "value", ["", "1856.1", "year.1.1", "1856.0.1", "1856.2.30", "1855.2.29", "0.1.1", "1856.1.1.2"]
)
def test_invalid_calendar_dates_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_date(value)


def test_candidates_in_same_month_use_day_distance() -> None:
    assert candidate_is_better("1856.1.1", "1856.1.20", "1856.1.1")
    assert not candidate_is_better("1856.1.20", "1856.1.1", "1856.1.1")
    assert candidate_is_better("1855.12.1", "1856.2.1", "1856.1.1")


def test_first_scan_does_not_mark_still_unstable_files_unavailable(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    _save(userdir / "save games/autosave.v3", "1858.1.1")
    _save(userdir / "save games/opening.v3", "1856.1.1")
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    collector.poll()
    assert collector.state["1856.1.1"]["status"] == "pending"
    collector.poll()
    assert collector.state["1856.1.1"]["status"] == "complete"
    assert collector.state["1856.1.1"]["selected_date"] == "1856.1.1"


def test_unavailable_only_after_full_window_without_matching_save(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    _save(userdir / "save games/autosave.v3", "1858.1.1")
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    collector.poll()
    collector.poll()
    assert collector.state["1856.1.1"]["status"] == "unavailable"


def test_archive_ignores_saves_from_other_campaigns(tmp_path: Path) -> None:
    userdir, cloud = tmp_path / "user", tmp_path / "cloud"
    _save(userdir / "save games/autosave.v3", "1855.12.1")
    _save(cloud / "other.v3", "1856.1.1", campaign="another-campaign")
    collector = SaveArchive(
        userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0, cloud_dirs=(cloud,)
    )
    collector.poll()
    collector.poll()
    assert collector.playthrough_id == "test-campaign"
    assert collector.state["1856.1.1"]["candidate"]["actual_date"] == "1855.12.1"


def test_copy_retries_if_source_changes_and_keeps_previous_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    userdir = tmp_path / "user"
    source = userdir / "save games/autosave.v3"
    _save(source, "1855.12.1")
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    collector.poll()
    collector.poll()
    previous = collector.state["1856.1.1"]["candidate"].copy()
    _save(source, "1856.1.1")
    collector.poll()
    original_fsync = save_archive.os.fsync

    def mutate_after_copy(fd):
        original_fsync(fd)
        _save(source, "1856.2.1", b"replaced body")

    monkeypatch.setattr(save_archive.os, "fsync", mutate_after_copy)
    collector.poll()
    assert collector.state["1856.1.1"]["candidate"] == previous
    assert not list((tmp_path / "out/candidates").glob("*.part"))


@pytest.mark.parametrize("inside_source", [False, True])
def test_archive_refuses_existing_output_or_game_directory(
    tmp_path: Path, inside_source: bool
) -> None:
    userdir = tmp_path / "user"
    output = userdir / "archive" if inside_source else tmp_path / "out"
    if not inside_source:
        output.mkdir()
        (output / "precious.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        SaveArchive(userdir, output, ("1856.1.1",))
    if not inside_source:
        assert (output / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_run_stops_after_exact_save_is_complete(tmp_path: Path, monkeypatch) -> None:
    userdir = tmp_path / "user"
    _save(userdir / "save games/autosave.v3", "1856.1.1")
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    monkeypatch.setattr(save_archive.time, "sleep", lambda _: None)
    assert collector.run() == 0
    assert (
        json.loads((tmp_path / "out/status.json").read_text(encoding="utf-8"))["status"]
        == "complete"
    )


def test_run_failure_records_failure_status(tmp_path: Path, monkeypatch) -> None:
    collector = SaveArchive(tmp_path / "user", tmp_path / "out", ("1856.1.1",))

    def fail_poll():
        raise OSError("disk error")

    monkeypatch.setattr(collector, "poll", fail_poll)
    with pytest.raises(OSError, match="disk error"):
        collector.run()
    assert (
        json.loads((tmp_path / "out/status.json").read_text(encoding="utf-8"))["status"] == "failed"
    )


def test_hash_failure_never_promotes_candidate(tmp_path: Path, monkeypatch) -> None:
    userdir = tmp_path / "user"
    _save(userdir / "save games/autosave.v3", "1856.1.1")
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    monkeypatch.setattr(save_archive, "sha256", lambda _: "invalid-digest")
    collector.poll()
    collector.poll()
    assert collector.state["1856.1.1"]["candidate"] is None
    assert list((tmp_path / "out/candidates").iterdir()) == []


@pytest.mark.parametrize(("actual", "expected_code"), [("1856.2.1", 0), ("1840.1.1", 2)])
def test_game_exit_drains_stable_save_and_reports_missing_targets(
    tmp_path: Path, monkeypatch, actual: str, expected_code: int
) -> None:
    userdir = tmp_path / "user"
    _save(userdir / "save games/autosave.v3", actual)
    collector = SaveArchive(userdir, tmp_path / "out", ("1856.1.1",), stable_seconds=0)
    collector.pid = 123
    collector.process_started_at = None
    clock = [0.0]
    monkeypatch.setattr(save_archive.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        save_archive.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(collector, "game_running", lambda: False)
    assert collector.run() == expected_code
    status = json.loads((tmp_path / "out/status.json").read_text(encoding="utf-8"))
    assert status["status"] == (
        "complete" if expected_code == 0 else "game_exited_before_all_targets"
    )


def test_explicit_campaign_allows_reading_cloud_save_without_local_autosave(
    tmp_path: Path,
) -> None:
    cloud = tmp_path / "cloud"
    _save(cloud / "save.v3", "1856.1.1")
    collector = SaveArchive(
        tmp_path / "user",
        tmp_path / "out",
        ("1856.1.1",),
        stable_seconds=0,
        cloud_dirs=(cloud,),
        playthrough_id="test-campaign",
    )
    collector.poll()
    collector.poll()
    assert collector.state["1856.1.1"]["status"] == "complete"
