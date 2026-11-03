"""同次编译复用规则输入；独立编译和独立 helper 调用保持新鲜。"""

from collections import Counter
from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated import compiler

pytestmark = pytest.mark.unit


def test_compiler_uses_one_policy_snapshot_and_rejects_next_invalid_input(monkeypatch):
    counts: Counter[str] = Counter()
    original_info = decision_rules.load
    original_adapters = decision_adapters.load

    def information():
        counts["information"] += 1
        return original_info()

    def adapters():
        counts["adapters"] += 1
        return original_adapters()

    monkeypatch.setattr(decision_rules, "load", information)
    monkeypatch.setattr(decision_adapters, "load", adapters)
    first = compiler.load_model()
    assert counts == {"information": 1, "adapters": 1}
    second = compiler.load_model()
    assert counts == {"information": 2, "adapters": 2}
    assert first == second
    assert first is not second

    def invalid():
        raise ValueError("current adapter input invalid")

    monkeypatch.setattr(decision_adapters, "load", invalid)
    with pytest.raises(ValueError, match="current adapter input invalid"):
        compiler.load_model()


@pytest.mark.parametrize("helper", ["_reader_facts", "_reader_shapes", "_production_inventory"])
def test_explicit_helper_inputs_do_not_read_another_snapshot(monkeypatch, helper):
    reader = decision_rules.Reader("probe", "legitimacy", "root", "points", "number")
    information = decision_rules.RuleSet((reader,), (), "", "info", frozenset())
    adapters = decision_adapters.AdapterSet((), (), "adapters")

    def unexpected():
        raise AssertionError("explicit inputs must not be reloaded")

    monkeypatch.setattr(decision_rules, "load", unexpected)
    monkeypatch.setattr(decision_adapters, "load", unexpected)
    args = () if helper == "_production_inventory" else ((),)
    value = getattr(compiler, helper)(*args, information=information, adapters=adapters)
    if helper == "_reader_facts":
        assert len(value) == 1
        assert value[0].trigger == "legitimacy"
    elif helper == "_reader_shapes":
        assert value == {"probe": (reader,)}
    else:
        assert value == ((), 0, {"information": "info", "adapters": "adapters"})


@pytest.mark.parametrize("helper", ["_reader_facts", "_reader_shapes", "_production_inventory"])
def test_standalone_helpers_observe_changed_inputs(monkeypatch, helper):
    first = decision_rules.Reader("probe", "legitimacy", "root", "points", "number")
    readers = iter((first, replace(first, engine="bureaucracy")))

    def information():
        reader = next(readers)
        return decision_rules.RuleSet((reader,), (), "", reader.engine, frozenset())

    monkeypatch.setattr(decision_rules, "load", information)
    monkeypatch.setattr(
        decision_adapters, "load", lambda: decision_adapters.AdapterSet((), (), "adapters")
    )
    args = () if helper == "_production_inventory" else ((),)
    before = getattr(compiler, helper)(*args)
    after = getattr(compiler, helper)(*args)
    assert before != after
