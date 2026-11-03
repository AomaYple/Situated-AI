"""Prepared independent PDX evaluation preserves fresh observations and failures."""

from copy import deepcopy

import pytest

from pdx.situated import pdx_eval

pytestmark = pytest.mark.unit

SCRIPT = """# ACTION joint [test];
if = { limit = { ROOT = { is_ai = yes } } multiply = {
    value = 1
    if = { limit = { ROOT = { need > 0 } } add = 0.2 }
    if = { limit = { ROOT = { cost > 0 } } add = -0.3 }
    min = 0.5 max = 1.5
} }
"""


def test_prepared_program_parses_once_but_does_not_cache_observations(monkeypatch):
    original = pdx_eval.parse_text
    calls = []

    def parse(text, *, path):
        calls.append((text, path))
        return original(text, path=path)

    monkeypatch.setattr(pdx_eval, "parse_text", parse)
    program = pdx_eval.prepare(SCRIPT, path="consumer")
    facts = {"ROOT": {"is_ai": True, "need": 1, "cost": 0}}
    before = deepcopy(facts)
    assert program.select(facts).delta == pytest.approx(1.2)
    assert facts == before
    facts["ROOT"]["cost"] = 1
    assert program.select(facts).delta == pytest.approx(0.9)
    facts["ROOT"]["is_ai"] = False
    assert program.select(facts).fallback == "vanilla"
    assert len(calls) == 1


@pytest.mark.parametrize("ai", [True, False, None])
@pytest.mark.parametrize("need", [0, 1, None])
@pytest.mark.parametrize("cost", [0, 1, None])
def test_prepared_and_fresh_paths_match_for_all_observations(ai, need, cost):
    facts = {"ROOT": {"is_ai": ai, "need": need, "cost": cost}}
    before = deepcopy(facts)
    prepared = pdx_eval.prepare(SCRIPT)
    assert prepared.evaluate(facts) == pdx_eval.evaluate(SCRIPT, facts)
    assert prepared.select(facts) == pdx_eval.select(SCRIPT, facts)
    assert facts == before


def test_prepared_source_changes_and_runtime_failures_are_not_hidden():
    assert pdx_eval.prepare(SCRIPT).select({"ROOT": {"is_ai": True, "need": 1}}).delta == 1.2
    changed = SCRIPT.replace("add = 0.2", "add = 0.4")
    assert pdx_eval.prepare(changed).select({"ROOT": {"is_ai": True, "need": 1}}).delta == 1.4
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.prepare(SCRIPT.rstrip()[:-1])
    # Both entry points reject unsupported effects; preparation must not
    # execute or retain observations.
    malformed = SCRIPT.replace("min = 0.5", "invalid_operation = 0.5")
    for evaluator in (
        lambda f: pdx_eval.prepare(malformed).select(f),
        lambda f: pdx_eval.select(malformed, f),
    ):
        with pytest.raises(pdx_eval.UnsupportedPdxError):
            evaluator({"ROOT": {"is_ai": True, "need": 1}})
    parameter = (
        "# ACTION typed [test];\nif = { limit = { has_law_or_variant = law_type:law_x } add = 1 }"
    )
    program = pdx_eval.prepare(parameter)
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="映射"):
        program.select({"has_law_or_variant": True})
