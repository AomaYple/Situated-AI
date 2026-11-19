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
from .model import Assignment, Scalar

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


__all__ = ["ResourceReference", "scan_file", "scan_tree", "script_symbol_references"]


SCRIPT_SYMBOL_CATEGORIES = {
    "script_values": "script_value",
    "scripted_values": "script_value",
    "scripted_triggers": "scripted_trigger",
    "scripted_effects": "scripted_effect",
}
NUMERIC_FIELDS = frozenset(
    {"value", "add", "subtract", "multiply", "divide", "min", "max", "base", "weight", "score"}
)
EXPRESSION_FIELDS = frozenset(
    {
        "value",
        "base",
        "add",
        "subtract",
        "multiply",
        "divide",
        "min",
        "max",
        "if",
        "else_if",
        "else",
        "limit",
        "always",
        "exists",
        "NOT",
        "OR",
        "AND",
        "NOR",
        "NAND",
        "trigger",
        "score",
        "potential",
    }
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_EXPLICIT_REF = re.compile(r"(?:script(?:ed)?_value|scripted_trigger|scripted_effect):([\w$]+)")
_PARAMETER = re.compile(r"\$[A-Za-z_0-9]+\$")


def script_symbol_references(
    item: Assignment | Scalar, names: set[str], parents: tuple[str, ...]
) -> list[tuple[str, str, str, str | None]]:
    """Return symbol, expression, syntax, requested kind; keep unknown explicit calls."""
    result: list[tuple[str, str, str, str | None]] = []
    if isinstance(item, Assignment):
        if item.key in names and parents:
            result.append((item.key, item.full_key, "assignment_key_call", None))
        elif parents and item.key.endswith(("_scripted_trigger", "_scripted_effect")):
            result.append((item.key, item.full_key, "unresolved_call_shaped_key", None))
        value = item.value
        if not isinstance(value, Scalar):
            return result
        expression = value.unquoted
        numeric = item.key in NUMERIC_FIELDS
        requested = SCRIPT_SYMBOL_CATEGORIES.get(
            item.key, item.key if item.key.startswith("scripted_") else None
        )
    else:
        expression = item.unquoted
        numeric = bool(parents and parents[-1] in NUMERIC_FIELDS)
        requested = None
    quoted = (isinstance(item, Scalar) and item.quoted) or (
        isinstance(item, Assignment) and isinstance(item.value, Scalar) and item.value.quoted
    )
    if quoted:
        # A quoted token can be a localization/path/string mention. Preserve
        # identifier-shaped names as observations, but never resolve them as
        # executable calls, including explicit ``scripted_value:`` prefixes.
        field_name = item.key if isinstance(item, Assignment) else (parents[-1] if parents else "")
        symbolish_field = (
            field_name in NUMERIC_FIELDS
            or field_name in EXPRESSION_FIELDS
            or field_name.startswith("scripted_")
            or expression in names
        )
        if symbolish_field and (
            _IDENTIFIER.fullmatch(expression) or _EXPLICIT_REF.fullmatch(expression)
        ):
            return [(expression, expression, "quoted_symbol_observation", requested)]
        return result
    explicit = list(_EXPLICIT_REF.finditer(expression))
    if explicit:
        for match in explicit:
            prefix = match.group(0).split(":")[0]
            kind = "script_value" if "value" in prefix else prefix
            result.append((match.group(1), expression, "explicit_symbol_prefix", kind))
        return result
    if requested in {"scripted_value", "script_value", "scripted_trigger", "scripted_effect"}:
        result.append(
            (
                expression,
                expression,
                "explicit_reference_field",
                "script_value" if "value" in requested else requested,
            )
        )
        return result
    if _PARAMETER.search(expression):
        result.append((expression, expression, "parameterized_reference", requested))
        return result
    words = _IDENTIFIER.findall(expression)
    known = [word for word in words if word in names]
    for word in dict.fromkeys(known):
        syntax = (
            "quoted_symbol_observation"
            if (
                (isinstance(item, Scalar) and item.quoted)
                or (
                    isinstance(item, Assignment)
                    and isinstance(item.value, Scalar)
                    and item.value.quoted
                )
            )
            else "scalar_or_scope_chained_call"
        )
        result.append((word, expression, syntax, "script_value" if numeric else None))
    if (
        not known
        and numeric
        and re.fullmatch(r"[A-Za-z_][\w.:]*", expression)
        and expression not in {"yes", "no"}
    ):
        result.append(
            (
                expression,
                expression,
                "unresolved_numeric_identifier_or_engine_getter",
                "script_value",
            )
        )
    return result


__all__ = ["ResourceReference", "scan_file", "scan_tree", "script_symbol_references"]
