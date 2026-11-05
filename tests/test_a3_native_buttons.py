"""Native button costs preserve exact actor, full source and production IR contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace

import pytest

from pdx import decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def buttons():
    from pdx import native_button_opportunities

    return native_button_opportunities


@pytest.fixture(scope="module")
def policies(buttons):
    derived = buttons.derive({"readers": {}})
    result = {}
    for spec in buttons.SPECS:
        rules = [r for r in derived["rules"] if r["source"] == spec.source]
        used = {c["fact"] for r in rules for c in r["conditions"]}
        used |= {key for r in rules for key in r.get("unknown_cost_required_known_facts", [])}
        policy = decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": derived["sources"][spec.source],
                "domains": {"political": True},
                "readers": {key: value for key, value in derived["readers"].items() if key in used},
                "rules": [{k: v for k, v in row.items() if k != "source"} for row in rules],
            },
            source_sha256="0" * 64,
        )
        result[spec.source] = programs.enable(policy, source=spec.source)
    return result


@pytest.fixture(scope="module")
def patched(buttons, policies):
    inputs = buttons.frozen_inputs()
    evidence = "\n".join(inputs.values())
    return {
        spec.source: decision_rules.patch(
            inputs[spec.source],
            policies[spec.source],
            baseline=inputs[spec.source],
            default_strategy=False,
            reader_evidence=evidence,
        )
        for spec in buttons.SPECS
    }


def _body(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


def _native_number(initial, body, facts):
    program = (
        "# ACTION original_tail [native]; actual generated numeric body\n"
        "if = { limit = { always = yes } multiply = { value = "
        + str(initial)
        + "\n"
        + body
        + "\n} }"
    )
    return pdx_eval.select(program, {**facts["ROOT"], **facts}).delta


def _facts(population=None, reserves=None, authority=None, influence=None, default=None, **extra):
    return {
        "ROOT": {
            "is_ai": True,
            "total_population": population,
            "gold_reserves": reserves,
            "authority": authority,
            "influence": influence,
            "in_default": default,
            **extra,
        }
    }


def _check(buttons, policies, patched, index, values, facts, expected):
    spec = buttons.SPECS[index]
    policy = policies[spec.source]
    values = {buttons.ACTOR: True, **values}
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    factor = reference.get(spec.field, ("", 1))[1]
    assert factor == pytest.approx(expected)
    body = _body(patched[spec.source], spec.field)
    assert _native_number(spec.native_base, body, facts) == pytest.approx(
        spec.native_base * expected
    )
    assert _native_number(0, body, facts) == 0
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


@pytest.mark.parametrize(
    ("cash", "population", "factor"),
    [
        (500000, None, 0.85),
        (599999.99, 1, 0.85),
        (600000, None, 0.95),
        (999999.99, None, 0.95),
        (1000000, None, 1),
        (2000000, 1, 1),
        (None, 1, 0.85),
        (None, None, 1),
        (-1, 1, 0.85),
        (True, 1, 0.85),
        (float("nan"), None, 1),
    ],
)
def test_haiti_payment_buffer_reference_and_actual_pdx(
    buttons, policies, patched, cash, population, factor
):
    _check(
        buttons,
        policies,
        patched,
        0,
        {buttons.RESERVES: cash, buttons.ANCHOR: population},
        _facts(population, cash),
        factor,
    )


@pytest.mark.parametrize(
    ("authority", "influence", "population", "factor"),
    [
        (500, 500, None, 1),
        (150, 100, None, 0.90),
        (50, -1, None, 0.70),
        (99.99, 200, None, 0.85),
        (100, 200, None, 0.95),
        (200, 0, None, 0.95),
        (200, -0.01, None, 0.85),
        (100, 0, None, 0.90),
        (200, 200, None, 1),
        (None, None, 1, 0.70),
        (None, None, None, 1),
        (50, None, None, 0.85),
        (50, None, 1, 0.70),
        (None, -1, None, 0.85),
        (float("nan"), 500, 1, 0.85),
        (500, True, None, 1),
    ],
)
def test_migration_distinct_resources_combine_without_double_tiering(
    buttons,
    policies,
    patched,
    authority,
    influence,
    population,
    factor,
):
    _check(
        buttons,
        policies,
        patched,
        1,
        {"authority": authority, buttons.INFLUENCE: influence, buttons.ANCHOR: population},
        _facts(population, authority=authority, influence=influence),
        factor,
    )


@pytest.mark.parametrize(
    ("default", "population", "factor"),
    [
        (False, 1, 0.97),
        (True, 1, 0.90),
        (None, 1, 0.90),
        (True, None, 0.90),
        (False, None, 0.97),
        (None, None, 0.97),
        (False, 100000000, 0.97),
        (True, -1, 0.90),
        (None, -1, 0.97),
    ],
)
def test_hokkaido_positive_commitment_not_random_branch_bill(
    buttons,
    policies,
    patched,
    default,
    population,
    factor,
):
    _check(
        buttons,
        policies,
        patched,
        2,
        {"default": default, buttons.ANCHOR: population},
        _facts(population, default=default),
        factor,
    )


def test_no_known_cost_needs_population_health_or_unrelated_benefits(buttons, policies, patched):
    for index, values, facts, expected in (
        (0, {buttons.RESERVES: 500000}, _facts(reserves=500000), 0.85),
        (1, {"authority": 50, buttons.INFLUENCE: -1}, _facts(authority=50, influence=-1), 0.70),
        (2, {"default": True}, _facts(default=True), 0.90),
    ):
        values_with_unknowns = {
            **values,
            "opportunity": None,
            "literacy": None,
            "education": None,
            "war": None,
        }
        facts["scope:target_country"] = {
            "gold_reserves": 0,
            "authority": -10000,
            "influence": -10000,
            "in_default": True,
        }
        facts["owner"] = {"total_population": 99999999}
        _check(buttons, policies, patched, index, values_with_unknowns, facts, expected)


def test_full_native_parents_siblings_effects_and_no_new_scans_or_state(
    buttons,
    policies,
    patched,
):
    inputs = buttons.frozen_inputs()
    for spec in buttons.SPECS:
        text = patched[spec.source]
        assert text.count("# SITAI BEGIN") == 1
        restored = re.sub(r"\n\s*# SITAI BEGIN.*?# SITAI END[^\n]*\n", "\n", text, flags=re.DOTALL)
        assert buttons._shape(parse_text(restored).root) == buttons._shape(
            parse_text(inputs[spec.source]).root
        )
        body = _body(text, spec.field)
        assert not any(
            token in body
            for token in (
                "set_variable",
                "change_variable",
                "any_country",
                "any_scope_state",
                "every_",
            )
        )
        facts = _facts(1, 500000, 0, -1, True, is_ai=False)
        assert _native_number(spec.native_base, body, facts) == spec.native_base
        assert (
            decision_rules.patch(
                inputs[spec.source],
                policies[spec.source],
                baseline=inputs[spec.source],
                default_strategy=False,
                enabled_domains=frozenset(),
            )
            == inputs[spec.source]
        )


def test_exact_native_caller_effect_and_five_option_cost_evidence(buttons):
    inputs = buttons.frozen_inputs()
    catalog = buttons.consumer_catalog()
    assert len(catalog) == 3
    assert {r["native_base"] for r in catalog} == {10, 50}
    assert {r["obligation"] for r in catalog} == {"B01.4.2", "B06.4.2", "B02.1.2"}
    assert all(
        r["native_root"] == "country" and r["actor"] == "root" and r["target"] == "none"
        for r in catalog
    )
    assert len(buttons.SPECS[1].callers) == 3
    assert "start_commitment_only" in catalog[2]["coverage"]
    migration = buttons._block(parse_text(inputs[buttons.MIGRATION_MOD]).root, "sa_migration_cost")
    assert [(r.key, r.value.unquoted) for r in migration.assignments() if r.key != "icon"] == [
        ("country_influence_mult", "-0.25"),
        ("country_authority_cost_add", "100"),
    ]
    event = buttons._block(parse_text(inputs[buttons.HOKKAIDO_EVENT]).root, "hokkaido_events.3")
    costs = [
        buttons._block(r.value, "add_modifier").all("multiplier")[0].value.unquoted
        for r in event.all("option")
    ]
    assert costs == ["money_amount_multiplier_large", *["money_amount_multiplier_medium"] * 4]
    assert len(buttons.derive({"readers": {}})["rules"]) == 8


def test_context_and_reader_permissions_cannot_move_to_other_objects(buttons, policies):
    for spec in buttons.SPECS:
        context = buttons.evaluation_context(spec.source, spec.field)
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind) == ("root", "country")
        assert not context.targets
        assert not context.auxiliary_scopes
        for reader in policies[spec.source].readers:
            buttons.validate_reader(reader, spec.source, spec.field)
            assert decision_interfaces.reader_scope(reader, (), native_root="country") == "country"
            for changed in (
                replace(reader, scope="target_country"),
                replace(reader, path=("owner",)),
                replace(reader, unit="wrong_unit"),
            ):
                with pytest.raises(ValueError, match="身份"):
                    buttons.validate_reader(changed, spec.source, spec.field)
            with pytest.raises(ValueError, match="权限"):
                buttons.validate_reader(
                    reader, spec.source, spec.field, actor_path=("owner",), native_root="state"
                )
    for source, field in (
        (buttons.HAITI, buttons.SPECS[1].field),
        (buttons.MIGRATION, "patagonia_button.ai_chance"),
    ):
        with pytest.raises(ValueError, match="精确"):
            buttons.evaluation_context(source, field)


@pytest.mark.parametrize(
    "key",
    [
        "native_button_reserves",
        "authority",
        "native_button_influence",
        "default",
        "cost_country_population",
    ],
)
def test_derivation_rejects_reader_identity_conflict(buttons, key):
    wrong = {**buttons.READERS[key], "scope": "target_country"}
    with pytest.raises(ValueError, match="完整身份"):
        buttons.derive({"readers": {key: wrong}})


def test_production_compiler_checks_exact_button_consumer_and_complete_reader_identity(
    buttons, policies
):
    from pdx.situated import compiler

    for spec in buttons.SPECS:
        policy = policies[spec.source]
        readers = {r.key: r for r in policy.readers}
        context = buttons.evaluation_context(spec.source, spec.field)
        args = {"source": spec.source, "native_root": "country", "input_keys": tuple(readers)}
        bindings = compiler.validate_context_readers(spec.field, context, readers, (), **args)
        assert {row[0] for row in bindings} == set(readers)
        for key, reader in readers.items():
            for changed in (
                replace(reader, unit="forged"),
                replace(reader, scope="target_country"),
            ):
                with pytest.raises(ValueError):
                    compiler.validate_context_readers(
                        spec.field, context, {**readers, key: changed}, (), **args
                    )
        with pytest.raises(ValueError):
            compiler.validate_context_readers(spec.field + "_forged", context, readers, (), **args)
        with pytest.raises(ValueError):
            compiler.validate_context_readers(
                spec.field, context, readers, (), **{**args, "source": buttons.HAITI + ".forged"}
            )


def test_every_source_requires_current_complete_identity(buttons):
    inputs = buttons.frozen_inputs()
    for source in buttons.SOURCES:
        with pytest.raises(ValueError, match="漂移"):
            buttons.verify_inputs({key: value for key, value in inputs.items() if key != source})
        with pytest.raises(ValueError, match="漂移"):
            buttons.verify_inputs({**inputs, source: inputs[source] + "\n# drift"})


def test_effect_drift_cannot_be_hidden_by_repinning_source_only(buttons, monkeypatch):
    snapshot = copy.deepcopy(buttons._snapshot())
    inputs = dict(snapshot["inputs"])
    inputs[buttons.MIGRATION_MOD] = inputs[buttons.MIGRATION_MOD].replace(
        "country_authority_cost_add = 100",
        "country_authority_cost_add = -100",
        1,
    )
    data = copy.deepcopy(buttons.load())
    data["sources"][buttons.MIGRATION_MOD] = hashlib.sha256(
        inputs[buttons.MIGRATION_MOD].encode()
    ).hexdigest()
    monkeypatch.setattr(buttons, "load", lambda: data)
    monkeypatch.setattr(buttons, "_snapshot", lambda: snapshot)
    with pytest.raises(ValueError, match="漂移"):
        buttons.verify_inputs(inputs)


def test_frozen_bytes_and_invalid_tuning_cannot_authorize_new_semantics(
    buttons, tmp_path, monkeypatch
):
    raw = buttons.FROZEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == buttons.FROZEN_SHA256
    assert json.loads(raw)["raw_source_hashes"].keys() == buttons.SOURCES
    invalid = tmp_path / "invalid.toml"
    original = buttons.PARAMETERS.read_text(encoding="utf-8")
    for replacement in ("0", "1.1", "true", "nan", "0.98"):
        invalid.write_text(
            original.replace(
                "haiti_very_thin_buffer = 0.85", f"haiti_very_thin_buffer = {replacement}"
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(buttons, "PARAMETERS", invalid)
        with pytest.raises(ValueError, match="边界"):
            buttons.load()


def test_joint_programs_are_positive_bounded_single_authors(buttons, policies):
    assert sum(len(p.consumer_programs) for p in policies.values()) == 3
    for policy in policies.values():
        assert all(
            r.operation == "multiply" and 0 < r.value < 1 and r.semantic_role == "cost"
            for r in policy.rules
        )
        assert all(0.5 <= p.lower <= p.upper <= 1 for p in policy.consumer_programs)
    haiti = policies[buttons.HAITI]
    assert len({r.contribution_group for r in haiti.rules}) == 1
    migration = policies[buttons.MIGRATION]
    assert len({r.contribution_group for r in migration.rules}) == 2
    # Normal -> observed crisis -> auxiliary unknown -> recovery, each state reread.
    for authority, influence, expected in (
        (500, 500, 1),
        (50, -1, 0.70),
        (None, None, 0.70),
        (500, 500, 1),
    ):
        values = {"authority": authority, buttons.INFLUENCE: influence, buttons.ANCHOR: 1}
        assert decision_rules.evaluate_ir(migration, values, is_ai=True).get(
            buttons.SPECS[1].field,
            ("", 1),
        )[1] == pytest.approx(expected)
