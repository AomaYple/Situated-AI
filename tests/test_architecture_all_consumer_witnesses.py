"""Executed six-role witnesses for each legacy physical consumer.

This module covers legacy numeric programs only. Explicit actions, continuous
SupportProgram writers and stage-wide responsibilities are separate work.
No evidence is signed unless the opt-in capture plugin receives an explicit
plan whose responsibility IDs match the mapping below.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

import pytest
import test_situated_writer_pdx_oracle as oracle

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_rules,
    decisions,
    version_contracts,
)
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, pdx_eval
from pdx.situated.native_treatments import _digest, _resolve

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.integration
INFO = oracle.INFO
DEFAULT = "common/ai_strategies/00_default_strategy.txt"
_OVERLAYS = re.compile(
    r"(?ms)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n"
)


def _identities():
    return tuple(
        (source, field)
        for source, policy in ((INFO, decision_rules.load()), *decision_adapters.load().policies)
        for field in sorted({rule.field for rule in policy.rules})
    )


IDENTITIES = _identities()


@pytest.fixture(scope="module")
def generated():
    return cast("Any", oracle.generated).__wrapped__()


def _responsibility(source, field):
    """One explicit functional owner; never broadcast a field to all exits."""
    name = ".".join(field)
    if source.startswith(("common/company_types/", "common/treaty_articles/")):
        return "S3", "market_trade_company_diplomacy"
    if source.startswith(
        ("common/mobilization_options/", "common/ship_modifications/")
    ) or source.endswith("20_military.txt"):
        return "S3", "military_security_recovery"
    if source.startswith("common/technology/"):
        return "S2", "economy_fiscal_construction" if source.endswith(
            "10_production.txt"
        ) else "society_education_knowledge"
    if source.startswith("common/buildings/"):
        return "S2", "society_education_knowledge" if field[
            0
        ] == "building_university" else "economy_fiscal_construction"
    if source.startswith("common/laws/"):
        filename = source.rsplit("/", 1)[1]
        if filename in {"00_army_model.txt", "00_navy_model.txt"}:
            return "S3", "military_security_recovery"
        if filename == "01_trade_policy.txt":
            return "S3", "market_trade_company_diplomacy"
        if filename in {
            "01_education_system.txt",
            "01_health_system.txt",
            "02_childrens_rights.txt",
            "02_welfare.txt",
        }:
            return "S2", "society_education_knowledge"
        if filename in {"01_economic_system.txt", "01_land_reform.txt", "01_taxation.txt"}:
            return "S2", "economy_fiscal_construction"
        return "S2", "politics_governance_identity"
    if source.endswith("01_admin_strategies.txt"):
        return "S2", "economy_fiscal_construction"
    if source.endswith("02_subject_diplomatic_strategies.txt"):
        return "S3", "complete_target_context"
    if source == INFO:
        if name in {
            "institution_scores.institution_schools",
            "institution_scores.institution_social_security",
        }:
            return "S2", "society_education_knowledge"
        if name in {"wanted_construction_output", "state_value"}:
            return "S2", "economy_fiscal_construction"
        if name in {"treaty_category_scores.trade", "treaty_category_scores.economy"}:
            return "S3", "market_trade_company_diplomacy"
        if name == "revolution_aversion":
            return "S2", "politics_governance_identity"
        return "S3", "military_security_recovery"
    if source == DEFAULT:
        if name.endswith("institution_scores.institution_health_system"):
            return "S2", "society_education_knowledge"
        if ".institution_scores." in name or field[-1] in {
            "interest_group_government_weight",
            "min_law_chance_to_pass",
        }:
            return "S2", "politics_governance_identity"
        if field[-1] == "nationalization_desire":
            return "S2", "economy_fiscal_construction"
        if (
            field[-1]
            in {
                "ship_construction_output_multiplier",
                "conscript_battalion_ratio",
                "wanted_num_supply_ships",
                "wanted_marines",
                "target_marine_formation_size",
            }
            or ".ai_ship_category_weights." in name
            or ".fleet_compositions." in name
        ):
            return "S3", "military_security_recovery"
        return "S3", "complete_target_context"
    raise AssertionError(f"unclassified actual legacy consumer: {source}:{name}")


def _json_observation(value):
    """Preserve actual tuple-key parameter identities using explicit JSON pairs."""
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {key: _json_observation(item) for key, item in value.items()}
        return {
            "identity_observations": [
                {"identity": _json_observation(key), "value": _json_observation(item)}
                for key, item in value.items()
            ]
        }
    if isinstance(value, (tuple, list)):
        return [_json_observation(item) for item in value]
    return value


def _units(operation, value):
    integer = round(value * 1000)
    assert value * 1000 == pytest.approx(integer, rel=0, abs=1e-8), (operation, value)
    return {"operation": operation, "value_thousandths": integer}


@pytest.fixture(scope="module")
def witness_candidate(generated):
    policies, model, files, info_text, inputs, baseline = generated
    compiled = {
        source: compiler.compile_policy(policy, source, model)[0] for source, policy in policies
    }
    adapters = decision_adapters.load()
    disabled, _ = decision_adapters.build(
        replace(
            adapters,
            policies=tuple((source, compiled[source]) for source, _ in policies if source != INFO),
        ),
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    disabled_info = decision_rules.patch(
        baseline,
        compiled[INFO],
        baseline=baseline,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    assert disabled_info == baseline
    return {
        "raw": dict(policies),
        "compiled": compiled,
        "model": model,
        "files": files,
        "info": info_text,
        "inputs": inputs,
        "baseline": baseline,
        "disabled": disabled,
        "initial": {(item.source, item.field): item for item in adapters.initial_values},
        "parsed": {},
    }


def _consumer(source, field):
    output = action_instances._output_source(source, ".".join(field))
    if source == INFO:
        definition, path = "ai_strategy_default", ".".join(field)
    elif output.endswith("sitai_adapter_values.txt"):
        definition, path = "sitai_adapter_fleet_supply_weight", "__body__"
    else:
        definition, path = field[0], ".".join(field[1:])
    root = decisions.product_path().relative_to(config.REPO).as_posix()
    return {"path": root + "/" + output, "definition": definition, "field": path}


def _root(candidate, text):
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key not in candidate["parsed"]:
        parsed = parse_text(text)
        assert not parsed.errors
        candidate["parsed"][key] = parsed.root
    return candidate["parsed"][key]


def _native_result(candidate, source, field, text):
    """Compare the entire retained native numeric AST, including implicit base."""
    original = candidate["baseline"] if source == INFO else candidate["inputs"][source]
    definition = "ai_strategy_default" if source == INFO else field[0]
    path = ".".join(field if source == INFO else field[1:])
    before, state = _resolve(_root(candidate, original), definition, path)
    if action_instances._output_source(source, ".".join(field)).endswith(
        "sitai_adapter_values.txt"
    ):
        after, current = _resolve(
            _root(candidate, _OVERLAYS.sub("\n", text)),
            "sitai_adapter_fleet_supply_weight",
            "__body__",
        )
    else:
        after, current = _resolve(_root(candidate, _OVERLAYS.sub("\n", text)), definition, path)
    assert current == "found"
    assert after is not None
    if before is None:
        assert state == "missing"
        initial = candidate["initial"][source, field]
        define, define_state = _resolve(
            _root(candidate, candidate["inputs"][initial.define_source]),
            initial.define[0],
            ".".join(initial.define[1:]),
        )
        assert define_state == "found"
        assert define is not None
        assert isinstance(define.value, Scalar)
        assert isinstance(after.value, Block)
        assert len(after.value.items) == 1
        value = after.value.first("value")
        assert value is not None
        assert isinstance(value.value, Scalar)
        expected = {"native_field": "implicit", "native_define_base": float(define.value.unquoted)}
        actual = {"native_field": "implicit", "native_define_base": float(value.value.unquoted)}
    elif isinstance(before.value, Scalar):
        assert isinstance(after.value, Block)
        assert len(after.value.items) == 1
        value = after.value.first("value")
        assert value is not None
        assert isinstance(value.value, Scalar)
        expected = {"native_scalar": float(before.value.unquoted)}
        actual = {"native_scalar": float(value.value.unquoted)}
    else:
        expected = {"native_numeric_ast": _digest(before.value)}
        actual = {"native_numeric_ast": _digest(after.value)}
    assert actual == expected
    return expected, actual


def _business_choices(policy, rules, index):
    """Choose real executed cases with a changed complete-consumer result."""
    neutral = 1 if rules[0].operation == "multiply" else 0
    for target in sorted(rules, key=lambda rule: rule.value <= neutral):
        choices = list(oracle._cases(policy, target, index))
        positive = choices[0]
        expected = oracle._independent_net(rules, positive[1], index, policy.enabled_domains)
        if expected[1] == pytest.approx(neutral):
            continue
        negatives = [
            (case, values, ai)
            for case, values, ai in choices
            if case.startswith("negative:")
            and oracle._independent_net(rules, values, index, policy.enabled_domains)[1]
            != pytest.approx(expected[1])
        ]
        unknowns = [
            item
            for item in choices
            if item[0].startswith("unknown:")
            and not any(
                reader.engine == "is_ai" and item[1].get(reader.key) is None
                for reader in policy.readers
                if reader.key in item[1]
            )
        ]
        if negatives and unknowns:
            return target, {"positive": positive, "negative": negatives[0], "unknown": unknowns[0]}
    raise AssertionError("no actual nonneutral positive/distinct-negative/local-unknown witness")


@pytest.mark.parametrize(
    ("source", "field"),
    IDENTITIES,
    ids=[source + ":" + ".".join(field) for source, field in IDENTITIES],
)
def test_each_legacy_physical_consumer_has_six_executed_roles(
    witness_candidate, architecture_witness, source, field
):
    candidate = witness_candidate
    raw = candidate["raw"][source]
    policy = candidate["compiled"][source]
    index = oracle._ReaderIndex.build(raw)
    rules = [
        rule for rule in raw.rules if rule.field == field and rule.domain in raw.enabled_domains
    ]
    target, choices = _business_choices(raw, rules, index)
    consumer = _consumer(source, field)
    output = action_instances._output_source(source, ".".join(field))
    built = candidate["info"] if source == INFO else candidate["files"][output]
    installed = (config.REPO / consumer["path"]).read_text(encoding="utf-8-sig")
    overlay = oracle._consumer_overlay(installed, ".".join(field))
    assert _digest(parse_text(overlay).root) == _digest(
        parse_text(oracle._consumer_overlay(built, ".".join(field))).root
    )
    program = oracle._ParsedProgram.build(overlay)
    stage, requirement = _responsibility(source, field)
    evidence_ids = ["a2.legacy." + requirement]
    base_id = hashlib.sha256((source + ":" + ".".join(field)).encode()).hexdigest()[:16]
    production = [
        source if source == INFO else "mod/decisions/adapters.toml",
        "src/pdx/situated/compiler.py",
        "src/pdx/decision_rules.py",
    ]
    linked_consumer = None
    if output.endswith("sitai_adapter_values.txt"):
        # The numeric body is reached through a separate physical strategy
        # field. Prove both ends; body-only evidence cannot close that field.
        linked_consumer = {
            "path": decisions.product_path().relative_to(config.REPO).as_posix() + "/" + source,
            "definition": field[0],
            "field": ".".join(field[1:]),
        }
        for text in (
            candidate["files"][source],
            (config.REPO / linked_consumer["path"]).read_text(encoding="utf-8-sig"),
        ):
            link, state = _resolve(_root(candidate, text), field[0], ".".join(field[1:]))
            assert state == "found"
            assert link is not None
            assert isinstance(link.value, Scalar)
            assert link.value.unquoted == "sitai_adapter_fleet_supply_weight"
        disabled_strategy = candidate["disabled"].get(source, candidate["inputs"][source])
        disabled_link, state = _resolve(
            _root(candidate, disabled_strategy), field[0], ".".join(field[1:])
        )
        assert state == "found"
        assert disabled_link is not None
        assert isinstance(disabled_link.value, Scalar)
        assert float(disabled_link.value.unquoted) == 1.0

    def record(role, observations, expected, reference, actual):
        assert expected == reference == actual
        architecture_witness(
            evidence_ids=evidence_ids,
            case_id=f"legacy.{base_id}.{role}",
            role=role,
            input={
                "contract_version": version_contracts.active_version(),
                "source": source,
                "field": ".".join(field),
                "responsibility_stage": stage,
                "responsibility_requirement": requirement,
                **_json_observation(observations),
            },
            expected=expected,
            reference=reference,
            generated=actual,
            production=production,
            consumers=[consumer],
        )
        if linked_consumer is not None:
            # Each case still binds exactly one consumer. Resolving the proven
            # scalar link gives precisely the executed body's result above;
            # disabled generation restores the independently known native 1.
            architecture_witness(
                evidence_ids=evidence_ids,
                case_id=f"legacy.{base_id}.strategy_link.{role}",
                role=role,
                input={
                    "contract_version": version_contracts.active_version(),
                    "script_value": "sitai_adapter_fleet_supply_weight",
                    "disabled_native_value": 1,
                    **_json_observation(observations),
                },
                expected=expected,
                reference=reference,
                generated=actual,
                production=production,
                consumers=[linked_consumer],
            )

    for role, (case, values, is_ai) in choices.items():
        expected = oracle._independent_net(rules, values, index, raw.enabled_domains)
        reference = decision_rules.evaluate(policy, values, is_ai=is_ai).get(".".join(field))
        neutral = 1.0 if expected[0] == "multiply" else 0.0
        reference_value = reference[1] if reference is not None else neutral
        if reference is not None:
            assert reference[0] == program.identity
        assert reference_value == pytest.approx(expected[1]), (role, case, expected, reference)
        facts = oracle._facts(raw, values, is_ai=is_ai, reader_index=index)
        actual = program.select(facts)
        assert actual == pdx_eval.select(overlay, facts)
        actual_value = actual.delta if actual.operation is not None else neutral
        assert actual.operation in {None, expected[0]}
        assert actual_value == pytest.approx(expected[1])
        record(
            role,
            {"case": case, "target_rule": target.id, "values": dict(values), "engine": facts},
            _units(*expected),
            _units(expected[0], reference_value),
            _units(expected[0], actual_value),
        )
    values = choices["positive"][1]
    player_reference = decision_rules.evaluate(policy, values, is_ai=False)
    player_actual = pdx_eval.select(
        overlay, oracle._facts(raw, values, is_ai=False, reader_index=index)
    )
    assert not player_reference
    assert player_actual.operation is None
    record(
        "player",
        {"is_ai": False, "engine": oracle._facts(raw, values, is_ai=False, reader_index=index)},
        {"contribution": False},
        {"contribution": bool(player_reference)},
        {"contribution": player_actual.operation is not None},
    )
    disabled_reference = decision_rules.evaluate(
        policy, values, is_ai=True, enabled_domains=frozenset()
    )
    disabled_output = candidate["disabled"].get(output)
    assert (
        disabled_output is None
        or f"# SITAI BEGIN information:{'.'.join(field)}" not in disabled_output
    )
    record(
        "disabled",
        {
            "enabled_domains": [],
            "original_input_sha256": hashlib.sha256(
                (candidate["baseline"] if source == INFO else candidate["inputs"][source]).encode()
            ).hexdigest(),
        },
        {"contribution": False},
        {"contribution": bool(disabled_reference)},
        {
            "contribution": disabled_output is not None
            and f"# SITAI BEGIN information:{'.'.join(field)}" in disabled_output
        },
    )
    expected_native, reference_native = _native_result(candidate, source, field, built)
    expected_native_again, actual_native = _native_result(candidate, source, field, installed)
    assert expected_native_again == expected_native
    record(
        "native_tail",
        {"native_source": source, "remove_only_declared_numeric_overlay": True},
        expected_native,
        reference_native,
        actual_native,
    )


def test_legacy_module_declares_only_its_actual_denominator(witness_candidate):
    candidate = witness_candidate
    actual = {
        (source, field)
        for source, policy in candidate["raw"].items()
        for field in {rule.field for rule in policy.rules}
    }
    assert set(IDENTITIES) == actual
    assert actual == {
        (consumer.source, consumer.field) for consumer in candidate["model"].production_consumers
    }
    writers = candidate["model"].consumer_ir.writers
    outside = [writer.writer_id for writer in writers if writer.kind != "rule_action"]
    assert outside, "explicit actions and SupportProgram must remain separate responsibilities"
    print(
        "legacy_witness_denominator", len(actual), "separate_nonlegacy_writers", json.dumps(outside)
    )
