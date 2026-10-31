"""D2 旧规则到行动层的精确绑定目录。

绑定是迁移追踪元数据，不是第二套业务规则。每个绑定只能指向一个生产来源、
定义、字段、作用域和操作；所有实际语义仍来自原规则加载器。
"""

from __future__ import annotations

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
    return (
        "target_state"
        if field and field[-1] in {"state_value", "colonial_interest_ratio"}
        else "none"
    )


def build() -> tuple[Binding, ...]:
    result: list[Binding] = []
    info = decision_rules.load()
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
    adapters = decision_adapters.load()
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
    result.sort(key=lambda item: item.binding_id)
    validate(tuple(result), check_complete=False)
    return tuple(result)


def load(path: Path = DEFAULT_SOURCE) -> tuple[Binding, ...]:
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
    validate(tuple(result))
    return tuple(result)


def validate(bindings: tuple[Binding, ...], *, check_complete: bool = True) -> None:
    if not bindings:
        raise ValueError("绑定目录不能为空")
    ids = [item.binding_id for item in bindings]
    if len(ids) != len(set(ids)):
        raise ValueError("绑定 ID 重复")
    for item in bindings:
        if item.disposition not in _DISPOSITIONS:
            raise ValueError(f"绑定处置无效：{item.binding_id}")
        if item.operation not in {"add", "multiply"}:
            raise ValueError(f"绑定 operation 无效：{item.binding_id}")
        if item.actor not in {"root", "owner"} or item.target not in {"none", "target_state"}:
            raise ValueError(f"绑定 actor/target 无效：{item.binding_id}")
        if not item.field or not item.consumer:
            raise ValueError(f"绑定字段为空：{item.binding_id}")
    if check_complete:
        expected_rows = {item.binding_id: item for item in build()}
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
    return {
        "schema": 1,
        "count": len(bindings),
        "dispositions": {
            name: sum(item.disposition == name for item in bindings)
            for name in sorted(_DISPOSITIONS)
        },
        "bindings": [item.as_dict() for item in bindings],
    }


__all__ = ["DEFAULT_SOURCE", "Binding", "build", "contract", "load", "validate"]
