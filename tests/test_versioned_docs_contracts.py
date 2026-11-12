"""Version identity guards the complete documentation and offline analysis routes."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from pdx import config, docgen, docs_mirror, snapshot, tables_offline, vanilla_index, verify
from pdx.version_contracts import active_version, is_115, select_version


def test_documentation_and_complete_claim_registry_switch_at_call_time():
    historical = verify.claims_for_version("1.14.5")
    current = verify.claims_for_version("1.15.0")
    assert [(c.id, c.kind, c.target) for c in historical] == [
        (c.id, c.kind, c.target) for c in current
    ]
    assert len(current) == 234
    for version, directory, claims, name in (
        ("1.14.5", config.HISTORICAL_DOCS, historical, "official-docs.manifest.json"),
        ("1.15.0", config.DOCS_115, current, "official-docs-1.15.0.manifest.json"),
    ):
        with select_version(version):
            assert config.docs_root() == directory
            assert verify.current_claims() is claims
            assert all(t.path.parent == directory for t in docgen.targets())
            assert docs_mirror.manifest_path().name == name
            assert {verify.claim_scope(c) for c in claims} == {
                "native_installation",
                "machine_snapshot",
            }
    for old, new in zip(historical, current, strict=True):
        assert verify.claim_scope(old) == verify.claim_scope(new)
        if verify.claim_scope(new) == "machine_snapshot":
            assert "本机" in new.note
            assert new.kind not in verify._SNAPSHOT_GETTERS
            assert new.kind not in verify._MANIFEST_GETTERS


def test_invalid_profile_fails_at_default_operation_in_a_fresh_process():
    environment = os.environ.copy()
    environment["V3_CONTRACT_PROFILE"] = "latest"
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", "from pdx import config; config.docs_root()"],
        cwd=config.REPO,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode != 0
    assert "未支持的原版合同版本" in result.stderr


def test_fresh_cli_explicit_profile_has_priority_over_an_unknown_environment():
    results = []
    for selected in ("1.15.0", "unknown"):
        environment = os.environ.copy()
        environment["V3_CONTRACT_PROFILE"] = selected
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-m",
                "pdx.cli",
                "modguard",
                "--profile",
                "1.15.0",
                "--offline",
            ],
            cwd=config.REPO,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        results.append(result)
    # The production lock can legitimately be unavailable during this migration.
    # Both fresh CLI calls must reach the same explicit profile contract result.
    assert (results[0].returncode, results[0].stdout, results[0].stderr) == (
        results[1].returncode,
        results[1].stdout,
        results[1].stderr,
    )
    assert "未支持的原版合同版本" not in results[1].stdout + results[1].stderr


def test_snapshot_selection_never_falls_back_to_a_different_version(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    old = snapshot.Snapshot(version={"caligula_branch": "release/1.14.5"}, compact=True)
    old.write(tmp_path / "release-1.14.5.compact.json")
    with select_version("1.15.0"):
        assert verify.latest_compact_snapshot_path() is None
        assert verify.latest_compact_snapshot() is None
        assert vanilla_index.snapshot_index() is None
        assert tables_offline.load_tables() == {}
    with select_version("1.14.5"):
        historical = verify.latest_compact_snapshot()
        assert historical is not None
        assert historical.version_label == "release/1.14.5"


@pytest.mark.parametrize("branch", ["release/1.14.5", "release/1.16.0", "", "unknown"])
def test_explicit_snapshot_cannot_supply_current_version_acceptance(tmp_path, branch):
    old = snapshot.Snapshot(version={"caligula_branch": branch}, compact=True)
    path = tmp_path / "explicit.compact.json"
    old.write(path)
    # Reading historical evidence remains available for deliberate comparison.
    assert snapshot.Snapshot.load(path).version_label == (branch or "?")
    with select_version("1.15.0"):
        with pytest.raises(snapshot.SnapshotFormatError, match="版本不匹配"):
            tables_offline.load_tables(path)
        with pytest.raises(snapshot.SnapshotFormatError, match="版本不匹配"):
            verify.verify_from_snapshot(old)
        with pytest.raises(snapshot.SnapshotFormatError, match="版本不匹配"):
            vanilla_index.snapshot_index(path)


def test_wrong_identity_or_corrupt_selected_snapshot_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    path = tmp_path / "release-1.15.0.compact.json"
    with select_version("1.15.0"):
        snapshot.Snapshot(version={"caligula_branch": "release/1.14.5"}).write(path)
        with pytest.raises(snapshot.SnapshotFormatError, match="版本不匹配"):
            verify.latest_compact_snapshot()
        path.write_text("{broken", encoding="utf-8")
        with pytest.raises(snapshot.SnapshotFormatError, match="无法读取快照"):
            verify.latest_compact_snapshot()


def test_official_manifest_identity_is_checked_independently_of_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESEARCH", tmp_path)
    with select_version("1.15.0"):
        path = docs_mirror.manifest_path()
        for version in ({}, {"caligula_branch": "release/1.14.5"}):
            path.write_text(json.dumps({"版本": version, "文档": {"x": {}}}), encoding="utf-8")
            with pytest.raises(ValueError, match="版本不匹配"):
                docs_mirror.load_manifest()
        path.write_text(
            json.dumps({"版本": {"caligula_branch": "release/1.15.0"}, "文档": {"x": {}}}),
            encoding="utf-8",
        )
        assert docs_mirror.entries() == {"x": {}}


def test_source_identity_keeps_original_bytes_and_filesystem_denominators(tmp_path, monkeypatch):
    for name in ("game", "jomini", "clausewitz"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(config, name.upper(), tmp_path / name)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    source = tmp_path / "game" / "sample.txt"
    source.write_bytes(b"\xef\xbb\xbfentry = { value = 1 }\r\n")
    (tmp_path / "game" / "asset.dds").write_bytes(b"binary")
    before = snapshot._source_identity_snapshot()
    assert before["game/asset.dds"] == ["size:6"]
    assert any(v.startswith("sha256:") for v in before["game/sample.txt"])
    source.write_bytes(b"entry = { value = 1 }\n")
    assert snapshot._source_identity_snapshot()["game/sample.txt"] != before["game/sample.txt"]


def test_selected_committed_evidence_binds_the_actual_version():
    snap = verify.latest_compact_snapshot()
    assert snap is not None
    snap.require_version()
    assert snap.version_label == f"release/{active_version()}"
    if is_115():
        assert snap.sections["source_identity"]["installation/caligula_rev.txt"]
        assert len(snap.sections["doc_tables"]) == sum(len(t.specs) for t in docgen.targets())


def test_current_snapshot_refuses_failed_table_rows_instead_of_freezing_placeholders(monkeypatch):
    monkeypatch.setattr(docgen, "render_all", lambda: {"fixture": ["<未取到：ValueError: bad>"]})
    with select_version("1.15.0"), pytest.raises(ValueError, match="生成表取值失败"):
        snapshot._doc_tables_snapshot()


def test_malformed_selected_manifest_is_a_hard_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESEARCH", tmp_path)
    with select_version("1.15.0"):
        docs_mirror.manifest_path().write_text("{broken", encoding="utf-8")
        with pytest.raises(ValueError, match="清单损坏"):
            docs_mirror.load_manifest()


def test_native_file_table_bytes_are_generated_from_explicit_original_source(tmp_path, monkeypatch):
    path = tmp_path / "common/sample/source.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xef\xbb\xbfvalue = 1\r\n")
    monkeypatch.setattr(config, "GAME", tmp_path)
    assert docgen._native_file_cells("common/sample", 2) == [
        ("source.txt", {2: str(path.stat().st_size)})
    ]


def test_external_directory_junction_or_link_cannot_enter_snapshot_sources(tmp_path, monkeypatch):
    installation = tmp_path / "installation"
    for name in ("game", "jomini", "clausewitz"):
        (installation / name).mkdir(parents=True)
        monkeypatch.setattr(config, name.upper(), installation / name)
    monkeypatch.setattr(config, "ROOT", installation)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "borrowed.txt").write_text("unreviewed = yes", encoding="utf-8")
    link = installation / "game/linked"
    if os.name == "nt":
        # cmd follows the console code page; only its exit status is needed here.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(external)],
            check=True,
            capture_output=True,
        )
        assert not link.is_symlink()  # Windows junctions bypass the old predicate.
    else:
        link.symlink_to(external, target_is_directory=True)
    assert link.resolve() == external.resolve()
    with pytest.raises(ValueError, match="链接或越界"):
        snapshot._source_identity_snapshot()
