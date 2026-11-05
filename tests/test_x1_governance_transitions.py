"""Hand-built X1 governance witnesses through the actual production patcher.

Focused policies use the same derivation, contribution program and native
insertion path as production, without constructing the unrelated full model.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    law_opportunities,
    observation_queries,
)
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.integration
LABOUR = "common/laws/02_labour_associations.txt"


def build_focused():
    raw = tomllib.loads((config.REPO / "mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    derived = law_opportunities.derive(raw)
    sources = set(raw["sources"]) | set(law_opportunities.load()["sources"])
    for reader in derived["readers"].values():
        if reader["engine"] in observation_queries.QUERY_ENGINES:
            query = observation_queries.from_reader(reader["engine"], reader.get("parameters", {}))
            sources.update(observation_queries.required_sources(query))
    inputs = {source: (config.GAME / source).read_text(encoding="utf-8-sig") for source in sources}
    law_opportunities.verify_inputs(inputs)
    for reader in derived["readers"].values():
        if reader["engine"] in observation_queries.QUERY_ENGINES:
            observation_queries.compile_query(
                observation_queries.from_reader(reader["engine"], reader.get("parameters", {})),
                inputs,
            )
    actual_policies = dict(decision_adapters.load().policies)
    policies, files = {}, {}
    for source in law_opportunities.load()["sources"]:
        policy = replace(
            programs.enable(actual_policies[source], source=source),
            baseline_sha256=hashlib.sha256(inputs[source].encode()).hexdigest(),
        )
        policies[source] = policy
        files[source] = decision_rules.patch(
            inputs[source],
            policy,
            baseline=inputs[source],
            default_strategy=False,
            country_policy=country_state.load(),
            reader_words=decision_interfaces.proven_reader_words()
            | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
        )
        assert (
            decision_rules.patch(
                inputs[source],
                policy,
                baseline=inputs[source],
                default_strategy=False,
                country_policy=country_state.load(),
                enabled_domains=frozenset(),
            )
            == inputs[source]
        )
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            files[source],
            flags=re.DOTALL,
        )
        # Every native token, including eligibility, petitions, ai_will_do and
        # terminal zero paths, survives the protected insertion unchanged.
        from pdx.lexer import tokenize

        assert [(t.kind, t.value) for t in tokenize(stripped)] == [
            (t.kind, t.value) for t in tokenize(inputs[source])
        ]
    return policies, files, inputs


@pytest.fixture(scope="module")
def focused():
    return build_focused()


def witness(focused, law, changes, expected, *, support=0.1, is_ai=True):
    policies, files, _inputs = focused
    source = law_opportunities.load()["candidates"][law]
    policy = policies[source]
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    values.update(legitimacy=60, union_approval=0, authority=0)
    movements = [] if support is None else [(law, support)]
    for reader in policy.readers:
        if reader.engine == "any_political_movement":
            params = dict(reader.parameters)
            values[reader.key] = any(
                candidate == params["law"] and strength >= float(params["minimum_support"])
                for candidate, strength in movements
            )
    values.update(changes)
    field = f"{law}.ai_enact_weight_modifier"
    result = decision_rules.evaluate(policy, values, is_ai=is_ai).get(field)
    assert (result[1] if result else 0) == expected
    facts = _facts(policy, values, is_ai=is_ai)
    facts["ROOT"]["any_political_movement"] = [
        {
            "law_enactment_stance": {
                (("law", "law_type:" + item),): int(item == candidate)
                for item in law_opportunities.load()["candidates"]
            },
            "political_movement_support": strength,
        }
        for candidate, strength in movements
    ]
    for key, value in changes.items():
        if key.endswith("_movement_base") and value is None:
            facts["ROOT"].pop("any_political_movement", None)
    facts["ROOT"]["any_scope_state"] = (
        None
        if changes.get("owned_state_turmoil", False) is None
        else [{"turmoil": 0.2}]
        if changes.get("owned_state_turmoil")
        else []
    )
    observed = pdx_eval.select(_overlay(files[source], field), facts)
    assert observed.delta == expected
    return facts


RIGHT = "law_right_to_associate"
COMBINATION = {"law_context_current_law_combination_acts": True}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 6),
        (COMBINATION, 6),
        ({**COMBINATION, "radical_share": 0.25}, 14),
        ({**COMBINATION, "radical_share": 0.249}, 6),
        ({**COMBINATION, "radical_share": None}, 6),
        ({"law_context_current_law_right_to_associate": True}, 0),
        ({"law_context_current_law_combination_acts": None}, 6),
        ({**COMBINATION, "union_clout": 0.2, "union_approval": -1}, 0),
        ({**COMBINATION, "union_clout": 0.2, "union_approval": -1, "union_government": True}, -3),
        ({**COMBINATION, "union_clout": 0.199, "union_approval": -1}, 6),
        ({**COMBINATION, "union_clout": 0.8, "union_approval": 0}, 6),
        ({**COMBINATION, "union_clout": None, "union_approval": -1}, 6),
        ({**COMBINATION, "union_clout": 0.8, "union_approval": None}, 6),
        ({**COMBINATION, "union_clout": 0.2, "union_approval": -1, "union_government": None}, 0),
        ({**COMBINATION, "radical_share": 0.3, "legitimacy": 24, "insurrection": True}, 4),
        (
            {
                **COMBINATION,
                "radical_share": 0.3,
                "legitimacy": 24,
                "insurrection": True,
                "union_clout": 0.2,
                "union_approval": -1,
                "union_government": True,
            },
            -5,
        ),
    ],
)
def test_g1_actual_transition_joint_reference_and_generated(focused, changes, expected):
    witness(focused, RIGHT, changes, expected)


@pytest.mark.parametrize("support", [0.1, 0.25])
def test_g1_known_adoption_withdraws_exact_agenda_tier_without_native_change(focused, support):
    witness(
        focused, RIGHT, {"law_context_current_law_right_to_associate": True}, 0, support=support
    )
    witness(
        focused,
        RIGHT,
        {"law_context_current_law_right_to_associate": None},
        6 if support == 0.1 else 10,
        support=support,
    )


def test_g1_negative_and_unknown_are_local_and_factory_native_refusal_survives(focused):
    witness(focused, RIGHT, COMBINATION, 0, support=None)
    witness(focused, RIGHT, {**COMBINATION, "radical_share": 0.3}, 0, support=None)
    witness(
        focused, RIGHT, {**COMBINATION, "union_clout": 0.2, "union_approval": -1}, -6, support=None
    )
    witness(focused, RIGHT, {f"law_context_{RIGHT}_movement_base": None}, 0, support=None)
    witness(focused, RIGHT, COMBINATION, 0, is_ai=False)
    witness(
        focused,
        "law_combination_acts",
        {
            "law_context_current_law_right_to_associate": True,
            "radical_share": 0.3,
        },
        0,
    )  # +6 agenda, -6 actual radicalization deterioration.
    witness(focused, "law_factory_councils", {}, 6)
    native = focused[2][LABOUR]
    assert "is_revolutionary = yes" in native
    assert re.search(r"law_factory_councils.*ai_will_do\s*=\s*\{\s*always = no", native, re.DOTALL)


def test_g1_complete_source_drift_is_hard_failure(focused):
    with pytest.raises(ValueError, match="漂移"):
        law_opportunities.verify_inputs({**focused[2], LABOUR: focused[2][LABOUR] + "\n"})


MULTICULTURAL = "law_multicultural"


@pytest.mark.parametrize(
    ("origin", "balance", "expected"),
    [
        ("law_ethnostate", 0, -2),
        ("law_ethnostate", 199, -2),
        ("law_ethnostate", 200, 6),
        ("law_cultural_exclusion", 49, -2),
        ("law_cultural_exclusion", 50, 6),
        ("law_cultural_exclusion", 100, 6),
        ("law_national_supremacy", 149, -2),
        ("law_national_supremacy", 150, 6),
        ("law_racial_segregation", 99, -2),
        ("law_racial_segregation", 100, 6),
        ("law_subjecthood", 99, -2),
        ("law_subjecthood", 100, 6),
        ("law_ethnostate", None, 6),
        ("law_multicultural", -1, 0),
    ],
)
def test_g2_actual_authority_loss_uses_current_difference(focused, origin, balance, expected):
    witness(
        focused,
        MULTICULTURAL,
        {
            f"law_context_current_{origin}": True,
            "authority": balance,
        },
        expected,
    )


@pytest.mark.parametrize(
    "law",
    [
        "law_ethnostate",
        "law_national_supremacy",
        "law_racial_segregation",
        "law_cultural_exclusion",
        "law_multicultural",
        "law_state_religion",
        "law_millet_system",
        "law_people_of_the_book",
        "law_freedom_of_conscience",
        "law_total_separation",
        "law_state_atheism",
    ],
)
def test_g2_all_eleven_real_agendas_adoption_unknown_player_and_no_agenda(focused, law):
    witness(focused, law, {}, 6)
    witness(focused, law, {}, 10, support=0.25)
    witness(focused, law, {}, 0, support=None)
    witness(focused, law, {}, 0, is_ai=False)
    witness(focused, law, {f"law_context_current_{law}": True}, 0, support=0.25)
    witness(focused, law, {f"law_context_current_{law}": None}, 6)


@pytest.mark.parametrize(
    ("law", "origin", "balance", "expected"),
    [
        ("law_ethnostate", "law_multicultural", -1, 12),
        ("law_ethnostate", "law_multicultural", 0, 6),
        ("law_ethnostate", "law_multicultural", None, 6),
        ("law_total_separation", "law_state_religion", 199, -2),
        ("law_total_separation", "law_millet_system", 199, -2),
        ("law_total_separation", "law_people_of_the_book", 200, 6),
        ("law_total_separation", "law_state_atheism", 199, -2),
        ("law_freedom_of_conscience", "law_millet_system", 99, -2),
        ("law_freedom_of_conscience", "law_millet_system", 100, 6),
        ("law_state_atheism", "law_state_religion", -1, 6),
        ("law_state_religion", "law_total_separation", -1, 12),
    ],
)
def test_g2_religion_variants_and_reverse_recovery(focused, law, origin, balance, expected):
    witness(focused, law, {f"law_context_current_{origin}": True, "authority": balance}, expected)


def test_g2_unknown_agenda_preserves_authority_cost_and_parent_variants_do_not_double(focused):
    witness(
        focused,
        MULTICULTURAL,
        {
            "law_context_current_law_ethnostate": True,
            "authority": 0,
            f"law_context_{MULTICULTURAL}_movement_base": None,
        },
        -8,
        support=None,
    )
    witness(
        focused,
        "law_total_separation",
        {
            "law_context_current_law_state_religion": True,
            "law_context_current_law_millet_system": True,
            "authority": 199,
        },
        -2,
    )
    witness(
        focused,
        MULTICULTURAL,
        {
            "law_context_current_law_ethnostate": True,
            "authority": 0,
            "legitimacy": 24,
            "insurrection": True,
            "radical_share": 0.3,
        },
        -12,
    )
    assert "law_subjecthood" not in law_opportunities.load()["candidates"]
    for source in ("common/laws/00_citizenship.txt", "common/laws/00_church_and_state.txt"):
        with pytest.raises(ValueError, match="漂移"):
            observation_queries.compile_query(
                observation_queries.LawMovementSupport(
                    "law_multicultural" if "citizenship" in source else "law_total_separation"
                ),
                {**focused[2], source: focused[2][source] + "\n"},
            )


@pytest.mark.parametrize(
    ("origin", "candidate", "expected"),
    [
        ("local", "no", 0),
        ("local", "local", 0),
        ("local", "dedicated", 6),
        ("local", "militarized", -2),
        ("dedicated", "no", 0),
        ("dedicated", "local", 6),
        ("dedicated", "dedicated", 0),
        ("dedicated", "militarized", -2),
        ("militarized", "no", 8),
        ("militarized", "local", 14),
        ("militarized", "dedicated", 14),
        ("militarized", "militarized", 0),
    ],
)
def test_g3_full_existing_transition_matrix(focused, origin, candidate, expected):
    witness(
        focused,
        f"law_{candidate}_police",
        {
            f"law_context_current_law_{origin}_police": True,
            "owned_state_turmoil": True,
            "radical_share": 0.3,
            "police_investment": 1,
        },
        expected,
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"police_investment": 0}, 6),
        ({"police_investment": 1}, -2),
        ({"police_investment": 3}, -6),
        ({"police_investment": 5}, -6),  # No assertion that three is the maximum.
        ({"police_investment": None}, 6),
        ({"owned_state_turmoil": False}, 6),
        ({"owned_state_turmoil": None}, 6),
        ({"law_context_current_law_dedicated_police": None}, 6),
        ({"bureaucracy": -1, "default": True}, -2),  # Existing same-price institution.
    ],
)
def test_g3_militarized_risk_uses_actual_investment_and_local_unknown(focused, changes, expected):
    witness(
        focused,
        "law_militarized_police",
        {
            "law_context_current_law_dedicated_police": True,
            "owned_state_turmoil": True,
            "police_investment": 1,
            **changes,
        },
        expected,
    )


@pytest.mark.parametrize(
    ("origin", "candidate", "investment", "turmoil", "expected"),
    [
        ("local", "dedicated", 0, True, 6),
        ("local", "dedicated", 1, True, 0),
        ("local", "dedicated", 3, True, -3),
        ("local", "dedicated", 1, False, 6),
        ("local", "dedicated", 1, None, 6),
        ("militarized", "dedicated", 0, True, 6),
        ("militarized", "dedicated", 1, True, 14),
        ("militarized", "dedicated", 3, True, 18),
        ("militarized", "dedicated", 1, False, 6),
        ("dedicated", "militarized", 3, False, 6),
    ],
)
def test_g3_protection_and_mortality_are_distinct_actual_differences(
    focused, origin, candidate, investment, turmoil, expected
):
    witness(
        focused,
        f"law_{candidate}_police",
        {
            f"law_context_current_law_{origin}_police": True,
            "owned_state_turmoil": turmoil,
            "police_investment": investment,
        },
        expected,
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 6),
        ({"bureaucracy": -1}, 0),
        ({"default": True}, -2),
        ({"bureaucracy": -1, "default": True}, -8),
        ({"bureaucracy": 0}, 6),
        # Known absence of police anchors the new institution. Missing cost
        # pressure keeps its finite conservative tier: +6 -6 -8 = -8.
        ({"bureaucracy": None, "default": True}, -8),
        ({"bureaucracy": -1, "default": None}, -8),
        ({"law_context_current_law_no_police": None, "bureaucracy": -1, "default": True}, 6),
    ],
)
def test_g3_new_institution_administration_and_default_are_independent(focused, changes, expected):
    witness(
        focused,
        "law_dedicated_police",
        {
            "law_context_current_law_no_police": True,
            "police_investment": 0,
            **changes,
        },
        expected,
    )


def test_g3_unknown_agenda_preserves_risk_and_native_refusals(focused):
    law = "law_militarized_police"
    witness(
        focused,
        law,
        {
            "law_context_current_law_local_police": True,
            "police_investment": 1,
            "owned_state_turmoil": True,
            f"law_context_{law}_movement_base": None,
        },
        -14,
        support=None,
    )
    witness(
        focused,
        law,
        {
            "law_context_current_law_local_police": True,
            "police_investment": 3,
            "owned_state_turmoil": True,
            "radical_share": 0.3,
            "legitimacy": 24,
            "insurrection": True,
        },
        -17,
    )
    for law in (
        "law_no_police",
        "law_local_police",
        "law_dedicated_police",
        "law_militarized_police",
    ):
        witness(focused, law, {}, 0, support=None)
        witness(focused, law, {}, 0, is_ai=False)
        witness(focused, law, {f"law_context_current_{law}": True}, 0, support=0.25)
    source = "common/laws/01_policing.txt"
    with pytest.raises(ValueError, match="漂移"):
        observation_queries.compile_query(
            observation_queries.LawMovementSupport(law),
            {**focused[2], source: focused[2][source] + "\n"},
        )
