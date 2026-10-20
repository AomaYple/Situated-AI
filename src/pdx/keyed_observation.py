"""研究与法律仪器共用的完整键集、布尔读取和日志帧合同。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING, Any

from .model import Block
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

KEY = re.compile(r"[a-z][a-z0-9_-]*\Z")
TAG = re.compile(r"[A-Z]{3}\Z")


def definition_snapshot(
    game: Path, directory: str, *, entity: str
) -> tuple[tuple[str, ...], dict[str, str]]:
    """定义与 SHA 来自同次原始字节读取，拒绝漏解析和重复键。"""
    keys: set[str] = set()
    sources: dict[str, str] = {}
    for path in sorted((game / directory).glob("*.txt")):
        raw = path.read_bytes()
        relative = path.relative_to(game).as_posix()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        parsed = parse_text(raw.decode("utf-8-sig"), relative)
        if parsed.errors:
            raise ValueError(f"{entity}定义无法解析：{path}")
        for assignment in parsed.root.assignments():
            if (
                not isinstance(assignment.value, Block)
                or not KEY.fullmatch(assignment.key)
                or assignment.key in keys
            ):
                raise ValueError(f"{entity}键无效或重复：{path}:{assignment.key}")
            keys.add(assignment.key)
    if not keys:
        raise ValueError(f"完整{entity}定义集合为空")
    return tuple(sorted(keys)), sources


def validate(keys: tuple[str, ...], tags: tuple[str, ...], *, entity: str) -> None:
    if not keys or len(keys) != len(set(keys)) or any(not KEY.fullmatch(k) for k in keys):
        raise ValueError(f"必须提供无重复的完整{entity}键集合")
    if not tags or len(tags) != len(set(tags)) or any(not TAG.fullmatch(t) for t in tags):
        raise ValueError("观察国标签无效或重复")


def boolean_reading(row: str, predicates: tuple[str, ...]) -> str:
    """每个原生条件独立求值；输出次序与条件次序一致，无状态写入。"""
    branches = [
        f'debug_log = "{row};' + ";".join(flags) + '"'
        for flags in product(("1", "0"), repeat=len(predicates))
    ]
    for predicate in reversed(predicates):
        branches = [
            f"if = {{ limit = {{ {predicate} }} {branches[index]} }} "
            f"else = {{ {branches[index + 1]} }}"
            for index in range(0, len(branches), 2)
        ]
    return branches[0]


@dataclass(frozen=True)
class FrameSchema:
    prefix: str
    row_kind: str
    entity: str
    values_key: str
    fields: tuple[str, ...]
    reasons: frozenset[str]
    single_active: str
    active_description: str = ""
    legacy_unknown_field: str | None = None
    target_reasons: frozenset[str] = frozenset()
    target_labels: Mapping[str, str] | None = None


def missing_country_errors(frames: Iterable[Mapping[str, Any]], tags: tuple[str, ...]) -> list[str]:
    """国家完全无输出也属于观测缺失，不能被其它国家的完整帧掩盖。"""
    observed = {frame["tag"] for frame in frames}
    return [f"观察国 {tag} 未取得有效完整帧" for tag in tags if tag not in observed]


def parse_frames(
    lines: Iterable[str], keys: tuple[str, ...], *, tags: tuple[str, ...], schema: FrameSchema
) -> tuple[list[dict[str, Any]], list[str]]:
    """保留完整帧及原始定位；坏帧失效后只接收下一独立完整帧。"""
    validate(keys, tags, entity=schema.entity)
    expected = set(keys)
    allowed_flags = tuple(
        frozenset({"0", "1", "yes", "no", "unknown"})
        if field == schema.legacy_unknown_field
        else frozenset({"0", "1"})
        for field in schema.fields
    )
    target_kind = "|TARGET" if schema.target_reasons else ""
    row_pattern = re.compile(
        re.escape(schema.prefix)
        + rf"(?P<tag>[A-Z]{{3}});(?P<kind>BEGIN|{schema.row_kind}|END{target_kind});"
        + r"(?P<body>[^\r\n]*)$"
    )
    frames: list[dict[str, Any]] = []
    errors: list[str] = []
    current: tuple[str, str] | None = None
    start_line = 0
    start_prefix = ""
    values: dict[str, dict[str, bool | None]] = {}
    targets: list[str] = []
    target_labels: list[str] = []
    invalid = False
    for number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r\n")
        if schema.prefix not in line:
            continue
        match = row_pattern.search(line)
        if match is None:
            errors.append(f"第 {number} 行观测格式无效")
            if current is not None:
                invalid = True
            continue
        tag, kind, body = match.group("tag", "kind", "body")
        if tag not in tags:
            errors.append(f"第 {number} 行出现未登记国家")
            if current is not None:
                invalid = True
            continue
        if kind == "BEGIN":
            if current is not None:
                errors.append(f"第 {number} 行上一帧未结束")
            if body not in schema.reasons:
                errors.append(f"第 {number} 行观测原因无效")
                current = None
                continue
            current, values, targets = (tag, body), {}, []
            target_labels = []
            invalid = False
            start_line, start_prefix = number, line[: match.start()]
        elif kind == schema.row_kind:
            parts = body.split(";")
            if current is None or current[0] != tag or len(parts) != 1 + len(schema.fields):
                errors.append(f"第 {number} 行{schema.entity}记录不属于活动帧")
                invalid = True
                continue
            key, *flags = parts
            if key not in expected or key in values:
                errors.append(f"第 {number} 行{schema.entity}键未知或重复")
                invalid = True
                continue
            reading: dict[str, bool | None] = {}
            for field, flag, allowed in zip(schema.fields, flags, allowed_flags, strict=True):
                if flag not in allowed:
                    errors.append(f"第 {number} 行布尔值无效或 getter 不可读")
                    invalid = True
                    break
                reading[field] = None if flag == "unknown" else flag in {"1", "yes"}
            else:
                values[key] = reading
        elif kind == "TARGET":
            target = body if schema.target_labels is None else schema.target_labels.get(body)
            if current is None or current[0] != tag or target not in expected:
                errors.append(f"第 {number} 行目标未知或不属于活动帧")
                invalid = True
            targets.append(target or "")
            target_labels.append(body)
        else:
            if current != (tag, body) or set(values) != expected:
                errors.append(f"第 {number} 行帧身份或完整{schema.entity}集合不匹配")
                invalid = True
            else:
                if sum(value[schema.single_active] is True for value in values.values()) > 1:
                    description = schema.active_description or schema.entity
                    errors.append(f"第 {number} 行存在多个当前{description}，getter 或时序待证")
                    invalid = True
                expected_targets = 1 if body in schema.target_reasons else 0
                if len(targets) != expected_targets:
                    errors.append(f"第 {number} 行目标缺失、重复或原因不匹配")
                    invalid = True
                if not invalid:
                    frame: dict[str, Any] = {
                        "tag": tag,
                        "reason": body,
                        schema.values_key: values,
                        "start_line": start_line,
                        "end_line": number,
                        "log_prefix": start_prefix,
                    }
                    if schema.target_reasons:
                        frame["target"] = targets[0] if targets else None
                        if schema.target_labels is not None:
                            frame["target_label"] = target_labels[0] if targets else None
                    frames.append(frame)
            current, values, targets = None, {}, []
            invalid = False
    if current is not None:
        errors.append("日志结束时观测帧未完成")
    return frames, errors
