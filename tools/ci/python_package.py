"""Build the Python wheel and verify that it contains every project module."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import zipfile
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="situated-ai-wheel-") as temporary:
        output = Path(temporary)
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
                str(REPO),
            ],
            cwd=REPO,
            check=False,
        )
        if result.returncode:
            print(f"[python-package] wheel 构建失败，退出码 {result.returncode}")
            return result.returncode
        wheels = tuple(output.glob("*.whl"))
        if len(wheels) != 1:
            print(f"[python-package] 预期恰有一个 wheel，实际为 {len(wheels)}")
            return 1
        omitted = missing_modules(wheels[0])
        if omitted:
            print(f"[python-package] wheel 缺少源码模块：{list(omitted)}")
            return 1
        print(f"[python-package] wheel 包含全部 {len(source_modules())} 个 Python 源模块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
