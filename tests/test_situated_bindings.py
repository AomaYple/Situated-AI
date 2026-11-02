"""D2 旧规则到行动层的逐项绑定合同。"""

from dataclasses import replace

import pytest

from pdx.situated.bindings import build, check, load, render, validate, write

pytestmark = pytest.mark.unit


def test_所有旧规则恰有一个精确绑定():
    bindings = load()
    assert len(bindings) == 1455
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


def test_绑定台账可由唯一生成器稳定重建(tmp_path):
    expected = build()
    rendered = render(expected)
    target = tmp_path / "action_bindings.toml"

    assert rendered == render(expected)
    assert rendered.endswith("\n")
    assert "lj02_coal_output_transport_foundation" in rendered
    assert "lj02_coal_transport_railway_support" in rendered
    assert write(target) == len(expected)
    assert target.read_text(encoding="utf-8") == rendered
    assert load(target) == expected
    assert check(target) == []


def test_绑定生成物与生产规则漂移时校验失败(tmp_path):
    target = tmp_path / "action_bindings.toml"
    target.write_text("schema = 1\n", encoding="utf-8", newline="\n")

    problems = check(target)

    assert problems
    assert "生产绑定源不一致" in problems[0]


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


@pytest.mark.parametrize("disposition", ["merge", "remove", "retain_vanilla"])
def test_无法表达目标或证据的处置必须拒绝而非静默迁移(disposition):
    rows = build()
    changed = (replace(rows[0], disposition=disposition), *rows[1:])
    with pytest.raises(ValueError, match=r"处置.*(证据|目标|未支持)"):
        validate(changed, check_complete=False)
