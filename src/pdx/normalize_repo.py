"""全仓文本规范化：每个修改先备份原始字节，二进制不做文本转换。"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import zipfile
from pathlib import Path

from pdx.repo_audit import BINARY_SUFFIXES, REPO
from pdx.textio import normalized_text

TEXT_SUFFIXES = frozenset(
    [
        ".py",
        ".pyi",
        ".pyw",
        ".pys",
        ".toml",
        ".json",
        ".jsonl",
        ".yml",
        ".yaml",
        ".txt",
        ".log",
        ".out",
        ".md",
        ".rst",
        ".csv",
        ".tsv",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".js",
        ".ts",
        ".sh",
        ".ps1",
        ".bat",
        ".cmd",
        ".cfg",
        ".ini",
        ".pth",
        ".c",
        ".h",
        ".cpp",
        ".f",
        ".f90",
        ".f95",
        ".pyf",
        ".pxd",
        ".pyx",
        ".rc",
        ".vbs",
        ".sct",
        ".idl",
        ".xsl",
        ".xslt",
        ".xsd",
        ".pc",
        ".tmpl",
        ".template",
        ".inc",
        ".build",
        ".typed",
        ".lock",
        ".exit",
        ".err",
        ".stdout",
        ".stderr",
        ".frozen",
    ]
)
BINARY_EXTRA = frozenset(
    [
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
        ".ttf",
        ".woff",
        ".woff2",
        ".otf",
        ".mo",
        ".a",
        ".so",
    ]
)


def normalize_bytes(raw: bytes, suffix: str) -> tuple[bytes | None, str]:
    """严格按 BOM 识别 UTF-16/32；无标记坏字节只做可审计转义，不猜代码页。"""
    if suffix in BINARY_SUFFIXES | BINARY_EXTRA:
        return None, "binary_suffix"
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        text, method = raw.decode("utf-32"), "utf-32-bom"
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text, method = raw.decode("utf-16"), "utf-16-bom"
    elif b"\0" in raw and suffix in {".log", ".out", ".err", ".exit"}:
        text = raw.decode("utf-8-sig", errors="backslashreplace").replace("\0", r"\x00")
        method = "text-nul-and-invalid-bytes-escaped"
    elif b"\0" in raw:
        return None, "binary_nul"
    else:
        try:
            text, method = raw.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            if suffix not in TEXT_SUFFIXES:
                return None, "binary_unknown"
            text, method = (
                raw.decode("utf-8", errors="backslashreplace"),
                "utf-8-invalid-bytes-escaped",
            )
    return normalized_text(text).encode("utf-8"), method


def normalize(root: Path, backup: Path) -> list[dict[str, object]]:
    """备份 ZIP 中含恢复清单；使用独占创建，绝不覆盖上一轮原件。"""
    root = root.resolve()
    backup = backup.resolve()
    backup.parent.mkdir(parents=True, exist_ok=True)
    changes: list[dict[str, object]] = []
    with zipfile.ZipFile(backup, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for base, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"})
            for name in sorted(names):
                path = Path(base) / name
                if path.resolve() == backup or path.is_symlink():
                    continue
                suffix = path.suffix.lower()
                if suffix in BINARY_SUFFIXES | BINARY_EXTRA or name.startswith(".coverage"):
                    continue
                raw = path.read_bytes()
                new, method = normalize_bytes(raw, suffix)
                if new is None or new == raw:
                    continue
                rel = path.relative_to(root).as_posix()
                archive.writestr(rel, raw)
                record = {
                    "path": rel,
                    "method": method,
                    "before_sha256": hashlib.sha256(raw).hexdigest(),
                    "after_sha256": hashlib.sha256(new).hexdigest(),
                    "before_bytes": len(raw),
                    "after_bytes": len(new),
                }
                changes.append(record)
        archive.writestr(
            "RESTORE-MANIFEST.json", json.dumps(changes, ensure_ascii=False, indent=2) + "\n"
        )
    with zipfile.ZipFile(backup) as archive:
        for change in changes:
            if (
                hashlib.sha256(archive.read(str(change["path"]))).hexdigest()
                != change["before_sha256"]
            ):
                raise ValueError(f"原件备份校验失败：{change['path']}")
        # 完整 ZIP 已关闭并逐件验证，之后才写源文件，避免中断留下不可读备份。
        for change in changes:
            path = root / str(change["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != change["before_sha256"]:
                raise ValueError(f"备份后源文件被再次编辑：{change['path']}")
            converted, _method = normalize_bytes(
                archive.read(str(change["path"])), path.suffix.lower()
            )
            if converted is None:
                raise ValueError(f"转换规则漂移：{change['path']}")
            path.write_bytes(converted)
    return changes


def restore(root: Path, backup: Path) -> int:
    """恢复前校验全部原件与当前版本；有后续编辑时拒绝覆盖。"""
    root = root.resolve()
    with zipfile.ZipFile(backup) as archive:
        records = json.loads(archive.read("RESTORE-MANIFEST.json"))
        for record in records:
            path = (root / record["path"]).resolve()
            if root not in path.parents:
                raise ValueError("恢复清单路径越界")
            if hashlib.sha256(archive.read(record["path"])).hexdigest() != record["before_sha256"]:
                raise ValueError(f"原件哈希不符：{record['path']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["after_sha256"]:
                raise ValueError(f"文件已被再次编辑，拒绝覆盖：{record['path']}")
        for record in records:
            (root / record["path"]).write_bytes(archive.read(record["path"]))
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.restore:
        print(f"已恢复 {restore(args.root, args.backup)} 件")
    else:
        changes = normalize(args.root, args.backup)
        manifest = args.backup.with_suffix(".manifest.json")
        manifest.write_text(
            json.dumps(changes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"已归一 {len(changes)} 件，原件备份：{args.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
