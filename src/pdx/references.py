"""保守的 mod 资源引用扫描。

Victoria 3 的脚本值既可能是完整相对路径，也可能是省略扩展名的资源名。
本模块只识别明确的字段赋值，不把普通业务字符串当成引用；解析失败时保留
来源文件和行号，便于作者回到游戏日志或原版资源树核对。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import config

_REFERENCE_RE = re.compile(
    r"\b(?P<field>icon|sound|music|gfx|texture|mesh|font|asset|layout)\s*=\s*"
    r"(?:\"(?P<quoted>[^\"]+)\"|(?P<bare>[A-Za-z0-9_./\\-]+))"
)
_RESOURCE_SUFFIXES = {
    ".dds",
    ".tga",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".wav",
    ".ogg",
    ".mp3",
    ".bank",
    ".fsb",
    ".flac",
    ".mesh",
    ".asset",
    ".anim",
    ".font",
    ".gui",
    ".layout",
}


@dataclass(frozen=True, slots=True)
class ResourceReference:
    field: str
    value: str
    file: str
    line: int
    resolved: str = ""
    status: str = "unresolved"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _candidate_values(field: str, value: str) -> tuple[str, ...]:
    value = value.replace("\\", "/").lstrip("/")
    if Path(value).suffix:
        return (value,)
    suffixes = {
        "icon": (".dds", ".png", ".tga"),
        "texture": (".dds", ".png", ".tga"),
        "sound": (".wav", ".ogg", ".bank", ".fsb"),
        "music": (".ogg", ".wav", ".bank"),
        "mesh": (".mesh", ".asset"),
        "font": (".font",),
        "asset": (".asset",),
        "layout": (".gui", ".layout"),
        "gfx": (".asset", ".mesh", ".dds"),
    }
    return tuple(value + suffix for suffix in suffixes.get(field, _RESOURCE_SUFFIXES))


def _resolve(value: str, field: str, root: Path) -> Path | None:
    candidates = _candidate_values(field, value)
    roots = (root, config.GAME, config.JOMINI, config.CLAUSEWITZ)
    seen: set[Path] = set()
    for base in roots:
        for rel in candidates:
            path = (base / rel).resolve()
            if path in seen:
                continue
            seen.add(path)
            try:
                if path.is_file():
                    return path
            except OSError:
                continue
    # 对省略扩展名的值只尝试常见资源目录的直接路径；不对每条引用递归
    # 扫描整棵游戏树。大型 Workshop 集合里这一步是最容易造成分钟级退化的热点，
    # 作者若使用深层资源路径应在脚本中写出目录前缀，断链报告会更可靠。
    if "/" not in value.replace("\\", "/"):
        directories = {
            "icon": "gfx",
            "texture": "gfx",
            "sound": "sound",
            "music": "music",
            "font": "fonts",
            "gfx": "gfx",
        }
        directory = directories.get(field)
        if directory:
            for base in roots:
                for rel in candidates:
                    path = (base / directory / rel).resolve()
                    if path.is_file():
                        return path
    return None


def scan_file(
    path: Path, *, root: Path | None = None
) -> tuple[list[ResourceReference], list[ResourceReference]]:
    """扫描一份文本文件，返回 ``(全部引用, 未解析引用)``。"""
    base = root or path.parent
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return [], []
    references: list[ResourceReference] = []
    unresolved: list[ResourceReference] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _REFERENCE_RE.finditer(line):
            field = match.group("field")
            value = (match.group("quoted") or match.group("bare") or "").strip()
            if not value:
                continue
            resolved = _resolve(value, field, base)
            item = ResourceReference(
                field=field,
                value=value,
                file=str(path),
                line=line_no,
                resolved=str(resolved) if resolved else "",
                status="ok" if resolved else "unresolved",
            )
            references.append(item)
            if resolved is None:
                unresolved.append(item)
    return references, unresolved


def scan_tree(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """扫描 mod 文本引用，按文件顺序返回可 JSON 化字典。"""
    references: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    suffixes = {".txt", ".gui", ".asset", ".font", ".layout", ".settings", ".profile"}
    if not root.is_dir():
        return references, unresolved
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            found, missing = scan_file(path, root=root)
            references.extend(item.to_dict() for item in found)
            unresolved.extend(item.to_dict() for item in missing)
    return references, unresolved


__all__ = ["ResourceReference", "scan_file", "scan_tree"]
