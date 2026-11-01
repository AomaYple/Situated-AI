"""K2 类型化状态、机会和承诺的参考语义。"""

from __future__ import annotations

import pytest

from pdx.situated import commitment, evidence, opportunity, state
from pdx.situated.schema import EvidenceValue

pytestmark = pytest.mark.unit


def values(**overrides: object) -> dict[str, EvidenceValue]:
    defaults: dict[str, object] = {
        "default": False,
        "war": False,
        "loans": False,
        "debt_ratio": 0.1,
        "net_surplus": 10,
        "bureaucracy": 100,
        "legitimacy": 60,
        "literacy": 0.7,
        "population": 1_000,
        "navy": 30,
        "industrial_route": True,
        "resource_route": False,
        "expansion_route": False,
        "insurrection": False,
        "war_defeat": False,
        "subject": False,
        "income": 20,
    }
    defaults.update(overrides)
    return {
        key: EvidenceValue(key, value, value is not None, provenance="test")
        for key, value in defaults.items()
    }


def test_typed_state_keeps_units_sources_and_expression() -> None:
    result = state.derive_typed(values())
    assert {item.id for item in result.capacities} >= {
        "layer_foundation",
        "layer_stable",
        "layer_expansion",
    }
    foundation = next(item for item in result.capacities if item.id == "layer_foundation")
    assert foundation.known
    assert foundation.value is True
    assert foundation.unit == "boolean"
    assert foundation.source_facts == ("default", "war", "debt_ratio", "income")
    assert foundation.expression


def test_unknown_does_not_become_false_or_healthy() -> None:
    result = state.derive_typed(values(default=None, war=None, debt_ratio=None, income=None))
    foundation = next(item for item in result.capacities if item.id == "layer_foundation")
    assert foundation.known is False
    assert foundation.value is None
    fiscal = next(item for item in result.needs if item.id == "need_fiscal")
    assert fiscal.known is False


def test_stale_values_are_unknown_but_keep_stale_provenance() -> None:
    stale_values = values()
    stale_values["debt_ratio"] = EvidenceValue("debt_ratio", 0.1, True, stale=True)
    result = state.derive_typed(stale_values)
    foundation = next(item for item in result.capacities if item.id == "layer_foundation")
    assert foundation.known is False
    assert foundation.value is None
    assert foundation.stale is True


def test_each_need_is_a_local_expression() -> None:
    result = state.derive_typed(values(war=True, literacy=0.2, industrial_route=False))
    need = {item.id: item for item in result.needs}
    assert need["need_security"].value is True
    assert need["need_education"].value is True
    assert need["need_industry"].value is False
    assert all(item.expression and item.source_facts for item in result.needs)


def test_opportunity_and_commitment_contract_preserve_unknown() -> None:
    opportunity_specs = {
        "education": {"source_fact": "literacy", "actions": ["education_and_research"]},
    }
    commitment_specs = {
        "debt_service": {"source_fact": "debt_ratio", "unit": "debt_to_credit_ratio"},
    }
    opportunities = opportunity.derive(values(literacy=0.1), opportunity_specs)
    commitments = commitment.derive(values(debt_ratio=None), commitment_specs)
    assert opportunities[0].bindings == ("education_and_research",)
    assert opportunities[0].known
    assert opportunities[0].value is True
    assert commitments[0].known is False
    assert commitments[0].value is None
    assert commitments[0].unit == "debt_to_credit_ratio"


def test_stale_opportunity_and_commitment_do_not_become_current() -> None:
    opportunity_specs = {
        "education": {"source_fact": "literacy", "actions": ["education_and_research"]},
    }
    commitment_specs = {
        "debt_service": {"source_fact": "debt_ratio", "unit": "debt_to_credit_ratio"},
    }
    stale_values = values(literacy=0.1, debt_ratio=0.1)
    stale_values["literacy"] = EvidenceValue("literacy", 0.1, True, stale=True)
    stale_values["debt_ratio"] = EvidenceValue("debt_ratio", 0.1, True, stale=True)
    assert opportunity.derive(stale_values, opportunity_specs)[0].known is False
    assert commitment.derive(stale_values, commitment_specs)[0].known is False


def test_nonfinite_opportunity_and_commitment_values_are_unknown() -> None:
    opportunity_specs = {
        "education": {"source_fact": "literacy", "actions": ["education_and_research"]},
    }
    commitment_specs = {
        "debt_service": {"source_fact": "debt_ratio", "unit": "debt_to_credit_ratio"},
    }
    invalid = values(literacy=float("nan"), debt_ratio=float("inf"))
    assert opportunity.derive(invalid, opportunity_specs)[0].known is False
    assert commitment.derive(invalid, commitment_specs)[0].known is False


def test_fact_schema_rejects_mixed_units_and_boolean_bounds(tmp_path) -> None:
    source = tmp_path / "facts.toml"
    source.write_text(
        """schema = 1

[facts.bad_boolean]
domain = "fiscal"
source = "test.txt"
scope = "root"
kind = "boolean"
unit = "flag"
refresh = "monthly"
unknown = "vanilla"
trigger = "is_ai = yes"
minimum = 0
""",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="布尔事实"):
        evidence.load(source)

    source.write_text(
        source.read_text(encoding="utf-8")
        .replace('kind = "boolean"\nunit = "flag"', 'kind = "ratio"\nunit = "points"')
        .replace("minimum = 0\n", ""),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="比例事实"):
        evidence.load(source)
