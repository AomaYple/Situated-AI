"""检查仓库中不应保留的可再生缓存和 Python 运行态文件。

这个检查只负责仓库卫生，不判断源码是否可以删除，也不扫描 ``tools/out``、
``.venv`` 或官方文档镜像中的运行态内容：这些目录分别由证据、环境和原文
字节契约管理。检查结果可以写入被忽略的 ``tools/out/ci``，不会改变仓库内容。

用法::

    python -m tools.ci.repo_hygiene
    python -m tools.ci.repo_hygiene --output tools/out/ci/repo-hygiene.json
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 根目录中测试、静态检查和一次性工具留下的可再生目录。
ROOT_CACHE_NAMES = frozenset(
    {
        ".benchmarks",
        ".cache",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pyre",
        ".pyright",
        ".pytest_cache",
        ".pytype",
        ".ruff_cache",
        ".tox",
    }
)
ROOT_CACHE_PREFIXES = (
    ".ruff-cache-",
    "sitai-perf-restore-",
    "v3-parse-cache-",
    "pip-install-",
    "pip-ephem-wheel-cache-",
)
ROOT_CACHE_FILES = (".coverage",)

# 这些目录的内容有独立字节契约或是本机运行环境，不属于源码卫生门禁。
EXCLUDED_ROOTS = (
    ".git",
    ".venv",
    "research/official-docs",
    "tools/out",
)


def _excluded(relative: Path) -> bool:
    """判断路径是否位于明确排除的环境、镜像或证据目录。"""

    text = relative.as_posix()
    return any(text == root or text.startswith(root + "/") for root in EXCLUDED_ROOTS)


def _is_root_cache(relative: Path) -> bool:
    """判断根目录下的缓存目录或覆盖率文件。"""

    if len(relative.parts) != 1:
        return False
    name = relative.name
    return (
        name in ROOT_CACHE_NAMES
        or any(name.startswith(prefix) for prefix in ROOT_CACHE_PREFIXES)
        or name in ROOT_CACHE_FILES
        or name.startswith(".coverage.")
    )


def find_violations(root: Path = ROOT) -> list[dict[str, str]]:
    """返回按路径排序的可再生运行态违规项。

    目录只报告一次；发现缓存目录后不再报告其子项。符号链接不跟随，避免
    检查范围越过仓库边界或触发外部文件系统访问。
    """

    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"卫生检查根目录不存在或不是目录：{root}")
    violations: list[dict[str, str]] = []

    def walk(base: Path) -> None:
        try:
            entries = sorted(base.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            base_relative = base.relative_to(root).as_posix() or "."
            violations.append({"path": base_relative, "kind": "read_error", "detail": str(exc)})
            return
        for path in entries:
            # Windows junctions are reparse points, but not symbolic links.
            # lstat is available on all supported Python versions (including 3.11).
            try:
                info = path.lstat()
            except OSError as exc:
                violations.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "kind": "read_error",
                        "detail": str(exc),
                    }
                )
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                continue
            relative = path.relative_to(root)
            if _excluded(relative):
                continue
            if _is_root_cache(relative):
                violations.append(
                    {
                        "path": relative.as_posix(),
                        "kind": "root_cache",
                        "detail": "根目录可再生缓存或覆盖率文件",
                    }
                )
                continue
            if path.is_dir():
                if path.name == "__pycache__":
                    violations.append(
                        {
                            "path": relative.as_posix(),
                            "kind": "bytecode_directory",
                            "detail": "Python 字节码缓存目录",
                        }
                    )
                    continue
                walk(path)
                continue
            if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
                violations.append(
                    {
                        "path": relative.as_posix(),
                        "kind": "bytecode_file",
                        "detail": "Python 字节码文件",
                    }
                )

    walk(root)
    return sorted(violations, key=lambda row: (row["path"], row["kind"]))


def report(root: Path = ROOT) -> dict[str, object]:
    """生成稳定、可机器读取的卫生报告。"""

    violations = find_violations(root)
    return {
        "schema": 1,
        "root": str(root.resolve()),
        "excluded_roots": list(EXCLUDED_ROOTS),
        "violation_count": len(violations),
        "violations": violations,
    }


def _write_report(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="写入 JSON 报告")
    args = parser.parse_args(argv)
    try:
        data = report(args.root)
        if args.output is not None:
            _write_report(args.output, data)
    except OSError as exc:
        print(f"[hygiene] 检查失败：{exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"violation_count": data["violation_count"], "violations": data["violations"]},
            ensure_ascii=False,
        )
    )
    return 1 if data["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
