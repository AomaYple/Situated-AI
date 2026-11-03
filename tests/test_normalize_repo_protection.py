"""规范化只改受控文本，第三方、缓存与冻结证据保留原始字节。"""

from __future__ import annotations

import codecs
import os
import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

from pdx import normalize_repo

if TYPE_CHECKING:
    from pathlib import Path

RAW = codecs.BOM_UTF8 + b"original\xff\r\n"


def test_default_cli_preserves_repository_protected_bytes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    protected = [
        ".venv/Lib/vendor.py",
        "research/official-docs/raw.md",
        "research/vanilla-ai/raw.txt",
        "research/situated/raw.txt",
        "tools/out/evidence/frozen.log",
        "tools/out/snapshots/sample.compact.json",
        "tools/prof/out/profile.txt",
        "evidence/raw.log",
        "build/library.py",
        "dist/package.txt",
        ".superpowers/state.json",
        "src/pdx/__pycache__/raw.txt",
        ".pytest_cache/state.json",
    ]
    for name in [*protected, "src/pdx/owned.py", "README.md"]:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(RAW)
    monkeypatch.setattr(normalize_repo, "REPO", repo)
    backup = tmp_path / "original.zip"
    monkeypatch.setattr(sys, "argv", ["normalize", "--backup", str(backup)])

    assert normalize_repo.main() == 0

    assert (repo / "src/pdx/owned.py").read_bytes() == b"original\\xff\n"
    assert (repo / "README.md").read_bytes() == b"original\\xff\n"
    for name in protected:
        assert (repo / name).read_bytes() == RAW, name
    with zipfile.ZipFile(backup) as archive:
        assert sorted(archive.namelist()) == [
            "README.md",
            "RESTORE-MANIFEST.json",
            "src/pdx/owned.py",
        ]


@pytest.mark.parametrize(
    "relative",
    [
        ".venv/Lib",
        "research/official-docs",
        "research/vanilla-ai",
        "research/situated",
        "tools/out/evidence",
        "tools/prof/out",
        "evidence",
        "build",
        "dist",
        ".pytest_cache",
    ],
)
def test_explicit_protected_root_rejected_before_backup(tmp_path, monkeypatch, relative):
    repo = tmp_path / "repo"
    root = repo / relative
    root.mkdir(parents=True)
    source = root / "raw.txt"
    source.write_bytes(RAW)
    monkeypatch.setattr(normalize_repo, "REPO", repo)
    backup = tmp_path / "backups" / "original.zip"

    with pytest.raises(ValueError, match="受保护"):
        normalize_repo.normalize(root, backup)

    assert source.read_bytes() == RAW
    assert not backup.parent.exists()


def test_parent_scan_cannot_enter_repository_protected_roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    raw = repo / "research" / "official-docs" / "raw.md"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(RAW)
    monkeypatch.setattr(normalize_repo, "REPO", repo)
    normalize_repo.normalize(tmp_path, tmp_path / "original.zip")
    assert raw.read_bytes() == RAW


def test_explicit_temporary_root_still_normalizes_and_restores(tmp_path):
    root = tmp_path / "temporary"
    source = root / "research" / "official-docs" / "evidence.log"
    source.parent.mkdir(parents=True)
    source.write_bytes(RAW)
    backup = tmp_path / "original.zip"

    records = normalize_repo.normalize(root, backup)

    assert [item["path"] for item in records] == ["research/official-docs/evidence.log"]
    assert source.read_bytes() == b"original\\xff\n"
    assert normalize_repo.restore(root, backup) == 1
    assert source.read_bytes() == RAW


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_root_fails_without_creating_backup(tmp_path, kind):
    root = tmp_path / "source"
    if kind == "file":
        root.write_bytes(RAW)
    backup = tmp_path / "backups" / "original.zip"
    expected = FileNotFoundError if kind == "missing" else NotADirectoryError
    with pytest.raises(expected):
        normalize_repo.normalize(root, backup)
    assert not backup.parent.exists()


def _directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        # typeshed on non-Windows hosts does not expose this Windows-only API.
        create_junction = vars(_winapi)["CreateJunction"]
        create_junction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_directory_link_does_not_escape_scan_root(tmp_path):
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    raw = outside / "raw.txt"
    raw.write_bytes(RAW)
    _directory_link(root / "linked", outside)

    records = normalize_repo.normalize(root, tmp_path / "original.zip")

    assert records == []
    assert raw.read_bytes() == RAW


@pytest.mark.parametrize("descendant", [False, True])
def test_explicit_root_through_directory_link_rejected(tmp_path, descendant):
    target = tmp_path / "target"
    source = target / "child" / "raw.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(RAW)
    link = tmp_path / "linked"
    _directory_link(link, target)
    root = link / "child" if descendant else link
    backup = tmp_path / "original.zip"

    with pytest.raises(ValueError, match=r"链接|重解析"):
        normalize_repo.normalize(root, backup)

    assert source.read_bytes() == RAW
    assert not backup.exists()


def test_source_directory_replaced_after_backup_is_not_written(tmp_path, monkeypatch):
    root = tmp_path / "source"
    inside = root / "owned"
    outside = tmp_path / "outside"
    inside.mkdir(parents=True)
    outside.mkdir()
    (inside / "raw.txt").write_bytes(RAW)
    raw = outside / "raw.txt"
    raw.write_bytes(RAW)
    archive_type = zipfile.ZipFile

    class SwapAfterBackup(zipfile.ZipFile):
        def __exit__(self, *args):
            result = super().__exit__(*args)
            if self.mode == "x":
                inside.rename(root / "saved-original")
                _directory_link(inside, outside)
            return result

    monkeypatch.setattr(normalize_repo.zipfile, "ZipFile", SwapAfterBackup)
    backup = tmp_path / "original.zip"
    with pytest.raises(ValueError, match="备份后源路径"):
        normalize_repo.normalize(root, backup)

    assert raw.read_bytes() == RAW
    assert (root / "saved-original" / "raw.txt").read_bytes() == RAW
    with archive_type(backup) as archive:
        assert archive.read("owned/raw.txt") == RAW


def test_controlled_hardlink_cannot_rewrite_protected_evidence(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    evidence = repo / "research" / "official-docs" / "raw.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(RAW)
    controlled = repo / "src" / "owned.txt"
    controlled.parent.mkdir()
    os.link(evidence, controlled)
    monkeypatch.setattr(normalize_repo, "REPO", repo)
    backup = tmp_path / "original.zip"

    assert normalize_repo.normalize(repo, backup) == []

    assert evidence.read_bytes() == controlled.read_bytes() == RAW
    assert controlled.samefile(evidence)
    with zipfile.ZipFile(backup) as archive:
        assert archive.namelist() == ["RESTORE-MANIFEST.json"]


def test_hardlink_added_after_backup_prevents_shared_write(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    controlled = root / "owned.txt"
    controlled.write_bytes(RAW)
    evidence = tmp_path / "evidence.txt"
    archive_type = zipfile.ZipFile

    class LinkAfterBackup(zipfile.ZipFile):
        def __exit__(self, *args):
            result = super().__exit__(*args)
            if self.mode == "x":
                os.link(controlled, evidence)
            return result

    monkeypatch.setattr(normalize_repo.zipfile, "ZipFile", LinkAfterBackup)
    backup = tmp_path / "original.zip"
    with pytest.raises(ValueError, match="备份后源路径"):
        normalize_repo.normalize(root, backup)

    assert evidence.read_bytes() == controlled.read_bytes() == RAW
    assert controlled.samefile(evidence)
    with archive_type(backup) as archive:
        assert archive.read("owned.txt") == RAW
