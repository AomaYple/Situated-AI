"""性能基准编排器的纯逻辑测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from typer.main import get_command

from pdx import cli

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "tools" / "benchmarks" / "perf_baseline.py"
    spec = importlib.util.spec_from_file_location("perf_baseline", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shards_cover_real_test_files(monkeypatch):
    module = _load_module()
    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    assert files
    cases = module.shard_cases()
    argv_files = [
        arg.removeprefix("tests/")
        for case in cases
        for arg in case["argv"]
        if arg.startswith("tests/")
    ]
    assert len(cases) == module.SHARD_COUNT
    assert sorted(argv_files) == files
    assert len(argv_files) == len(set(argv_files))
    shard_files = [
        {arg.removeprefix("tests/") for arg in case["argv"] if arg.startswith("tests/")}
        for case in cases
    ]
    assert all(shard_files)
    assert all(
        shard_files[i].isdisjoint(shard_files[j])
        for i in range(len(shard_files))
        for j in range(i + 1, len(shard_files))
    )
    assert all(
        "-n" in case["argv"] and case["argv"][case["argv"].index("-n") + 1] == "1" for case in cases
    )


def test_shard_test_files_is_stable_and_validates_count():
    module = _load_module()
    files = ["test_c.py", "test_a.py", "test_b.py", "test_d.py", "test_e.py"]
    assert module.shard_test_files(files, 2) == [
        ["test_a.py", "test_c.py", "test_e.py"],
        ["test_b.py", "test_d.py"],
    ]
    for invalid in (0, -1):
        try:
            module.shard_test_files(files, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid shard count must fail")


def test_cli_measurements_reference_existing_commands():
    module = _load_module()
    tree = get_command(cli.app)
    for case in (item for item in module.CASES if item["group"] == "cli"):
        argv = case["argv"]
        tokens = argv[argv.index("pdx.cli") + 1 :]
        command = tree
        traversed = False
        for token in tokens:
            if token.startswith("-"):
                break
            children = getattr(command, "commands", {})
            if token in children:
                command = children[token]
                traversed = True
                continue
            break
        if tokens and all(token.startswith("-") for token in tokens):
            assert tokens == ["--help"], f"{case['id']} 含未知根级参数：{tokens}"
        else:
            assert traversed, f"{case['id']} 引用了不存在的 CLI 命令：{tokens}"
