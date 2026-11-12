"""逐件盘点工作区；原始证据和第三方文件只读，不执行扫描到的脚本。"""

from __future__ import annotations

import argparse
import ast
import codecs
import hashlib
import json
import os
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

from pdx import version_contracts
from pdx.situated import r2_reader_authority

REPO = Path(__file__).resolve().parents[2]
CHUNK_SIZE = 64 * 1024
BINARY_SUFFIXES = frozenset(
    [
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".dds",
        ".tga",
        ".ico",
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".zip",
        ".gz",
        ".7z",
        ".exe",
        ".dll",
        ".pyd",
        ".pyc",
        ".bin",
        ".idx",
        ".prof",
        ".pyisession",
        ".db",
        ".sqlite",
        ".coverage",
    ]
)
BINARY_SUFFIXES |= frozenset(
    {
        ".lib",
        ".npy",
        ".npz",
        ".whl",
        ".bmp",
        ".chm",
        ".pkl",
        ".pickle",
        ".fits",
        ".dat",
        ".mo",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".so",
        ".a",
    }
)
CACHE_DIRS = frozenset(
    {"__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".hypothesis", ".benchmarks"}
)
NATIVE_EVIDENCE_ROOT = "research/vanilla-ai/1.15.0/native/"
READER_EVIDENCE_ROOT = "research/vanilla-ai/1.15.0/r2-readers/"
NATIVE_EVIDENCE_PATHS = frozenset(
    {
        "launcher/launcher-settings.json",
        "caligula_branch.txt",
        "caligula_rev.txt",
        "clausewitz_branch.txt",
        "clausewitz_rev.txt",
        "binaries/checksum.txt",
        "game/common/decrees/00_decree.txt",
        "game/common/ai_strategies/00_default_strategy.txt",
        "game/common/ai_strategies/03_political_strategies.txt",
        "game/common/diplomatic_actions/00_relations_actions.txt",
    }
)


def is_native_evidence_path(rel: str) -> bool:
    """Only individually pinned upstream files have an original-byte exception."""
    for version in ("1.15.0", "1.15.1"):
        native_root = f"research/vanilla-ai/{version}/native/"
        reader_root = f"research/vanilla-ai/{version}/r2-readers/"
        with version_contracts.select_version(version):
            if (
                rel.startswith(native_root)
                and rel.removeprefix(native_root) in NATIVE_EVIDENCE_PATHS
            ) or (
                rel.startswith(reader_root)
                and rel.removeprefix(reader_root) in r2_reader_authority.source_hashes()
            ):
                return True
    return False


def reader_evidence_contract(root: Path) -> dict[str, str]:
    """Grant byte exceptions only after each version's complete closure verifies."""
    result: dict[str, str] = {}
    for version in ("1.15.0", "1.15.1"):
        relative = f"research/vanilla-ai/{version}/r2-readers/"
        evidence = root / relative
        if not evidence.exists() and not evidence.is_symlink():
            continue
        with version_contracts.select_version(version):
            r2_reader_authority.verify_frozen(evidence)
            result.update(
                {
                    relative + name: digest
                    for name, digest in r2_reader_authority.source_hashes().items()
                }
            )
    return result


def _native_evidence_contract(root: Path, version: str) -> dict[str, str]:
    """Bind the exact raw-byte set to its production declaration and manifest."""
    relative = f"research/vanilla-ai/{version}/native/"
    native = root / relative
    declaration = (
        root
        / "mod/decisions"
        / ("architecture_1151.toml" if version == "1.15.1" else "architecture_115.toml")
    )
    if not native.exists() and not native.is_symlink() and not declaration.exists():
        return {}
    manifest = native / "baseline-manifest.json"

    def fail(message: str) -> ValueError:
        return ValueError(f"{relative}: {message}")

    if native.is_symlink() or native.resolve() != native.absolute() or not native.is_dir():
        raise fail("原版证据目录必须是仓库内的真实目录")
    if manifest.is_symlink() or not manifest.is_file():
        raise fail("baseline-manifest 必须是真实文件")
    try:
        data = tomllib.loads(declaration.read_text(encoding="utf-8"))
        rows = data["identity"] + data["input"]
        hashes: dict[str, str] = {}
        for row in rows:
            name, digest = row["path"], row["sha256"]
            if (
                name not in NATIVE_EVIDENCE_PATHS
                or name in hashes
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise fail("原版声明含非法、重复路径或 SHA-256")
            hashes[name] = digest
        if set(hashes) != NATIVE_EVIDENCE_PATHS:
            raise fail("原版声明必须恰好包含十个锁定路径")
        contents = json.loads(manifest.read_text(encoding="utf-8"))
        expected = [{"path": name, "sha256": digest} for name, digest in hashes.items()]
        if (
            not isinstance(contents, dict)
            or contents.get("schema") != 1
            or contents.get("profile") != data.get("profile")
            or contents.get("game_version") != data.get("game_version")
            or contents.get("files") != expected
        ):
            raise fail("baseline-manifest 与生产声明不一致")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        raise fail(f"无法验证原版声明与 manifest: {error}") from error
    actual = {
        path.relative_to(native).as_posix()
        for path in native.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != NATIVE_EVIDENCE_PATHS | {"baseline-manifest.json"}:
        raise fail("原版证据含未声明文件或缺少锁定文件")
    for name, digest in hashes.items():
        path = native / name
        if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
            raise fail(f"{name}: 缺少真实文件或检测到链接")
        if inspect_bytes(path)["sha256"] != digest:
            raise fail(f"{name}: 原始字节 SHA-256 漂移")
    return {relative + name: digest for name, digest in hashes.items()}


def native_evidence_contract(root: Path) -> dict[str, str]:
    """Verify all explicitly supported raw snapshots, including historical inputs."""
    return {
        name: digest
        for version in ("1.15.0", "1.15.1")
        for name, digest in _native_evidence_contract(root, version).items()
    }


def category(rel: str) -> str:
    """分类只决定处置，不把被忽略文件从盘点里藏起来。"""
    path = Path(rel)
    parts = path.parts
    if ".venv" in parts:
        return "third_party_environment"
    if any(part in CACHE_DIRS for part in parts) or parts[0].startswith("v3-parse-cache-"):
        return "cache"
    if rel.startswith("research/official-docs/"):
        return "third_party_mirror"
    if rel.startswith((".agent-teams/", ".agents/", ".codex/")):
        return "local_runtime"
    if rel.startswith("tools/out/") and not rel.endswith(".compact.json"):
        return "raw_evidence"
    # Frozen native baselines preserve upstream bytes verbatim, including the
    # engine's BOM/CR conventions.  They remain inventoried and hash-checked,
    # but are evidence rather than repository-authored source.
    if is_native_evidence_path(rel):
        return "raw_evidence"
    if path.suffix.lower() in BINARY_SUFFIXES or path.name.startswith(".coverage"):
        return "binary_asset"
    if rel.startswith("tests/"):
        return "test"
    if path.suffix == ".py":
        return "source"
    if rel.startswith("mod/decisions/"):
        return "source"
    if rel.startswith("mod/"):
        return "generated"
    if path.suffix == ".md":
        return "documentation"
    return "configuration_or_data"


def inspect_bytes(path: Path, *, chunk_size: int = CHUNK_SIZE) -> dict[str, object]:
    """一次流式读取计算哈希、严格 UTF-8、BOM、CR 和 NUL；内存与文件大小无关。"""
    digest = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    utf8 = True
    size = cr = nul = 0
    first = b""
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            if size < 4:
                first = (first + chunk)[:4]
            size += len(chunk)
            digest.update(chunk)
            cr += chunk.count(b"\r")
            nul += chunk.count(b"\0")
            if utf8:
                try:
                    decoder.decode(chunk)
                except UnicodeDecodeError:
                    utf8 = False
        if utf8:
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                utf8 = False
    return {
        "bytes": size,
        "sha256": digest.hexdigest(),
        "utf8": utf8,
        "bom": first.startswith(codecs.BOM_UTF8),
        "cr": cr,
        "nul": nul,
    }


def git_paths(root: Path, *args: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", *args], cwd=root, capture_output=True, check=True
    )
    return {p.decode("utf-8") for p in result.stdout.split(b"\0") if p}


def source_issues(root: Path) -> list[str]:
    """提交门禁包括已跟踪和未忽略的新文件，严格检查所有自有文本。"""
    issues = []
    try:
        native_files = {**native_evidence_contract(root), **reader_evidence_contract(root)}
    except ValueError as error:
        issues.append(str(error))
        native_files = {}
    for rel in sorted(git_paths(root, "--cached", "--others", "--exclude-standard")):
        path = root / rel
        if not path.exists():
            continue  # 已删除但尚未提交的文件不在工作区文本集合内。
        if path.is_symlink():
            issues.append(f"{rel}: 符号链接需要单独审查")
            continue
        if rel in native_files:
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        result = inspect_bytes(path)
        bad = [key for key in ("bom", "cr", "nul") if result[key]]
        if not result["utf8"]:
            bad.append("non_utf8")
        if bad:
            issues.append(f"{rel}: {', '.join(bad)}")
    return issues


def inventory(root: Path) -> dict[str, object]:
    """遍历所有目录，排除 Git 对象库；符号链接只记目标，不跟随到仓库外。"""
    tracked = git_paths(root)
    untracked = git_paths(root, "--others", "--exclude-standard")
    ignored = git_paths(root, "--others", "--ignored", "--exclude-standard")
    records: list[dict[str, object]] = []
    directories: list[str] = []
    errors: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    totals: Counter[str] = Counter()

    def walk_error(error: OSError) -> None:
        errors.append({"path": str(error.filename), "error": str(error)})

    for base, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        directory = Path(base)
        directories.append(directory.relative_to(root).as_posix())
        links = [d for d in dirs if (directory / d).is_symlink()]
        directories.extend((directory / d).relative_to(root).as_posix() for d in links)
        dirs[:] = [d for d in dirs if d not in links]
        for name in sorted([*names, *links]):
            path = directory / name
            rel = path.relative_to(root).as_posix()
            group = category(rel)
            state = (
                "tracked"
                if rel in tracked
                else "untracked"
                if rel in untracked
                else "ignored"
                if rel in ignored
                else "unclassified"
            )
            record: dict[str, object] = {"path": rel, "category": group, "git": state}
            try:
                if path.is_symlink():
                    record["symlink"] = str(path.readlink())
                else:
                    record.update(inspect_bytes(path))
                    binary = (
                        path.suffix.lower() in BINARY_SUFFIXES
                        or name.startswith(".coverage")
                        or bool(record["nul"])
                        or (not path.suffix and not record["utf8"])
                    )
                    record["binary"] = binary
                    if not binary:
                        record["encoding_issues"] = [
                            key for key in ("bom", "cr", "nul") if record[key]
                        ] + ([] if record["utf8"] else ["non_utf8"])
                    if path.suffix == ".py" and group not in {"third_party_environment", "cache"}:
                        try:
                            source = path.read_text(encoding="utf-8-sig")
                            tree = ast.parse(source, filename=rel)
                            record["python"] = {
                                "lines": len(source.splitlines()),
                                "functions": sum(
                                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                    for n in ast.walk(tree)
                                ),
                                "imports": sorted(
                                    {
                                        n.names[0].name.split(".")[0]
                                        if isinstance(n, ast.Import)
                                        else (n.module or "").split(".")[0]
                                        for n in ast.walk(tree)
                                        if isinstance(n, (ast.Import, ast.ImportFrom))
                                    }
                                ),
                            }
                        except (SyntaxError, UnicodeError) as error:
                            record["python_error"] = str(error)
            except OSError as error:
                record["read_error"] = str(error)
                errors.append({"path": rel, "error": str(error)})
            counts[group] += 1
            totals[group] += int(str(record.get("bytes", 0)))
            records.append(record)
    return {
        "schema": 1,
        "scope": "盘上除 .git 外的全部文件；不跟随链接",
        "counts": dict(sorted(counts.items())),
        "bytes": dict(sorted(totals.items())),
        "directories": directories,
        "read_errors": errors,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-only", action="store_true", help="提交门禁：包含未忽略的新文件")
    args = parser.parse_args()
    if args.project_only:
        issues = source_issues(args.root.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print("\n".join(issues) or "仓库文本 UTF-8 无 BOM + LF 检查通过")
        return int(bool(issues))
    result = inventory(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in {"files", "directories"}},
            ensure_ascii=False,
        )
    )
    return 1 if result["read_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
