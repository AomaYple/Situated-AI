"""K4 关系降低与局部联动的反例。"""

from dataclasses import replace

import pytest

from pdx import decisions
from pdx.parser import parse_text
from pdx.situated import relations
from pdx.situated.compiler import load_model, strategy_overlay

pytestmark = pytest.mark.unit


def test_complement_is_soft_and_conditioned_in_generated_consumer() -> None:
    model = load_model()
    overlay = strategy_overlay(model)
    text = overlay["economic_vs_government_spending_balance"]
    assert "# ACTION industrial_foundation" in text
    assert "# ACTION education_and_research" in text
    # 互补项以行动内部的条件增量出现，不能成为主行动的硬资格门。
    assert "add = 1" in text
    assert "ROOT ?= {  AND = { is_ai = yes" in text
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
