"""Actual institution identities and investment use; current maximum is unknown.

Existing institutions and investment are observed, while research demand tiers
are design choices. Colonial funding does not establish an available target.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    version_contracts,
)
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/30_society.txt"
INSTITUTIONS = (
    "police",
    "colonial_affairs",
    "social_security",
    "workplace_safety",
    "schools",
    "health_system",
    "home_affairs",
)
TECHNOLOGIES = {
    "law_enforcement": "police",
    "mass_surveillance": "home_affairs",
    "colonization": "colonial_affairs",
    "civilizing_mission": "colonial_affairs",
}


# Independently measured from the identity-verified 1.15.0 native files.
# Historical hashes below retain their 1.14.5 contract.
_CURRENT_NATIVE_HASHES = {
    "common/institutions/00_institutions.txt": (
        "9d3b8474e2e99a34cd23cc38343253b850d0b2991a0f9418c85577c68c8ece2b",
        "77a48abeb8e5ce35a36652c0ae5f6dd58f4d6dc55a508181a6e5840f55e9763f",
    ),
    "common/achievements/base_achievements.txt": (
        "276ed2057159ccc2c2b6ebe874e4e97a935300b9707d9b110e553f3c9c68602e",
        "d073f27521c4d459410b61dea9f82b785603748ebd1a133e067ac029ec450414",
    ),
    "common/political_movements/00_ideological_movements.txt": (
        "6c1c4ae0a9b3d3f65165093fc3f52b32beb20cfebfd955e797053de8db119d8c",
        "17f682b4c10a64139c19230dbda69c212669319cb7e50e893e47bf2ea1f90dfb",
    ),
}


def _field(technology: str) -> str:
    return f"{technology}.ai_weight"


def _program_id(technology: str) -> str:
    return "program_" + hashlib.sha256(f"{SOURCE}:{_field(technology)}".encode()).hexdigest()[:16]


@pytest.fixture(scope="module")
def production() -> tuple[Any, str, str]:
    adapters = decision_adapters.load()
    raw = dict(adapters.policies)[SOURCE]
    fields = {_field(technology) for technology in TECHNOLOGIES}
    rules = tuple(rule for rule in raw.rules if ".".join(rule.field) in fields)
    assert {".".join(rule.field) for rule in rules} == fields
    assert len(rules) == 8
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    raw = replace(
        raw,
        rules=rules,
        readers=tuple(reader for reader in raw.readers if reader.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(raw, SOURCE, model)
    inputs = decision_adapters.read_inputs(adapters)
    selected = replace(
        adapters, policies=((SOURCE, policy),), initial_values=(), scalar_values=(), supply=None
    )
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, inputs[SOURCE], files[SOURCE]


def _values(technology: str, changes: Mapping[str, object]) -> dict[str, object]:
    institution = TECHNOLOGIES[technology]
    values: dict[str, object] = {
        **{f"has_{name}_institution": False for name in set(TECHNOLOGIES.values())},
        **{f"{name}_investment": 0 for name in set(TECHNOLOGIES.values())},
    }
    values[f"has_{institution}_institution"] = changes.get("exists", True)
    values[f"{institution}_investment"] = changes.get("level", 0)
    values.update({key: value for key, value in changes.items() if key not in {"exists", "level"}})
    return values


def _engine(values: Mapping[str, object], *, is_ai: bool = True) -> dict[str, Any]:
    root: dict[str, Any] = {
        "is_ai": is_ai,
        "has_institution": {
            (("argument", f"institution_{name}"),): values.get(f"has_{name}_institution")
            for name in set(TECHNOLOGIES.values())
        },
        "institution_investment_level": {
            (("institution", f"institution_{name}"),): values.get(f"{name}_investment")
            for name in set(TECHNOLOGIES.values())
        },
    }
    for key in (
        "candidate_selected",
        "institution_expanding",
        "war",
        "default",
        "bureaucracy",
        "net_surplus",
    ):
        if key in values:
            root[key] = values[key]
    return {"ROOT": root}


def _overlay(text: str, technology: str) -> str:
    start = text.index(f"# SITAI BEGIN information:{_field(technology)}")
    end = text.index(f"# SITAI END information:{_field(technology)}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _assert_result(production, technology: str, changes: Mapping[str, object], expected: float):
    policy, _native, generated = production
    values = _values(technology, changes)
    result = pdx_eval.select(_overlay(generated, technology), _engine(values))
    assert (result.action_id, result.operation) == (_program_id(technology), "multiply")
    assert result.delta == pytest.approx(expected)
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(_field(technology))
    if expected == 1:
        assert reference is None
    else:
        assert reference is not None
        assert reference[0] == _program_id(technology)
        assert reference[1] == pytest.approx(expected)
    return result


CASES = [
    (technology, changes, expected)
    for technology in TECHNOLOGIES
    for changes, expected in (
        ({"exists": True, "level": 0}, 1),
        ({"exists": True, "level": 0.999}, 1),
        ({"exists": True, "level": 1}, 1.08),
        ({"exists": True, "level": 2.999}, 1.08),
        ({"exists": True, "level": 3}, 1.12),
        ({"exists": True, "level": 5}, 1.12),
        ({"exists": True, "level": 100}, 1.12),
        ({"exists": False, "level": 0}, 1),
        ({"exists": False, "level": 3}, 1),
        ({"exists": None, "level": 3}, 1),
        ({"exists": True, "level": None}, 1),
        ({"exists": None, "level": None}, 1),
        ({"exists": True, "level": -1}, 1),
        (
            {
                "exists": True,
                "level": 3,
                "war": True,
                "default": True,
                "bureaucracy": -100,
                "net_surplus": -100,
            },
            1.12,
        ),
    )
]


@pytest.mark.parametrize(("technology", "changes", "expected"), CASES)
def test_handwritten_investment_tiers_match_complete_reference_and_actual_pdx(
    production, technology, changes, expected
):
    _assert_result(production, technology, changes, expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"exists": True, "level": float("nan")},
        {"exists": True, "level": float("inf")},
        {"exists": 1, "level": 3},
        {"exists": True, "level": True},
        {"exists": True, "level": "3"},
    ],
)
def test_malformed_typed_observation_is_not_silently_accepted_by_independent_pdx(
    production, changes
):
    policy, _native, generated = production
    technology = "law_enforcement"
    values = _values(technology, changes)
    assert _field(technology) not in decision_rules.evaluate(policy, values, is_ai=True)
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.select(_overlay(generated, technology), _engine(values))


@pytest.mark.parametrize("technology", TECHNOLOGIES)
def test_player_module_candidate_and_country_boundaries(production, technology):
    policy, _native, generated = production
    result = _assert_result(production, technology, {"level": 3}, 1.12)
    values = _values(technology, {"level": 3})
    overlay = _overlay(generated, technology)
    assert pdx_eval.select(overlay, _engine(values, is_ai=False)).operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        pdx_eval.select(
            overlay, _engine({**values, "candidate_selected": True, "institution_expanding": True})
        )
        == result
    )
    facts = _engine(values)
    facts["other_country"] = facts.pop("ROOT")
    facts["ROOT"] = {"is_ai": True}
    assert pdx_eval.select(overlay, facts).delta == 1


@pytest.mark.parametrize("technology", TECHNOLOGIES)
@pytest.mark.parametrize("query", ["has_institution", "institution_investment_level"])
def test_wrong_institution_parameter_cannot_supply_a_missing_observation(
    production, technology, query
):
    _policy, _native, generated = production
    facts = _engine(_values(technology, {"level": 3}))
    parameter = "argument" if query == "has_institution" else "institution"
    observations = facts["ROOT"][query]
    correct = ((parameter, f"institution_{TECHNOLOGIES[technology]}"),)
    value = observations.pop(correct)
    observations[((parameter, "institution_schools"),)] = value
    assert pdx_eval.select(_overlay(generated, technology), facts).delta == 1


@pytest.mark.parametrize("technology", TECHNOLOGIES)
def test_missing_level_does_not_become_zero_or_a_positive_existence_only_tier(
    production, technology
):
    policy, _native, generated = production
    values = _values(technology, {"level": 3})
    values.pop(f"{TECHNOLOGIES[technology]}_investment")
    assert _field(technology) not in decision_rules.evaluate(policy, values, is_ai=True)
    facts = _engine(values)
    facts["ROOT"].pop("institution_investment_level")
    assert pdx_eval.select(_overlay(generated, technology), facts).delta == 1


def test_production_has_only_one_causal_group_and_exact_used_parameter_identities(production):
    policy, _native, _generated = production
    assert len(policy.consumer_programs) == 4
    assert {rule.contribution_group for rule in policy.rules} == {"institution_capacity_use"}
    readers = {reader.key: reader for reader in policy.readers}
    assert len(readers) == 6
    for technology, name in TECHNOLOGIES.items():
        existence = readers[f"has_{name}_institution"]
        level = readers[f"{name}_investment"]
        assert (existence.engine, existence.argument, existence.kind, existence.unit) == (
            "has_institution",
            f"institution_{name}",
            "boolean",
            "boolean",
        )
        assert (
            level.engine,
            level.value_field,
            dict(level.parameters),
            level.kind,
            level.unit,
        ) == (
            "institution_investment_level",
            "value",
            {"institution": f"institution_{name}"},
            "number",
            "institution_level",
        )
        assert level.minimum == 0
        assert level.maximum is None
        assert level.argument is None
        assert existence.minimum is None
        assert existence.maximum is None
        assert existence.parameters == ()
        assert existence.value_field is None
        for reader in (existence, level):
            assert reader.scope == "root"
            assert reader.path == ()
        rules = [rule for rule in policy.rules if ".".join(rule.field) == _field(technology)]
        assert len(rules) == 2
        assert all(rule.input_keys() == frozenset({existence.key, level.key}) for rule in rules)


def _signature_data(institution: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "baseline_sha256": "0" * 64,
        "domains": {"political": True},
        "readers": {
            "institution_exists": {
                "engine": "has_institution",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "argument": f"institution_{institution}",
            },
            "investment": {
                "engine": "institution_investment_level",
                "scope": "root",
                "kind": "number",
                "unit": "institution_level",
                "minimum": 0,
                "value_field": "value",
                "parameters": {"institution": f"institution_{institution}"},
            },
        },
        "rules": [
            {
                "id": "institution_signature_witness",
                "domain": "political",
                "field": "law_enforcement.ai_weight",
                "priority": 1,
                "operation": "multiply",
                "value": 1.08,
                "contribution_group": "institution_capacity_use",
                "conditions": [
                    {"fact": "institution_exists", "op": "=", "value": True},
                    {"fact": "investment", "op": ">=", "value": 1},
                ],
                "why": "Typed interface witness only",
                "counterexample": "No runtime claim",
            }
        ],
    }


@pytest.mark.parametrize("institution", INSTITUTIONS)
def test_all_seven_declared_institutions_have_typed_parser_and_independent_parameter_witnesses(
    institution,
):
    policy = decision_rules.from_data(_signature_data(institution), source_sha256="0" * 64)
    readers = {reader.key: reader for reader in policy.readers}
    assert all(
        decision_interfaces.reader_scope(reader, ()) == "country" for reader in policy.readers
    )
    body = (
        "ROOT = { "
        + " ".join(readers[p.fact].expression(p.op, p.value) for p in policy.rules[0].conditions)
        + " }"
    )
    condition = parse_text(body)
    assert not condition.errors
    facts = {
        "ROOT": {
            "has_institution": {(("argument", f"institution_{institution}"),): True},
            "institution_investment_level": {(("institution", f"institution_{institution}"),): 1},
        }
    }
    assert pdx_eval.condition(condition.root, facts) is True
    facts["ROOT"]["institution_investment_level"] = {(("institution", "institution_wrong"),): 5}
    assert pdx_eval.condition(condition.root, facts) is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"value_field": None},
        {"value_field": "percent"},
        {"kind": "boolean"},
        {"parameters": {}},
        {"parameters": {"type": "institution_police"}},
        {"parameters": {"institution": "institution_unknown"}},
        {"parameters": {"institution": "institution_police", "who": "root"}},
        {"unit": "company_count"},
        {"scope": "target_country"},
        {"path": ["owner"]},
        {"minimum": None},
        {"maximum": 5},
    ],
)
def test_investment_query_rejects_unproved_shape_kind_unit_scope_and_invented_maximum(mutation):
    data = _signature_data("police")
    data["readers"]["investment"].update(mutation)
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="0" * 64)


@pytest.mark.parametrize(
    "mutation",
    [
        {"argument": "institution_unknown"},
        {"argument": "institution_type:institution_police"},
        {"argument": None},
        {"parameters": {"institution": "institution_police"}},
        {"kind": "number"},
        {"scope": "target_country"},
        {"path": ["owner"]},
    ],
)
def test_existence_query_rejects_wrong_parameter_shape_or_object(mutation):
    data = _signature_data("police")
    data["readers"]["institution_exists"].update(mutation)
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="0" * 64)


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_native_definitions_prerequisites_strategy_and_colonization_tails_are_preserved(production):
    _policy, native, generated = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL | re.MULTILINE,
    )
    before, after = parse_text(native), parse_text(stripped)
    assert not before.errors
    assert not after.errors
    assert _tree(before.root) == _tree(after.root)


def test_disabled_module_emits_no_override(production):
    policy, _native, _generated = production
    adapters = decision_adapters.load()
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=(),
        scalar_values=(),
        supply=None,
    )
    files, _ = decision_adapters.build(
        selected, texts=decision_adapters.read_inputs(adapters), enabled_domains=frozenset()
    )
    assert files == {}


def test_native_capacity_effects_are_real_and_do_not_claim_colonial_targets(production):
    _policy, native, _generated = production
    root = parse_text(native).root
    expected = {
        "law_enforcement": {"country_institution_police_max_investment_add": 1},
        "mass_surveillance": {
            "state_tax_capacity_add": 25,
            "country_support_separatism_resistance_mult": 0.25,
            "country_institution_home_affairs_max_investment_add": 1,
            "state_incorporation_speed_mult": 0.05,
        },
        "colonization": {
            "country_institution_colonial_affairs_max_investment_add": 2,
            "country_infamy_generation_against_unrecognized_mult": -0.1,
        },
        "civilizing_mission": {
            "country_institution_colonial_affairs_max_investment_add": 1,
            "country_infamy_generation_against_unrecognized_mult": -0.25,
        },
    }
    for technology, effects in expected.items():
        definition = root.first(technology)
        assert definition is not None
        assert isinstance(definition.value, Block)
        modifier = definition.value.first("modifier")
        assert modifier is not None
        assert isinstance(modifier.value, Block)
        observed = {}
        for item in modifier.value.assignments():
            assert isinstance(item.value, Scalar)
            observed[item.key] = float(item.value.unquoted)
        assert observed == effects


def test_all_seven_ids_have_real_definitions_and_numeric_achievement_consumers():
    definitions = parse_text(
        (config.GAME / "common/institutions/00_institutions.txt").read_text(encoding="utf-8-sig")
    )
    assert not definitions.errors
    assert {row.key for row in definitions.top_assignments} == {
        f"institution_{name}" for name in INSTITUTIONS
    }
    achievements = parse_text(
        (config.GAME / "common/achievements/base_achievements.txt").read_text(encoding="utf-8-sig")
    )
    assert not achievements.errors
    block = achievements.root.first("institutional")
    assert block is not None
    assert isinstance(block.value, Block)
    happened = block.value.first("happened")
    assert happened is not None
    assert isinstance(happened.value, Block)
    hidden = happened.value.first("hidden_trigger")
    assert hidden is not None
    assert isinstance(hidden.value, Block)
    alternatives = hidden.value.first("or")
    assert alternatives is not None
    assert isinstance(alternatives.value, Block)
    actual = set()
    for item in alternatives.value.assignments():
        assert item.key == "institution_investment_level"
        assert isinstance(item.value, Block)
        institution = item.value.first("institution")
        level = item.value.first("value")
        assert institution is not None
        assert level is not None
        assert isinstance(institution.value, Scalar)
        assert isinstance(level.value, Scalar)
        assert (level.op, level.value.unquoted) == ("=", "5")
        actual.add(institution.value.unquoted)
    assert actual == {f"institution_{name}" for name in INSTITUTIONS}


def test_existence_signature_has_country_owner_consumers_and_generic_institution_type():
    movements = parse_text(
        (config.GAME / "common/political_movements/00_ideological_movements.txt").read_text(
            encoding="utf-8-sig"
        )
    )
    assert not movements.errors
    owner_arguments: set[str] = set()

    def visit(block: Block, *, in_owner: bool = False) -> None:
        for item in block.assignments():
            if item.key == "has_institution":
                assert in_owner
                assert isinstance(item.value, Scalar)
                owner_arguments.add(item.value.unquoted)
            if isinstance(item.value, Block):
                visit(item.value, in_owner=in_owner or item.key == "owner")

    visit(movements.root)
    expected_arguments = {
        "institution_social_security",
        "institution_workplace_safety",
        "institution_police",
    }
    if version_contracts.active_version() == "1.14.5":
        expected_arguments.add("institution_schools")
    assert owner_arguments == expected_arguments
    tutorial = parse_text(
        (config.GAME / "common/journal_entries/00_tutorial.txt").read_text(encoding="utf-8-sig")
    )
    assert not tutorial.errors
    entry = tutorial.root.first("je_tutorial_invest_into_an_institution")
    assert entry is not None
    assert isinstance(entry.value, Block)
    if version_contracts.active_version() == "1.15.0":
        invalid_outcomes = []
        for outcome in entry.value.all("outcome"):
            assert isinstance(outcome.value, Block)
            flags = outcome.value.first("flags")
            if flags is not None:
                assert isinstance(flags.value, Block)
                if any(
                    isinstance(flag, Scalar) and flag.unquoted == "invalid_outcome"
                    for flag in flags.value.items
                ):
                    invalid_outcomes.append(outcome.value)
        assert len(invalid_outcomes) == 1
        invalid = invalid_outcomes[0].first("trigger")
    else:
        invalid = entry.value.first("invalid")
    assert invalid is not None
    assert isinstance(invalid.value, Block)
    assert _tree(invalid.value) == (
        ("NOT", "=", (("has_institution", "=", "scope:journal_entry.target.type"),)),
    )


def test_this_slice_registers_no_second_capacity_award_on_existing_institution_consumers():
    adapters = decision_adapters.load()
    rules = dict(adapters.policies)[SOURCE].rules
    added = [rule for rule in rules if rule.id.startswith("s2_institution_")]
    assert len(added) == 8
    assert {rule.field for rule in added} == {
        (technology, "ai_weight") for technology in TECHNOLOGIES
    }


@pytest.mark.parametrize(
    ("source", "raw_hash", "normalized_hash"),
    [
        (
            "common/institutions/00_institutions.txt",
            "9d3b8474e2e99a34cd23cc38343253b850d0b2991a0f9418c85577c68c8ece2b",
            "77a48abeb8e5ce35a36652c0ae5f6dd58f4d6dc55a508181a6e5840f55e9763f",
        ),
        (
            "common/achievements/base_achievements.txt",
            "dc5a50c8313fffbe50d68f0a6b8c9b9d05f1794f46725d23f2c0e67f7369799f",
            "2d3e7fa2cc1239682b12377605e03aea4b530d2eeffcfb9d7c6ec2f73c8fef3d",
        ),
        (
            "common/political_movements/00_ideological_movements.txt",
            "834a1b97f09c65b9b64eafdaffe4ee68965aaac262066140793a482eefd23a6b",
            "4462653e5fa326f3d84f03b6a551ddc76e9dead91409678adad56dcdb7f11035",
        ),
    ],
)
def test_new_source_evidence_is_locked_to_actual_original_bytes(source, raw_hash, normalized_hash):
    if version_contracts.active_version() == "1.15.0":
        raw_hash, normalized_hash = _CURRENT_NATIVE_HASHES[source]
    raw = (config.GAME / source).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == raw_hash
    assert (
        hashlib.sha256(normalized_text(raw.decode("utf-8-sig")).encode()).hexdigest()
        == normalized_hash
    )
