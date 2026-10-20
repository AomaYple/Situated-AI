"""有界研究观测：完整科技集合、可研究集与主动研究状态分别记录。

观测只能显式附加至临时验证副本。GUI 的 IsResearching 仍须实机核对，
获取科技 hook 不提供来源分类，不能把传播或事件授予当作研究完成。
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from .model import Block
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

KEY = re.compile(r"[a-z][a-z0-9_-]*\Z")
TAG = re.compile(r"[A-Z]{3}\Z")
PREFIX = "SITAI RESEARCH;"
ROW = re.compile(
    r"SITAI RESEARCH;(?P<tag>[A-Z]{3});(?P<kind>BEGIN|TECH|END);"
    r"(?P<body>[^\r\n]*)$"
)
REASONS = frozenset({"MONTHLY", "START", "ACQUIRED", "SPREAD"})


def technology_keys(game: Path) -> tuple[str, ...]:
    """从全部科技定义取键；缺文件、解析失败和重复键均拒绝。"""
    return technology_snapshot(game)[0]


def technology_snapshot(game: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    """键与指纹来自同一份原始字节，不将后读版本冒充解析输入。"""
    paths = sorted((game / "common/technology/technologies").glob("*.txt"))
    keys: set[str] = set()
    sources: dict[str, str] = {}
    for path in paths:
        raw = path.read_bytes()
        relative = path.relative_to(game).as_posix()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        parsed = parse_text(raw.decode("utf-8-sig"), relative)
        if parsed.errors:
            raise ValueError(f"科技定义无法解析：{path}")
        for assignment in parsed.root.assignments():
            if (
                not isinstance(assignment.value, Block)
                or not KEY.fullmatch(assignment.key)
                or assignment.key in keys
            ):
                raise ValueError(f"科技键无效或重复：{path}:{assignment.key}")
            keys.add(assignment.key)
    if not keys:
        raise ValueError("完整科技定义集合为空")
    return tuple(sorted(keys)), sources


def _validate(keys: tuple[str, ...], tags: tuple[str, ...]) -> None:
    if not keys or len(keys) != len(set(keys)) or any(not KEY.fullmatch(k) for k in keys):
        raise ValueError("必须提供无重复的完整科技键集合")
    if not tags or len(tags) != len(set(tags)) or any(not TAG.fullmatch(t) for t in tags):
        raise ValueError("观察国标签无效或重复")


def build(keys: tuple[str, ...], *, tags: tuple[str, ...]) -> dict[str, str]:
    """仅生成显式选择国家的 hook，不写研究、策略、变量或世界状态。"""
    _validate(keys, tags)
    effects = []
    for tag in sorted(tags):
        readings = []
        for key in sorted(keys):
            # 以原版国家 trigger 读取分母；不从 GUI 的显示过滤器推断完整资格。
            # 当前研究 getter 单独标注为待证，不能仅凭生成/解析通过提升证据。
            active = f"[GetTechnology('{key}').IsResearching(THIS.GetCountry.Self)]"

            def leaf(
                legal: int, owned: int, *, tag: str = tag, key: str = key, active: str = active
            ) -> str:
                return f'debug_log = "{PREFIX}{tag};TECH;{key};{legal};{owned};{active}"'

            branches = [
                f"if = {{ limit = {{ has_technology_researched = {key} }} {leaf(legal, 1)} }} "
                f"else = {{ {leaf(legal, 0)} }}"
                for legal in (1, 0)
            ]
            readings.append(
                f"if = {{ limit = {{ can_research = {key} }} {branches[0]} }} "
                f"else = {{ {branches[1]} }}"
            )
        effects.append(f"sitai_research_observe_read_{tag} = {{\n" + "\n".join(readings) + "\n}")
    # 同一个读取块由每个原因复用，避免四份完整科技枚举或逐日世界扫描。
    actions: list[str] = []
    for reason, hook in (
        ("MONTHLY", "on_monthly_pulse_country"),
        ("START", "on_research_technology_started"),
        ("ACQUIRED", "on_acquired_technology"),
        ("SPREAD", "on_spreading_technology"),
    ):
        name = f"sitai_research_observe_{reason.lower()}"
        blocks = [
            f"if = {{ limit = {{ c:{tag} ?= this }} "
            f'debug_log = "{PREFIX}{tag};BEGIN;{reason}" '
            f"sitai_research_observe_read_{tag} = yes "
            f'debug_log = "{PREFIX}{tag};END;{reason}" }}'
            for tag in sorted(tags)
        ]
        actions.extend(
            (
                f"{hook} = {{ on_actions = {{ {name} }} }}",
                f"{name} = {{ effect = {{ {' '.join(blocks)} }} }}",
            )
        )
    return {
        "common/scripted_effects/zz_sitai_research_observation.txt": "\n".join(effects) + "\n",
        "common/on_actions/zz_sitai_research_observation.txt": "\n".join(actions) + "\n",
    }


def analyze(text: str, keys: tuple[str, ...], *, tags: tuple[str, ...]) -> dict[str, object]:
    return analyze_lines(text.splitlines(), keys, tags=tags)


def analyze_lines(
    lines: Iterable[str], keys: tuple[str, ...], *, tags: tuple[str, ...]
) -> dict[str, object]:
    """只接受完整同序的观测帧；残缺、重复、未知和不合法布尔值保留失败。"""
    # 复用生成端输入验证，避免解析端接受生成端不会产生的身份。
    _validate(keys, tags)
    expected = set(keys)
    frames: list[dict[str, object]] = []
    errors: list[str] = []
    current: tuple[str, str] | None = None
    start_line = 0
    start_prefix = ""
    values: dict[str, dict[str, bool]] = {}
    frame_invalid = False
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r\n")
        if PREFIX not in line:
            continue
        match = ROW.search(line)
        if match is None:
            errors.append(f"第 {line_number} 行观测格式无效")
            if current is not None:
                frame_invalid = True
            continue
        tag, kind, body = match.group("tag", "kind", "body")
        if tag not in tags:
            errors.append(f"第 {line_number} 行出现未登记国家")
            if current is not None:
                frame_invalid = True
            continue
        if kind == "BEGIN":
            if current is not None:
                errors.append(f"第 {line_number} 行上一帧未结束")
            if body not in REASONS:
                errors.append(f"第 {line_number} 行观测原因无效")
                current = None
                continue
            current, values = (tag, body), {}
            frame_invalid = False
            start_line, start_prefix = line_number, line[: match.start()]
        elif kind == "TECH":
            parts = body.split(";")
            if current is None or current[0] != tag or len(parts) != 4:
                errors.append(f"第 {line_number} 行科技记录不属于活动帧")
                frame_invalid = True
                continue
            key, legal, owned, active = parts
            if key not in expected or key in values:
                errors.append(f"第 {line_number} 行科技键未知或重复")
                frame_invalid = True
                continue
            if (
                legal not in {"0", "1"}
                or owned not in {"0", "1"}
                or active not in {"yes", "no", "0", "1"}
            ):
                errors.append(f"第 {line_number} 行布尔值无效或 getter 不可读")
                frame_invalid = True
                continue
            values[key] = {
                "can_research": legal == "1",
                "researched": owned == "1",
                "researching": active in {"yes", "1"},
            }
        else:
            if current != (tag, body) or set(values) != expected:
                errors.append(f"第 {line_number} 行帧身份或完整科技集合不匹配")
                frame_invalid = True
            else:
                if sum(value["researching"] for value in values.values()) > 1:
                    errors.append(f"第 {line_number} 行存在多个当前研究，getter 或时序待证")
                    frame_invalid = True
                if not frame_invalid:
                    frames.append(
                        {
                            "tag": tag,
                            "reason": body,
                            "technologies": values,
                            "start_line": start_line,
                            "end_line": line_number,
                            "log_prefix": start_prefix,
                        }
                    )
            current, values = None, {}
            frame_invalid = False
    if current is not None:
        errors.append("日志结束时观测帧未完成")
    return {
        "frames": frames,
        "errors": errors,
        "complete": bool(frames) and not errors,
        "technology_count": len(keys),
        "getter_runtime_verified": False,
        "ai_candidate_denominator_complete": False,
        "behavior_quality": "not_evaluated",
        "limits": "can_research 集合不是已证明的 AI 内部排名；取得科技不区分传播、研究完成和事件授予；START 时序和 GUI getter 须另验；日志前缀仅是定位依据，不能冒充游戏日期；hook/快照不证明字段因果。",
    }
