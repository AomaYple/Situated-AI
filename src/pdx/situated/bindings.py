"""D2 旧规则到行动层的精确绑定目录。

绑定是迁移追踪元数据，不是第二套业务规则。每个绑定只能指向一个生产来源、
定义、字段、作用域和操作；所有实际语义仍来自原规则加载器。
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from pdx import decision_adapters, decision_rules

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO / "mod" / "decisions" / "action_bindings.toml"
_SAFE = re.compile(r"[^a-z0-9_]+")
_DISPOSITIONS = {"migrate", "merge", "remove", "retain_vanilla"}


@dataclass(frozen=True, slots=True)
class Binding:
    binding_id: str
    source: str
    definition: str
    field: str
    actor: str
    target: str
    operation: str
    disposition: str
    consumer: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _binding_id(source: str, rule_id: str) -> str:
    return "binding_" + _SAFE.sub("_", f"{source}_{rule_id}".lower()).strip("_")


def _target(field: tuple[str, ...]) -> str:
    return "target_state" if field and field[-1] == "state_value" else "none"


def build(
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> tuple[Binding, ...]:
    result: list[Binding] = []
    info = decision_rules.load() if information is None else information
    for rule in info.rules:
        source = "mod/decisions/information.toml"
        result.append(
            Binding(
                _binding_id(source, rule.id),
                source,
                rule.id,
                ".".join(rule.field),
                "root",
                _target(rule.field),
                rule.operation,
                "migrate",
                ".".join(rule.field),
            )
        )
    adapters = decision_adapters.load() if adapters is None else adapters
    for source, policy in adapters.policies:
        actor = "owner" if policy.actor_path else "root"
        result.extend(
            Binding(
                _binding_id(source, rule.id),
                source,
                rule.id,
                ".".join(rule.field),
                actor,
                _target(rule.field),
                rule.operation,
                "migrate",
                ".".join(rule.field),
            )
            for rule in policy.rules
        )
    result.extend(
        Binding(
            _binding_id(p.source, p.definition),
            p.source,
            p.definition,
            p.field,
            "root",
            "target_region",
            "add",
            "migrate",
            p.consumer_id,
        )
        for p in adapters.regional_resource_programs
    )
    result.sort(key=lambda item: item.binding_id)
    validate(tuple(result), check_complete=False)
    return tuple(result)


def load(
    path: Path = DEFAULT_SOURCE,
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> tuple[Binding, ...]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if (
        data.get("schema") != 1
        or set(data) != {"schema", "bindings"}
        or not isinstance(data["bindings"], list)
    ):
        raise ValueError("action_bindings.toml schema 无效")
    result: list[Binding] = []
    required = {
        "binding_id",
        "source",
        "definition",
        "field",
        "actor",
        "target",
        "operation",
        "disposition",
        "consumer",
    }
    for index, raw in enumerate(data["bindings"]):
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError(f"绑定字段无效：{index}")
        if any(not isinstance(raw[key], str) or not raw[key].strip() for key in required):
            raise ValueError(f"绑定身份为空：{index}")
        result.append(Binding(**raw))
    # 绑定文件是生成式台账；读取时按稳定身份排序，避免文件分段或
    # 新增批次的物理插入位置改变 IR、报告和验收顺序。
    ordered = tuple(sorted(result, key=lambda item: item.binding_id))
    validate(ordered, information=information, adapters=adapters)
    return ordered


def render(rows: tuple[Binding, ...] | None = None) -> str:
    """Render the exact binding ledger derived from current production rules."""

    bindings = build() if rows is None else tuple(rows)
    validate(bindings, check_complete=False)
    lines = ["# 由 src/pdx/situated/bindings.py 生成；每条旧规则只允许一个精确处置。", "schema = 1"]
    for item in bindings:
        lines.extend(("", "[[bindings]]"))
        for field in Binding.__dataclass_fields__:
            value = json.dumps(getattr(item, field), ensure_ascii=False)
            lines.append(f"{field} = {value}")
    return "\n".join(lines) + "\n"


def write(path: Path = DEFAULT_SOURCE) -> int:
    """Write the generated binding ledger using repository text conventions."""

    bindings = build()
    path.write_text(render(bindings), encoding="utf-8", newline="\n")
    return len(bindings)


def check(path: Path = DEFAULT_SOURCE) -> list[str]:
    """Compare the checked-in ledger with the current deterministic source."""

    try:
        actual = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"绑定生成物缺失：{path}"]
    except (OSError, UnicodeError) as exc:
        return [f"绑定生成物不可读：{path}: {exc}"]
    if actual != render():
        return [f"生产绑定源不一致：{path}"]
    return []


def validate_disposition(item: Binding) -> None:
    """Only migrate has executable semantics in schema 1.

    Keep every original identity; a future merge/removal requires a target or
    disposition evidence and a production lowering contract before acceptance.
    """
    if item.disposition not in _DISPOSITIONS:
        raise ValueError(f"绑定处置无效：{item.binding_id}")
    if item.disposition != "migrate":
        requirement = (
            "合并目标与原分支映射证据" if item.disposition == "merge" else "处置证据与原版保留映射"
        )
        raise ValueError(
            f"绑定处置 {item.disposition} 未支持：schema 1 缺少{requirement}：{item.binding_id}"
        )


def validate(
    bindings: tuple[Binding, ...],
    *,
    check_complete: bool = True,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> None:
    if not bindings:
        raise ValueError("绑定目录不能为空")
    ids = [item.binding_id for item in bindings]
    if len(ids) != len(set(ids)):
        raise ValueError("绑定 ID 重复")
    for item in bindings:
        validate_disposition(item)
        if item.operation not in {"add", "multiply"}:
            raise ValueError(f"绑定 operation 无效：{item.binding_id}")
        if item.actor not in {"root", "owner"} or item.target not in {
            "none",
            "target_state",
            "target_region",
        }:
            raise ValueError(f"绑定 actor/target 无效：{item.binding_id}")
        if not item.field or not item.consumer:
            raise ValueError(f"绑定字段为空：{item.binding_id}")
    if check_complete:
        expected_rows = {
            item.binding_id: item for item in build(information=information, adapters=adapters)
        }
        expected = set(expected_rows)
        actual = set(ids)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(f"绑定目录不完整：缺失={missing[:3]} 多余={extra[:3]}")
        for item in bindings:
            expected_item = expected_rows[item.binding_id]
            for field in (
                "source",
                "definition",
                "field",
                "actor",
                "target",
                "operation",
                "consumer",
            ):
                if getattr(item, field) != getattr(expected_item, field):
                    raise ValueError(f"绑定与生产源不一致：{item.binding_id}.{field}")


def contract(bindings: tuple[Binding, ...]) -> dict[str, object]:
    for item in bindings:
        validate_disposition(item)
    return {
        "schema": 1,
        "count": len(bindings),
        "dispositions": {
            name: sum(item.disposition == name for item in bindings)
            for name in sorted(_DISPOSITIONS)
        },
        "bindings": [item.as_dict() for item in bindings],
    }


__all__ = [
    "DEFAULT_SOURCE",
    "Binding",
    "build",
    "check",
    "contract",
    "load",
    "render",
    "validate",
    "validate_disposition",
    "write",
]
