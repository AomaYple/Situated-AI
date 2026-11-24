"""人工安装夹具及独立 OS 枚举；不读取真实安装或签发完整 epoch。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, BinaryIO, Literal, cast

import pytest

from pdx import input_inventory as inventory
from pdx.input_contracts import (
    CaptureCheck,
    InputIdentity,
    SnapshotProvenance,
    dumps_contract,
    loads_contract,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


def test_full_installation_matches_independent_os_walk(tmp_path: Path) -> None:
    """漏掉脚本以外的任何根、未知格式或空文件均应破坏对账。"""
    contents = {
        "game/common/test.txt": b"x = yes",
        "game/gui/window.gui": b"window = {}",
        "game/gfx/person.dna": b"dna",
        "game/localization/test.yml": b"l_english:",
        "game/map_data/provinces.png": b"\x89PNG",
        "game/fonts/body.ttf": b"font",
        "game/music/theme.ogg": b"audio",
        "game/dlc/fixture/archive.zip": b"archive",
        "game/gfx/map/map_object_data/generated/map.txt": b"map = {}",
        "jomini/gui/base.gui": b"gui",
        "clausewitz/common/base.txt": b"engine",
        "binaries/game.exe": b"MZ",
        "launcher/launcher-settings.json": b"{}",
        "licenses/LICENSE": b"permission",
        "other/new.unrecognized": b"unknown",
        "ROOTFILE": b"root",
        "empty-file": b"",
    }
    for relative, raw in contents.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (tmp_path / "empty-directory").mkdir()

    independent: dict[str, tuple[int, str]] = {}
    for directory, _, names in os.walk(tmp_path, followlinks=False):
        for name in names:
            path = Path(directory) / name
            raw = path.read_bytes()
            independent[path.relative_to(tmp_path).as_posix()] = (
                len(raw),
                hashlib.sha256(raw).hexdigest(),
            )

    result = inventory.inventory_installation(tmp_path, chunk_size=3)
    assert result.scan_status == "complete", result.diagnostics
    assert {record.path: (record.size, record.sha256) for record in result.records} == independent
    assert result.observed_paths == tuple(sorted(contents))
    assert "empty-directory" in result.directories
    assert result.summary.file_count == 17
    assert result.summary.known_bytes == sum(len(raw) for raw in contents.values())
    assert sum(count for _, count in result.summary.category_counts) == 17
    categories = {record.path: record.category for record in result.records}
    assert categories["binaries/game.exe"] == "binary"
    assert categories["licenses/LICENSE"] == "documentation"
    assert categories["game/gfx/person.dna"] == "asset_entity_dna"
    assert categories["game/localization/test.yml"] == "localization"
    assert categories["other/new.unrecognized"] == "unknown"
    assert categories["ROOTFILE"] == "unknown"
    assert all(record.raw is None for record in result.records)
    assert all(record.parse_status == "not_attempted" for record in result.records)
    assert all(record.completeness == "partial" for record in result.records)


def _installation(tmp_path: Path) -> Path:
    (tmp_path / "game").mkdir()
    (tmp_path / "game/a.txt").write_bytes(b"abc")
    return tmp_path


def test_read_denial_keeps_row_without_fabricated_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    original_open = inventory._open_verified

    def denied(path: Path) -> int:
        if Path(path) == root / "game/a.txt":
            raise PermissionError("fixture: access denied")
        return original_open(path)

    monkeypatch.setattr(inventory, "_open_verified", denied)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert result.observed_paths == ("game/a.txt",)
    (record,) = result.records
    assert record.size == 3
    assert record.sha256 is None
    assert record.read_status == "failed"
    assert "read_failed" in {problem.code for problem in result.diagnostics}
    assert inventory.estimate_capacity(result).required_bytes is None


def test_unreadable_directory_is_a_frontier_not_an_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    blocked = root / "private"
    blocked.mkdir()
    (blocked / "unseen.txt").write_bytes(b"not counted as zero")
    original_scandir = os.scandir

    def denied(path: Path) -> Iterator[os.DirEntry[str]]:
        if Path(path) == blocked:
            raise PermissionError("fixture: cannot enumerate")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", denied)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert result.blocked_directories == ("private",)
    assert "private" in result.directories
    assert result.summary.file_count == 1
    assert "enumeration_failed" in {problem.code for problem in result.diagnostics}


@pytest.mark.parametrize("change", ["add", "remove", "same_size_edit"])
def test_scan_drift_never_signs_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = _installation(tmp_path)
    trigger = root / "game/z.txt"
    trigger.write_bytes(b"trigger")
    victim = root / "game/a.txt"
    original_stat = victim.stat()
    original_open = inventory._open_verified
    changed = False

    def mutate(path: Path) -> int:
        nonlocal changed
        if Path(path) == trigger and not changed:
            changed = True
            if change == "add":
                (root / "new.unknown").write_bytes(b"new")
            elif change == "remove":
                victim.unlink()
            else:
                victim.write_bytes(b"xyz")
                os.utime(victim, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        return original_open(path)

    monkeypatch.setattr(inventory, "_open_verified", mutate)
    result = inventory.inventory_installation(root, chunk_size=2)
    assert result.scan_status == "partial"
    codes = {problem.code for problem in result.diagnostics}
    records = {record.path: record for record in result.records}
    if change == "add":
        assert "path_added" in codes
        assert records["new.unknown"].read_status == "not_read"
        assert records["new.unknown"].size == 3
        assert records["new.unknown"].sha256 is None
    elif change == "remove":
        assert "path_removed" in codes
        assert "game/a.txt" in records
    else:
        assert "content_changed" in codes
        assert records["game/a.txt"].sha256 == hashlib.sha256(b"abc").hexdigest()


def test_casefold_collision_cannot_have_denominator_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    original_scandir = os.scandir

    @contextmanager
    def colliding(path: Path) -> Iterator[Iterator[os.DirEntry[str] | SimpleNamespace]]:
        with original_scandir(path) as iterator:
            entries: list[os.DirEntry[str] | SimpleNamespace] = list(iterator)
        if Path(path) == root / "game":
            # Windows 默认不允许创建仅大小写不同的二文件；模拟枚举实际会给出的
            # 两个名字，后续路径打开、lstat、哈希及分母拒绝都走真实实现。
            entries.append(SimpleNamespace(name="A.txt", path=str(root / "game/a.txt")))
        yield iter(entries)

    monkeypatch.setattr(os, "scandir", colliding)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert result.observed_paths == ("game/A.txt", "game/a.txt")
    assert result.file_set_sha256 is None
    assert "case_collision" in {problem.code for problem in result.diagnostics}


def test_reparse_point_is_visible_but_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    target = root / "game/a.txt"
    original_lstat = Path.lstat
    original_open = os.open

    def reparse(path: Path) -> os.stat_result | SimpleNamespace:
        value = original_lstat(path)
        if path == target:
            fields = {
                name: getattr(value, name)
                for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            }
            return SimpleNamespace(**fields, st_file_attributes=0x400)
        return value

    def refused(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        assert Path(path) != target, "重解析节点不应打开目标"
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "lstat", reparse)
    monkeypatch.setattr(os, "open", refused)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    (record,) = result.records
    assert record.read_status == "not_read"
    assert record.size is None
    assert record.sha256 is None
    assert "link_refused" in {problem.code for problem in result.diagnostics}


def test_real_link_outside_root_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside scope")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"本机缺少符号链接权限或能力，不能创建符号链接：{error}")
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert "escape" in result.observed_paths
    assert all("secret.txt" not in record.path for record in result.records)
    assert "link_refused" in {problem.code for problem in result.diagnostics}


def test_empty_root_and_missing_or_content_only_root_are_distinct(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    empty = inventory.inventory_installation(tmp_path)
    assert empty.scan_status == "complete"
    assert empty.records == ()
    assert empty.blocked_directories == ()
    missing = inventory.inventory_installation(tmp_path / "missing")
    assert missing.scan_status == "failed"
    assert missing.blocked_directories == (".",)
    content_only = inventory.inventory_installation(tmp_path / "game")
    assert content_only.scan_status == "partial"
    assert "missing_installation_root" in {problem.code for problem in content_only.diagnostics}


def test_path_traversal_rejected_before_filesystem_reads(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="路径穿越"):
        inventory.inventory_installation(tmp_path / ".." / tmp_path.name)
    for path in ("../a.txt", "/absolute", "game\\bad", "game/a:b", "game//a"):
        with pytest.raises(ValueError, match="POSIX"):
            inventory.classify_path(path)


def test_external_materials_require_authorization_and_stay_separate(tmp_path: Path) -> None:
    (tmp_path / "manual.pdf").write_bytes(b"manual")
    denied = inventory.inventory_material(
        tmp_path,
        source_layer="official_docs",
        authorization="enumeration only",
        read_authorized=False,
    )
    assert denied.scan_status == "partial"
    assert denied.records[0].sha256 is None
    assert denied.records[0].read_status == "not_read"
    assert "read_not_authorized" in {problem.code for problem in denied.diagnostics}
    allowed = inventory.inventory_material(
        tmp_path, source_layer="official_docs", authorization="fixture read", read_authorized=True
    )
    assert allowed.scan_status == "complete"
    assert allowed.is_installation is False
    assert allowed.records[0].source_layer == "official_docs"
    assert allowed.summary.file_count == 1
    with pytest.raises(ValueError, match="来源"):
        inventory.inventory_material(
            tmp_path, source_layer="installation", authorization="bad", read_authorized=True
        )


def test_full_inventory_includes_paths_outside_the_script_scan(tmp_path: Path) -> None:
    root = _installation(tmp_path)
    fixtures = {
        "game/a.txt": (b"abc", "pdx_script"),
        "game/gfx/map/map_object_data/generated/map.txt": (b"generated", "pdx_script"),
        "game/soundtrack/track.ogg": (b"audio", "audio_video"),
        "binaries/game.exe": (b"MZ", "binary"),
        "launcher/launcher-settings.json": (b"{}", "structured_configuration"),
        "unknown/new.blob": (b"unknown", "unknown"),
    }
    for relative, (raw, _) in fixtures.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    result = inventory.inventory_installation(root)

    assert result.scan_status == "complete", result.diagnostics
    assert result.observed_paths == tuple(sorted(fixtures))
    assert result.summary.file_count == len(fixtures)
    assert {
        record.path: (record.size, record.sha256, record.category) for record in result.records
    } == {
        relative: (len(raw), hashlib.sha256(raw).hexdigest(), category)
        for relative, (raw, category) in fixtures.items()
    }


def test_capacity_assumes_no_compression_and_preserves_redundancies(tmp_path: Path) -> None:
    root = _installation(tmp_path)
    (root / "game/large.zip").write_bytes(b"12345")
    result = inventory.inventory_installation(root)
    estimate = inventory.estimate_capacity(result)
    assert estimate.source_bytes == 8
    assert estimate.largest_file_bytes == 5
    assert estimate.required_bytes == 37  # 8 原件 + 8 staging + 8 retry + 8 recovery + 5 最大文件
    assert estimate.compression_saving_bytes == 0
    assert (
        inventory.estimate_capacity(
            result, staging_copies=0, retry_copies=0, recovery_copies=0
        ).required_bytes
        == 13
    )
    before = set(tmp_path.iterdir())
    target = inventory.inspect_capacity_target(
        tmp_path, estimate, copy_authorized=False, access_boundary="fixture local disk only"
    )
    assert target.path == tmp_path.as_posix()
    assert target.available_bytes is not None
    assert target.write_access == "unverified"
    assert target.copy_authorized is False
    assert target.access_boundary == "fixture local disk only"
    assert set(tmp_path.iterdir()) == before
    with pytest.raises(ValueError, match="非负整数"):
        inventory.estimate_capacity(result, staging_copies=-1)


def test_binding_requires_supplied_matching_identity_and_stays_partial(tmp_path: Path) -> None:
    result = inventory.inventory_installation(_installation(tmp_path))
    assert result.file_set_sha256 is not None
    check = CaptureCheck("fixture-only", "a" * 64, result.file_set_sha256, "stable")
    identity = InputIdentity(
        result.root,
        "fixture-version",
        "fixture-build",
        "fixture-branch",
        (),
        (),
        1,
        result.file_set_sha256,
        (),
        (),
        check,
        check,
        SnapshotProvenance("installation", "fixture-only", None, None),
        "partial",
    )
    contract = inventory.bind_inventory(result, identity)
    assert contract.epoch_id == identity.epoch_id
    assert contract.completeness == "partial"
    assert loads_contract(dumps_contract(contract)) == contract
    with pytest.raises(ValueError, match="分母"):
        inventory.bind_inventory(result, replace(identity, file_count=2))


def test_changes_during_stream_do_not_publish_partial_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    target = root / "game/a.txt"
    original_fdopen = os.fdopen
    mutated = False

    class MutatingReader:
        def __init__(self, stream: BinaryIO) -> None:
            self.stream = stream

        def fileno(self) -> int:
            return self.stream.fileno()

        def read(self, size: int) -> bytes:
            nonlocal mutated
            raw = self.stream.read(size)
            if raw and not mutated:
                mutated = True
                target.write_bytes(b"longer")
            return raw

    @contextmanager
    def mutate_during_read(fd: int, mode: Literal["rb"]) -> Iterator[MutatingReader]:
        with original_fdopen(fd, mode) as stream:
            yield MutatingReader(stream)

    monkeypatch.setattr(os, "fdopen", mutate_during_read)
    result = inventory.inventory_installation(root, chunk_size=1)
    assert result.scan_status == "partial"
    (record,) = result.records
    assert record.read_status == "failed"
    assert record.sha256 is None
    assert "file_changed" in {problem.code for problem in record.diagnostics}


@pytest.mark.parametrize("size", [0, -1, True])
def test_invalid_chunk_sizes_do_not_begin_scanning(tmp_path: Path, size: int) -> None:
    with pytest.raises(ValueError, match="正整数"):
        inventory.inventory_installation(tmp_path, chunk_size=size)


def test_directory_summaries_reconcile_direct_children_and_empty_directories(
    tmp_path: Path,
) -> None:
    root = _installation(tmp_path)
    (root / "game/empty").mkdir()
    (root / "ROOTFILE").write_bytes(b"root")
    result = inventory.inventory_installation(root)
    summaries = {row.path: row for row in inventory.summarize_directories(result)}
    assert summaries["."].file_count == 1
    assert summaries["."].known_bytes == 4
    assert summaries["game"].file_count == 1
    assert summaries["game"].known_bytes == 3
    assert summaries["game/empty"].file_count == 0
    assert summaries["game/empty"].blocked is False
    assert sum(row.file_count for row in summaries.values()) == 2
    assert sum(row.known_bytes for row in summaries.values()) == 7


def test_capacity_target_rejects_unc_before_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = inventory.inventory_installation(_installation(tmp_path))
    estimate = inventory.estimate_capacity(result)
    original_lstat = Path.lstat

    def reject_remote(path: Path) -> os.stat_result:
        assert not str(path).startswith(("\\\\", "//")), "不得读取远程候选路径"
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", reject_remote)
    target = inventory.inspect_capacity_target(
        Path("//fixture.invalid/remote"),
        estimate,
        copy_authorized=False,
        access_boundary="remote is outside authorization",
    )
    assert target.available_bytes is None
    assert "nonlocal_target" in {problem.code for problem in target.diagnostics}


def test_real_windows_junction_and_linked_root_are_refused(tmp_path: Path) -> None:
    windows_api = pytest.importorskip("_winapi", reason="需要 Windows 的 _winapi 模块")
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"outside scope")
    junction = root / "escape"
    try:
        windows_api.CreateJunction(str(outside), str(junction))
    except OSError as error:
        pytest.skip(f"Windows 本机不能创建 junction：{error}")
    try:
        result = inventory.inventory_installation(root)
        assert result.scan_status == "partial"
        assert "escape" in result.observed_paths
        assert all("secret.txt" not in record.path for record in result.records)
        assert "link_refused" in {problem.code for problem in result.diagnostics}
        linked_root = inventory.inventory_installation(junction)
        assert linked_root.scan_status == "failed"
        assert linked_root.blocked_directories == (".",)
        assert linked_root.records == ()
        assert secret.read_bytes() == b"outside scope"
    finally:
        junction.rmdir()


def test_junction_swap_after_checks_reads_zero_outside_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows_api = pytest.importorskip("_winapi", reason="需要 Windows 的 _winapi 模块")
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"external fixture sentinel")
    game = root / "game"
    saved = tmp_path / "saved-game"
    target = game / "a.txt"
    original_check = inventory._check_components
    original_fdopen = os.fdopen
    switched = False
    read_sizes = []

    def switch_after_check(path: Path) -> None:
        nonlocal switched
        original_check(path)
        if path == target and not switched:
            game.rename(saved)
            windows_api.CreateJunction(str(outside), str(game))
            switched = True

    class WatchedReader:
        def __init__(self, stream: BinaryIO) -> None:
            self.stream = stream

        def fileno(self) -> int:
            return self.stream.fileno()

        def read(self, size: int) -> bytes:
            raw = self.stream.read(size)
            read_sizes.append(len(raw))
            return raw

    @contextmanager
    def watched_fdopen(fd: int, mode: Literal["rb"]) -> Iterator[WatchedReader]:
        with original_fdopen(fd, mode) as stream:
            yield WatchedReader(stream)

    monkeypatch.setattr(inventory, "_check_components", switch_after_check)
    monkeypatch.setattr(os, "fdopen", watched_fdopen)
    try:
        result = inventory.inventory_installation(root)
    finally:
        if switched:
            game.rmdir()
            saved.rename(game)
    assert switched
    assert read_sizes == [], "根外句柄必须在任何流式 read 之前被拒绝"
    assert result.scan_status == "partial"
    assert "opened_path_mismatch" in {problem.code for problem in result.diagnostics}


@pytest.mark.parametrize("deny_stat", [False, True])
def test_iterator_error_preserves_each_already_yielded_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deny_stat: bool
) -> None:
    root = _installation(tmp_path)
    original_scandir = os.scandir
    original_lstat = Path.lstat
    yielded = []

    @contextmanager
    def partial_scandir(path: Path) -> Iterator[Iterator[os.DirEntry[str]]]:
        with original_scandir(path) as stream:
            if Path(path) != root / "game":
                yield stream
                return
            first = next(stream)

            def failing_iterator() -> Iterator[os.DirEntry[str]]:
                yielded.append(first.name)
                yield first
                raise PermissionError("fixture: iterator failed after a visible path")

            yield failing_iterator()

    monkeypatch.setattr(os, "scandir", partial_scandir)
    if deny_stat:

        def denied(path: Path) -> os.stat_result:
            if path == root / "game/a.txt":
                raise PermissionError("fixture: visible path cannot be statted")
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", denied)
    result = inventory.inventory_installation(root)
    assert yielded == ["a.txt", "a.txt"]
    assert result.scan_status == "partial"
    assert result.observed_paths == ("game/a.txt",)
    assert result.summary.file_count == 1
    assert result.blocked_directories == ("game",)
    if deny_stat:
        assert result.records[0].size is None
        assert result.records[0].sha256 is None
    else:
        assert result.records[0].size == 3
        assert result.records[0].sha256 == hashlib.sha256(b"abc").hexdigest()
    assert "enumeration_failed" in {problem.code for problem in result.diagnostics}


@pytest.mark.skipif(os.name != "nt", reason="仅验证 Windows 原生句柄路径 API 失败")
def test_windows_handle_query_failure_never_enters_read_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)

    def unavailable(_descriptor: int) -> None:
        raise OSError("fixture: final handle path query failed")

    def forbidden_fdopen(*_args: object, **_kwargs: object) -> None:
        pytest.fail("实际对象边界不可核验时不得建立读取流")

    monkeypatch.setattr(inventory, "_windows_final_path", unavailable)
    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert result.records[0].sha256 is None
    assert "opened_path_unverifiable" in {problem.code for problem in result.diagnostics}


def test_unsupported_secure_open_platform_explicitly_refuses_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)

    class UnsupportedPlatform:
        name = "fixture-unsupported-platform"

        def __getattr__(self, name: str) -> object:
            return getattr(os, name)

    def forbidden_fdopen(*_args: object, **_kwargs: object) -> None:
        pytest.fail("平台没有安全打开能力时不得建立读取流")

    monkeypatch.setattr(inventory, "os", UnsupportedPlatform())
    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert result.records[0].sha256 is None
    assert "secure_open_unsupported" in {problem.code for problem in result.diagnostics}


@pytest.mark.skipif(
    os.name != "posix", reason="需要 Linux/macOS 等 POSIX 平台：dir_fd/O_NOFOLLOW 实测待对应平台"
)
def test_posix_parent_symlink_swap_does_not_read_external_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"external fixture sentinel")
    game = root / "game"
    saved = tmp_path / "saved-game"
    target = game / "a.txt"
    original_check = inventory._check_components
    switched = False

    def switch_after_check(path: Path) -> None:
        nonlocal switched
        original_check(path)
        if path == target and not switched:
            game.rename(saved)
            game.symlink_to(outside, target_is_directory=True)
            switched = True

    def forbidden_fdopen(*_args: object, **_kwargs: object) -> None:
        pytest.fail("父目录已换成符号链接，不能建立读取流")

    monkeypatch.setattr(inventory, "_check_components", switch_after_check)
    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)
    try:
        result = inventory.inventory_installation(root)
    finally:
        if switched:
            game.unlink()
            saved.rename(game)
    assert switched
    assert result.scan_status == "partial"
    assert result.records[0].sha256 is None


def test_public_source_reader_yields_original_bytes_and_is_read_only(tmp_path: Path) -> None:
    root = _installation(tmp_path)
    with inventory.open_inventory_source(root, "game/a.txt") as stream:
        assert stream.read() == b"abc"
        assert stream.writable() is False
    assert stream.closed
    assert (root / "game/a.txt").read_bytes() == b"abc"


def test_public_source_reader_rejects_traversal_and_reports_exit_drift(tmp_path: Path) -> None:
    root = _installation(tmp_path)
    with (
        pytest.raises(inventory.InputContractError, match="invalid_path"),
        inventory.open_inventory_source(root, "../outside"),
    ):
        pytest.fail("路径穿越不能进入 context")

    def mutate_source() -> None:
        with inventory.open_inventory_source(root, "game/a.txt") as stream:
            assert stream.read(1) == b"a"
            (root / "game/a.txt").write_bytes(b"changed")

    with pytest.raises(inventory.InputContractError, match="file_changed"):
        mutate_source()


@pytest.mark.skipif(os.name != "nt", reason="Windows 真实 junction 竞态")
def test_public_source_reader_refuses_junction_swap_before_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows_api = pytest.importorskip("_winapi", reason="需要 Windows 的 _winapi 模块")
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_bytes(b"outside")
    game = root / "game"
    saved = tmp_path / "saved-game"
    target = game / "a.txt"
    original_check = inventory._check_components
    switched = False

    def switch_after_check(path: Path) -> None:
        nonlocal switched
        original_check(path)
        if path == target and not switched:
            game.rename(saved)
            windows_api.CreateJunction(str(outside), str(game))
            switched = True

    monkeypatch.setattr(inventory, "_check_components", switch_after_check)
    try:
        with (
            pytest.raises(inventory.InputContractError, match="opened_path_mismatch"),
            inventory.open_inventory_source(root, "game/a.txt"),
        ):
            pytest.fail("根外对象不能进入可读取 context")
    finally:
        if switched:
            game.rmdir()
            saved.rename(game)


@pytest.mark.parametrize("vary_raw_attribute", [False, True])
def test_windows_raw_attribute_representation_is_not_content_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vary_raw_attribute: bool
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows 路径/句柄属性来源口径")
    root = _installation(tmp_path)
    target = root / "game/a.txt"
    original_lstat = Path.lstat
    calls = 0

    def alternate_reported_attribute(path: Path) -> os.stat_result | SimpleNamespace:
        nonlocal calls
        value = original_lstat(path)
        if path != target:
            return value
        calls += 1
        fields = {
            name: getattr(value, name)
            for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        marker = 0x40000 if not vary_raw_attribute or calls % 2 else 0
        return SimpleNamespace(**fields, st_file_attributes=value.st_file_attributes | marker)

    monkeypatch.setattr(Path, "lstat", alternate_reported_attribute)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "complete", result.diagnostics
    assert result.records[0].sha256 == hashlib.sha256(b"abc").hexdigest()
    assert target.read_bytes() == b"abc"
    if not vary_raw_attribute:
        metadata = asdict(inventory._path_state(target))
        assert metadata["attributes"] & 0x40000
        assert metadata["comparison_attributes"] == original_lstat(target).st_file_attributes


def test_windows_temporary_file_with_extended_attributes_is_readable(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows 真实临时扩展属性夹具")
    import ctypes
    import msvcrt
    import struct
    from ctypes import wintypes

    root = _installation(tmp_path)
    target = root / "game/a.txt"

    class IoStatus(ctypes.Structure):
        _fields_ = [("status_or_pointer", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    name, value = b"SITAI_FIXTURE", b"metadata"
    raw = struct.pack("<IBBH", 0, 0, len(name), len(value)) + name + b"\0" + value
    buffer = ctypes.create_string_buffer(raw)
    status = IoStatus()
    setter = ctypes.WinDLL("ntdll").NtSetEaFile
    setter.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG)
    setter.restype = ctypes.c_long
    descriptor = os.open(target, os.O_RDWR | os.O_BINARY)
    try:
        code = setter(msvcrt.get_osfhandle(descriptor), ctypes.byref(status), buffer, len(raw))
    finally:
        os.close(descriptor)
    if code != 0:
        pytest.skip(f"Windows 临时文件系统不支持 EA 夹具：NTSTATUS={code:#x}")
    # EA 是否令某 API 报告 0x40000 由平台决定；本夹具不据此推断 recall。
    result = inventory.inventory_installation(root)
    assert result.scan_status == "complete", result.diagnostics
    assert result.records[0].sha256 == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode"])
def test_public_source_reader_keeps_real_identity_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    root = _installation(tmp_path)
    target = root / "game/a.txt"
    original_lstat = Path.lstat

    def changed_identity(path: Path) -> os.stat_result | SimpleNamespace:
        value = original_lstat(path)
        if path != target:
            return value
        fields = {
            name: getattr(value, name)
            for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        fields[field] = 0o020000 if field == "st_mode" else fields[field] + 1
        return SimpleNamespace(**fields, st_file_attributes=getattr(value, "st_file_attributes", 0))

    monkeypatch.setattr(Path, "lstat", changed_identity)
    with (
        pytest.raises(inventory.InputContractError, match=r"file_changed|file_type_changed"),
        inventory.open_inventory_source(root, "game/a.txt"),
    ):
        pytest.fail("真实对象类型、device、inode、大小或mtime差异不能进入读取 context")


@pytest.mark.skipif(os.name != "nt", reason="Windows 规范属性同口径检查")
@pytest.mark.parametrize("attribute", [0x1, 0x400, 0x40000])
def test_windows_canonical_attribute_differences_are_not_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: int
) -> None:
    root = _installation(tmp_path)
    target = root / "game/a.txt"
    original_attributes = inventory._windows_basic_attributes
    target_observations = 0

    def change_handle_attributes(handle: int) -> int:
        nonlocal target_observations
        actual = inventory._windows_handle_path(handle)
        value = original_attributes(handle)
        if os.path.normcase(actual) == os.path.normcase(str(target)):
            target_observations += 1
            if target_observations > 1:
                return value | attribute
        return value

    def forbidden_fdopen(*_args: object, **_kwargs: object) -> None:
        pytest.fail("规范属性不同（包括REPARSE）时不得建立内容读取流")

    monkeypatch.setattr(inventory, "_windows_basic_attributes", change_handle_attributes)
    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)
    with (
        pytest.raises(inventory.InputContractError, match=r"file_changed|link_refused"),
        inventory.open_inventory_source(root, "game/a.txt"),
    ):
        pytest.fail("规范属性不是可任意屏蔽的字段")


@pytest.mark.skipif(os.name != "nt", reason="Windows 元数据句柄失败边界")
def test_windows_metadata_query_failure_never_enters_content_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    error = PermissionError("fixture: metadata query denied")

    def denied_attributes(_handle: int) -> None:
        raise error

    def forbidden_fdopen(*_args: object, **_kwargs: object) -> None:
        pytest.fail("元数据失败不能进入内容读取流")

    monkeypatch.setattr(inventory, "_windows_basic_attributes", denied_attributes)
    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)
    with (
        pytest.raises(PermissionError) as caught,
        inventory.open_inventory_source(root, "game/a.txt"),
    ):
        pytest.fail("元数据查询失败必须显式传播")
    assert caught.value is error


def test_directory_drift_diagnostic_contains_exact_state_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    target = root / "game"
    original_state = inventory._path_state
    before = original_state(target)
    after = replace(
        before,
        changed_ns=before.changed_ns + 7,
        size=before.size + 32,
        attributes=before.attributes ^ 0x40000,
        comparison_attributes=before.comparison_attributes ^ 0x1,
    )
    calls = 0

    def changed_directory(path: Path) -> inventory._State:
        nonlocal calls
        if path != target:
            return original_state(path)
        calls += 1
        # 首次为父目录中的条目 stat，第二/三次为该目录枚举前/后。
        return after if calls >= 3 else before

    monkeypatch.setattr(inventory, "_path_state", changed_directory)
    result = inventory._enumerate(root)
    (problem,) = (problem for problem in result.diagnostics if problem.code == "directory_changed")
    detail = json.loads(problem.message)
    assert detail["path"] == "game"
    assert detail["before"] == asdict(before)
    assert detail["after"] == asdict(after)
    assert detail["changed_fields"]["changed_ns"] == {
        "before": before.changed_ns,
        "after": before.changed_ns + 7,
        "compared": True,
    }
    assert detail["changed_fields"]["size"] == {
        "before": before.size,
        "after": before.size + 32,
        "compared": os.name != "nt",
    }
    assert detail["changed_fields"]["attributes"]["compared"] is False
    assert detail["changed_fields"]["comparison_attributes"]["compared"] is True


def test_directory_set_diagnostic_explains_added_removed_and_changed_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _installation(tmp_path)
    (root / "removed").mkdir()
    original_enumerate = inventory._enumerate
    game_before = inventory._path_state(root / "game")
    removed_before = inventory._path_state(root / "removed")
    added_after = replace(game_before, inode=game_before.inode + 1)
    game_after = replace(game_before, changed_ns=game_before.changed_ns + 9)
    calls = 0

    def injected_snapshot(path: Path) -> inventory._Enumeration:
        nonlocal calls
        result = original_enumerate(path)
        calls += 1
        if calls == 2:
            del result.directories["removed"]
            result.directories["added"] = added_after
            result.directories["game"] = game_after
        return result

    monkeypatch.setattr(inventory, "_enumerate", injected_snapshot)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    (problem,) = (
        problem for problem in result.diagnostics if problem.code == "directory_set_changed"
    )
    detail = json.loads(problem.message)
    assert detail["added"] == {"added": asdict(added_after)}
    assert detail["removed"] == {"removed": asdict(removed_before)}
    assert detail["changed"]["game"]["before"] == asdict(game_before)
    assert detail["changed"]["game"]["after"] == asdict(game_after)
    assert detail["changed"]["game"]["changed_fields"] == {
        "changed_ns": {
            "before": game_before.changed_ns,
            "after": game_before.changed_ns + 9,
            "compared": True,
        },
    }


@pytest.mark.parametrize(
    ("platform_name", "mode", "same_identity"),
    [
        ("nt", stat.S_IFDIR | 0o777, True),
        ("nt", stat.S_IFREG | 0o666, False),
        ("posix", stat.S_IFDIR | 0o755, False),
        ("posix", stat.S_IFREG | 0o644, False),
        ("unknown", stat.S_IFDIR | 0o755, False),
    ],
)
def test_size_comparison_respects_platform_and_actual_file_type(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, mode: int, same_identity: bool
) -> None:
    # Only the metadata adapter sees the simulated platform, not pathlib or real I/O.
    monkeypatch.setattr(inventory, "os", SimpleNamespace(name=platform_name))
    fields = {
        "st_mode": mode,
        "st_dev": 11,
        "st_ino": 22,
        "st_size": 0,
        "st_mtime_ns": 101,
        "st_ctime_ns": 202,
        "st_file_attributes": 16 if stat.S_ISDIR(mode) else 32,
    }
    before = inventory._state(cast("os.stat_result", SimpleNamespace(**fields)))
    fields["st_size"] = 8192
    after = inventory._state(cast("os.stat_result", SimpleNamespace(**fields)))
    assert (before == after) is same_identity
    assert asdict(before)["size"] == 0
    assert asdict(after)["size"] == 8192
    detail = inventory._state_change_details(before, after)
    assert detail["changed_fields"] == {
        "size": {"before": 0, "after": 8192, "compared": not same_identity}
    }


def test_windows_directory_size_representation_does_not_invent_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows 目录 size 无跨来源文件字节语义")
    root = _installation(tmp_path)
    target = root / "game"
    original_lstat = Path.lstat
    calls = 0

    def alternate_size(path: Path) -> os.stat_result | SimpleNamespace:
        nonlocal calls
        value = original_lstat(path)
        if path != target:
            return value
        calls += 1
        fields = {
            name: getattr(value, name)
            for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        fields["st_size"] = 8192 if calls % 2 else 0
        return SimpleNamespace(**fields, st_file_attributes=value.st_file_attributes)

    monkeypatch.setattr(Path, "lstat", alternate_size)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "complete", result.diagnostics
    assert result.observed_paths == ("game/a.txt",)
    assert result.records[0].size == 3
    assert result.records[0].sha256 == hashlib.sha256(b"abc").hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows 新旧目录比较合同不可静默混用")
def test_legacy_directory_state_cannot_be_promoted_by_reloading_fields(tmp_path: Path) -> None:
    current = inventory._path_state(tmp_path)
    legacy = inventory._State(**asdict(current))
    assert legacy != current
    detail = inventory._state_change_details(legacy, current)
    assert detail["changed_fields"] == {}
    assert detail["state_type_change"] == {
        "before": "_State",
        "after": "_WindowsDirectoryState",
        "compared": True,
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_directory_file_type_transition_has_explicit_comparison_evidence(
    monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    monkeypatch.setattr(inventory, "os", SimpleNamespace(name="nt"))
    fields = {
        "st_mode": stat.S_IFDIR | 0o777,
        "st_dev": 11,
        "st_ino": 22,
        "st_size": 4096,
        "st_mtime_ns": 101,
        "st_ctime_ns": 202,
        "st_file_attributes": 16,
    }
    directory = inventory._state(cast("os.stat_result", SimpleNamespace(**fields)))
    fields.update(st_mode=stat.S_IFREG | 0o666, st_size=8192, st_file_attributes=32)
    regular = inventory._state(cast("os.stat_result", SimpleNamespace(**fields)))
    before, after = (regular, directory) if reverse else (directory, regular)
    assert before != after
    detail = json.loads(
        inventory._directory_diagnostic(
            "directory_changed", "fixture", inventory._state_change_details(before, after)
        ).message
    )
    assert detail["changed_fields"]["size"]["compared"] is True
    assert detail["changed_fields"]["mode"]["compared"] is True
    assert detail["state_type_change"] == {
        "before": "_State" if reverse else "_WindowsDirectoryState",
        "after": "_WindowsDirectoryState" if reverse else "_State",
        "compared": True,
    }


@pytest.mark.parametrize(
    "field",
    ["device", "inode", "mode", "modified_ns", "changed_ns", "comparison_attributes", "attributes"],
)
def test_directory_identity_time_and_reparse_changes_still_block_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    root = _installation(tmp_path)
    target = root / "game"
    original_state = inventory._path_state
    calls = 0

    def changed_directory(path: Path) -> inventory._State:
        nonlocal calls
        value = original_state(path)
        if path != target:
            return value
        calls += 1
        if calls < 3:
            return value
        change = (
            value.attributes | 0x400
            if field == "attributes"
            else stat.S_IFREG | 0o644
            if field == "mode"
            else getattr(value, field) + 1
        )
        return replace(value, **{field: change})

    monkeypatch.setattr(inventory, "_path_state", changed_directory)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    assert {row.code for row in result.diagnostics} & {
        "directory_changed",
        "directory_set_changed",
        "link_refused",
    }


@pytest.mark.parametrize(
    "change",
    [
        "file_add",
        "file_remove",
        "file_rename",
        "dir_add",
        "dir_remove",
        "dir_rename",
        "dir_replace",
    ],
)
def test_real_namespace_mutations_still_block_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "installation"
    root.mkdir()
    _installation(root)
    (root / "empty").mkdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    parent_times = {path: path.stat() for path in (root, root / "game")}
    original_enumerate = inventory._enumerate
    calls = 0

    def mutate_after_snapshot(path: Path) -> inventory._Enumeration:
        nonlocal calls
        result = original_enumerate(path)
        calls += 1
        if calls != 1:
            return result
        if change == "file_add":
            (root / "game/b.txt").write_bytes(b"new")
        elif change == "file_remove":
            (root / "game/a.txt").unlink()
        elif change == "file_rename":
            (root / "game/a.txt").rename(root / "game/b.txt")
        elif change == "dir_add":
            (root / "added").mkdir()
        elif change == "dir_remove":
            (root / "empty").rmdir()
        elif change == "dir_rename":
            (root / "empty").rename(root / "renamed")
        else:
            (root / "empty").rmdir()
            replacement.rename(root / "empty")
        # Namespace reconciliation must work even with restored parent mtimes.
        for parent, observed in parent_times.items():
            os.utime(parent, ns=(observed.st_atime_ns, observed.st_mtime_ns))
        return result

    monkeypatch.setattr(inventory, "_enumerate", mutate_after_snapshot)
    result = inventory.inventory_installation(root)
    assert result.scan_status == "partial"
    codes = {problem.code for problem in result.diagnostics}
    if change.startswith("file_"):
        if change in {"file_add", "file_rename"}:
            assert "path_added" in codes
            assert "game/b.txt" in result.observed_paths
        if change in {"file_remove", "file_rename"}:
            assert "path_removed" in codes
            assert "game/a.txt" in result.observed_paths
    else:
        (problem,) = (row for row in result.diagnostics if row.code == "directory_set_changed")
        detail = json.loads(problem.message)
        if change == "dir_add":
            assert "added" in detail["added"]
        elif change == "dir_remove":
            assert "empty" in detail["removed"]
        elif change == "dir_rename":
            assert "empty" in detail["removed"]
            assert "renamed" in detail["added"]
        else:
            assert "empty" in detail["changed"]
            assert "inode" in detail["changed"]["empty"]["changed_fields"]
