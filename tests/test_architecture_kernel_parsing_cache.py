"""Syntax reuse must preserve complete-field witnesses and fresh observations."""

from __future__ import annotations

import pytest
import test_architecture_kernel_witnesses as kernel

from pdx.situated import pdx_eval

TEXT = """
ai_strategy_default = {
    target = { value = 2 if = { limit = { is_at_war = yes } add = 3 } }
    other = { value = 9 }
}
another_definition = { target = { value = 12 } }
"""


def test_complete_field_cache_reuses_only_syntax_and_rechecks_changed_observations(monkeypatch):
    parsed_texts = []
    parse = kernel.parse_text

    def counted_parse(text):
        parsed_texts.append(text)
        return parse(text)

    monkeypatch.setattr(kernel, "parse_text", counted_parse)
    candidate = {"field_trees": kernel._FieldTrees()}
    engine: dict[str, object | None] = {"is_at_war": True}
    assert kernel._complete_value(candidate, TEXT, "target", engine) == 5
    engine["is_at_war"] = False
    assert kernel._complete_value(candidate, TEXT, "target", engine) == 2
    engine["is_at_war"] = None
    assert kernel._complete_value(candidate, TEXT, "target", engine) == 2
    assert kernel._complete_value(candidate, TEXT, "target", {"is_at_war": True}) == 5
    assert parsed_texts == [TEXT]


def test_complete_field_cache_observes_text_and_field_identity():
    candidate = {"field_trees": kernel._FieldTrees()}
    changed = TEXT.replace("value = 2", "value = 7")
    for text in (TEXT, changed, TEXT):
        for field in ("target", "other"):
            assert kernel._field(candidate, text, field) == kernel.explicit._field(text, field)
    assert kernel._complete_value(candidate, TEXT, "target", {"is_at_war": True}) == 5
    assert kernel._complete_value(candidate, changed, "target", {"is_at_war": True}) == 10
    assert kernel._complete_value(candidate, changed, "other", {}) == 9
    other_definition = candidate["field_trees"].field(TEXT, "another_definition", "target")
    assert pdx_eval._numeric_value(other_definition, {}) == 12


def test_complete_field_cache_belongs_to_one_fixture_instance():
    first = kernel._FieldTrees()
    second = kernel._FieldTrees()
    first_node = first.field(TEXT, kernel.explicit.DEFINITION, "target")
    assert first.field(TEXT, kernel.explicit.DEFINITION, "target") is first_node
    assert second.field(TEXT, kernel.explicit.DEFINITION, "target") is not first_node


@pytest.mark.parametrize(
    "invalid",
    [
        "ai_strategy_default = { target = { value = 2 }",
        "ai_strategy_default = { other = 2 }",
        "ai_strategy_default = { target = 2 target = 3 }",
        "ai_strategy_default = { target = 2 } ai_strategy_default = { target = 3 }",
    ],
    ids=["parse-error", "missing-field", "ambiguous-field", "ambiguous-definition"],
)
def test_complete_field_cache_keeps_uncached_failure_after_valid_text(invalid):
    candidate = {"field_trees": kernel._FieldTrees()}
    kernel._field(candidate, TEXT, "target")
    for _ in range(2):
        with pytest.raises(AssertionError):
            kernel._field(candidate, invalid, "target")
        with pytest.raises(AssertionError):
            kernel.explicit._field(invalid, "target")


def test_complete_field_cache_does_not_hide_numeric_evaluation_failure():
    candidate = {"field_trees": kernel._FieldTrees()}
    invalid = "ai_strategy_default = { target = { value = 2 divide = 0 } }"
    for _ in range(2):
        with pytest.raises(pdx_eval.UnsupportedPdxError, match="除零"):
            kernel._complete_value(candidate, invalid, "target", {})
