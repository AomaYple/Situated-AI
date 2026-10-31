"""K2 类型化状态、机会和承诺的参考语义。"""

from __future__ import annotations

import pytest

from pdx.situated import commitment, opportunity, state
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
