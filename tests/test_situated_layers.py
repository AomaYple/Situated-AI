"""D1 三层声明和有界关系图合同。"""

from dataclasses import replace

import pytest

from pdx.situated.compiler import load_model
from pdx.situated.layers import ToolLayer, load, validate, validate_links

pytestmark = pytest.mark.unit


def test_层级源覆盖十九领域且工具恰有一个主领域():
    model = load()
    assert len(model.strategies) == 7
    assert len(model.domains) == 19
    assert all(tool.domain_id in {item.id for item in model.domains} for tool in model.tools)
    assert all(
        tool.strategy_id is None or tool.strategy_id in {item.id for item in model.strategies}
        for tool in model.tools
    )
    assert all(tool.neutral_local or tool.strategy_id is not None for tool in model.tools)


def test_层级关系无环且使能深度有界():
    model = load()
    validate(model)
    assert max(model.enables_depth.values(), default=0) <= 2
    assert all(source != target for source, target in model.enables)


def test_层级关系必须与实际行动关系一致():
    model = load_model()
    layer_model = model.layer_model
    assert layer_model is not None
    validate_links(layer_model, model.actions, model.relations)
    first = layer_model.tools[0]
    altered = replace(first, relations=())
    if altered.relations == first.relations:
        altered = replace(first, relations=(first.id,))
    broken = replace(layer_model, tools=(altered, *layer_model.tools[1:]))
    with pytest.raises(ValueError, match="关系"):
        validate_links(broken, model.actions, model.relations)


def test_对称关系必须成对而不误判为有向使能环():
    model = load()
    first = model.tools[0]
    broken = replace(
        model,
        tools=(
            *model.tools,
            ToolLayer("broken_tool", first.domain_id, None, True, ("broken_tool",), ()),
        ),
    )
    with pytest.raises(ValueError, match=r"使能|未知|enables"):
        validate(broken)


def test_层级类型错误指出身份():
    domains = {
        name: {"description": name}
        for name in (
            "fiscal",
            "administrative",
            "industry",
            "resources",
            "market",
            "research",
            "education",
            "political",
            "population",
            "social",
            "identity",
            "diplomacy",
            "subjects",
            "army",
            "war",
            "navy",
            "overseas",
            "geography",
            "temporal",
        )
    }
    with pytest.raises(ValueError, match="domain"):
        validate(
            load(
                data={
                    "schema": 1,
                    "strategies": {},
                    "domains": domains,
                    "tools": {
                        "tool": {
                            "domain": "missing",
                            "strategy": None,
                            "neutral_local": True,
                            "enables": [],
                            "relations": [],
                        }
                    },
                }
            )
        )
