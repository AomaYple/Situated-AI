"""地图配置结构和不透明二进制的可核对元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .input_contracts import is_contract_path
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from .input_contracts import ParseStatus
    from .model import ParsedFile

_BINARY = frozenset({"map_nodes", "spline_network"})
_SUFFIX_FORMAT = {
    ".map": "map_configuration",
    ".heightmap": "heightmap_configuration",
    ".terrain": "terrain_configuration",
    ".vertical_borders": "vertical_border_configuration",
    ".splnet": "spline_network",
}
_ASSET_FIELDS = {
    "map_configuration": frozenset({"provinces", "topology", "rivers", "adjacencies"}),
    "heightmap_configuration": frozenset({"heightmap_file", "indirection_file"}),
}
Diagnostic = dict[str, str | int]


@dataclass(frozen=True, slots=True)
class MapStructure:
    format: str
    scope: str
    status: ParseStatus
    diagnostics: tuple[Diagnostic, ...]
    metadata: dict[str, object]


def map_structure_format(path: str) -> str | None:
    """按安装相对路径选择地图结构入口。"""
    canonical = path.casefold()
    suffix = PurePosixPath(canonical).suffix
    if canonical == "game/map_data/nodes.dat":
        return "map_nodes"
    if suffix in _SUFFIX_FORMAT:
        return _SUFFIX_FORMAT[suffix]
    if suffix != ".txt":
        return None
    if canonical.startswith("game/map_data/"):
        return "map_geography"
    parts = canonical.split("/")
    game_parts = parts[3:] if parts[:2] == ["game", "dlc"] else parts[1:]
    if parts[0] == "game" and game_parts[:3] == ["gfx", "map", "spline_network"]:
        return "spline_configuration"
    return None


def _binary_structure(format_name: str, raw: bytes) -> MapStructure:
    diagnostics: tuple[Diagnostic, ...] = ({"code": "map_binary_schema_unknown"},)
    if not raw:
        diagnostics += ({"code": "map_binary_empty", "offset": 0},)
    return MapStructure(
        format_name,
        "binary_observations",
        "not_attempted",
        diagnostics,
        {
            "byte_size": len(raw),
            "observed_prefix_hex": raw[:8].hex(),
            "payload_status": "unknown",
        },
    )


def _map_text_structure(format_name: str, parsed: ParsedFile) -> MapStructure:
    assignments: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    diagnostics: list[Diagnostic] = [
        {"code": item["kind"], "line": item["line"], "column": item["column"]}
        for item in parsed.diagnostics
    ]
    asset_fields = _ASSET_FIELDS.get(format_name, frozenset())
    for assignment in parsed.root.assignments():
        value = assignment.value
        row: dict[str, object] = {"key": assignment.full_key, "line": assignment.line}
        if isinstance(value, Block):
            row["kind"] = "block"
            row["item_count"] = len(value.items)
            row["field_names"] = list(dict.fromkeys(value.keys()))
        elif isinstance(value, Scalar):
            row["kind"] = "scalar"
            if assignment.op == "=" and assignment.key in asset_fields:
                target = value.unquoted.replace("\\", "/")
                if is_contract_path(target) and target == target.strip():
                    references.append(
                        {"field": assignment.key, "line": value.line, "target": target}
                    )
                else:
                    diagnostics.append({"code": "map_invalid_asset_path", "line": value.line})
        else:
            row["kind"] = "missing"
        assignments.append(row)

    if parsed.errors and not parsed.diagnostics:
        diagnostics.append({"code": "map_pdx_syntax_error"})
    if parsed.unconsumed_tokens and not parsed.diagnostics:
        _, _, line, column = parsed.unconsumed_tokens[0]
        diagnostics.append({"code": "map_pdx_unconsumed", "line": line, "column": column})
    if not assignments or len(parsed.root.items) != len(assignments):
        diagnostics.append({"code": "map_expected_top_level_assignments", "line": 1})
    return MapStructure(
        format_name,
        "pdx_map_configuration",
        "partial" if diagnostics else parsed.parse_status,
        tuple(diagnostics),
        {
            "max_depth": parsed.max_depth,
            "assignments": assignments,
            "asset_references": references,
        },
    )


def read_map_structure(
    path: str, raw: bytes, *, parsed: ParsedFile | None = None
) -> MapStructure | None:
    """返回地图文本结构或字节观察，路径只作为格式选择和诊断来源。"""
    format_name = map_structure_format(path)
    if format_name is None:
        return None
    if format_name in _BINARY:
        return _binary_structure(format_name, raw)
    if parsed is None or parsed.decoding_error is not None:
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            # utf-8-sig 将跳过 BOM 后的字节串交给 UTF-8 解码器。
            offset = error.start + (3 if raw.startswith(b"\xef\xbb\xbf") else 0)
            return MapStructure(
                format_name,
                "pdx_map_configuration",
                "failed",
                ({"code": "map_decode_failed", "offset": offset},),
                {},
            )
        parsed = parse_text(decoded, path)
    if b"\0" in raw:
        return MapStructure(
            format_name,
            "pdx_map_configuration",
            "failed",
            ({"code": "map_text_contains_nul", "offset": raw.index(b"\0")},),
            {},
        )
    return _map_text_structure(format_name, parsed)
