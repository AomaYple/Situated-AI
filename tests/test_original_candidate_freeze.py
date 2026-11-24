"""Exercise candidate promotion, isolation from previous outputs and failure recovery."""

import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from rich.console import Console
from typer.testing import CliRunner

from pdx import cli, decisions, distribution
from pdx import original_candidate as candidate
from pdx.cli_commands import release
from pdx.publishing import local


@pytest.fixture
def fixture_files():
    return candidate._payload(
        "# synthetic company input\n", (candidate.config.REPO / "mod/thumbnail.png").read_bytes()
    )


def freeze(root, files, *, reviewed=None):
    hashes = {
        path: hashlib.sha256(raw).hexdigest() for path, raw in distribution.payloads(files).items()
    }
    review = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return candidate._freeze(
        root,
        files,
        reviewed_digest=review if reviewed is None else reviewed,
        origins=dict.fromkeys(files, "synthetic-fixture"),
        generation={"publication_channel": "local_candidate"},
        identity=candidate.IDENTITY,
        zip_name=candidate.ZIP_NAME,
    )


def test_cli_uses_only_candidate_renderer(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("legacy generator entered")

    monkeypatch.setattr(distribution, "package", forbidden)
    monkeypatch.setattr(decisions, "build", forbidden)
    archive = tmp_path / "candidate.zip"
    monkeypatch.setattr(candidate, "build", lambda: archive)
    monkeypatch.setattr(release, "console", Console(width=len(str(archive)) + 40))
    result = CliRunner().invoke(cli.app, ["package", "--original-candidate"])
    assert result.exit_code == 0, result.output
    assert str(archive) in result.output
    result = CliRunner().invoke(
        cli.app, ["package", "--original-candidate", "--output", str(tmp_path / "release.zip")]
    )
    assert result.exit_code != 0
    assert not (tmp_path / "release.zip").exists()


def test_duplicate_concurrent_build_and_old_tree_are_isolated(tmp_path, fixture_files):
    root = tmp_path / "isolated"
    old = root / "old/checksum/common"
    old.mkdir(parents=True)
    old_member = old / "original.txt"
    old_member.write_bytes(b"synthetic old payload")
    unknown = root / "local-notes"
    unknown.write_bytes(b"owned by user")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: freeze(root, fixture_files), range(2)))
    assert results[0] == results[1]
    archive = results[0]
    assert archive.parent.name == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert {p.name for p in root.iterdir()} == {"old", "local-notes", archive.parent.name}
    assert unknown.read_bytes() == b"owned by user"
    assert old_member.read_bytes() == b"synthetic old payload"
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {*fixture_files, distribution.MANIFEST_NAME}
        for name in zipped.namelist():
            assert (
                zipped.read(name)
                == (archive.parent / candidate.IDENTITY.install_directory / name).read_bytes()
            )
    with pytest.raises(ValueError):
        distribution._validate_archive(
            archive, expected_data=None, expected_generation=None, release=True
        )


def test_frozen_unknown_or_modified_file_is_preserved(tmp_path, fixture_files):
    archive = freeze(tmp_path, fixture_files)
    unknown = archive.parent / "unknown.txt"
    unknown.write_bytes(b"user data")
    with pytest.raises(ValueError, match="unknown files"):
        freeze(tmp_path, fixture_files)
    assert unknown.read_bytes() == b"user data"
    unknown.unlink()
    installed = archive.parent / candidate.IDENTITY.install_directory / "README.md"
    installed.write_bytes(b"user changed existing file")
    with pytest.raises(ValueError, match="changed"):
        freeze(tmp_path, fixture_files)
    assert installed.read_bytes() == b"user changed existing file"


def test_injected_failure_leaves_predecessor_and_no_partial_tree(
    tmp_path, fixture_files, monkeypatch
):
    first = freeze(tmp_path, fixture_files)
    before = local.tree(tmp_path)
    files = {**fixture_files, "README.md": "second generation"}

    def fail_readback(*_):
        raise ValueError("injected post-write check")

    monkeypatch.setattr(candidate, "_check_frozen", fail_readback)
    with pytest.raises(ValueError, match="injected"):
        freeze(tmp_path, files)
    assert local.tree(tmp_path) == before
    assert first.is_file()


def test_rejected_source_admission_writes_nothing(tmp_path, fixture_files):
    root = tmp_path / "unused"
    with pytest.raises(ValueError, match="admission"):
        freeze(root, {**fixture_files, "common/synthetic-unknown.txt": "added"}, reviewed="0" * 64)
    assert not root.exists()
