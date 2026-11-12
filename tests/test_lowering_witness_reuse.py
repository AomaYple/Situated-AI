"""Private reducers retain public fresh-parse results and source identities."""

from dataclasses import replace
from typing import cast

import pytest

from pdx.situated import action_instances, ir, lowering


def _text(value=1):
    return f"# same [economy]; proof\nif = {{ limit = {{ is_ai = yes }} add = {value} }}"


def _instance(source, action):
    return action_instances.ActionInstance(
        action, "rule_action", source, "same", "economy", "score", "add", 1, (), "owner", "keep", ()
    )


def test_private_reducers_equal_fresh_public_apis_and_keep_source_identity():
    texts = {"a.txt": _text(), "b.txt": _text()}
    instances = (_instance("a.txt", "first"), _instance("b.txt", "second"))
    expected = (ir.ActionIR("same", "a.txt", "economy", "score", "add", 1, (), "keep"),)
    numeric = lowering.witnesses(texts)
    ast = lowering.ast_witnesses(texts)
    assert lowering._missing(expected, numeric) == lowering.missing(expected, texts)
    assert lowering._mismatches(expected, numeric) == lowering.mismatches(expected, texts)
    assert lowering._ast_mismatches(ast) == lowering.ast_mismatches(texts)
    result = action_instances._behavior_witness_contract(instances, numeric)
    assert result == action_instances.behavior_witness_contract(instances, texts)
    assert result["missing"] == result["mismatches"] == result["duplicate_ids"] == []
    rows = cast("list[dict[str, object]]", result["rows"])
    assert {row["witness_source"] for row in rows} == {"a.txt", "b.txt"}
    with pytest.raises(AttributeError):
        numeric[0].value = 9  # type: ignore[misc]  # Exercise frozen dataclass rejection.


def test_public_next_call_reparses_changed_missing_or_duplicate_text():
    instances = (_instance("a.txt", "first"), _instance("b.txt", "second"))
    texts = {"a.txt": _text(), "b.txt": _text()}
    assert action_instances.behavior_witness_contract(instances, texts)["mismatches"] == []
    texts["b.txt"] = _text(2)
    assert action_instances.behavior_witness_contract(instances, texts)["mismatches"] == ["second"]
    del texts["a.txt"]
    assert action_instances.behavior_witness_contract(instances, texts)["missing"] == ["first"]
    texts["b.txt"] = _text() + "\n" + _text()
    result = action_instances.behavior_witness_contract(instances, texts)
    assert result["duplicate_ids"] == ["same"]
    assert result["mismatches"] == ["second"]
    texts["b.txt"] = "broken = {"
    with pytest.raises(ValueError, match="PDX"):
        action_instances.behavior_witness_contract(instances, texts)


def test_numeric_and_ast_error_reducers_keep_missing_wrong_value_and_no_limit():
    expected = (ir.ActionIR("same", "a.txt", "economy", "score", "add", 1, (), "keep"),)
    assert lowering._missing(expected, ()) == ("same",)
    wrong = lowering.witnesses({"a.txt": _text(2)})
    assert lowering._mismatches(expected, wrong) == ("same",)
    assert lowering._mismatches((replace(expected[0], value=2),), wrong) == ()
    bad = {"a.txt": "# same [economy]; proof\nif = { add = 1 }"}
    assert lowering._ast_mismatches(lowering.ast_witnesses(bad)) == ("same",)


def test_public_mismatches_consumes_ir_before_invalid_text_and_last_duplicate_wins():
    def invalid_ir():
        raise RuntimeError("IR iteration fails first")
        yield

    with pytest.raises(RuntimeError, match="IR iteration fails first"):
        lowering.mismatches(invalid_ir(), {"broken.txt": "bad = {"})
    first = ir.ActionIR("same", "a.txt", "economy", "score", "add", 1, (), "keep")
    events = []

    def duplicate_ir():
        events.append("first")
        yield first
        events.append("last")
        yield replace(first, value=2)

    assert lowering.mismatches(duplicate_ir(), {"a.txt": _text(2)}) == ()
    assert events == ["first", "last"]
