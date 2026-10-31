"""机会窗口的有限判定。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .signals import OpportunitySignal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .schema import EvidenceValue


def available(opportunities: Mapping[str, float | None], name: str) -> bool | None:
    value = opportunities.get(name)
    if value is None:
        return None
    return value > 0


def _bindings(spec: Mapping[str, object]) -> tuple[str, ...]:
    actions = spec.get("actions")
    if not isinstance(actions, list):
        return ()
    return tuple(item for item in actions if isinstance(item, str))


def derive(
    values: Mapping[str, EvidenceValue],
    specifications: Mapping[str, Mapping[str, object]],
) -> tuple[OpportunitySignal, ...]:
    """把机会源声明降低为带来源和消费者绑定的类型化信号。"""

    result: list[OpportunitySignal] = []
    for name, spec in sorted(specifications.items()):
        source = spec.get("source_fact")
        if not isinstance(source, str) or not source:
            raise ValueError(f"机会 {name} 缺少 source_fact")
        item = values.get(source)
        known = item is not None and item.known
        raw = item.value if item is not None and known else None
        if known and type(raw) is bool:
            available_value = raw
        elif known and isinstance(raw, (int, float)) and not isinstance(raw, bool):
            available_value = raw > 0
        else:
            available_value = None
            known = False
        bindings = _bindings(spec)
        result.append(
            OpportunitySignal(
                id=f"opportunity_{name}",
                source=f"mod/decisions/opportunities.toml:{name}",
                unit="boolean",
                scope="country",
                value=available_value if known else None,
                known=known,
                stale=bool(item.stale) if item is not None else False,
                quality="derived",
                expression=f"{source} > 0",
                source_facts=(source,),
                bindings=bindings,
            )
        )
    return tuple(result)


def contract(specifications: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    """导出机会窗口的来源、作用域、TTL/绑定合同。"""

    return {
        "schema": 1,
        "signals": [
            {
                "id": f"opportunity_{name}",
                "source": str(spec.get("source_fact", "")),
                "unit": "boolean",
                "scope": "country",
                "bindings": list(_bindings(spec)),
                "ttl": spec.get("ttl_days"),
            }
            for name, spec in sorted(specifications.items())
        ],
        "unknown": "preserve_and_fallback_vanilla",
    }
