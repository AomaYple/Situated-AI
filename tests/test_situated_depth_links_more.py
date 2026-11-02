"""D9 additional local production links, with explicit observed inputs."""

from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

MINES = "common/buildings/03_mines.txt"
RAIL = "common/buildings/11_private_infrastructure.txt"
COAL = "building_coal_mine.ai_value"
RAILWAY = "building_railway.ai_value"
COAL_PM = "pm_active_building_coal_mine_pm_picks_and_shovels_building_coal_mine"
RAIL_PM = "pm_active_building_railway_pm_early_trains"


@pytest.fixture(scope="module")
def legacy_policies():
    result = {}
    for source, policy in decision_adapters.load().policies:
        if source not in (MINES, RAIL):
            continue
        field = COAL if source == MINES else RAILWAY
        rules = tuple(r for r in policy.rules if ".".join(r.field) == field)
        keys = frozenset(k for rule in rules for k in rule.input_keys())
        result[source] = replace(
            policy,
            rules=rules,
            readers=tuple(r for r in policy.readers if r.key in keys),
            enabled_domains=frozenset(r.domain for r in rules),
            semantic_ir=(),
        )
    return result


@pytest.fixture(scope="module")
def policies(legacy_policies: Any) -> dict[str, Any]:
    """Compile the production reference once, then render those same policies."""
    model = compiler.load_model()
    return {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in legacy_policies.items()
    }


def observed(policy: Any, changes: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update(
        {
            COAL_PM: True,
            RAIL_PM: True,
            "state_owner_default": False,
            "state_owner_loans": False,
            "state_owner_coal_price": 0.6,
            "state_owner_coal_balance": -1,
            "state_owner_engines_price": 0.2,
            "state_owner_engines_balance": 0,
            "state_transport_price": 0.2,
            "state_infrastructure": 0,
        }
    )
    values.update(changes)
    return values


def scores(policies: Any, changes: dict[str, Any]) -> tuple[float, ...]:
    out = []
    for source, field in ((MINES, COAL), (RAIL, RAILWAY)):
        policy = policies[source]
        values = observed(policy, changes)
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        out.append(selected[1] if selected else 1)
    return tuple(out)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.2, 0.8)),
        ({COAL_PM: False}, (1.15, 0.8)),
        ({"state_owner_coal_price": 0.2, "state_owner_coal_balance": 0}, (1.0, 1.0)),
        (
            {
                "state_infrastructure": -1,
                "state_transport_price": 0.6,
                "state_owner_coal_price": 0.2,
                "state_owner_coal_balance": 0,
            },
            # Generic logistics 1.2 is the strongest positive tier; the
            # active coal-to-rail link's 1.1 is a correlated alternative.
            (1.0, 1.2),
        ),
        (
            {
                RAIL_PM: None,
                "state_infrastructure": -1,
                "state_transport_price": 0.6,
                "state_owner_coal_price": 0.2,
                "state_owner_coal_balance": 0,
            },
            # Missing the active method skips its local link, while the
            # generic known infrastructure/transport shortage stays valid.
            (1.0, 1.2),
        ),
        (
            {
                "state_infrastructure": -1,
                "state_transport_price": 0.6,
                "state_owner_coal_price": 0.2,
                "state_owner_coal_balance": 0,
                "candidate_selected": True,
                "construction_queued": True,
            },
            (1.0, 1.2),
        ),
    ],
)
def test_lj02_real_coal_and_railway_inputs(
    policies: Any, changes: dict[str, Any], expected: tuple[float, float]
) -> None:
    assert scores(policies, changes) == pytest.approx(expected)


@pytest.mark.unit
def test_lj06_and_lj07_use_only_the_proven_local_reader_contract() -> None:
    """局部就业/粮食链已接线；未证明的迁移、机械化和健康输入仍不应出现。"""
    adapters = decision_adapters.load()
    ids = {
        rule.id
        for _, policy in adapters.policies
        for rule in policy.rules
        if rule.id.startswith(("lj06_", "lj07_"))
    }
    assert ids == {
        "lj06_employment_food_unemployment_support",
        "lj06_employment_textile_unemployment_support",
        "lj07_grain_health_foundation",
        "lj07_grain_health_social_capacity",
    }
    info_ids = {rule.id for rule in decision_rules.load().rules if rule.id.startswith("lj07_")}
    assert info_ids == {"lj07_grain_social_foundation", "lj07_grain_social_capacity"}


def _engine_facts(policy: Any, values: dict[str, Any], *, is_ai: bool = True) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for reader in policy.readers:
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        observed_value = values.get(reader.key)
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(params["building_type"], {})[
                params["production_method"]
            ] = observed_value
        else:
            current[reader.engine] = observed_value
    owner = root.setdefault("owner", {})
    owner["is_ai"] = is_ai
    return {"ROOT": root}


def _entry(text: str, name: str) -> Block:
    entry = parse_text(text).root.first(name)
    assert entry is not None
    assert isinstance(entry.value, Block)
    return entry.value


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


@pytest.fixture(scope="module")
def generated(policies: Any) -> tuple[dict[str, str], dict[str, str]]:
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = tuple((source, policies[source]) for source in (MINES, RAIL))
    fields = {(source, rule.field) for source, policy in compiled for rule in policy.rules}
    selected = replace(
        adapters,
        policies=compiled,
        initial_values=tuple(
            row for row in adapters.initial_values if (row.source, row.field) in fields
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row in fields),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return inputs, files


def _pdx_scores(
    policies: Any,
    generated: tuple[dict[str, str], dict[str, str]],
    changes: dict[str, Any],
    *,
    is_ai: bool = True,
) -> tuple[float, float]:
    _, files = generated
    result: list[float] = []
    for source, field in ((MINES, COAL), (RAIL, RAILWAY)):
        values = observed(policies[source], changes)
        overlay = files[source]
        begin_marker = f"# SITAI BEGIN information:{field}"
        end_marker = f"# SITAI END information:{field}"
        begin = overlay.index(begin_marker)
        end = overlay.index(end_marker, begin)
        snippet = overlay[begin:end]
        actual = pdx_eval.select(snippet, _engine_facts(policies[source], values, is_ai=is_ai))
        result.append(actual.delta if actual.operation == "multiply" else 1.0)
    return tuple(result)  # type: ignore[return-value]


RAIL_READY = {
    "state_infrastructure": -1,
    "state_transport_price": 0.6,
    "state_owner_coal_price": 0.2,
    "state_owner_coal_balance": 0,
}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({COAL_PM: None}, (1.0, 0.8)),
        (RAIL_READY, (1.0, 1.1)),
        ({**RAIL_READY, RAIL_PM: None}, (1.0, 1.0)),
    ],
)
def test_raw_ruleset_legacy_priority_and_unknown_are_separate_from_production(
    legacy_policies: Any, changes: dict[str, Any], expected: tuple[float, float]
) -> None:
    assert all(not policy.consumer_programs for policy in legacy_policies.values())
    assert scores(legacy_policies, changes) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (1.2, 0.8)),
        ({COAL_PM: False}, (1.15, 0.8)),
        ({"state_owner_default": True}, (1.0, 0.8)),
        # Unknown mine method skips recipe tiers, retaining the independently
        # observed generic coal shortage 1.15; railway coal cost stays -.20.
        ({COAL_PM: None}, (1.15, 0.8)),
        ({"state_owner_coal_price": 0.2, "state_owner_coal_balance": 0}, (1.0, 1.0)),
        ({"candidate_selected": True, "construction_queued": True}, (1.2, 0.8)),
        # Logistics +.20 supersedes the active local support +.10 tier.
        (RAIL_READY, (1.0, 1.2)),
        ({**RAIL_READY, RAIL_PM: False}, (1.0, 1.2)),
        (
            {**RAIL_READY, "state_owner_engines_price": 0.6, "state_owner_engines_balance": -1},
            (1.0, 0.8),
        ),
        ({**RAIL_READY, RAIL_PM: None}, (1.0, 1.2)),
        ({**RAIL_READY, "state_transport_price": 0.2}, (1.0, 1.0)),
        ({**RAIL_READY, "candidate_selected": True, "construction_queued": True}, (1.0, 1.2)),
    ],
)
def test_lj02_real_generated_pdx_scenarios(
    policies: Any,
    generated: tuple[dict[str, str], dict[str, str]],
    changes: dict[str, Any],
    expected: tuple[float, float],
) -> None:
    assert scores(policies, changes) == pytest.approx(expected)
    assert _pdx_scores(policies, generated, changes) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"state_owner_coal_price": 0.5}, (1.2, 1.0)),
        ({"state_owner_coal_price": 0.5001}, (1.2, 0.8)),
        ({**RAIL_READY, "state_transport_price": 0.25}, (1.0, 1.0)),
        ({**RAIL_READY, "state_transport_price": 0.2501}, (1.0, 1.2)),
        ({**RAIL_READY, "state_owner_coal_balance": -0.001}, (1.0, 1.2)),
        ({**RAIL_READY, "state_owner_coal_balance": 0}, (1.0, 1.2)),
    ],
)
def test_lj02_generated_thresholds(
    policies: Any,
    generated: tuple[dict[str, str], dict[str, str]],
    changes: dict[str, Any],
    expected: tuple[float, float],
) -> None:
    assert scores(policies, changes) == pytest.approx(expected)
    assert _pdx_scores(policies, generated, changes) == pytest.approx(expected)


@pytest.mark.integration
def test_lj02_players_disabled_and_native_definitions(
    policies: Any, generated: tuple[dict[str, str], dict[str, str]]
) -> None:
    inputs, files = generated
    assert _pdx_scores(policies, generated, {}, is_ai=False) == (1, 1)
    assert _pdx_scores(policies, generated, RAIL_READY, is_ai=False) == (1, 1)
    disabled, _ = decision_adapters.build(
        decision_adapters.load(), texts=inputs, enabled_domains=frozenset()
    )
    assert disabled == {}
    for source, name in ((MINES, "building_coal_mine"), (RAIL, "building_railway")):
        before, after = _entry(inputs[source], name), _entry(files[source], name)
        assert tuple(
            _tree(item)
            for item in before.items
            if not isinstance(item, Assignment) or item.key != "ai_value"
        ) == tuple(
            _tree(item)
            for item in after.items
            if not isinstance(item, Assignment) or item.key != "ai_value"
        )
