"""K4 关系降低与局部联动的反例。"""

from dataclasses import replace

import pytest

from pdx import decisions
from pdx.parser import parse_text
from pdx.situated import pdx_eval, relations
from pdx.situated.compiler import load_model, strategy_overlay

pytestmark = pytest.mark.unit


def test_complement_is_soft_and_conditioned_in_generated_consumer() -> None:
    model = load_model()
    overlay = strategy_overlay(model)
    text = overlay["economic_vs_government_spending_balance"]
    assert "# ACTION industrial_foundation" in text
    assert "# ACTION education_and_research" in text
    # 互补项以行动内部的条件增量出现，不能成为主行动的硬资格门。
    assert "ROOT ?= {  AND = { is_ai = yes" in text
    facts = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": 60,
        "bureaucracy": 1,
        "literacy_rate": 0.3,
        "scaled_debt": 0.4,
        "net_total_income": 1,
    }
    # 同一基础行动在两个、一个、零个互补条件成立时均可选中；
    # 最多一个互补增加 0.25，不把对方变成基础行动的资格门。
    for changes, expected in (
        ({}, 1.5),
        ({"literacy_rate": 0.6}, 1.5),
        ({"literacy_rate": 0.6, "any_insurrection_ongoing": True}, 1.25),
    ):
        result = pdx_eval.select(text, {**facts, **changes})
        assert (result.action_id, result.delta) == ("industrial_foundation", expected)
    patched = decisions.patch_default(
        decisions.BASELINE.read_text(encoding="utf-8"),
        decisions.load(),
        decisions.load_extensions(profile="release"),
        action_overlay=overlay,
    )
    assert not parse_text(patched).errors


def test_duplicate_and_asymmetric_relations_fail_closed() -> None:
    model = load_model()
    first = next(item for item in model.actions if item.id == "industrial_foundation")
    duplicate = replace(first, complements=(*first.complements, "political_reform"))
    with pytest.raises(ValueError, match="重复"):
        relations.validate((duplicate, *(item for item in model.actions if item.id != first.id)))

    political = next(item for item in model.actions if item.id == "political_reform")
    asymmetric = replace(first, complements=("education_and_research",))
    with pytest.raises(ValueError, match="对称配对"):
        relations.validate(
            (
                asymmetric,
                political,
                *(item for item in model.actions if item.id not in {first.id, political.id}),
            )
        )
