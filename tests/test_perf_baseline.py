"""性能基准编排器的纯逻辑测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

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
