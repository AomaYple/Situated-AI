"""只读提取 Victoria 3 文本存档；大型区段只扫描边界，不构建全存档 AST。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SPACE = re.compile(rb"(?:\s+|#[^\r\n]*)*")
_ASSIGN = re.compile(rb'([^\s{}=#"]+)\s*=\s*("(?:\\.|[^"\\])*"|\{|[^\s{}#"]+)')
_STRUCTURE = re.compile(rb'"(?:\\.|[^"\\])*"|#[^\r\n]*|[{}"]')
_RELATED = {
    "technology": "technology",
    "ai": "ai",
    "interest_groups": "interest_groups",
    "ai_regional_objective_manager": "regional_objectives",
    "states": "states",
}
_AI_FIELDS = {
    "enabled",
    "ai_strategy",
    "cached_ai_weights",
    "ai_memories",
    "strategic_region_stances",
    "potential_money_spending",
    "potential_building_constructions",
    "potential_private_investment_building_constructions",
    "spending_variables",
    "num_failed_money_spending_attempts",
    "num_failed_autonomous_investments",
}


def _end(data: bytes, opening: int, limit: int) -> int:
    depth = 0
    for match in _STRUCTURE.finditer(data, opening, limit):
        token = match[0]
        if token == b'"':
            raise ValueError("存档包含未闭合字符串")
        if token == b"{":
            depth += 1
        elif token == b"}":
            depth -= 1
            if depth == 0:
                return match.end()
    raise ValueError("存档尚未写完或花括号未闭合")


def _members(data: bytes, start: int, end: int) -> Iterator[tuple[str, int, int, bool]]:
    while start < end:
        whitespace = _SPACE.match(data, start, end)
        assert whitespace is not None
        start = whitespace.end()
        if start == end:
            return
        match = _ASSIGN.match(data, start, end)
        if match is None:
            raise ValueError(f"不支持的文本存档结构，字节偏移 {start}")
        opening = match.start(2)
        block = match[2] == b"{"
        finish = _end(data, opening, end) if block else match.end(2)
        yield match[1].decode("utf-8"), opening, finish, block
        start = finish


def _scalar(data: bytes, start: int, end: int) -> str:
    value = data[start:end].decode("utf-8")
    return value[1:-1] if value.startswith('"') else value


def _plain(block: Block) -> Any:
    assignments = list(block.assignments())
    if not assignments:
        values: list[Any] = []
        for item in block.items:
            if isinstance(item, Scalar):
                values.append(item.unquoted)
            elif isinstance(item, Block):
                values.append(_plain(item))
            else:
                value = item.value
                values.append(
                    {
                        item.key: _plain(value)
                        if isinstance(value, Block)
                        else value.unquoted
                        if isinstance(value, Scalar)
                        else None
                    }
                )
        return values
    result: dict[str, Any] = {}
    for assignment in assignments:
        value = assignment.value
        converted = (
            _plain(value)
            if isinstance(value, Block)
            else value.unquoted
            if isinstance(value, Scalar)
            else None
        )
        if assignment.key in result:
            raise ValueError(f"摘要字段出现未声明重复键：{assignment.key}")
        result[assignment.key] = converted
    return result


def _value(data: bytes, start: int, end: int, block: bool) -> Any:
    if not block:
        return _scalar(data, start, end)
    parsed = parse_text("value=" + data[start:end].decode("utf-8"))
    if parsed.errors:
        raise ValueError(f"存档区段解析失败：{parsed.errors[:3]}")
    assignment = parsed.root.first("value")
    assert assignment is not None
    assert isinstance(assignment.value, Block)
    return _plain(assignment.value)


def _fields(data: bytes, start: int, end: int, allowed: set[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    repeated = {"ai_strategy"}
    for key, a, b, block in _members(data, start + 1, end - 1):
        if allowed is not None and key not in allowed:
            continue
        # 过大的候选缓存保留明确截断标记；原始存档归档可供进一步深挖。
        value = {"omitted_bytes": b - a} if b - a > 512 * 1024 else _value(data, a, b, block)
        if key in repeated:
            result.setdefault(key, []).append(value)
        elif key not in result:
            result[key] = value
        else:
            raise ValueError(f"存档重复字段：{key}")
    return result


def _records(data: bytes, span: tuple[int, int]) -> Iterator[tuple[str, int, int]]:
    for key, start, end, block in _members(data, span[0] + 1, span[1] - 1):
        if key == "database" and block:
            for identifier, a, b, is_block in _members(data, start + 1, end - 1):
                if is_block:
                    yield identifier, a, b
            return


def read_save(path: Path, *, definitions: tuple[str, ...] = ()) -> dict[str, Any]:
    """读取完整文本存档。数字保持原始字面量，计数器不解释为存续对象数。"""
    data = path.read_bytes()
    if not data.startswith(b"SAV") or b"\n" not in data[:128]:
        raise ValueError("只支持当前引擎输出的完整 SAV 文本存档；压缩/二进制格式未支持")
    root_start = data.index(b"\n") + 1
    top = {key: (a, b, block) for key, a, b, block in _members(data, root_start, len(data))}
    if "meta_data" not in top or "country_manager" not in top:
        raise ValueError("存档缺少 meta_data 或 country_manager")
    a, b, _ = top["meta_data"]
    metadata = _fields(data, a, b, {"version", "game_date", "mods", "game_rules"})
    if not metadata.get("version") or not metadata.get("game_date"):
        raise ValueError("存档版本或游戏日期缺失")
    for key in ("playthrough_id", "date", "speed", "seed"):
        if key in top:
            a, b, block = top[key]
            metadata[key] = _value(data, a, b, block)
    if "counters" in top:
        a, b, _ = top["counters"]
        metadata["internal_counters"] = _fields(data, a, b)
    countries: dict[str, dict[str, Any]] = {}
    databases: dict[str, int] = {}
    section_spans = {key: (a, b) for key, (a, b, block) in top.items() if block}
    records = list(_records(data, section_spans["country_manager"]))
    databases["country_manager"] = len(records)
    for identifier, a, b in records:
        fields = list(_members(data, a + 1, b - 1))
        tag = next(
            (
                _scalar(data, x, y)
                for key, x, y, block in fields
                if key == "definition" and not block
            ),
            None,
        )
        if tag is None or (definitions and tag not in definitions):
            continue
        country: dict[str, Any] = {"definition": tag}
        for key, x, y, block in fields:
            if not block:
                country[key] = _scalar(data, x, y)
            elif key == "budget":
                budget = _fields(
                    data,
                    x,
                    y,
                    {
                        "money",
                        "principal",
                        "credit",
                        "investment_pool",
                        "weekly_income",
                        "weekly_expenses",
                        "base_wage",
                        "average_productivity",
                    },
                )
                for k, u, v, is_block in _members(data, x + 1, y - 1):
                    if k == "balance_trend" and is_block:
                        budget[k] = _fields(data, u, v, {"current"})
                country[key] = budget
            elif key == "variables":
                for k, u, v, is_block in _members(data, x + 1, y - 1):
                    if k == "data" and is_block:
                        raw = _value(data, u, v, True)
                        if isinstance(raw, list):
                            country["variables"] = [
                                item
                                for item in raw
                                if isinstance(item, dict)
                                and str(item.get("flag", "")).startswith("sitai_")
                            ]
            elif key in {"construction_queue", "pop_statistics"}:
                country[key] = _value(data, x, y, True)
        countries[identifier] = country
    for section, span in section_spans.items():
        if section == "country_manager":
            continue
        count = 0
        for identifier, a, b in _records(data, span):
            count += 1
            if section not in {*_RELATED, "laws"}:
                continue
            fields = list(_members(data, a + 1, b - 1))
            owner = next(
                (
                    _scalar(data, u, v)
                    for key, u, v, block in fields
                    if key == "country" and not block
                ),
                None,
            )
            if owner not in countries:
                continue
            if section == "laws":
                law = _fields(data, a, b, {"law", "active"})
                if law.get("active") == "yes":
                    countries[owner].setdefault("active_laws", []).append(law["law"])
            elif section == "ai":
                countries[owner]["ai"] = _fields(data, a, b, _AI_FIELDS)
            elif section == "technology":
                countries[owner]["technology"] = _fields(
                    data,
                    a,
                    b,
                    {
                        "research_technology",
                        "research_queue",
                        "acquired_technologies",
                        "progressed_technologies",
                    },
                )
            else:
                allowed = {
                    "definition",
                    "clout",
                    "political_strength",
                    "approval",
                    "region",
                    "type",
                    "stance",
                    "status",
                    "start_date",
                    "conclusion_date",
                    "infrastructure",
                    "infrastructure_usage",
                }
                value = {"id": identifier, **_fields(data, a, b, allowed)}
                countries[owner].setdefault(_RELATED[section], []).append(value)
        if count or section in {"war_manager", "diplomatic_plays", "ai"}:
            databases[section] = count
    return {
        "schema_version": 1,
        "evidence": "snapshot",
        "metadata": metadata,
        "countries": countries,
        "databases": databases,
    }
