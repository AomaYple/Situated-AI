"""检查并按白名单清理仓库中不应保留的可再生缓存和运行态文件。

这个检查只负责仓库卫生，不判断源码是否可以删除，也不扫描 ``tools/out``、
``.venv``、``.claude``、``.superpowers`` 或官方文档镜像中的运行态内容：这些
目录分别由证据、环境、协作工具和原文字节契约管理。默认只报告，不改变仓库
内容；``--clean`` 仍是 dry-run，只有显式传入 ``--apply`` 才会删除白名单项目。
清理不会跟随符号链接或 Windows reparse point，也不会触碰受控证据目录。

用法::

    python -m tools.ci.repo_hygiene
    python -m tools.ci.repo_hygiene --output tools/out/ci/repo-hygiene.json
    python -m tools.ci.repo_hygiene --clean       # 只列出可清理项目
    python -m tools.ci.repo_hygiene --clean --apply
"""

import argparse
import json
import shutil
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
ROOT_BUILD_NAMES = frozenset({"build", "dist"})
ROOT_BUILD_SUFFIXES = (".egg-info",)

# 只有这些报告类别可由本入口清理。未知文件、读取错误和证据目录永远不
# 会被递归删除；构建目录只限根目录和 src 直接子目录的 egg-info。
CLEANABLE_KINDS = frozenset({"root_cache", "build_artifact", "bytecode_directory", "bytecode_file"})

# 这些目录的内容有独立字节契约或是本机运行环境，不属于源码卫生门禁。
EXCLUDED_ROOTS = (
    ".git",
    ".venv",
    ".claude",
    ".superpowers",
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


def _is_root_build(relative: Path) -> bool:
    """判断根构建目录，以及根目录或 src 直接子目录的 egg-info。"""

    name = relative.name
    return (len(relative.parts) == 1 and name in ROOT_BUILD_NAMES) or (
        name.endswith(ROOT_BUILD_SUFFIXES)
        and (len(relative.parts) == 1 or (len(relative.parts) == 2 and relative.parts[0] == "src"))
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
            if _is_root_build(relative):
                violations.append(
                    {
                        "path": relative.as_posix(),
                        "kind": "build_artifact",
                        "detail": "根构建目录或根/src 直接子目录的可再生 egg-info",
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


def _safe_target(root: Path, relative: str) -> Path | None:
    """解析一个内部报告路径，并拒绝越出根目录的链接或路径。"""

    root = root.resolve()
    target = root / Path(relative)
    try:
        info = target.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        return None
    try:
        resolved = target.resolve()
    except OSError:
        return None
    if resolved != root and root not in resolved.parents:
        return None
    return target


def clean(root: Path = ROOT, *, apply: bool = False) -> dict[str, object]:
    """按白名单清理报告中的项目；默认只返回 dry-run 计划。"""

    root = root.resolve()
    violations = find_violations(root)
    candidates = [row for row in violations if row["kind"] in CLEANABLE_KINDS]
    skipped = [row for row in violations if row["kind"] not in CLEANABLE_KINDS]
    removed: list[str] = []
    failures: list[dict[str, str]] = []
    if apply:
        # 先处理父目录，避免清理根缓存后再对其中子项重复操作。
        candidates = sorted(candidates, key=lambda row: (row["path"].count("/"), row["path"]))
        removed_targets: list[Path] = []
        for row in candidates:
            target = _safe_target(root, row["path"])
            if target is None or any(
                target == parent or parent in target.parents for parent in removed_targets
            ):
                failures.append({**row, "detail": "目标不存在、已处理或位于链接/reparse point"})
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except OSError as exc:
                failures.append({**row, "detail": f"删除失败：{exc}"})
                continue
            removed.append(row["path"])
            removed_targets.append(target)
    return {
        "mode": "apply" if apply else "dry-run",
        "cleanable": candidates
        if not apply
        else [row for row in violations if row["kind"] in CLEANABLE_KINDS],
        "skipped": skipped,
        "removed": removed,
        "failures": failures,
    }


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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="列出白名单可清理项目；默认 dry-run，不修改文件",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="与 --clean 联用，实际删除白名单项目",
    )
    args = parser.parse_args(argv)
    if args.apply and not args.clean:
        parser.error("--apply 必须与 --clean 一起使用")
    try:
        data = report(args.root)
        cleanup = clean(args.root, apply=args.apply) if args.clean else None
        if args.output is not None:
            payload: dict[str, object] = dict(data)
            if cleanup is not None:
                payload["cleanup"] = cleanup
            _write_report(args.output, payload)
    except OSError as exc:
        print(f"[hygiene] 检查失败：{exc}", file=sys.stderr)
        return 2
    payload = {"violation_count": data["violation_count"], "violations": data["violations"]}
    if cleanup is not None:
        payload["cleanup"] = cleanup
        if args.apply:
            refreshed = report(args.root)
            payload["remaining_violation_count"] = refreshed["violation_count"]
            payload["remaining_violations"] = refreshed["violations"]
            print(json.dumps(payload, ensure_ascii=False))
            return 1 if refreshed["violations"] else 0
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if data["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
