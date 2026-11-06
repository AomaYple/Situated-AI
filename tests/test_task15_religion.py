"""Exact finite transitions through the real parser/program/PDX writer."""

import re
from dataclasses import replace

import pytest
from test_a3_culture import _religious_facts
from test_remaining_joint_consumers import _block, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx import culture_opportunities as culture
from pdx.lexer import tokenize
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs, resources


@pytest.fixture(scope="module")
def generated():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[culture.SOURCE]
    fields = {culture.FIELD, "law_total_separation.ai_enact_weight_modifier"}
    rules = tuple(rule for rule in original.rules if ".".join(rule.field) in fields)
    used = {key for rule in rules for key in rule.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=culture.SOURCE)
    decision_interfaces.validate(policy)
    inputs = decision_adapters.read_inputs(adapters)
    native = inputs[culture.SOURCE]
    text = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    return policy, native, text


def witness(
    generated,
    *,
    current=culture.ORIGIN,
    candidate=culture.CANDIDATE,
    need=True,
    protection=True,
    authority=300,
    crisis=False,
    ai=True,
):
    policy, _native, text = generated
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        for prefix in ("culture_current_", "law_context_current_"):
            if key.startswith(prefix):
                law = key.removeprefix(prefix)
                values[key] = current is not None and (
                    law == current or (law == culture.ORIGIN and current in culture.VARIANTS)
                )
    values.update(
        authority=authority,
        legitimacy=20 if crisis else 60,
        radical_share=0.3 if crisis else 0,
        insurrection=crisis,
        culture_nonstate_religious_exposure=need,
        culture_state_religious_protection_exposure=protection,
    )
    facts = _facts(policy, values, is_ai=ai)
    religious = _religious_facts(
        shares={"sunni": 0.1 if need else 0, "catholic": 0.7 if protection else 0},
        acceptance={"sunni": -1, "catholic": 25},
    )
    if need is None:
        religious["religion_percent_country"][(("target", "rel:sunni"),)] = None
    if protection is None:
        religious["religion_percent_country"][(("target", "rel:catholic"),)] = None
    facts["ROOT"].update(religious)
    facts["ROOT"]["any_political_movement"] = []
    field = candidate + ".ai_enact_weight_modifier"
    overlay = _overlay(text, field)
    actual = pdx_eval.select(overlay, facts).delta
    reference = decision_rules.evaluate(policy, values, is_ai=ai).get(field, ("neutral", 0))[1]
    return actual, reference, facts, values, field


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, 2),  # +6 distinct nonstate need, -4 independent state protection.
        ({"protection": False}, 6),
        ({"need": False}, -4),
        ({"need": False, "protection": False}, 0),
        ({"protection": None}, 2),  # Exact conversion core known: bounded conservative loss.
        ({"need": None}, -4),
        ({"authority": 99}, -6),  # +6-4-8: authority cannot hide protection loss.
        ({"authority": 99, "crisis": True}, -16),
        ({"current": "law_caesaropapism"}, 2),
        ({"candidate": "law_total_separation"}, 2),
        ({"current": "law_caesaropapism", "candidate": "law_total_separation"}, 2),
        ({"current": "law_millet_system", "candidate": "law_total_separation"}, 2),
        ({"current": "law_people_of_the_book", "candidate": "law_total_separation"}, 2),
        ({"current": "law_millet_system", "candidate": "law_total_separation", "need": False}, -4),
        (
            {
                "current": "law_people_of_the_book",
                "candidate": "law_total_separation",
                "protection": False,
            },
            6,
        ),
        ({"candidate": "law_total_separation", "authority": 199}, -6),
        ({"current": "law_millet_system"}, 0),
        ({"current": "law_people_of_the_book"}, 0),
        ({"current": culture.CANDIDATE}, 0),
        ({"current": "law_total_separation", "candidate": "law_total_separation"}, 0),
        ({"current": None}, 0),
        ({"ai": False}, 0),
    ],
)
def test_real_rule_parser_scalar_program_and_parsed_pdx(generated, kwargs, expected):
    actual, reference, *_ = witness(generated, **kwargs)
    assert actual == reference == expected


@pytest.mark.parametrize("origin", ["law_millet_system", "law_people_of_the_book"])
def test_added_transition_enter_adopt_exit_restore_unknown(generated, origin):
    steps = [
        ({"current": origin}, 2),
        ({"current": "law_total_separation"}, 0),
        ({"current": origin, "need": False}, -4),
        ({"current": origin, "need": False, "protection": False}, 0),
        ({"current": origin, "protection": False}, 6),
        ({"current": None}, 0),
        ({"current": origin}, 2),
    ]
    for state, expected in steps:
        actual, reference, *_ = witness(generated, candidate="law_total_separation", **state)
        assert actual == expected
        assert reference == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("nonstate_religious_exposure", True),
        ("state_religious_protection_exposure", True),
    ],
)
def test_finite_queries_keep_same_country_same_religion_and_unknown(mode, expected):
    query = culture.query_from_reader("OR", {"culture_query": mode})
    compiled = culture.compile_query(query, culture.frozen_inputs())
    facts = _religious_facts(
        shares={"sunni": 0.1, "catholic": 0.7}, acceptance={"sunni": -1, "catholic": 25}
    )
    block = parse_text(compiled.expression).root
    assert pdx_eval.condition(block, facts) is expected
    facts["religion_percent_country"][(("target", "rel:catholic"),)] = 0
    facts["country_average_religious_acceptance"][(("target", "rel:sunni"),)] = 25
    assert pdx_eval.condition(block, facts) is False
    facts["religion_percent_country"][(("target", "rel:catholic"),)] = None
    facts["country_average_religious_acceptance"][(("target", "rel:sunni"),)] = None
    assert pdx_eval.condition(block, facts) is None
    metrics = resources.pdx_metrics(compiled.expression)
    assert metrics["object_scan_sites"] == metrics["persistent_write_sites"] == 0
    disjunction = parse_text(compiled.expression).root.first("OR")
    assert disjunction is not None
    assert isinstance(disjunction.value, Block)
    assert len(disjunction.value.all("AND")) == 17


def test_native_complete_numeric_ast_journal_paths_player_and_domain_off(generated):
    policy, native, text = generated
    for candidate, base in ((culture.CANDIDATE, 1750), ("law_total_separation", 750)):
        actual, reference, facts, values, _field = witness(generated, candidate=candidate)
        facts["ROOT"].update(
            ai_has_enact_weight_modifier_journal_entries=True,
            has_journal_entry={
                (("argument", "je_sick_man_education"),): True,
                (("argument", "je_shinbutsu_bunri"),): False,
            },
        )
        body = _block(_block(parse_text(text).root, candidate), "ai_enact_weight_modifier")
        expression = "\n".join(_render(item) for item in body.assignments())
        projected = (
            "# ACTION complete_native [native]; complete locked consumer\n"
            "if = { limit = { always = yes } add = { " + expression + " } }"
        )
        assert pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta == base + 2
        player = {**facts, "ROOT": {**facts["ROOT"], "is_ai": False}}
        assert pdx_eval.select(projected, {**player["ROOT"], **player}).delta == base
        assert actual == reference == 2
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
    disabled = decision_rules.patch(
        native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
    )
    assert disabled == native
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]


def test_actual_effect_matrix_and_local_lifecycle(generated):
    culture.verify_inputs(culture.frozen_inputs())
    assert tuple(
        b - a
        for a, b in zip(
            culture.EFFECTS[culture.ORIGIN], culture.EFFECTS["law_total_separation"], strict=True
        )
    ) == (-10, 15, 25, 40)
    # Preference is not adoption: actual need/protection/authority each exit locally.
    for kwargs, expected in (
        ({}, 2),
        ({"authority": 99}, -6),
        ({"need": False, "authority": 99}, -12),
        ({"need": False}, -4),
        ({"need": False, "protection": False}, 0),
        ({"current": culture.CANDIDATE}, 0),
    ):
        assert witness(generated, **kwargs)[:2] == (expected, expected)


@pytest.mark.parametrize(
    "params",
    [
        {"culture_query": "state_religious_protection_exposure", "target": "scope:target_country"},
        {"culture_query": "state_religious_protection_exposure", "threshold": "0"},
        {"culture_query": "mixed_trait_benefit"},
    ],
)
def test_no_free_query_authority(params):
    with pytest.raises(ValueError, match="宗教暴露"):
        culture.query_from_reader("OR", params)
