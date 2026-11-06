"""Literal marginal costs, current shared ports, and actual parsed native PDX."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_a3_colonial as colonial_tests
import test_a3_import_blockade as supply
import test_a3_war_pressure as pressure_tests
from conquest_physical_reference import number
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render

from pdx import config, country_state, decision_adapters, decision_interfaces, decision_rules
from pdx import treaty_acceptance_opportunities as acceptance
from pdx import war_pressure_opportunities as pressure
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import decision_ir, pdx_eval
from pdx.situated import external_security_ports as external


@pytest.fixture(scope="module")
def adapters():
    return decision_adapters.load()


@pytest.fixture(scope="module")
def writer_rows():
    raw = json.loads(
        (
            config.REPO / "research/vanilla-ai/1.15.0/classification/current/migration_writers.json"
        ).read_bytes()
    )
    result = {}
    for row in raw.values():
        context = row.get("evaluation_context")
        if row["kind"] != "rule_action" or not context or context["status"] != "observed":
            continue

        def bind(value):
            return decision_ir.ContextBinding(**value)

        typed = decision_ir.EvaluationContext(
            bind(context["actor_scope"]),
            tuple(bind(r) for r in context["targets"]),
            tuple(bind(r) for r in context["auxiliary_scopes"]),
            tuple(context["evidence"]),
        )
        result[(row["source"], row["definition"])] = SimpleNamespace(
            source=row["source"],
            definition=row["definition"],
            kind="rule_action",
            field=row["field"],
            evaluation_context=typed,
            reader_context_bindings=tuple(tuple(r) for r in row["reader_context_bindings"]),
        )
    return result


def narrow(original, rules):
    used = {key for rule in rules for key in rule.input_keys()}
    return replace(
        original,
        rules=tuple(rules),
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
        port_bindings=(),
        rule_relation_bindings=(),
        enabled_domains=frozenset(r.domain for r in rules),
    )


def bind_policy(source, policy, writer_rows):
    selected = {(source, ".".join(rule.field)) for rule in policy.rules}
    return external.bind(
        ((source, policy),),
        selected_consumers=selected,
        writers=tuple(writer_rows[(source, r.id)] for r in policy.rules),
        hard_cap={"ports": 4096, "origins": 2048, "uses": 2048, "partitions": 256},
    )


def patch(_source, policy, native):
    decision_interfaces.validate(policy)
    return decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(
            decision_adapters.reader_evidence(
                decision_adapters.read_inputs(decision_adapters.load())
            )
        )
        | frozenset(
            re.findall(
                r"[A-Za-z_][A-Za-z_0-9:]*",
                native
                + "\n"
                + "\n".join(acceptance.frozen_inputs().values())
                + "\n"
                + "\n".join(colonial_tests.colonial.frozen_inputs().values()),
            )
        ),
    )


@pytest.fixture(scope="module")
def conquest(adapters, writer_rows):
    original = dict(adapters.policies)[pressure.SOURCE]
    ids = {
        pressure.RULE,
        "target_strategy_goal_conquer_state_reconstruction",
        "target_strategy_goal_conquer_state_default",
    }
    policy = narrow(original, tuple(r for r in original.rules if r.id in ids))
    assert {r.id for r in policy.rules} == ids
    (ported,), batch = bind_policy(pressure.SOURCE, policy, writer_rows)
    policy = ported[1]
    native = pressure.frozen_inputs()[pressure.SOURCE]
    text = patch(pressure.SOURCE, policy, native)
    return policy, batch, native, text, _overlay(text, pressure.FIELD)


@pytest.mark.parametrize(
    ("supports", "defeat", "default", "population", "expected"),
    [
        ([49, 49], False, False, 1, 17),
        ([49, 50], False, False, 1, 20),
        ([], True, False, 1, 18),
        ([49, 49], True, False, 1, 15),
        ([49, 49], True, True, 1, 12),
        ([49, 49], False, True, 1, 14),
        ([49, None], True, False, 1, 18),
        ([100, None], True, False, 1, 18),
        ([49, None, 49], True, False, 1, 15),
        ([49, 49], None, False, 1, 17),
        ([49, 49], True, None, 1, 12),
        ([49, 49], True, False, None, 20),
        ([49, 49], True, False, 0, 20),
        ([50, 50], False, False, 1, 20),
    ],
)
def test_independent_current_commitment_recovery_and_financing_literal_pdx(
    conquest, supports, defeat, default, population, expected
):
    policy, _, _, _, overlay = conquest
    low = sum(x is not None and x < 50 for x in supports)
    missing = sum(x is None for x in supports)
    observed = True if low >= 2 else False if low + missing < 2 else None
    values = {
        pressure.READER: observed,
        "war_defeat": defeat,
        "default": default,
        "prospective_subject_population": population,
    }
    root = pressure_tests._country(supports)
    root.update(
        is_ai=True, in_default=default, has_variable={(("argument", "recently_lost_war"),): defeat}
    )
    env = {"ROOT": root, "scope:target_country": {"total_population": population}}
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(pressure.FIELD, ("add", 0))[
        1
    ]
    assert 20 + reference == expected
    assert _native_number(20, overlay, env) == expected
    assert len(policy.consumer_programs) == 1
    groups = {r.contribution_group for r in policy.rules}
    assert groups == {
        "ongoing_multiwar_commitment_cost",
        "target_reconstruction_opportunity",
        "target_financing",
    }


def test_current_cost_and_memory_have_separate_real_exit_and_own_identity(conquest):
    policy, _, _, _, overlay = conquest
    env = {
        "ROOT": pressure_tests._country([49, 49]),
        "scope:target_country": {"total_population": 1},
    }
    env["ROOT"].update(
        is_ai=True, in_default=False, has_variable={(("argument", "recently_lost_war"),): True}
    )
    assert _native_number(20, overlay, env) == 15
    env["ROOT"]["any_scope_war"] = []
    assert _native_number(20, overlay, env) == 18
    env["ROOT"]["has_variable"][(("argument", "recently_lost_war"),)] = False
    assert _native_number(20, overlay, env) == 20
    # Enemy support remains low in both own wars; own support is healthy.
    env["ROOT"]["any_scope_war"] = pressure_tests._country([100, 100])["any_scope_war"]
    assert _native_number(20, overlay, env) == 20
    env["scope:target_country"].update(pressure_tests._country([0, 0]))
    env["ROOT"].pop("any_scope_war")
    assert _native_number(20, overlay, env) == 20
    assert decision_rules.evaluate(policy, {}, is_ai=False) == {}
    assert decision_rules.evaluate(policy, {}, is_ai=True, enabled_domains=frozenset()) == {}


def test_original_complete_conquest_tail_zero_and_saturation_unchanged(conquest):
    policy, _, native, text, overlay = conquest
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]
    original = _block(
        _block(_block(parse_text(native).root, "ai_strategy_default"), "wargoal_scores"),
        "conquer_state",
    )
    zeroes = original.all("if")[1:3]
    body = (
        overlay
        + "\n"
        + "\n".join(_render(r) for r in zeroes)
        + "\n"
        + "\n".join(_render(original.first(k)) for k in ("min", "max"))
    )
    root = pressure_tests._country([49, 49])
    root.update(
        is_ai=True,
        in_default=True,
        has_variable={
            (("argument", "recently_lost_war"),): True,
            (("argument", "attack_bolivia"),): False,
        },
        ai_russia_gendarme_spares_china=False,
    )
    env = {"ROOT": root, "scope:target_country": {"total_population": 1}}
    assert _native_number(0, body, env) == 0
    assert _native_number(3, body, env) == 0
    assert _native_number(100, body, env) == 92
    root["ai_russia_gendarme_spares_china"] = True
    assert _native_number(100, body, env) == 0
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )


@pytest.mark.parametrize(
    ("initial", "ambition", "state_value", "secret", "spare", "expected"),
    [
        (20, False, 0, False, False, 9),
        (20, True, 0, False, False, 30),
        (3, False, 0, False, False, 0),
        (200, True, 0, False, False, 250),
        (0, False, 40, True, False, 24),
        (0, True, 40, True, False, 80),
        (20, True, 40, True, True, 0),
    ],
)
def test_complete_actual_conquest_numeric_ast_native_region_and_final_order(
    conquest, initial, ambition, state_value, secret, spare, expected
):
    _, _, _, text, _ = conquest
    body = _block(
        _block(_block(parse_text(text).root, "ai_strategy_default"), "wargoal_scores"),
        "conquer_state",
    )
    root = pressure_tests._country([49, 49])
    root.update(
        is_ai=True,
        in_default=True,
        has_variable={
            (("argument", "recently_lost_war"),): True,
            (("argument", "attack_bolivia"),): False,
        },
        ai_russia_gendarme_spares_china=spare,
        ai_state_ambition_regional_objective=ambition,
        has_secret_goal=secret,
        has_attitude=False,
        any_country_strategic_region=[],
    )
    world = {
        "ROOT": root,
        "scope:target_country": {"total_population": 1},
        "scope:target_state": {"ai_state_value:root": state_value},
        "define:NAI|AI_STRONGLY_DESIRES_STATE_VALUE_THRESHOLD": 30,
        "scope:diplomatic_play": None,
    }
    assert number(body, world, initial) == expected


@pytest.fixture(scope="module")
def supply_policy():
    # Existing migration has no observed mission frame yet; do not invent one.
    wrapped = getattr(supply.generated, "__wrapped__", None)
    assert callable(wrapped)
    complete = wrapped()
    policy, _, _, files, overlay, _ = complete
    return policy, files, overlay, complete


@pytest.mark.parametrize(("changes", "expected"), supply.CASES)
def test_independent_source_identities_keep_bounded_supply_mission_envelope(
    supply_policy, changes, expected
):
    policy, files, overlay, _ = supply_policy
    values, facts = supply._values(**changes)
    result = decision_rules.evaluate(policy, values, is_ai=True).get(supply.exposure.FIELD)
    assert (result[1] if result else 1) == pytest.approx(expected)
    assert pdx_eval.select(overlay, facts).delta == pytest.approx(expected)
    assert {r.contribution_group for r in policy.rules} == {"external_supply_mission_pressure"}
    keys = {r.key for r in policy.readers}
    assert {
        "import_blockade_arms_import_volume",
        "import_blockade_owned_state_blockade",
        "steamers_price",
    } <= keys
    assert not parse_text(files[supply.VALUE_SOURCE]).errors


def test_complete_fleet_parent_qualifications_other_missions_and_original_zero(supply_policy):
    supply.test_full_native_fleets_qualification_zero_disable_and_unknown_preserved(
        supply_policy[3]
    )


@pytest.fixture(scope="module")
def ported_colonial(adapters, writer_rows):
    source = colonial_tests.SOURCE
    original = dict(adapters.policies)[source]
    policy = narrow(
        original, tuple(r for r in original.rules if ".".join(r.field) == colonial_tests.FIELD)
    )
    (ported,), batch = bind_policy(source, policy, writer_rows)
    native = pressure.frozen_inputs()[pressure.SOURCE]
    text = patch(source, ported[1], native)
    return ported[1], batch, text


@pytest.mark.parametrize(
    ("changes", "states", "expected"),
    [
        ({}, [{"is_under_colonization": True}], 1.18),
        ({"colonial_affairs_investment": 5}, [{"is_under_colonization": True}], 1.04),
        (
            {"default": True, "bureaucracy": -1, "colonial_affairs_investment": 3},
            [{"is_under_colonization": True}],
            0.63,
        ),
        ({"colonial_active_projects": False, "colonial_affairs_investment": 3}, [], 0.85),
    ],
)
def test_colonial_actual_shared_graph_keeps_project_need_saturation_and_independent_cost(
    ported_colonial, changes, states, expected
):
    policy, batch, text = ported_colonial
    values = colonial_tests._values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        colonial_tests.FIELD, ("", 1)
    )[1]
    env = colonial_tests._engine(policy, values, states)
    assert reference == pytest.approx(expected)
    assert _native_number(1, _overlay(text, colonial_tests.FIELD), env) == pytest.approx(expected)
    assert len(batch.partitions) == 1


def test_full_external_existing_fields_share_actual_graph_without_new_roles(
    adapters, writer_rows, tmp_path
):
    wanted = {
        (pressure.SOURCE, pressure.FIELD),
        (pressure.SOURCE, "ai_strategy_default.institution_scores.institution_colonial_affairs"),
        ("mod/decisions/information.toml", "wanted_navy_size"),
    }
    selected = []
    for source, policy in (
        *adapters.policies,
        ("mod/decisions/information.toml", decision_rules.load()),
    ):
        rules = tuple(r for r in policy.rules if (source, ".".join(r.field)) in wanted)
        if rules:
            selected.append((source, narrow(policy, rules)))
    bound, batch = external.bind(
        tuple(selected),
        selected_consumers=wanted,
        writers=tuple(writer_rows[(s, r.id)] for s, p in selected for r in p.rules),
        hard_cap={"ports": 512, "origins": 256, "uses": 256, "partitions": 3},
    )
    assert len(batch.partitions) == 3
    assert batch.uses_count == sum(len(p.rules) for _, p in selected)
    assert all(len(p.consumer_programs) == len({r.field for r in p.rules}) for _, p in bound)
    costs = [r for _, p in bound for r in p.rules if r.semantic_role == "cost"]
    assert pressure.RULE in {r.id for r in costs}
    assert "target_strategy_goal_conquer_state_reconstruction" in {r.id for r in costs}
    (tmp_path / "external-graph-measurements.json").write_text(
        json.dumps(
            {
                "partitions": len(batch.partitions),
                "uses": batch.uses_count,
                "ports": batch.ports_count,
                "origins": len(batch.origin_pool),
                "real_object_kinds": sorted({o.entity_kind for o in batch.origin_pool}),
                "selected": [list(k) for k in sorted(wanted)],
                "semantic_costs": sorted(r.id for r in costs),
                "scope": "current_existing_fields_only; no_product_completion",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_reject_missing_context_wrong_object_and_too_small_budget(adapters, writer_rows):
    policy = narrow(
        dict(adapters.policies)[pressure.SOURCE],
        tuple(r for r in dict(adapters.policies)[pressure.SOURCE].rules if r.id == pressure.RULE),
    )
    writer = writer_rows[(pressure.SOURCE, pressure.RULE)]
    args = {
        "selected_consumers": {(pressure.SOURCE, pressure.FIELD)},
        "hard_cap": {"ports": 32, "origins": 32, "uses": 4, "partitions": 1},
    }
    with pytest.raises(ValueError, match="精确现有writer"):
        external.bind(((pressure.SOURCE, policy),), writers=(), **args)
    missing = SimpleNamespace(**{**vars(writer), "evaluation_context": None})
    with pytest.raises(ValueError, match="frame"):
        external.bind(((pressure.SOURCE, policy),), writers=(missing,), **args)
    bad = SimpleNamespace(
        **{
            **vars(writer),
            "reader_context_bindings": tuple(
                (k, "foreign", "country", "actor") for k, *_ in writer.reader_context_bindings
            ),
        }
    )
    with pytest.raises(ValueError, match="对象/角色"):
        external.bind(((pressure.SOURCE, policy),), writers=(bad,), **args)
    with pytest.raises(ValueError, match="总cap"):
        external.bind(
            ((pressure.SOURCE, policy),),
            writers=(writer,),
            **{**args, "hard_cap": {"ports": 1, "origins": 32, "uses": 4, "partitions": 1}},
        )
