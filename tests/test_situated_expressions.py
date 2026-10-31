"""K1 三值表达式合同。"""

import pytest

from pdx.situated.expressions import (
    All,
    Any,
    BooleanLiteral,
    Compare,
    Not,
    truth_all,
    truth_any,
    truth_not,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("values", "expected"),
    [((True, True), True), ((True, None), None), ((False, None), False), ((), True)],
)
def test_all_preserves_unknown(values, expected):
    assert truth_all(values) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [((False, False), False), ((False, None), None), ((True, None), True), ((), False)],
)
def test_any_preserves_unknown(values, expected):
    assert truth_any(values) is expected


def test_compare_rejects_missing_and_mixed_types():
    expression = Compare("debt", "lt", 0.5)
    assert expression.evaluate({}) is None
    assert expression.evaluate({"debt": None}) is None
    assert expression.evaluate({"debt": True}) is None
    assert expression.evaluate({"debt": 0.4}) is True


def test_nested_expression_has_explicit_unknown_not_health_default():
    expression = All(
        (
            Compare("debt", "lt", 0.5),
            Not(Any((BooleanLiteral(False), Compare("war", "eq", True)))),
        )
    )
    assert expression.evaluate({"debt": 0.4}) is None
    assert expression.evaluate({"debt": 0.4, "war": False}) is True
    assert truth_not(None) is None
