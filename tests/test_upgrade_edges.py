"""整理后的故障边界、算法等价、三平台依赖与命令入口。"""

from __future__ import annotations

import codecs
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from packaging import markers
from packaging.markers import InvalidMarker

from pdx import (
    citations,
    distribution,
    docs_mirror,
    localization,
    lockfile,
    normalize_repo,
    performance,
    platform_support,
    repo_audit,
    textio,
)


def test_citations_reads_once_but_observes_next_edit(tmp_path, monkeypatch):
    target = tmp_path / "sample.txt"
    target.write_bytes(b"x\ny\n")
    original = citations._line_count
    reads = []

    def counted(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(citations, "_line_count", counted)
    result = citations.scan_text("sample.txt:2\n" * 100, where="test", root=tmp_path)
    assert all(item.ok for item in result)
    assert reads == [target]
    target.write_bytes(b"x\n")
    result = citations.scan_text("sample.txt:2", where="test", root=tmp_path)
    assert result[0].status == "out_of_range"
    assert reads == [target, target]


@given(st.binary(max_size=1024))
def test_streamed_header_equivalent_to_original(raw):
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        loc = root / "localization"
        loc.mkdir()
        target = loc / "sample.yml"
        target.write_bytes(raw)
        original = (
            target.read_text(encoding="utf-8-sig", errors="replace").split("\n", 1)[0].strip()
        )
        assert localization.language_header_counts(root) == Counter({original: 1})


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_native_guard(platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    if platform == "win32":
        platform_support.require_windows("test")
    else:
        with pytest.raises(platform_support.WindowsOnlyError, match=platform):
            platform_support.require_windows("test")
        module = platform_support.UnavailableWindowsModule("win32gui")
        with pytest.raises(platform_support.WindowsOnlyError, match="GetWindowRect"):
            _ = module.GetWindowRect


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_dependency_marker_platforms(platform, monkeypatch):
    environment = markers.default_environment()
    environment["sys_platform"] = platform
    monkeypatch.setattr(markers, "default_environment", lambda: environment)
    assert lockfile._requirement_names(
        [
            "base>=1",
            "native>=1; sys_platform == 'win32'",
            "other; sys_platform == 'linux' or sys_platform == 'darwin'",
        ]
    ) == (["base", "native"] if platform == "win32" else ["base", "other"])


def test_invalid_and_boolean_markers():
    with pytest.raises(InvalidMarker):
        lockfile._marker_allows("invented == 'x'")
    assert lockfile._marker_allows("python_version >= '3.11' and (extra == '' or extra == 'dev')")
    assert not lockfile._marker_allows("python_version < '3.0' or extra == 'missing'")


@pytest.mark.parametrize(
    "name",
    [
        "DISTRIBUTION-MANIFEST.json",
        "distribution-manifest.json",
        "NUL.txt",
        "a/CON",
        "a./b",
        "a /b",
        "a\0.txt",
        "a?.txt",
    ],
)
def test_reserved_delivery_names(name):
    with pytest.raises(ValueError):
        distribution.payloads({name: "data"})


def test_delivery_case_collision():
    with pytest.raises(ValueError, match="大小写冲突"):
        distribution.payloads({"common/A.txt": "x", "common/a.txt": "y"})


def test_package_refuses_drift_without_touching_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(distribution.decisions, "check", lambda *_: ["modified"])
    target = tmp_path / "existing.zip"
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="拒绝打包"):
        distribution.package(target)
    assert target.read_bytes() == b"existing"


def test_zip_failure_keeps_existing_and_removes_temporary(tmp_path, monkeypatch):
    target = tmp_path / "existing.zip"
    target.write_bytes(b"existing")
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda _: "bad.txt")
    with pytest.raises(ValueError, match="校验失败"):
        distribution.write_zip({"a.txt": "x"}, target)
    assert target.read_bytes() == b"existing"
    assert sorted(tmp_path.iterdir()) == [target]


def test_restore_validates_all_hashes_before_writes(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_bytes(b"a\n")
    (root / "b.txt").write_bytes(b"b\n")
    records = []
    backup = tmp_path / "bad.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        for name in ("a", "b"):
            original = f"{name}\r\n".encode()
            archive.writestr(f"{name}.txt", original)
            records.append(
                {
                    "path": f"{name}.txt",
                    "before_sha256": hashlib.sha256(original).hexdigest()
                    if name == "a"
                    else "corrupt",
                    "after_sha256": hashlib.sha256(f"{name}\n".encode()).hexdigest(),
                }
            )
        archive.writestr("RESTORE-MANIFEST.json", json.dumps(records))
    with pytest.raises(ValueError, match="哈希不符"):
        normalize_repo.restore(root, backup)
    assert (root / "a.txt").read_bytes() == b"a\n"


def test_deploy_rejects_source_ancestor(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="之外"):
        textio.deploy_tree(source, tmp_path)


def test_deploy_preflights_links_before_writing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (source / "z-link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("系统未授予符号链接权限")
    destination = tmp_path / "delivery"
    with pytest.raises(ValueError, match="符号链接"):
        textio.deploy_tree(source, destination)
    assert not destination.exists()


def test_deploy_rejects_destination_parent_link(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("系统未授予符号链接权限")
    with pytest.raises(ValueError, match="符号链接"):
        textio.deploy_tree(source, link / "delivery")
    assert not list(outside.iterdir())


def test_deploy_rejects_existing_target_link(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a\n")
    outside = tmp_path / "original.txt"
    outside.write_bytes(b"unchanged")
    destination = tmp_path / "delivery"
    destination.mkdir()
    try:
        (destination / "a.txt").symlink_to(outside)
    except OSError:
        pytest.skip("系统未授予符号链接权限")
    with pytest.raises(ValueError, match="符号链接"):
        textio.deploy_tree(source, destination)
    assert outside.read_bytes() == b"unchanged"


def test_normalized_mirror_retains_original_game_hash(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    original = codecs.BOM_UTF8 + b"# game\r\n"
    (game / "doc.md").write_bytes(original)
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", game),))
    manifest = docs_mirror.build_manifest()
    entries = docs_mirror.entries(manifest)
    assert entries["game/doc.md"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert entries["game/doc.md"]["镜像sha256"] == hashlib.sha256(b"# game\n").hexdigest()
    mirror = tmp_path / "mirror"
    (mirror / "game").mkdir(parents=True)
    (mirror / "game/doc.md").write_bytes(b"# game\n")
    monkeypatch.setattr(docs_mirror.config, "OFFICIAL_DOCS_MIRROR", mirror)
    assert docs_mirror.diff_mirror(manifest) == []
    assert docs_mirror.diff_against_game(manifest) == []


def test_measure_rejects_nondeterminism():
    count = iter(range(10))
    with pytest.raises(ValueError, match="不确定"):
        performance.measure(lambda: next(count), rounds=2)


def test_inventory_cli(tmp_path, monkeypatch):
    import subprocess

    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    target = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", ["audit", "--root", str(root), "--output", str(target)])
    assert repo_audit.main() == 0
    assert json.loads(target.read_text(encoding="utf-8"))["read_errors"] == []


def test_performance_cli_and_comparison(tmp_path, monkeypatch):
    result: dict[str, object] = {"environment": {}, "workloads": {}}
    monkeypatch.setattr(performance, "workloads", lambda **_: result)
    target = tmp_path / "perf.json"
    monkeypatch.setattr(sys, "argv", ["perf", "--output", str(target)])
    assert performance.main() == 0
    monkeypatch.setattr(sys, "argv", ["perf", "--output", str(target), "--compare", str(target)])
    assert performance.main() == 0


def test_performance_real_workloads_have_results():
    result = performance.workloads(rounds=1)
    assert isinstance(result["workloads"], dict)
    assert set(result["workloads"]) == {
        "citations.repeated_file",
        "localization.header_large_file",
        "modgen.all_archives",
    }
    for metrics in result["workloads"].values():
        assert metrics["median_s"] > 0
        assert metrics["python_peak_bytes"] > 0
        assert len(metrics["result_sha256"]) == 64


def test_normalizer_cli_roundtrip(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    original = codecs.BOM_UTF8 + b"x\r\n"
    (source / "x.txt").write_bytes(original)
    backup = tmp_path / "backup.zip"
    monkeypatch.setattr(sys, "argv", ["normalize", "--root", str(source), "--backup", str(backup)])
    assert normalize_repo.main() == 0
    assert (source / "x.txt").read_bytes() == b"x\n"
    monkeypatch.setattr(
        sys, "argv", ["normalize", "--root", str(source), "--backup", str(backup), "--restore"]
    )
    assert normalize_repo.main() == 0
    assert (source / "x.txt").read_bytes() == original


def test_distribution_cli(tmp_path, monkeypatch):
    target = tmp_path / "delivery.zip"
    monkeypatch.setattr(
        distribution, "package", lambda path: distribution.write_zip({"a.txt": "x"}, path)
    )
    monkeypatch.setattr(sys, "argv", ["distribution", "--output", str(target)])
    assert distribution.main() == 0
    with zipfile.ZipFile(target) as archive:
        assert archive.read("a.txt") == codecs.BOM_UTF8 + b"x"


def test_package_cli_success_and_refusal(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pdx import cli

    target = tmp_path / "delivery.zip"
    runner = CliRunner()
    assert runner.invoke(cli.app, ["package", "--output", str(target)]).exit_code == 0
    assert target.is_file()
    before = target.read_bytes()
    monkeypatch.setattr(distribution.decisions, "check", lambda *_: ["drift"])
    result = runner.invoke(cli.app, ["package", "--output", str(target)])
    assert result.exit_code == 1
    assert "拒绝打包" in result.stdout
    assert target.read_bytes() == before


def test_encoding_gate_includes_untracked_and_invalid_bytes(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_bytes(b"ignored.txt\n")
    (tmp_path / "ignored.txt").write_bytes(b"ignored\r\n")
    (tmp_path / "new.py").write_bytes(codecs.BOM_UTF8 + b"bad\r\n\0\xff")
    (tmp_path / "image.png").write_bytes(b"\0\xff")
    assert repo_audit.source_issues(tmp_path) == ["new.py: bom, cr, nul, non_utf8"]
    output = tmp_path / "checks.json"
    monkeypatch.setattr(
        sys, "argv", ["audit", "--root", str(tmp_path), "--project-only", "--output", str(output)]
    )
    assert repo_audit.main() == 1
    (tmp_path / "new.py").write_bytes(b"x = 1\n")
    assert repo_audit.main() == 0


def test_damaged_evidence_is_escaped_and_recoverable(tmp_path):
    original = codecs.BOM_UTF8 + b"raw\0\xff\r\n"
    (tmp_path / "evidence.log").write_bytes(original)
    backup = tmp_path / "evidence-original.zip"
    records = normalize_repo.normalize(tmp_path, backup)
    assert records[0]["method"] == "text-nul-and-invalid-bytes-escaped"
    assert (tmp_path / "evidence.log").read_bytes() == b"raw\\x00\\xff\n"
    assert normalize_repo.restore(tmp_path, backup) == 1
    assert (tmp_path / "evidence.log").read_bytes() == original


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_check_driver_uses_compatible_venv(platform, tmp_path, monkeypatch):
    from tools.ci import run_check

    for path in (tmp_path / ".venv/Scripts/python.exe", tmp_path / ".venv/bin/python"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")
    monkeypatch.setattr(sys, "platform", platform)
    expected = tmp_path / (
        ".venv/Scripts/python.exe" if platform == "win32" else ".venv/bin/python"
    )
    assert run_check.interpreter(tmp_path) == expected
    expected.unlink()
    assert run_check.interpreter(tmp_path) == Path(sys.executable)


def test_profile_summary_counts_real_calls(tmp_path, request):
    import cProfile

    from tools.benchmarks import profile_suite

    outer = getattr(request.session, "repository_profile", None)
    if outer is not None:
        outer.disable()  # Python 3.14 不允许两个 cProfile 同时占用同一监控工具。
    try:
        profile = cProfile.Profile()
        profile.runcall(textio.normalized_text, "a\r\n")
        profile.dump_stats(str(tmp_path / "sample.prof"))
    finally:
        if outer is not None:
            outer.enable()
    summary = profile_suite.summarize(tmp_path)
    assert summary["profiles"] == ["sample.prof"]
    assert isinstance(summary["modules"], dict)
    assert summary["modules"]["src/pdx/textio.py"]["calls"] == 1
    assert all(name.endswith(".py") for name in summary["modules"])
    assert profile_suite.summarize(tmp_path / "missing")["profiles"] == []


def test_process_enumeration_uses_names_and_platform(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pdx import game_auto

    monkeypatch.setattr(
        game_auto.psutil,
        "process_iter",
        lambda _: [
            SimpleNamespace(pid=10, info={"name": "Victoria3.EXE"}),
            SimpleNamespace(pid=20, info={"name": "victoria3"}),
            SimpleNamespace(pid=30, info={"name": None}),
            SimpleNamespace(pid=40, info={"name": "other"}),
        ],
    )
    monkeypatch.setattr(sys, "platform", "win32")
    assert game_auto._process_pids() == [10]
    monkeypatch.setattr(sys, "platform", "linux")
    assert game_auto._process_pids() == [20]
    assert game_auto._process_pids("VICTORIA3.EXE") == [10]


def test_kill_ignores_process_that_already_exited(monkeypatch):
    from pdx import game_auto

    monkeypatch.setattr(game_auto, "_process_pids", lambda: [999])

    def exited(pid):
        raise game_auto.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(game_auto.psutil, "Process", exited)
    assert game_auto.kill_game() == []


@pytest.mark.parametrize("offline", [False, True])
def test_table_cli_detects_repairs_and_preserves_prose(tmp_path, monkeypatch, offline):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from pdx import cli, config, docgen, tables_offline
    from pdx.doc_tables import TableSpec

    game = tmp_path / "game"
    (game / "common").mkdir(parents=True)
    monkeypatch.setattr(config, "GAME", game)
    doc = tmp_path / "99-sample.md"
    doc.write_bytes(
        b"# Sample\n\nProse before.\n\n| Name | Count |\n|---|---|\n| alpha | 999 |\n\nProse after.\n"
    )
    rows = ["| alpha | 1 |"]
    spec = TableSpec("sample", "| Name | Count |", lambda: rows)
    target = SimpleNamespace(name=doc.name, path=doc, specs=(spec,))
    monkeypatch.setattr(docgen, "targets", lambda: (target,))
    monkeypatch.setattr(tables_offline, "load_tables", lambda: {"99-sample.md::sample": rows})
    runner = CliRunner()
    args = ["tables", *(["--offline"] if offline else [])]
    before = doc.read_bytes()
    failure = runner.invoke(cli.app, args)
    assert failure.exit_code == 1, failure.output
    assert "999" in failure.output
    assert doc.read_bytes() == before
    repaired = runner.invoke(cli.app, [*args, "--write"])
    assert repaired.exit_code == 0, repaired.output
    raw = doc.read_bytes()
    assert b"| alpha | 1 |" in raw
    assert b"999" not in raw
    assert b"Prose before." in raw
    assert b"Prose after." in raw
    assert b"\r" not in raw
    assert not raw.startswith(codecs.BOM_UTF8)
    assert runner.invoke(cli.app, args).exit_code == 0
    assert runner.invoke(cli.app, [*args, "--write"]).exit_code == 0
    assert doc.read_bytes() == raw


@pytest.mark.parametrize("offline", [False, True])
@pytest.mark.parametrize("write", [False, True])
def test_table_cli_missing_header_reports_prerequisite(tmp_path, monkeypatch, offline, write):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from pdx import cli, config, docgen, tables_offline
    from pdx.doc_tables import TableSpec

    (tmp_path / "game/common").mkdir(parents=True)
    monkeypatch.setattr(config, "GAME", tmp_path / "game")
    doc = tmp_path / "99-sample.md"
    doc.write_bytes(b"# No table\n")
    spec = TableSpec("sample", "| Name | Count |", lambda: ["| alpha | 1 |"])
    monkeypatch.setattr(
        docgen, "targets", lambda: (SimpleNamespace(name=doc.name, path=doc, specs=(spec,)),)
    )
    monkeypatch.setattr(
        tables_offline, "load_tables", lambda: {"99-sample.md::sample": ["| alpha | 1 |"]}
    )
    args = ["tables", *(["--offline"] if offline else []), *(["--write"] if write else [])]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    assert "TableNotFoundError" in result.output
    assert doc.read_bytes() == b"# No table\n"


@pytest.mark.parametrize("separator", ["/", chr(92)])
def test_coverage_gate_uses_actual_statement_and_branch_counts(tmp_path, separator):
    from pdx import covgate

    files = {}
    for name, statements, lines, branches, covered_branches in [
        ("small", 10, 10, 90, 0),
        ("large", 100, 100, 0, 0),
    ]:
        files[separator.join(["src", "pdx", name + ".py"])] = {
            "summary": {
                "num_statements": statements,
                "covered_lines": lines,
                "num_branches": branches,
                "covered_branches": covered_branches,
                "percent_covered": 100 * (lines + covered_branches) / (statements + branches),
            }
        }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"files": files}), encoding="utf-8", newline="\n")
    rows = covgate.load_coverage(path)
    assert len(rows) == 2
    assert covgate.total_percent(rows) == pytest.approx(55.0)
    assert covgate.total_percent([]) == 0
