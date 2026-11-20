"""Build the Python wheel and verify the source modules and artifact boundary."""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "src" / "pdx"
WHEEL_METADATA_FILES = frozenset(
    {"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD", "licenses/LICENSE"}
)
REQUIRED_WHEEL_METADATA = frozenset({"METADATA", "WHEEL", "RECORD", "entry_points.txt"})


class _EntryPointConfig(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        # The entry point specification treats script names as case-sensitive.
        return optionstr


def source_modules(source: Path = SOURCE) -> set[str]:
    """Return the wheel paths for all Python source modules."""

    return {
        path.relative_to(source.parent).as_posix()
        for path in source.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _package_modules(names: Iterable[str]) -> set[str]:
    return {name for name in names if name.startswith("pdx/") and name.endswith(".py")}


def wheel_modules(wheel: Path) -> set[str]:
    """Return package Python module paths from a built wheel."""

    with zipfile.ZipFile(wheel) as archive:
        return _package_modules(archive.namelist())


def missing_modules(wheel: Path, source: Path = SOURCE) -> tuple[str, ...]:
    """Find source modules omitted by the distributable wheel."""

    return tuple(sorted(source_modules(source) - wheel_modules(wheel)))


def _v3_entry_point_issue(archive: zipfile.ZipFile, name: str) -> str | None:
    entry_points = _EntryPointConfig(interpolation=None, delimiters=("=",))
    try:
        entry_points.read_string(archive.read(name).decode("utf-8"))
    except configparser.Error, UnicodeDecodeError:
        return f"invalid: {name} (cannot read v3 console script)"
    target = entry_points.get("console_scripts", "v3", fallback="")
    module, _, attribute = target.partition(":")
    if entry_points.defaults() or (module.strip(), attribute.strip()) != ("pdx.cli", "app"):
        return f"invalid: {name} (expected [console_scripts] v3 = pdx.cli:app)"
    return None


def wheel_issues(wheel: Path, source: Path = SOURCE) -> tuple[str, ...]:
    """Check module bytes, archive integrity, required metadata and the v3 launcher."""
    expected = source_modules(source)
    # Wheel filenames start with the normalized distribution and version.
    wheel_identity = wheel.stem.split("-", 2)
    if len(wheel_identity) != 3:
        return (f"invalid wheel filename: {wheel.name}",)
    distribution, version, _tags = wheel_identity
    dist_info = f"{distribution}-{version}.dist-info"
    allowed_metadata = {f"{dist_info}/{name}" for name in WHEEL_METADATA_FILES}
    required_metadata = {f"{dist_info}/{name}" for name in REQUIRED_WHEEL_METADATA}
    entries_path = f"{dist_info}/entry_points.txt"
    with zipfile.ZipFile(wheel) as archive:
        counts = Counter(archive.namelist())
        actual = _package_modules(counts)
        issues = [f"missing: {name}" for name in expected - actual]
        issues.extend(f"missing: {name}" for name in required_metadata - counts.keys())
        issues.extend(f"unexpected: {name}" for name in counts.keys() - expected - allowed_metadata)
        issues.extend(f"duplicate: {name}" for name, count in counts.items() if count > 1)
        damaged = archive.testzip()
        if damaged is None:
            issues.extend(
                f"changed: {name}"
                for name in expected & actual
                if archive.read(name) != (source.parent / name).read_bytes()
            )
            if counts[entries_path] == 1 and (
                issue := _v3_entry_point_issue(archive, entries_path)
            ):
                issues.append(issue)
        else:
            issues.append(f"corrupt: {damaged}")
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
        print(
            f"[python-package] wheel 包含全部 {len(source_modules(SOURCE))} 个 Python 源模块，"
            "必需元数据与 v3 命令入口完整，其余条目均为允许的打包元数据"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
