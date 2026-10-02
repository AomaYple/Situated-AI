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
    assert sorted(argv_files) == files
    assert all(any(arg.startswith("tests/") for arg in case["argv"]) for case in cases)
