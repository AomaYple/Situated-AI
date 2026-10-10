"""pytest cProfile 插件：每个 worker 独立落盘，按模块汇总真实执行的函数自身耗时。

用法：python -m pytest -p tools.benchmarks.profile_suite --profile-directory tools/out/profiles
汇总：python tools/benchmarks/profile_suite.py --directory tools/out/profiles
分析 profile 有额外开销；墙钟/RSS 基线必须另跑 pdx.performance。
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def pytest_addoption(parser: Any) -> None:
    parser.addoption("--profile-directory", default="tools/out/repository-audit/profiles")


def pytest_sessionstart(session: Any) -> None:
    profile = cProfile.Profile()
    session.repository_profile = profile
    profile.enable()


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    profile = session.repository_profile
    profile.disable()
    directory = Path(session.config.getoption("--profile-directory"))
    directory.mkdir(parents=True, exist_ok=True)
    profile.dump_stats(str(directory / f"{os.getpid()}-exit{int(exitstatus)}.prof"))


def summarize(directory: Path, root: Path = ROOT) -> dict[str, object]:
    modules: dict[str, dict[str, float | int]] = {}
    profiles = sorted(directory.glob("*.prof"))
    resolved_root = root.resolve()
    paths: dict[str, str | None] = {}
    for path in profiles:
        for (filename, _line, _function), (
            _primitive,
            calls,
            own,
            _cumulative,
            _callers,
        ) in pstats.Stats(str(path)).stats.items():  # type: ignore[attr-defined]
            if not filename.endswith(".py"):
                continue  # 内建函数的伪文件名不是仓库模块。
            if filename not in paths:
                try:
                    paths[filename] = Path(filename).resolve().relative_to(resolved_root).as_posix()
                except ValueError:
                    paths[filename] = None
            relative = paths[filename]
            if relative is None:
                continue
            if relative.startswith((".venv/", "tests/", "tools/out/")):
                continue
            record = modules.setdefault(relative, {"calls": 0, "self_elapsed_s": 0.0})
            record["calls"] += calls
            record["self_elapsed_s"] += own
    return {
        "schema": 1,
        "method": "cProfile 自身耗时之和，不是操作系统 CPU 时间；包含分析器开销；内存另行测量",
        "profiles": [p.name for p in profiles],
        "modules": dict(
            sorted(modules.items(), key=lambda item: float(item[1]["self_elapsed_s"]), reverse=True)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.directory)
    target = args.directory / "module-cost.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(target)
    return 0 if report["profiles"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
