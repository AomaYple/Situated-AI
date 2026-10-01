"""确定性游戏 ZIP：仓库无 BOM，交付脚本与本地化带 BOM。"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pdx import modgen
from pdx.textio import GAME_SUFFIXES, text_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping


def payloads(files: Mapping[str, str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    portable_names: set[str] = set()
    for name, text in sorted(files.items()):
        if name.casefold() == "distribution-manifest.json":
            raise ValueError("交付清单文件名为保留名称")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
            raise ValueError(f"非法交付路径：{name!r}")
        if path.as_posix() != name:
            raise ValueError(f"交付路径必须规范化：{name!r}")
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if any(
            part.rstrip(" .") != part
            or part.split(".")[0].upper() in reserved
            or any(c in part for c in '<>"|?*\0')
            for part in path.parts
        ):
            raise ValueError(f"交付路径不兼容 Windows：{name!r}")
        if name.casefold() in portable_names:
            raise ValueError(f"交付路径大小写冲突：{name!r}")
        portable_names.add(name.casefold())
        result[name] = text_bytes(text, game=path.suffix.lower() in GAME_SUFFIXES)
    return result


def write_zip(files: Mapping[str, str], destination: Path) -> Path:
    """先完成并核验临时 ZIP，再原子替换目标；不修改仓库产物。"""
    data = payloads(files)
    manifest = {
        "schema": 1,
        "encoding": "game .txt/.yml: UTF-8 BOM + LF; other text: UTF-8 + LF",
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()},
    }
    data["DISTRIBUTION-MANIFEST.json"] = text_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for name, raw in sorted(data.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        with zipfile.ZipFile(temporary) as archive:
            broken = archive.testzip()
            if broken:
                raise ValueError(f"交付 ZIP 校验失败：{broken}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def package(destination: Path) -> Path:
    built = modgen.build_all(modgen.load_all())
    issues = modgen.check(built)
    if issues:
        raise ValueError("生成物不一致，拒绝打包：\n" + "\n".join(issues))
    return write_zip(built.files, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
