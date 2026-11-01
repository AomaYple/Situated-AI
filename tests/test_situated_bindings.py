"""D2 旧规则到行动层的逐项绑定合同。"""

from dataclasses import replace

import pytest

from pdx.situated.bindings import build, load, validate

pytestmark = pytest.mark.unit


def test_所有旧规则恰有一个精确绑定():
    bindings = load()
    assert len(bindings) == 1414
    assert len({item.binding_id for item in bindings}) == len(bindings)
    assert {item.disposition for item in bindings} <= {
        "migrate",
        "merge",
        "remove",
        "retain_vanilla",
    }
    assert all(item.source and item.definition and item.field for item in bindings)
    validate(bindings)


def test_绑定身份包含actor_target和操作且可由生产源重建():
    expected = build()
    actual = load()
    assert tuple(item.binding_id for item in actual) == tuple(item.binding_id for item in expected)
    assert all(item.actor and item.target and item.operation for item in actual)


def test_重复或缺失绑定被拒绝():
    bindings = list(load())
    bindings.pop()
    with pytest.raises(ValueError, match=r"完整|缺失"):
        validate(tuple(bindings))


@pytest.mark.parametrize(
    "field", ["source", "definition", "field", "actor", "target", "operation", "consumer"]
)
def test_绑定内容篡改不能只凭ID通过(field):
    bindings = list(load())
    original = bindings[0]
    value = {
        "source": "different.toml",
        "definition": "different",
        "field": "different",
        "actor": "owner" if original.actor == "root" else "root",
        "target": "target_state" if original.target == "none" else "none",
        "operation": "multiply" if original.operation == "add" else "add",
        "consumer": "different",
    }[field]
    bindings[0] = replace(original, **{field: value})
    with pytest.raises(ValueError, match="不一致"):
        validate(tuple(bindings))


def test_缺少绑定源文件必须失败(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "missing.toml")
