"""Production exact diplomatic proposal tradeoffs and independent PDX witnesses."""

from __future__ import annotations

import copy
import hashlib
import re
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from pdx import decision_rules, native_action_opportunities
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import cost_policies, pdx_eval, programs

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def actions():
    return native_action_opportunities


@pytest.fixture(scope="module")
def derived(actions):
    adapters = tomllib.loads(Path("mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    return actions.derive(adapters)


@pytest.fixture(scope="module")
def compiled(actions, derived):
    inputs = actions.load_baseline()["texts"]
    result = {}
    for identity, source in actions.BATCH_CANDIDATES.items():
        rules = [
            {key: value for key, value in rule.items() if key != "source"}
            for rule in derived["rules"]
            if rule["source"] == source
        ]
        used = {c["fact"] for rule in rules for c in rule["conditions"]}
        used.update(
            key for rule in rules for key in rule.get("unknown_cost_required_known_facts", [])
        )
        policy = decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": derived["sources"][source],
                "readers": {key: value for key, value in derived["readers"].items() if key in used},
                "rules": rules,
                "domains": {"diplomacy": True},
            },
            source_sha256="0" * 64,
        )
        actions.validate_batch_policy(policy, source)
        context = actions.batch_evaluation_context(source, f"{identity}.ai.propose_score")
        assert context.actor_scope is not None
        policy = programs.enable(policy, source=source)
        output = decision_rules.patch(
            inputs[source],
            policy,
            baseline=inputs[source],
            default_strategy=False,
            reader_evidence="\n".join(inputs.values()),
        )
        result[identity] = policy, output, inputs[source]
    return result


def _body(output, identity):
    marker = f"information:{identity}.ai.propose_score"
    begin = output.index(f"# SITAI BEGIN {marker}")
    end = output.index(f"# SITAI END {marker}", begin)
    return "\n".join(output[begin:end].splitlines()[1:])


def _facts(policy, values, *, is_ai=True, target_decoy=None):
    result = {"ROOT": {"is_ai": is_ai}}
    for reader in policy.readers:
        scope = "ROOT" if reader.scope == "root" else f"scope:{reader.scope}"
        observed = result.setdefault(scope, {})
        value = values.get(reader.key)
        if reader.argument is None:
            observed[reader.engine] = value
        else:
            observed.setdefault(reader.engine, {})[(("argument", reader.argument),)] = value
    if target_decoy is not None:
        result["scope:target"] = target_decoy
        result["ROOT"]["owner"] = target_decoy
    return result


def _number(base, body, facts):
    text = (
        "# ACTION native_tail [native]; actual generated body\nif = { limit = { always = yes } multiply = { value = "
        + str(base)
        + "\n"
        + body
        + "\n} }"
    )
    return pdx_eval.select(text, {**facts["ROOT"], **facts}).delta


def _check(compiled, identity, values, expected):
    policy, output, _ = compiled[identity]
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    factor = reference.get(f"{identity}.ai.propose_score", ("", 1))[1]
    assert factor == pytest.approx(expected)
    base = 100 if identity == "violate_sovereignty" else 10
    body = _body(output, identity)
    facts = _facts(policy, values, target_decoy={"liberty_desire": 0, "in_default": True})
    assert _number(base, body, facts) == pytest.approx(base * expected)
    assert _number(0, body, facts) == 0
    assert _number(base, body, _facts(policy, values, is_ai=False)) == base
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


@pytest.mark.parametrize(
    ("war", "factor"), [(False, 1), (True, 0.90), (None, 1), (0, 1), ("yes", 1)]
)
def test_exempt_only_observed_existing_war_opportunity_cost(compiled, war, factor):
    _check(compiled, "exempt_from_service", {"war": war}, factor)


@pytest.mark.parametrize(
    ("values", "factor"),
    [
        ({"default": False, "net_surplus": 0, "war_defeat": False}, 1),
        ({"default": True}, 0.85),
        ({"net_surplus": -0.01}, 0.93),
        ({"default": True, "net_surplus": -100}, 0.85),
        ({"war_defeat": True}, 0.95),
        ({"default": True, "net_surplus": -100, "war_defeat": True}, 0.80),
        ({"net_surplus": -1, "war_defeat": True}, 0.88),
        ({"default": None, "net_surplus": 0}, 1),
        ({"default": None, "net_surplus": -1}, 0.93),
        ({"cost_country_population": 1}, 0.85),
        ({}, 1),
        ({"war_defeat": True, "cost_country_population": 1}, 0.80),
        ({"default": False, "net_surplus": 0, "war_defeat": None}, 1),
        ({"default": False, "net_surplus": float("nan"), "cost_country_population": 1}, 0.93),
        ({"default": True, "net_surplus": None, "cost_country_population": None}, 0.85),
    ],
)
def test_sovereignty_same_financing_strongest_and_independent_recovery(compiled, values, factor):
    _check(compiled, "violate_sovereignty", values, factor)


@pytest.mark.parametrize(
    ("values", "factor"),
    [
        ({"net_surplus": 0, "raise_target_liberty": 20}, 1),
        ({"net_surplus": -1, "raise_target_liberty": 20}, 1.12),
        ({"net_surplus": -1, "raise_target_liberty": 49.99}, 1.12),
        ({"net_surplus": -1, "raise_target_liberty": 50}, 1.02),
        ({"net_surplus": -1, "raise_target_liberty": 64.99}, 1.02),
        ({"net_surplus": -1, "raise_target_liberty": 65}, 0.94),
        ({"net_surplus": -1, "raise_target_liberty": 74.99}, 0.94),
        ({"net_surplus": None, "raise_target_liberty": 50}, 0.90),
        ({"net_surplus": None, "raise_target_liberty": 65}, 0.82),
        ({"net_surplus": -1}, 1.12),
        ({"net_surplus": -1, "raise_target_population": 1}, 0.94),
        ({"raise_target_population": 1}, 0.82),
        ({}, 1),
        ({"raise_target_liberty": -1}, 1),
        ({"raise_target_liberty": 101, "raise_target_population": 1}, 0.82),
        ({"raise_target_liberty": True}, 1),
    ],
)
def test_raise_income_need_cannot_mask_independent_real_target_risk(compiled, values, factor):
    _check(compiled, "raise_payments", values, factor)


def test_exact_target_identity_differs_from_actor_and_foreign_decoys(compiled):
    identity = "raise_payments"
    policy, output, _ = compiled[identity]
    values = {"net_surplus": -1, "raise_target_liberty": 65}
    facts = _facts(policy, values)
    facts["ROOT"]["liberty_desire"] = 0
    facts["scope:target"] = {"liberty_desire": 0}
    facts["scope:overlord"] = {"liberty_desire": 0}
    assert _number(10, _body(output, identity), facts) == pytest.approx(9.4)
    facts["scope:target_country"]["liberty_desire"] = 20
    facts["ROOT"]["liberty_desire"] = 100
    assert _number(10, _body(output, identity), facts) == pytest.approx(11.2)


def test_nested_root_retains_global_named_target_and_local_owner_scope(compiled):
    policy, output, _ = compiled["raise_payments"]
    facts = _facts(policy, {"net_surplus": -1, "raise_target_liberty": 65})
    facts["ROOT"]["scope:target_country"] = {"liberty_desire": 0}
    assert _number(10, _body(output, "raise_payments"), facts) == pytest.approx(9.4)
    text = "# ACTION scope_probe [native]; nested named and local scope evidence\nif = { limit = { ROOT = { owner = { authority > 0 } scope:target_country = { liberty_desire >= 65 } } } add = 7 }"
    facts["ROOT"]["owner"] = {"authority": 1}
    assert pdx_eval.select(text, facts).delta == 7
    facts["ROOT"]["owner"]["authority"] = -1
    assert pdx_eval.select(text, facts).delta == 0


def test_flat_and_nested_saved_scopes_use_global_identity_and_explicit_root():
    parsed = parse_text(
        "limit = { ROOT = { average_sol < 8 "
        "scope:anti_public_healthcare_ig = { ig_clout >= 0.2 } } }"
    )
    assignment = parsed.root.first("limit")
    assert assignment is not None
    assert isinstance(assignment.value, Block)
    block = assignment.value
    for nested in (False, True):
        actor = {
            "average_sol": 7,
            "scope:anti_public_healthcare_ig": {"ig_clout": 0.9},
        }
        facts = {"ROOT": actor, "average_sol": 99} if nested else actor.copy()
        facts["scope:anti_public_healthcare_ig"] = {"ig_clout": 0.3}
        assert pdx_eval.condition(block, facts) is True
        facts["scope:anti_public_healthcare_ig"] = {"ig_clout": 0.1}
        assert pdx_eval.condition(block, facts) is False
        facts["scope:anti_public_healthcare_ig"] = None
        assert pdx_eval.condition(block, facts) is False
        del facts["scope:anti_public_healthcare_ig"]
        assert pdx_eval.condition(block, facts) is None
    assert pdx_eval.condition(block, {"ROOT": None, "average_sol": 7}) is False


def test_production_cost_application_preserves_exact_anchors_and_independent_costs(
    actions, derived
):
    inputs = actions.load_baseline()["texts"]
    original = {
        "schema": 1,
        "readers": copy.deepcopy(derived["readers"]),
        "rules": [
            {key: value for key, value in rule.items() if key != "source"}
            for rule in derived["rules"]
        ],
        "domains": {"diplomacy": True},
    }
    untouched = copy.deepcopy(original)
    applied = cost_policies.apply(original, source="adapters")
    assert original == untouched
    assert applied["readers"] == original["readers"]
    before_rules = {rule["id"]: rule for rule in original["rules"]}
    for rule in applied["rules"]:
        assert rule["conditions"] == before_rules[rule["id"]]["conditions"]
    by_id = {rule["id"]: rule for rule in applied["rules"]}
    raise_rule = by_id["native_action_raise_liberty_high"]
    assert raise_rule["unknown_cost_required_known_facts"] == ["raise_target_population"]
    assert raise_rule["conservative_unknown_facts"] == ["raise_target_liberty"]
    for name, pressure in (("default", "default"), ("deficit", "net_surplus")):
        rule = by_id[f"native_action_sovereignty_{name}"]
        assert rule["unknown_cost_required_known_facts"] == ["cost_country_population"]
        assert rule["conservative_unknown_facts"] == [pressure]
    cases: dict[str, list[tuple[dict[str, object | None], float]]] = {
        "exempt_from_service": [({"war": True}, 0.9)],
        "raise_payments": [
            ({"net_surplus": -1, "raise_target_liberty": 65}, 0.94),
            ({"raise_target_liberty": 65}, 0.82),
            ({"net_surplus": -1, "raise_target_population": 1}, 0.94),
            ({"net_surplus": -1}, 1.12),
            ({}, 1),
        ],
        "violate_sovereignty": [
            ({"default": True}, 0.85),
            ({"default": True, "war_defeat": True}, 0.80),
            ({"net_surplus": -1, "war_defeat": True}, 0.88),
            ({"cost_country_population": 1}, 0.85),
            ({}, 1),
        ],
    }
    for data in (original, applied):
        compiled = {}
        for identity, source in actions.BATCH_CANDIDATES.items():
            rules = [
                rule for rule in data["rules"] if rule["field"] == f"{identity}.ai.propose_score"
            ]
            used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
            used.update(
                key for rule in rules for key in rule.get("unknown_cost_required_known_facts", [])
            )
            policy = decision_rules.from_data(
                {
                    **data,
                    "baseline_sha256": derived["sources"][source],
                    "readers": {
                        key: value for key, value in data["readers"].items() if key in used
                    },
                    "rules": rules,
                },
                source_sha256="0" * 64,
            )
            actions.validate_batch_policy(policy, source)
            policy = programs.enable(policy, source=source)
            output = decision_rules.patch(
                inputs[source],
                policy,
                baseline=inputs[source],
                default_strategy=False,
                reader_evidence="\n".join(inputs.values()),
            )
            compiled[identity] = policy, output, inputs[source]
        for identity, examples in cases.items():
            for values, expected in examples:
                _check(compiled, identity, values, expected)


def test_whole_native_ast_effects_siblings_eligibility_and_off_exact(compiled, actions):
    for identity, (policy, output, native) in compiled.items():
        stripped = re.sub(
            r"\n\s*# SITAI BEGIN.*?# SITAI END[^\n]*\n", "\n", output, flags=re.DOTALL
        )
        assert actions._shape(parse_text(stripped).root) == actions._shape(parse_text(native).root)
        assert output.count("# SITAI BEGIN") == 1
        assert not parse_text(output).errors
        body = _body(output, identity)
        assert not any(
            token in body
            for token in (
                "set_variable",
                "change_variable",
                "any_country",
                "every_",
                "violate_sovereignty_join",
            )
        )
        assert (
            decision_rules.patch(
                native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
            )
            == native
        )


def test_batch_context_and_identity_anti_permission_leak(compiled, actions):
    for identity, (policy, _, _) in compiled.items():
        source = actions.BATCH_CANDIDATES[identity]
        context = actions.batch_evaluation_context(source, f"{identity}.ai.propose_score")
        assert [target.name for target in context.targets] == (
            ["target_country"] if identity == actions.RAISE else []
        )
        for reader in policy.readers:
            for changed in (
                replace(reader, path=("owner",)),
                replace(reader, unit="wrong"),
                replace(reader, scope="root" if reader.scope != "root" else "target_country"),
            ):
                altered = replace(
                    policy,
                    readers=tuple(
                        changed if item.key == reader.key else item for item in policy.readers
                    ),
                )
                with pytest.raises(ValueError, match="身份"):
                    actions.validate_batch_policy(altered, source)
        with pytest.raises(ValueError, match="合同"):
            actions.validate_batch_policy(replace(policy, actor_path=("owner",)), source)
        with pytest.raises(ValueError, match="消费者"):
            actions.batch_evaluation_context(source, f"{identity}.ai.accept_score")


def test_full_sources_effects_alias_and_raw_freeze_drift_rejected(actions, monkeypatch):
    frozen = actions.load_baseline()
    for source in frozen["texts"]:
        with pytest.raises(ValueError, match="漂移"):
            actions.verify_inputs({k: v for k, v in frozen["texts"].items() if k != source})
        with pytest.raises(ValueError, match="漂移"):
            actions.verify_inputs(
                {**frozen["texts"], source: frozen["texts"][source] + "\n# drift"}
            )
    changed = dict(frozen["texts"])
    source = actions.BATCH_CANDIDATES[actions.RAISE]
    changed[source] = changed[source].replace(
        "country_liberty_desire_add = 0.10", "country_liberty_desire_add = -0.10"
    )
    hashes = {**actions.SOURCE_HASHES, source: hashlib.sha256(changed[source].encode()).hexdigest()}
    monkeypatch.setattr(actions, "SOURCE_HASHES", hashes)
    monkeypatch.setattr(actions, "_snapshot", lambda: frozen)
    monkeypatch.setattr(actions, "load", lambda: {"sources": hashes})
    with pytest.raises(ValueError, match="父结构"):
        actions.verify_inputs(changed)


def test_existing_actions_unchanged_and_no_duplicate_capacity_or_default_target_rules(
    actions, derived
):
    assert len(derived["rules"]) == 16
    assert len(derived["covered"]) == 7
    added = [
        rule for rule in derived["rules"] if rule["source"] in actions.BATCH_CANDIDATES.values()
    ]
    assert len(added) == 7
    assert not any(
        c["fact"] in {"influence", "raise_target_default"}
        for rule in added
        for c in rule["conditions"]
    )
    assert {rule["field"].split(".")[0] for rule in added} == set(actions.BATCH_CANDIDATES)
    legacy_hashes = {
        "common/diplomatic_actions/40_subjects_knowledge_sharing.txt": "0e8d089a62180b570dfba7b1bb644238fa3dab6f936d12af9f21b5cedcc5afcd",
        "common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
        "common/diplomatic_actions/38_subjects_increase_autonomy.txt": "533689cd0cb50a664fc7c9b35a9b7ee125080aae27d12c60e2060fbdaa786a0c",
        "common/diplomatic_actions/33_subjects_decrease_payments.txt": "af342203edff8a52b5e265803f372939342e315750d74b4842e7759d1d54c2df",
        "common/diplomatic_actions/26_join_power_bloc.txt": "a66a61d5ee5a86282cec8f09b38bd0e58f3f12ac170f080499b3126370a9c28e",
    }
    texts = actions.load_baseline()["texts"]
    for source, expected in legacy_hashes.items():
        assert hashlib.sha256(texts[source].encode()).hexdigest() == expected


def test_restoration_sequence_reads_current_world(compiled):
    for values, expected in (
        ({"net_surplus": 1, "raise_target_liberty": 20}, 1),
        ({"net_surplus": -1, "raise_target_liberty": 65}, 0.94),
        ({"net_surplus": None, "raise_target_liberty": 65}, 0.82),
        ({"net_surplus": -1, "raise_target_liberty": None, "raise_target_population": 1}, 0.94),
        ({"net_surplus": 1, "raise_target_liberty": 20}, 1),
    ):
        _check(compiled, "raise_payments", values, expected)


@pytest.mark.parametrize(
    "key",
    [
        "war",
        "war_defeat",
        "default",
        "net_surplus",
        "cost_country_population",
        "raise_target_liberty",
        "raise_target_population",
    ],
)
def test_shared_reader_identity_conflicts_rejected(actions, key):
    adapters = tomllib.loads(Path("mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    adapters["readers"][key] = {**actions.BATCH_READERS[key], "unit": "wrong_unit"}
    with pytest.raises(ValueError, match="完整身份"):
        actions.derive(adapters)


def test_explicit_target_anchor_permission_has_no_other_consumer_or_identity_grant(
    actions, derived, compiled
):
    source = actions.BATCH_CANDIDATES[actions.RAISE]
    rules = [
        {k: v for k, v in r.items() if k != "source"}
        for r in derived["rules"]
        if r["source"] == source
    ]
    original = {
        "schema": 1,
        "baseline_sha256": derived["sources"][source],
        "readers": {
            k: actions.BATCH_READERS[k]
            for k in ("net_surplus", "raise_target_liberty", "raise_target_population")
        },
        "rules": rules,
        "domains": {"diplomacy": True},
    }
    for field in (
        "exempt_from_service.ai.propose_score",
        "raise_payments.ai.accept_score",
        "raise_payments.ai.propose_break_score",
    ):
        data = copy.deepcopy(original)
        for rule in data["rules"]:
            rule["field"] = field
        with pytest.raises(ValueError, match="actor国家人口"):
            decision_rules.from_data(data, source_sha256="0" * 64)
    for key, change in (
        ("raise_target_liberty", {"scope": "root"}),
        ("raise_target_population", {"minimum": 1}),
        ("raise_target_population", {"argument": "root"}),
        ("raise_target_population", {"path": ["owner"]}),
    ):
        data = copy.deepcopy(original)
        data["readers"][key].update(change)
        with pytest.raises(ValueError, match=r"身份|actor国家人口|读取器|数值参数"):
            decision_rules.from_data(data, source_sha256="0" * 64)
    assert len(compiled[actions.RAISE][0].consumer_programs) == 1


@pytest.mark.parametrize("replacement", ["0", "1.1", "true", "nan", "0.95"])
def test_invalid_risk_tuning_and_freeze_bytes_cannot_reauthorize(
    actions, replacement, tmp_path, monkeypatch
):
    data = actions.PARAMETERS.read_text(encoding="utf-8")
    target = tmp_path / "tuning.toml"
    target.write_text(
        data.replace("raise_liberty_high = 0.82", f"raise_liberty_high = {replacement}"),
        encoding="utf-8",
    )
    monkeypatch.setattr(actions, "PARAMETERS", target)
    with pytest.raises(ValueError, match=r"边界|分档|有限"):
        actions.load()


def test_frozen_byte_identity_is_required(actions, tmp_path, monkeypatch):
    changed = tmp_path / "frozen.json"
    changed.write_bytes(actions.FROZEN.read_bytes() + b"\n")
    monkeypatch.setattr(actions, "FROZEN", changed)
    with pytest.raises(ValueError, match="冻结完整源身份漂移"):
        actions.load_baseline()
