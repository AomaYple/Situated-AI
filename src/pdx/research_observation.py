"""有界研究观测：完整科技集合、可研究集与主动研究状态分别记录。

观测只能显式附加至临时验证副本。研究状态使用原版国家 trigger，
不调用 GUI getter；获取科技 hook 不提供来源分类，不能把传播或事件授予当作研究完成。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from .keyed_observation import (
    FrameSchema,
    boolean_reading,
    definition_snapshot,
    missing_country_errors,
    parse_frames,
    validate,
)
from .localization import parse_loc_entries_with_lines
from .localization_languages import DEFAULT_LANGUAGE_BY_HEADER

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

PREFIX = "SITAI RESEARCH;"
REASONS = frozenset({"MONTHLY", "START", "ACQUIRED", "SPREAD"})
SCHEMA = FrameSchema(
    prefix=PREFIX,
    row_kind="TECH",
    entity="科技",
    values_key="technologies",
    fields=("can_research", "researched", "researching"),
    reasons=REASONS,
    single_active="researching",
    active_description="研究",
    legacy_unknown_field="researching",
)


def technology_keys(game: Path) -> tuple[str, ...]:
    """从全部科技定义取键；缺文件、解析失败和重复键均拒绝。"""
    return technology_snapshot(game)[0]


def technology_snapshot(game: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    """键与指纹来自同一份原始字节，不将后读版本冒充解析输入。"""
    return definition_snapshot(game, "common/technology/technologies", entity="科技")


def _validate_labels(keys: tuple[str, ...], labels: Mapping[str, str]) -> None:
    if (
        set(labels) != set(keys)
        or len(set(labels.values())) != len(keys)
        or any(not value or any(c in value for c in "\r\n$[]\\#") for value in labels.values())
    ):
        raise ValueError("科技名称必须完整、无歧义且为可直接比较的静态文本")


def label_snapshot(
    game: Path, keys: tuple[str, ...], *, language: str
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str | int]]]:
    """复用本地化解析器；遍历该语言全部文件，拒绝缺项和覆盖歧义。"""
    selected = DEFAULT_LANGUAGE_BY_HEADER.get(language)
    if selected is None:
        raise ValueError(f"未登记研究目标语言：{language}")
    wanted = set(keys)
    labels: dict[str, str] = {}
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    sources: dict[str, str] = {}
    origins: dict[str, dict[str, str | int]] = {}
    for path in sorted((game / "localization" / selected.directory).rglob("*.yml")):
        raw = path.read_bytes()
        relative = path.relative_to(game).as_posix()
        sources[relative] = hashlib.sha256(raw).hexdigest()
        header, entries = parse_loc_entries_with_lines(raw.decode("utf-8-sig"))
        if header != language:
            raise ValueError(f"研究名称来源语言不符：{relative}:{header}")
        for key, value, line in entries:
            if key in values:
                duplicates.add(key)
            values[key] = value
            if key in wanted:
                origins[key] = {"source": relative, "line": line}

    def resolve(key: str, visiting: tuple[str, ...] = ()) -> str:
        if key in visiting or len(visiting) >= 32 or key not in values or key in duplicates:
            raise ValueError(f"科技名称或别名缺失、重复、循环或过深：{key}")
        return re.sub(
            r"\$([A-Za-z0-9_.-]+)\$", lambda m: resolve(m[1], (*visiting, key)), values[key]
        )

    labels = {key: resolve(key) for key in keys}
    _validate_labels(keys, labels)
    return labels, sources, origins


def build(
    keys: tuple[str, ...], *, tags: tuple[str, ...], with_targets: bool = False
) -> dict[str, str]:
    """仅生成显式选择国家的 hook，不写研究、策略、变量或世界状态。"""
    validate(keys, tags, entity="科技")
    effects = []
    for tag in sorted(tags):
        readings = [
            boolean_reading(
                f"{PREFIX}{tag};TECH;{key}",
                (
                    f"can_research = {key}",
                    f"has_technology_researched = {key}",
                    f"is_researching_technology = {key}",
                ),
            )
            for key in sorted(keys)
        ]
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
        target = (
            "[SCOPE.sTechnology('technology').GetNameNoFormatting]"
            if with_targets and reason != "MONTHLY"
            else None
        )
        blocks = [
            f"if = {{ limit = {{ c:{tag} ?= this }} "
            f'debug_log = "{PREFIX}{tag};BEGIN;{reason}" '
            + (f'debug_log = "{PREFIX}{tag};TARGET;{target}" ' if target else "")
            + f"sitai_research_observe_read_{tag} = yes "
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
    lines: Iterable[str],
    keys: tuple[str, ...],
    *,
    tags: tuple[str, ...],
    hook_labels: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """只接受完整同序的观测帧；残缺、重复、未知和不合法布尔值保留失败。"""
    schema = SCHEMA
    if hook_labels is not None:
        _validate_labels(keys, hook_labels)
        schema = replace(
            SCHEMA,
            target_reasons=REASONS - {"MONTHLY"},
            target_labels={label: key for key, label in hook_labels.items()},
        )
    frames, errors = parse_frames(lines, keys, tags=tags, schema=schema)
    if hook_labels is not None:
        valid_frames = []
        for frame in frames:
            if (
                frame["reason"] == "START"
                and frame["technologies"][frame["target"]]["researching"] is not True
            ):
                errors.append(f"第 {frame['start_line']} 行 START 目标与原生主动研究不一致或不可读")
            else:
                valid_frames.append(frame)
        frames = valid_frames
    errors.extend(missing_country_errors(frames, tags))
    return {
        "frames": frames,
        "errors": errors,
        "complete": bool(frames) and not errors,
        "technology_count": len(keys),
        "getter_runtime_verified": False,
        "ai_candidate_denominator_complete": False,
        "behavior_quality": "not_evaluated",
        "limits": "can_research 集合不是已证明的 AI 内部排名；取得科技不区分传播、研究完成和事件授予；原生研究 trigger 的运行期有效性和 START 时序须另验，历史 unknown 保持未知；日志前缀仅是定位依据，不能冒充游戏日期；hook/快照不证明字段因果。",
    }
