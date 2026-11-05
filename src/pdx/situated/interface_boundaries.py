"""Offline, bounded interface investigation; never runtime reader authority.

This contract reuses complete frozen native texts. A failed finite probe only
describes the listed source set; it never establishes engine-wide unsupported
status. Positive neighbors retain their actual kind instead of impersonating
the missing amount getter or candidate writer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, cast

from pdx import config
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

CONTRACT = config.REPO / "research/vanilla-ai/1.15.0/interface-boundaries.json"
TOPICS = frozenset(
    {
        "strata_tax_amounts",
        "qualification_stock",
        "innovation_cap_gap",
        "mobilized_workers",
        "precise_peace_writer",
        "dynamic_pm_writer",
        "direct_trade_route_writer",
        "convoy_loss_amount",
    }
)
_KINDS = frozenset(
    {
        "native_tax_enum",
        "static_tax_coefficient",
        "authority_cost_schema",
        "qualification_growth_formula",
        "native_internal_ai_factor",
        "static_trigger_localization",
        "weekly_innovation_modifier",
        "actual_theater_unit_count",
        "actual_employment_deployment_condition",
        "native_global_peace_tuning",
        "post_peace_hook",
        "war_support_reader_not_peace_writer",
        "static_pm_weight_schema",
        "pm_selection_enum",
        "history_pm_activation",
        "country_good_stance",
        "directed_treaty_article_score",
        "actual_state_blockade",
        "commented_country_raid_example",
    }
)
_ROW_FIELDS = {
    "id",
    "status",
    "question",
    "scope_limit",
    "examined_sources",
    "probes",
    "expected_probe_hits",
    "neighbors",
    "preserves",
    "does_not_prove",
    "remaining_requirement",
}


def _safe_carrier(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("接口边界完整源载体必须是仓库相对路径")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or not value.startswith("research/")
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("接口边界完整源载体越界")
    return value


def load() -> dict[str, Any]:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "sources", "boundaries"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"]
        != "bounded_static_investigation_not_runtime_capability_or_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or not isinstance(data["sources"], dict)
        or not data["sources"]
        or not isinstance(data["boundaries"], list)
    ):
        raise ValueError("接口边界静态调查schema无效")
    for source, row in data["sources"].items():
        if (
            not isinstance(source, str)
            or not source.startswith("common/")
            or set(row) != {"carrier", "storage", "normalized_sha256"}
            or row["storage"] not in {"complete_text", "inputs_json"}
            or not isinstance(row["normalized_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", row["normalized_sha256"])
        ):
            raise ValueError("接口边界完整原版身份无效")
        _safe_carrier(row["carrier"])
    if (
        len(data["boundaries"]) != len(TOPICS)
        or {row.get("id") for row in data["boundaries"]} != TOPICS
    ):
        raise ValueError("接口边界必须保持八个精确未证问题")
    for row in data["boundaries"]:
        if (
            set(row) != _ROW_FIELDS
            or row["status"] != "bounded_unproven"
            or not isinstance(row["examined_sources"], list)
            or not row["examined_sources"]
            or len(set(row["examined_sources"])) != len(row["examined_sources"])
            or not set(row["examined_sources"]) <= data["sources"].keys()
            or not isinstance(row["probes"], list)
            or not row["probes"]
            or not isinstance(row["expected_probe_hits"], list)
            or not isinstance(row["neighbors"], list)
            or not row["neighbors"]
            or any(
                not isinstance(row[key], str) or not row[key]
                for key in (
                    "question",
                    "scope_limit",
                    "preserves",
                    "does_not_prove",
                    "remaining_requirement",
                )
            )
        ):
            raise ValueError("接口边界状态/有限范围/相邻保留责任无效")
        for pattern in row["probes"]:
            if not isinstance(pattern, str) or not re.fullmatch(r"[a-z_0-9|()?:]+", pattern):
                raise ValueError("接口边界只接受有限候选标识符探针")
            re.compile(pattern)
        for neighbor in row["neighbors"]:
            if (
                set(neighbor) != {"source", "kind", "selector", "expected", "meaning"}
                or neighbor["source"] not in row["examined_sources"]
                or neighbor["kind"] not in _KINDS
                or not neighbor["meaning"]
            ):
                raise ValueError("接口边界相邻正证类型无效；不能推成缺失能力")
    return cast("dict[str, Any]", data)


def frozen_inputs() -> dict[str, str]:
    """Read complete existing carriers only; installation is never consulted."""
    data = load()
    carriers: dict[str, dict[str, Any]] = {}
    inputs = {}
    for source, row in data["sources"].items():
        path = config.REPO / _safe_carrier(row["carrier"])
        if row["storage"] == "complete_text":
            text = normalized_text(path.read_text(encoding="utf-8-sig"))
        else:
            if row["carrier"] not in carriers:
                carriers[row["carrier"]] = json.loads(path.read_text(encoding="utf-8"))
            payload = carriers[row["carrier"]]
            if not isinstance(payload.get("inputs"), dict):
                raise ValueError("接口边界载体缺少完整inputs")
            text = payload["inputs"].get(source)
        if not isinstance(text, str):
            raise ValueError(f"接口边界载体缺少完整原版：{source}")
        inputs[source] = text
    return inputs


def _signature(value: Assignment | Block | Scalar | None) -> Any:
    if value is None:
        return None
    if isinstance(value, Assignment):
        return [value.key, value.op, _signature(value.value)]
    if isinstance(value, Scalar):
        return value.unquoted
    return [_signature(item) for item in value.items]


def _selected(root: Block, selector: list[list[Any]]) -> Assignment:
    current = root
    selected = None
    for key, ordinal in selector:
        rows = current.all(key)
        if type(ordinal) is not int or ordinal < 0 or ordinal >= len(rows):
            raise ValueError("接口边界相邻原版AST路径漂移")
        selected = rows[ordinal]
        if isinstance(selected.value, Block):
            current = selected.value
    if selected is None:
        raise ValueError("接口边界不能选择空原版AST路径")
    return selected


def _probe_hits(
    row: Mapping[str, Any], inputs: Mapping[str, str], roots: Mapping[str, Block]
) -> list[dict[str, Any]]:
    patterns = tuple(re.compile(pattern) for pattern in row["probes"])
    hits = []
    for source in sorted(row["examined_sources"]):
        if source not in roots:
            continue

        def walk(block: Block, path: tuple[str, ...] = (), source: str = source) -> None:
            for item in block.assignments():
                if any(pattern.fullmatch(item.key) for pattern in patterns):
                    hits.append(
                        {
                            "source": source,
                            "line": item.line,
                            "path": [*path, item.key],
                            "kind": "presentation_mapping"
                            if "/trigger_localization/" in source
                            else "active_assignment",
                        }
                    )
                if isinstance(item.value, Block):
                    walk(item.value, (*path, item.key))

        walk(roots[source])
        for number, line in enumerate(inputs[source].splitlines(), 1):
            if line.lstrip().startswith("#") and any(
                any(pattern.fullmatch(token) for pattern in patterns)
                for token in re.findall(r"[a-z][a-z0-9_]*", line)
            ):
                hits.append({"source": source, "line": number, "path": [], "kind": "comment_only"})
    return sorted(hits, key=lambda value: (value["source"], value["line"], value["kind"]))


@dataclass(frozen=True, slots=True)
class InterfaceBoundary:
    id: str
    status: Literal["bounded_unproven"]
    question: str
    scope_limit: str
    inspected_sources: tuple[str, ...]
    neighbor_kinds: tuple[str, ...]
    preserves: str
    does_not_prove: str
    remaining_requirement: str
    creates_reader: Literal[False] = False
    creates_writer: Literal[False] = False


def verify_inputs(inputs: Mapping[str, str]) -> tuple[InterfaceBoundary, ...]:
    data = load()
    roots = {}
    for source, identity in data["sources"].items():
        text = inputs.get(source)
        if (
            not isinstance(text, str)
            or hashlib.sha256(text.encode()).hexdigest() != identity["normalized_sha256"]
        ):
            raise ValueError(f"接口边界完整原版来源漂移：{source}")
        if source.endswith(".txt"):
            parsed = parse_text(text)
            if parsed.errors:
                raise ValueError(f"接口边界完整原版解析失败：{source}")
            roots[source] = parsed.root
    findings = []
    for row in data["boundaries"]:
        for neighbor in row["neighbors"]:
            source = neighbor["source"]
            selector = neighbor["selector"]
            if isinstance(selector, list):
                if (
                    source not in roots
                    or _signature(_selected(roots[source], selector)) != neighbor["expected"]
                ):
                    raise ValueError(f"接口边界相邻原版AST漂移：{row['id']}/{neighbor['kind']}")
            elif isinstance(selector, dict) and set(selector) == {"start_line", "end_line"}:
                lines = inputs[source].splitlines()[
                    selector["start_line"] - 1 : selector["end_line"]
                ]
                if "\n".join(lines) != neighbor["expected"]:
                    raise ValueError(f"接口边界原文/注释上下文漂移：{row['id']}")
                if neighbor["kind"] == "commented_country_raid_example" and any(
                    line.strip() and not line.lstrip().startswith("#") for line in lines
                ):
                    raise ValueError("被注释的遭袭候选不能冒称现行调用")
            else:
                raise ValueError("接口边界相邻原版定位无效")
        if _probe_hits(row, inputs, roots) != row["expected_probe_hits"]:
            raise ValueError(f"接口边界有限查询集合变化；须复核而非沿用未证结论：{row['id']}")
        findings.append(
            InterfaceBoundary(
                row["id"],
                "bounded_unproven",
                row["question"],
                row["scope_limit"],
                tuple(row["examined_sources"]),
                tuple(neighbor["kind"] for neighbor in row["neighbors"]),
                row["preserves"],
                row["does_not_prove"],
                row["remaining_requirement"],
            )
        )
    return tuple(findings)
