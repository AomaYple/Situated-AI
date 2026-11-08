"""Build the Python wheel and verify that it contains every project module."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "pdx"


def source_modules(source: Path = SOURCE) -> set[str]:
    """Return the wheel paths for all Python source modules."""

    return {
        path.relative_to(source.parent).as_posix()
        for path in source.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def wheel_modules(wheel: Path) -> set[str]:
    """Return package Python module paths from a built wheel."""

    with zipfile.ZipFile(wheel) as archive:
        return {
            name for name in archive.namelist() if name.startswith("pdx/") and name.endswith(".py")
        }


def missing_modules(wheel: Path, source: Path = SOURCE) -> tuple[str, ...]:
    """Find source modules omitted by the distributable wheel."""

    return tuple(sorted(source_modules(source) - wheel_modules(wheel)))


def wheel_issues(wheel: Path, source: Path = SOURCE) -> tuple[str, ...]:
    """Check exact module membership, bytes, ZIP integrity and duplicate paths."""
    expected = source_modules(source)
    actual = wheel_modules(wheel)
    issues = [f"missing: {name}" for name in sorted(expected - actual)]
    issues.extend(f"unexpected: {name}" for name in sorted(actual - expected))
    with zipfile.ZipFile(wheel) as archive:
        issues.extend(
            f"duplicate: {name}" for name, count in Counter(archive.namelist()).items() if count > 1
        )
        damaged = archive.testzip()
        if damaged is not None:
            issues.append(f"corrupt: {damaged}")
        issues.extend(
            f"changed: {name}"
            for name in sorted(expected & actual)
            if archive.read(name) != (source.parent / name).read_bytes()
        )
    return tuple(sorted(issues))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="situated-ai-wheel-") as temporary:
        output = Path(temporary) / "wheels"
        output.mkdir()
        staging = Path(temporary) / "source"
        staging.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(REPO / name, staging / name)
        shutil.copytree(
            SOURCE,
            staging / "src" / "pdx",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(output),
                str(staging),
            ],
            cwd=staging,
            check=False,
            env=env,
        )
        if result.returncode:
            print(f"[python-package] wheel 构建失败，退出码 {result.returncode}")
            return result.returncode
        wheels = tuple(output.glob("*.whl"))
        if len(wheels) != 1:
            print(f"[python-package] 预期恰有一个 wheel，实际为 {len(wheels)}")
            return 1
        issues = wheel_issues(wheels[0], SOURCE)
        if issues:
            print(f"[python-package] wheel 校验失败：{list(issues)}")
            return 1
        print(f"[python-package] wheel 精确包含全部 {len(source_modules(SOURCE))} 个 Python 源模块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
