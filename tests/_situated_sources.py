"""Authored identities and complete policy-input identities for coverage checks.

``production_sources`` reads only the two authored TOML files, never compiler
models or generated bindings. Information rules use their authored-file identity;
adapters retain each explicit
native source. Duplicate source/rule keys must fail before set construction can
hide them, including duplicates that disagree on their field.

``production_policy_sources`` additionally reads the upstream policy inputs to
check complete downstream propagation, including derived rules. That consistency
set is not an independent oracle for derivation semantics; the opportunity-domain
tests retain their handwritten/native-input expectations.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_INFORMATION_SOURCE = "mod/decisions/information.toml"


@dataclass(frozen=True)
class ProductionSources:
    rules: frozenset[tuple[str, str, str]]

    @property
    def consumers(self) -> frozenset[tuple[str, str]]:
        return frozenset((source, field) for source, _rule_id, field in self.rules)


def production_sources(
    information: Path = _ROOT / _INFORMATION_SOURCE,
    adapters: Path = _ROOT / "mod/decisions/adapters.toml",
) -> ProductionSources:
    """Return current authored identities, rejecting incomplete denominators."""
    identities: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for path, fixed_source in ((information, _INFORMATION_SOURCE), (adapters, None)):
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        rows = data.get("rules")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path}: rules must be a nonempty array")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{path}: rules[{index}] must be a table")
            values: dict[str, str] = {}
            for name in ("source", "id", "field"):
                value = (
                    fixed_source if name == "source" and fixed_source is not None else row.get(name)
                )
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{path}: rules[{index}].{name} must be a nonempty string")
                values[name] = value
            source, rule_id, field = (values[name] for name in ("source", "id", "field"))
            identity = (source, rule_id)
            if identity in seen:
                raise ValueError(f"{path}: duplicate source/rule identity {identity}")
            seen.add(identity)
            identities.add((source, rule_id, field))
    return ProductionSources(frozenset(identities))


def production_policy_sources() -> ProductionSources:
    """Check all policy inputs exactly, retaining the independent authored subset.

    Read neither SituatedModel nor its bindings, inventory, IR, or generated PDX.
    A derivation omitted by its own loader must still fail its independent domain
    tests; this helper only detects losses between policy inputs and outputs.
    """
    from pdx import decision_adapters, decision_rules

    policies = (
        (_INFORMATION_SOURCE, decision_rules.load()),
        *decision_adapters.load().policies,
    )
    identities: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for source, policy in policies:
        for rule in policy.rules:
            identity = (source, rule.id)
            if identity in seen:
                raise ValueError(f"duplicate policy source/rule identity {identity}")
            seen.add(identity)
            identities.add((source, rule.id, ".".join(rule.field)))
    missing = production_sources().rules - identities
    if missing:
        raise ValueError(f"policy inputs omit authored source identities: {sorted(missing)}")
    return ProductionSources(frozenset(identities))


def production_supply_sources() -> ProductionSources:
    """Read the independent, authored goods-stance program identities."""
    with (_ROOT / "mod/decisions/adapters.toml").open("rb") as stream:
        supply = tomllib.load(stream)["supply"]
    source, goods = supply["source"], supply["goods"]
    if not isinstance(source, str) or not source or not isinstance(goods, list) or not goods:
        raise ValueError("supply must have a source and nonempty goods array")
    if any(not isinstance(good, str) or not good for good in goods) or len(set(goods)) != len(
        goods
    ):
        raise ValueError("supply goods must have distinct nonempty identities")
    return ProductionSources(
        frozenset((source, good, f"ai_strategy_default.goods_stances.{good}") for good in goods)
    )
