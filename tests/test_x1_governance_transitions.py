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
from test_law_opportunities import _policy
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import config, decision_interfaces, decision_rules, law_opportunities, observation_queries
from pdx.situated import pdx_eval

pytestmark = pytest.mark.integration
LABOUR = "common/laws/02_labour_associations.txt"


@pytest.fixture(scope="module")
def focused():
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
    policies, files = {}, {}
    for source in law_opportunities.load()["sources"]:
        policy = replace(
            _policy(derived, source),
            baseline_sha256=hashlib.sha256(inputs[source].encode()).hexdigest(),
        )
        policies[source] = policy
        files[source] = decision_rules.patch(
            inputs[source],
            policy,
            baseline=inputs[source],
            default_strategy=False,
            reader_words=decision_interfaces.proven_reader_words()
            | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
        )
        assert (
            decision_rules.patch(
                inputs[source],
                policy,
                baseline=inputs[source],
                default_strategy=False,
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
