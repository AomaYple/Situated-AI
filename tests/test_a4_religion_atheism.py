"""Production atheism transition through ordinary adapters and parsed PDX."""

import json
import re
from dataclasses import replace

import pytest
from test_a3_culture import _religious_facts
from test_remaining_joint_consumers import _block, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    culture_opportunities,
    decision_adapters,
    decision_interfaces,
    decision_rules,
)
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs, resources

FIELD = "law_total_separation.ai_enact_weight_modifier"
RULE = "culture_law_state_atheism_to_law_total_separation_observed_exposure"


@pytest.fixture
def candidate():
    return culture_opportunities


@pytest.fixture
def generated(candidate):
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[candidate.SOURCE]
    rules = tuple(r for r in original.rules if ".".join(r.field) == FIELD)
    keys = {k for r in rules for k in r.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in keys),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=candidate.SOURCE)
    decision_interfaces.validate(policy)
    frozen = json.loads(
        (candidate.config.REPO / "research/vanilla-ai/1.15.0/production-inputs.json").read_bytes()
    )
    inputs = frozen["inputs"]
    inputs.update(candidate.frozen_inputs())
    native = inputs[candidate.SOURCE]
    text = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    return candidate, policy, native, text


def witness(
    generated,
    *,
    state="atheist",
    current="law_state_atheism",
    need=True,
    authority=300,
    crisis=False,
    ai=True,
    unrelated_unknown=False,
):
    candidate, policy, _, text = generated
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        for prefix in ("culture_current_", "law_context_current_"):
            if key.startswith(prefix):
                law = key.removeprefix(prefix)
                values[key] = (
                    None
                    if current is None
                    else (
                        law == current
                        or (law == candidate.ORIGIN and current in candidate.VARIANTS)
                    )
                )
                if unrelated_unknown and law not in {"law_state_atheism", "law_total_separation"}:
                    values[key] = None
    values.update(
        authority=authority,
        legitimacy=20 if crisis else 60,
        radical_share=0.3 if crisis else 0,
        insurrection=crisis,
        culture_atheism_nonstate_exposure=need
        if state == "atheist"
        else None
        if state is None
        else False,
    )
    facts = _facts(policy, values, is_ai=ai)
    religion = _religious_facts(
        state=state, shares={"sunni": 0.1 if need else 0}, acceptance={"sunni": -1}
    )
    if need is None:
        religion["religion_percent_country"][(("target", "rel:sunni"),)] = None
    if state is None:
        religion["country_has_state_religion"] = dict.fromkeys(
            religion["country_has_state_religion"]
        )
    facts["ROOT"].update(religion)
    facts["ROOT"]["any_political_movement"] = []
    actual = pdx_eval.select(_overlay(text, FIELD), facts).delta
    reference = decision_rules.evaluate(policy, values, is_ai=ai).get(FIELD, ("neutral", 0))[1]
    return actual, reference


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, 6),
        ({"need": False}, 0),
        ({"need": None}, 0),
        ({"state": "catholic"}, 0),
        ({"state": None}, 0),
        ({"current": None}, 0),
        ({"current": "law_total_separation"}, 0),
        ({"ai": False}, 0),
        ({"authority": 199}, -2),
        ({"authority": 200}, 6),
        ({"authority": None}, 6),
        ({"unrelated_unknown": True}, 6),
        ({"authority": 199, "need": False}, -8),
        ({"authority": 199, "state": None}, -8),
        ({"authority": 199, "crisis": True}, -12),
    ],
)
def test_exact_joined_benefit_independent_cost_unknown_and_player(generated, kwargs, expected):
    assert witness(generated, **kwargs) == (expected, expected)


def test_same_object_query_boundaries_and_foreign_facts(candidate):
    query = candidate.compile_query(
        candidate.query_from_reader("OR", {"culture_query": "atheism_nonstate_exposure"}),
        candidate.frozen_inputs(),
    )
    parsed = parse_text(query.expression).root
    for state in candidate.RELIGIONS:
        for religion in candidate.RELIGIONS:
            for share, acceptance in ((0.1, -1), (0.09999, -1), (0.1, 0)):
                facts = _religious_facts(
                    state=state, shares={religion: share}, acceptance={religion: acceptance}
                )
                assert pdx_eval.condition(parsed, facts) is (
                    state == "atheist" and religion != "atheist" and share >= 0.1 and acceptance < 0
                )
    facts = _religious_facts(state="atheist", shares={"sunni": 0.2}, acceptance={"hindu": -10})
    facts["scope:target_country"] = _religious_facts(state="atheist")
    assert pdx_eval.condition(parsed, facts) is False
    metrics = resources.pdx_metrics(query.expression)
    assert metrics["max_depth"] <= 7
    assert metrics["object_scan_sites"] == metrics["persistent_write_sites"] == 0
    assert "52" in query.runtime_cost


def test_no_false_protection_loss_and_disabled_restoration(generated):
    _candidate, policy, native, text = generated
    added = [r for r in policy.rules if r.id == RULE]
    assert len(added) == 1
    assert added[0].semantic_role == "benefit"
    assert not any("atheism" in r.id and "protection" in r.id for r in policy.rules)
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]
    for kwargs, expected in (
        ({}, 6),
        ({"current": "law_total_separation"}, 0),
        ({"need": False}, 0),
        ({"state": None}, 0),
        ({}, 6),
    ):
        assert witness(generated, **kwargs) == (expected, expected)


def test_full_native_numeric_tail_and_player(generated):
    _candidate, policy, _, text = generated
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        if key.endswith("law_state_atheism") and key.startswith(
            ("culture_current_", "law_context_current_")
        ):
            values[key] = True
    values.update(
        authority=300,
        legitimacy=60,
        radical_share=0,
        insurrection=False,
        culture_atheism_nonstate_exposure=True,
    )
    facts = _facts(policy, values, is_ai=True)
    facts["ROOT"].update(_religious_facts(state="atheist"))
    facts["ROOT"]["any_political_movement"] = []
    facts["ROOT"]["ai_has_enact_weight_modifier_journal_entries"] = True
    body = _block(_block(parse_text(text).root, "law_total_separation"), "ai_enact_weight_modifier")
    expression = "\n".join(_render(item) for item in body.assignments())
    projected = (
        "# ACTION full_native [native]; complete locked law\nif = { limit = { always = yes } add = { "
        + expression
        + " } }"
    )
    ai_score = pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta
    facts["ROOT"]["is_ai"] = False
    player_score = pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta
    assert ai_score - player_score == 6


def test_source_lock_and_repinned_ast_drift(candidate):
    inputs = candidate.frozen_inputs()
    changed = dict(inputs)
    changed[candidate.SOURCE] = inputs[candidate.SOURCE].replace(
        "set_state_religion = rel:atheist", "set_state_religion = rel:catholic"
    )
    with pytest.raises(ValueError, match="漂移"):
        candidate.verify_inputs(changed)
    # Even independently repinning the complete input must not erase the exact
    # consumer/activation AST contract enforced after the source lock.
    for old, new in (
        ("country_has_state_religion = rel:mahayana", "country_has_state_religion = rel:sunni"),
        ("set_state_religion = root.country_definition.religion", "set_state_religion = rel:sunni"),
        ("value = 0.1", "value = 0.2"),
    ):
        root = parse_text(inputs[candidate.SOURCE].replace(old, new)).root
        with pytest.raises(ValueError, match="漂移"):
            candidate._verify_atheism_transition(root)


def test_existing_budget_enforced(candidate, monkeypatch):
    monkeypatch.setattr(candidate.religious_channels, "MAX_PREDICATES", 51)
    with pytest.raises(ValueError, match="预算"):
        candidate.render_query(candidate.ReligiousExposureQuery("atheism_nonstate_exposure"))


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("AND", {"culture_query": "atheism_nonstate_exposure"}),
        ("OR", {"culture_query": "atheism_nonstate_exposure", "target": "scope:target_country"}),
        ("OR", {"culture_query": "atheism_nonstate_exposure", "threshold": "0"}),
    ],
)
def test_closed_shape_rejects_expansion(candidate, engine, parameters):
    with pytest.raises(ValueError, match="宗教暴露"):
        candidate.query_from_reader(engine, parameters)
