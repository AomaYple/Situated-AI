"""Hand-calculated unknown cost cases at real school/construction consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from test_remaining_joint_consumers import INFO, _overlay, _values
from test_remaining_joint_consumers import production as _production
from test_situated_joint_witnesses import _facts

from pdx import decision_rules
from pdx.situated import pdx_eval

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    return cast("Callable[[], Any]", _production._get_wrapped_function())()


@pytest.mark.parametrize(
    ("field", "changes", "expected"),
    [
        (
            "institution_scores.institution_schools",
            {"literacy": 0.3, "bureaucracy": 1, "net_surplus": 1, "default": False},
            1.25,
        ),
        (
            "institution_scores.institution_schools",
            {"literacy": 0.3, "bureaucracy": 1, "net_surplus": 1, "default": True},
            1.03,
        ),
        (
            "institution_scores.institution_schools",
            {"literacy": 0.3, "bureaucracy": 1, "net_surplus": 1, "default": None},
            1.03,
        ),
        (
            "institution_scores.institution_schools",
            {"literacy": 0.3, "bureaucracy": None, "net_surplus": 1},
            1.10,
        ),
        (
            "institution_scores.institution_schools",
            {"literacy": None, "bureaucracy": -1, "default": True},
            0.75,
        ),
        ("wanted_construction_output", {"war_defeat": True, "default": None}, 0.87),
        ("wanted_construction_output", {"war_defeat": True, "default": False, "loans": None}, 1.12),
        (
            "wanted_construction_output",
            {
                "war_defeat": True,
                "default": False,
                "loans": True,
                "debt_ratio": None,
                "bankruptcy_horizon": 1,
            },
            0.97,
        ),
        (
            "wanted_construction_output",
            {
                "war_defeat": True,
                "default": False,
                "loans": True,
                "debt_ratio": None,
                "bankruptcy_horizon": 52,
            },
            1.12,
        ),
    ],
)
def test_real_cost_unknown_is_bounded_conservative_not_free_benefit(
    production, field, changes, expected
):
    policies, files, _native, _model = production
    policy = policies[INFO]
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert reference.get(field, ("", 1))[1] == pytest.approx(expected)
    result = pdx_eval.select(_overlay(files[INFO], field), _facts(policy, values))
    assert result.delta == pytest.approx(expected)


def test_declared_unknown_cost_preserves_rule_ir_roundtrip(production):
    policy = production[0][INFO]
    for item in policy.semantic_ir:
        rule = item.to_rule()
        if rule.conservative_unknown_facts:
            assert rule.semantic_role == "cost"
            assert rule.unknown_cost_basis
            assert item.conservative_unknown_facts == rule.conservative_unknown_facts
