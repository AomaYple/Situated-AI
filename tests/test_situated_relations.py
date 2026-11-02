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
    # 工业基础 +.15；低识字教育方向 -.10、政治成本 +.02、
    # 已有行政承载互补 -.025，合计 .045。需求信号未提供，不能假定成立。
    # 识字改善后教育项退出，工业的知识互补 +.025；合法性达到75且
    # 没有起义时另有政治互补 +.025。关系只改贡献，不成为工业资格门。
    for changes, expected in (
        ({}, 0.045),
        ({"literacy_rate": 0.6}, 0.175),
        ({"literacy_rate": 0.6, "legitimacy": 80}, 0.2),
        ({"literacy_rate": 0.6, "legitimacy": 80, "any_insurrection_ongoing": True}, 0.175),
    ):
        result = pdx_eval.select(text, {**facts, **changes})
        assert result.action_id == "joint_economic_balance"
        assert result.operation == "add"
        assert result.delta == pytest.approx(expected)
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
