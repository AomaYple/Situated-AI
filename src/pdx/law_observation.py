"""有界法律状态观测；法律可用性、现行法和自主立法分别取证。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .keyed_observation import (
    FrameSchema,
    boolean_reading,
    definition_snapshot,
    missing_country_errors,
    parse_frames,
    validate,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

PREFIX = "SITAI LAW;"
REASONS = frozenset({"MONTHLY", "START", "PASS", "FAIL", "ENDED", "ACTIVATED"})
SCHEMA = FrameSchema(
    prefix=PREFIX,
    row_kind="LAW",
    entity="法律",
    values_key="laws",
    fields=("object_present", "availability_trigger", "active", "enacting"),
    reasons=REASONS,
    single_active="enacting",
    target_reasons=REASONS - {"MONTHLY"},
)


def law_snapshot(game: Path) -> tuple[tuple[str, ...], dict[str, str]]:
    return definition_snapshot(game, "common/laws", entity="法律")


def _target(keys: tuple[str, ...], tag: str, *, activated: bool) -> str:
    link = "this.type" if activated else "currently_enacting_law.type"
    branches = [
        f"{'if' if index == 0 else 'else_if'} = {{ limit = {{ {link} ?= law_type:{key} }} "
        f'debug_log = "{PREFIX}{tag};TARGET;{key}" }}'
        for index, key in enumerate(sorted(keys))
    ]
    branches.append(f'else = {{ debug_log = "{PREFIX}{tag};TARGET;unknown" }}')
    text = " ".join(branches)
    if not activated:
        text = (
            "if = { limit = { exists = currently_enacting_law } "
            + text
            + f' }} else = {{ debug_log = "{PREFIX}{tag};TARGET;none" }}'
        )
    return text


def build(keys: tuple[str, ...], *, tags: tuple[str, ...]) -> dict[str, str]:
    """只读列出的国家；激活使用 law root，其它 hook 使用 country root。"""
    validate(keys, tags, entity="法律")
    effects: list[str] = []
    actions: list[str] = []
    for tag in sorted(tags):
        readings = []
        for key in sorted(keys):
            match = f"this.type ?= law_type:{key}"
            readings.append(
                boolean_reading(
                    f"{PREFIX}{tag};LAW;{key}",
                    (
                        f"any_law = {{ {match} }}",
                        f"any_law = {{ {match} law_is_available = yes }}",
                        f"has_law = law_type:{key}",
                        f"is_enacting_law = law_type:{key}",
                    ),
                )
            )
        effects.append(f"sitai_law_observe_read_{tag} = {{\n" + "\n".join(readings) + "\n}")
    for reason, hook in (
        ("MONTHLY", "on_monthly_pulse_country"),
        ("START", "on_law_enactment_started"),
        ("PASS", "on_law_enactment_pass"),
        ("FAIL", "on_law_enactment_fail"),
        ("ENDED", "on_law_enactment_ended"),
        ("ACTIVATED", "on_law_activated"),
    ):
        activated = reason == "ACTIVATED"
        blocks = []
        for tag in sorted(tags):
            target = _target(keys, tag, activated=activated) if reason != "MONTHLY" else ""
            read = f"sitai_law_observe_read_{tag} = yes"
            if activated:
                read = f"owner = {{ {read} }}"
            condition = f"owner = {{ c:{tag} ?= this }}" if activated else f"c:{tag} ?= this"
            blocks.append(
                f"if = {{ limit = {{ {condition} }} "
                f'debug_log = "{PREFIX}{tag};BEGIN;{reason}" '
                + target
                + " "
                + read
                + f' debug_log = "{PREFIX}{tag};END;{reason}" }}'
            )
        name = "sitai_law_observe_" + reason.lower()
        actions.extend(
            (
                f"{hook} = {{ on_actions = {{ {name} }} }}",
                f"{name} = {{ effect = {{ " + " ".join(blocks) + " } }",
            )
        )
    return {
        "common/scripted_effects/zz_sitai_law_observation.txt": "\n".join(effects) + "\n",
        "common/on_actions/zz_sitai_law_observation.txt": "\n".join(actions) + "\n",
    }


def analyze(text: str, keys: tuple[str, ...], *, tags: tuple[str, ...]) -> dict[str, Any]:
    return analyze_lines(text.splitlines(), keys, tags=tags)


def analyze_lines(
    lines: Iterable[str], keys: tuple[str, ...], *, tags: tuple[str, ...]
) -> dict[str, Any]:
    frames, errors = parse_frames(lines, keys, tags=tags, schema=SCHEMA)
    valid_frames = []
    for frame in frames:
        invalid = False
        for value in frame["laws"].values():
            if not value["object_present"] and value["availability_trigger"]:
                errors.append(f"第 {frame['start_line']} 行帧在法律对象缺失时报告可用")
                invalid = True
            value["available"] = value["availability_trigger"] if value["object_present"] else None
        if not invalid:
            valid_frames.append(frame)
    errors.extend(missing_country_errors(valid_frames, tags))
    return {
        "frames": valid_frames,
        "errors": errors,
        "complete": bool(valid_frames) and not errors,
        "law_count": len(keys),
        "getter_runtime_verified": False,
        "ai_candidate_denominator_complete": False,
        "behavior_quality": "not_evaluated",
        "limits": "law_is_available 不是完整可立法资格；缺法律对象时可用性未知。激活可能来自初始化或事件设法，不能当成自主立法；各 hook 的目标与时序分别实测，完整帧不证明内部排名、字段因果或行为质量。",
    }
