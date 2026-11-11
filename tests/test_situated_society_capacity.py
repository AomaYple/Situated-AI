"""Company slots and authority: production reference and generated PDX witnesses.

Company use is a declared demand proxy. Counts at capacity are observed slot
pressure, not proof of a profitable new company or exhausted free charters.
Authority deficits concern the actual authority modifier, not political choices.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest

from pdx import config, country_state, decision_adapters, decision_rules, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
SOURCE = "common/technology/technologies/30_society.txt"
COMPANY = (
    "corporate_charters",
    "joint_stock_companies",
    "investment_banks",
    "corporate_management",
)
AUTHORITY = ("mass_communication", "nationalism", "pan-nationalism", "political_agitation")
TECHNOLOGIES = (*COMPANY, *AUTHORITY)


# Independently measured from the identity-verified 1.15.0 native files.
# Historical hashes below retain their 1.14.5 contract.
_CURRENT_NATIVE_HASHES = {
    "common/technology/technologies/30_society.txt": (
        "204340e2ff81f31d5bceddb36824566d57fa2be941dc2ba90407d56be75176dc",
        "9e4a9ec6b2df956da8104339460b87f2d78b8ae038e394f9dfaebb74e44052ad",
    ),
    "common/alert_types/00_alert_types.txt": (
        "ca60cb0f7425744d2695560d905f4ec58bbeb9dd3e6f1aedfcc891ceb23a55e3",
        "06099e868214b521f615cac1b5cf1f0d410aff5c8809484e44e56f66213545da",
    ),
    "common/journal_entries/00_tutorial.txt": (
        "83e4f81f813ae2cb04563ed02bed77d760d93b7b1f196bf58da11ac933d7ab78",
        "0fb0757ac536ac0ef76f0b925ec8754056feaef14511de947028be2125ca541a",
    ),
    "common/character_interactions/01_additional_interactions.txt": (
        "a36ecfbddbc8a4454393f832e0a0bc02d43afe73320185896520ba6312f0386f",
        "1ae63b1785cc7df424b487192561c220d603d24ad8921c0b3d7759b4f75262e9",
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
    assert len(rules) == 17
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
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return policy, inputs[SOURCE], files[SOURCE]


def _values(changes: Mapping[str, object]) -> dict[str, object]:
    return {
        "num_companies": 0,
        "max_num_companies": 4,
        "authority": 0,
        "sol": 20,
        "literacy": 0.8,
        **changes,
    }


def _engine(values: Mapping[str, object], *, is_ai: bool = True) -> dict[str, Any]:
    # Independently name the actual engine getters; do not derive these names
    # from production readers, which could otherwise hide an identity mistake.
    root = {
        "is_ai": is_ai,
        "num_companies": values.get("num_companies"),
        "max_num_companies": values.get("max_num_companies"),
        "authority": values.get("authority"),
        "average_sol": values.get("sol"),
        "literacy_rate": values.get("literacy"),
    }
    for key in (
        "candidate_selected",
        "company_established",
        "construction_queued",
        "default",
        "war",
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
    values = _values(changes)
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


# Expected values are handwritten from the causal contract, not a second
# invocation of the compiler. Higher tiers replace lower tiers of one cause.
CASES: list[tuple[str, Mapping[str, object], float]] = [
    (technology, changes, expected)
    for technology in COMPANY
    for changes, expected in (
        ({"num_companies": 0, "max_num_companies": 0}, 1),
        ({"num_companies": 0, "max_num_companies": 4}, 1),
        ({"num_companies": 1, "max_num_companies": 4}, 1.08),
        ({"num_companies": 3, "max_num_companies": 4}, 1.08),
        ({"num_companies": 4, "max_num_companies": 4}, 1.15),
        ({"num_companies": 5, "max_num_companies": 4}, 1.15),
        ({"num_companies": 1, "max_num_companies": 0}, 1.15),
        ({"num_companies": 1, "max_num_companies": None}, 1.08),
        ({"num_companies": 0, "max_num_companies": None}, 1),
        ({"num_companies": None, "max_num_companies": 0}, 1),
        ({"num_companies": None, "max_num_companies": 4}, 1),
        ({"num_companies": None, "max_num_companies": None}, 1),
        ({"num_companies": 4, "max_num_companies": -1}, 1.08),
        ({"num_companies": -1, "max_num_companies": 0}, 1),
        (
            {
                "num_companies": 4,
                "max_num_companies": 4,
                "war": True,
                "default": True,
                "bureaucracy": None,
                "net_surplus": -100,
                "literacy": None,
            },
            1.15,
        ),
    )
]
CASES += [
    (technology, {"authority": balance}, expected)
    for technology in AUTHORITY
    for balance, expected in (
        (100, 1),
        (0, 1),
        (-0.001, 1.08),
        (-1, 1.08),
        (-10, 1.08),
        (-10.001, 1.15),
        (-100, 1.15),
        (None, 1),
    )
]
CASES += [
    ("political_agitation", changes, expected)
    for changes, expected in (
        ({"authority": -1, "literacy": 0.5, "sol": 10}, 1),
        ({"authority": -11, "literacy": 0.5, "sol": 10}, 1.07),
        ({"authority": 0, "literacy": 0.5, "sol": 10}, 0.92),
        ({"authority": None, "literacy": 0.5, "sol": 10}, 0.92),
        ({"authority": -11, "literacy": None, "sol": 10}, 1.15),
        ({"authority": -11, "literacy": 0.5, "sol": None}, 1.15),
        ({"authority": -11, "literacy": 0.499, "sol": 10}, 1.15),
        ({"authority": -11, "literacy": 0.5, "sol": 12}, 1.15),
        ({"authority": None, "literacy": None, "sol": None}, 1),
        ({"authority": None, "literacy": None, "sol": 10}, 1),
        ({"authority": 0, "literacy": 0.5, "sol": 11.999}, 0.92),
        (
            {
                "authority": -11,
                "literacy": 0.5,
                "sol": 10,
                "bureaucracy": None,
                "net_surplus": -100,
                "default": True,
                "war": True,
            },
            1.07,
        ),
    )
]


@pytest.mark.parametrize(("technology", "changes", "expected"), CASES)
def test_handwritten_joint_values_match_compiled_reference_and_generated_pdx(
    production, technology, changes, expected
):
    _assert_result(production, technology, changes, expected)


POSITIVES = [
    *((technology, {"num_companies": 4, "max_num_companies": 4}, 1.15) for technology in COMPANY),
    *((technology, {"authority": -11}, 1.15) for technology in AUTHORITY),
    ("political_agitation", {"authority": -11, "literacy": 0.5, "sol": 10}, 1.07),
    ("political_agitation", {"authority": None, "literacy": 0.5, "sol": 10}, 0.92),
]


@pytest.mark.parametrize(("technology", "changes", "expected"), POSITIVES)
def test_country_identity_player_module_and_candidate_boundaries(
    production, technology, changes, expected
):
    policy, _native, generated = production
    result = _assert_result(production, technology, changes, expected)
    values = _values(changes)
    overlay = _overlay(generated, technology)
    assert pdx_eval.select(overlay, _engine(values, is_ai=False)).operation is None
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        pdx_eval.select(
            overlay, _engine({**values, "candidate_selected": True, "company_established": True})
        )
        == result
    )
    facts = _engine(values)
    facts["other_country"] = facts.pop("ROOT")
    facts["ROOT"] = {"is_ai": True, "candidate_selected": True}
    assert pdx_eval.select(overlay, facts).delta == 1


@pytest.mark.parametrize("technology", COMPANY)
def test_capacity_from_another_country_cannot_replace_root_capacity(production, technology):
    _policy, _native, generated = production
    facts = _engine(_values({"num_companies": 4, "max_num_companies": None}))
    facts["other_country"] = {"max_num_companies": 4}
    result = pdx_eval.select(_overlay(generated, technology), facts)
    assert result.delta == pytest.approx(1.08)
    assert '"ROOT.max_num_companies"' in _overlay(generated, technology)


@pytest.mark.parametrize("technology", COMPANY)
def test_missing_capacity_is_unknown_and_preserves_observed_company_use(production, technology):
    policy, _native, generated = production
    values = _values({"num_companies": 1})
    values.pop("max_num_companies")
    reference = decision_rules.evaluate(policy, values, is_ai=True)[_field(technology)]
    assert reference[1] == pytest.approx(1.08)
    facts = _engine(values)
    facts["ROOT"].pop("max_num_companies")
    assert pdx_eval.select(_overlay(generated, technology), facts).delta == pytest.approx(1.08)


def test_reader_units_bounds_parameters_and_relative_identity_are_explicit(production):
    policy, _native, _generated = production
    assert len(policy.consumer_programs) == 8
    readers = {reader.key: reader for reader in policy.readers}
    assert set(readers) == {"num_companies", "max_num_companies", "authority", "literacy", "sol"}
    for key in ("num_companies", "max_num_companies", "authority"):
        reader = readers[key]
        assert (reader.engine, reader.scope, reader.kind) == (key, "root", "number")
        assert (reader.path, reader.argument, reader.parameters, reader.value_field) == (
            (),
            None,
            (),
            None,
        )
        assert reader.maximum is None
    assert readers["num_companies"].unit == readers["max_num_companies"].unit == "company_count"
    assert readers["num_companies"].minimum == readers["max_num_companies"].minimum == 0
    assert readers["authority"].unit == "capacity_balance"
    assert readers["authority"].minimum is None
    assert readers["authority"].accepts(-100)
    assert not readers["authority"].accepts(float("nan"))
    assert not readers["num_companies"].accepts(-1)
    assert readers["literacy"].engine == "literacy_rate"
    assert readers["sol"].engine == "average_sol"
    for technology in COMPANY:
        rules = [rule for rule in policy.rules if ".".join(rule.field) == _field(technology)]
        assert len(rules) == 2
        assert {rule.contribution_group for rule in rules} == {"company_slot_pressure"}
        base = next(rule for rule in rules if rule.value == 1.08)
        full = next(rule for rule in rules if rule.value == 1.15)
        assert base.input_keys() == frozenset({"num_companies"})
        assert full.input_keys() == frozenset({"num_companies", "max_num_companies"})
        references = [
            p.value for p in full.conditions if isinstance(p.value, decision_rules.FactReference)
        ]
        assert references == [
            decision_rules.FactReference("max_num_companies", "ROOT.max_num_companies")
        ]
    for technology in AUTHORITY:
        benefits = [
            rule
            for rule in policy.rules
            if ".".join(rule.field) == _field(technology) and rule.value > 1
        ]
        assert len(benefits) == 2
        assert {rule.contribution_group for rule in benefits} == {"authority_capacity_pressure"}
        assert all(rule.input_keys() == frozenset({"authority"}) for rule in benefits)


def _tree(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_all_native_definition_effects_prerequisites_and_strategy_culture_tails_survive(production):
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


def test_disabled_module_emits_no_source_override(production):
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


def test_capacity_and_side_effect_claims_match_actual_native_modifiers(production):
    policy, native, _generated = production
    root = parse_text(native).root
    effects: dict[str, dict[str, object]] = {
        "corporate_charters": {"country_max_companies_add": 1, "country_free_charters_add": 2},
        "joint_stock_companies": {
            "country_max_companies_add": 1,
            "state_urbanization_per_level_mult": -0.1,
        },
        "investment_banks": {
            "country_max_companies_add": 1,
            "country_free_charters_add": 1,
            "state_urbanization_per_level_mult": -0.15,
        },
        "corporate_management": {
            "country_max_companies_add": 1,
            "state_urbanization_per_level_mult": -0.25,
        },
        "mass_communication": {"country_authority_mult": 0.1, "country_voting_power_mult": 0.1},
        "nationalism": {
            "country_authority_mult": 0.1,
            "country_voting_power_mult": 0.1,
            "country_homeland_infamy_reduction_bool": "yes",
        },
        "pan-nationalism": {
            "country_authority_mult": 0.1,
            "country_voting_power_mult": 0.1,
            "country_support_separatism_strength_mult": 0.25,
            "country_shared_language_infamy_reduction_bool": "yes",
        },
        "political_agitation": {
            "country_authority_mult": 0.1,
            "country_voting_power_mult": 0.1,
            "state_expected_sol_from_literacy": 1,
            "country_agitator_slots_add": 1,
        },
    }
    for technology, expected in effects.items():
        definition = root.first(technology)
        assert definition is not None
        assert isinstance(definition.value, Block)
        modifier = definition.value.first("modifier")
        assert modifier is not None
        assert isinstance(modifier.value, Block)
        observed = {}
        for assignment in modifier.value.assignments():
            assert isinstance(assignment.value, Scalar)
            literal = assignment.value.unquoted
            observed[assignment.key] = literal if literal == "yes" else float(literal)
        assert observed == expected
    costs = [rule for rule in policy.rules if rule.value < 1]
    assert len(costs) == 1
    assert (costs[0].field, costs[0].contribution_group, costs[0].value) == (
        ("political_agitation", "ai_weight"),
        "reform_expectation",
        0.92,
    )


@pytest.mark.parametrize(
    ("source", "raw_hash", "normalized_hash"),
    [
        (
            SOURCE,
            "39fb1574d4dafdb67293b4e0e465a82b82bee63e4ac810f9715727d48a0fd918",
            "52c0b085e7429cf3961dfeacc4e1891056e2a2e80c740ce7ebcca6f61124e880",
        ),
        (
            "common/alert_types/00_alert_types.txt",
            "14ff4bb983f84c17fc2825d79ce93620bc68cde7284f8d1fa2dbba6845420aea",
            "399eaa0ed4bb11e29bac7d0de29e2fa1e191cbdbf3b1290fba5abac9b622f912",
        ),
        (
            "common/journal_entries/00_tutorial.txt",
            "f4e44394601d6bb52b85e4184012f9181391831f64af1c4251f8bbeb3978da13",
            "dbd90b3993566ccb0c777912a9429013186367449b2d6b6e88b91acdb4e356da",
        ),
        (
            "common/character_interactions/01_additional_interactions.txt",
            "9f7e23778afa1adc23ece0819e3ec0a694e5a7355cfeaf1cf5acefd6cafc3809",
            "d7cfbfccdd9b7b0b504908e4db43e38646838c26cb29c834abe5595210a22b53",
        ),
    ],
)
def test_reader_evidence_uses_exact_native_bytes_and_registered_normalization(
    source, raw_hash, normalized_hash
):
    if version_contracts.is_115():
        raw_hash, normalized_hash = _CURRENT_NATIVE_HASHES[source]
    raw = (config.GAME / source).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == raw_hash
    text = normalized_text(raw.decode("utf-8-sig"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == normalized_hash


def test_original_count_comparison_and_authority_getter_have_actual_country_consumers():
    alerts = parse_text(
        (config.GAME / "common/alert_types/00_alert_types.txt").read_text(encoding="utf-8-sig")
    )
    assert not alerts.errors
    alert = alerts.root.first("above_company_limit")
    assert alert is not None
    assert isinstance(alert.value, Block)
    context = alert.value.first("script_context")
    assert context is not None
    assert isinstance(context.value, Scalar)
    assert context.value.unquoted == "player_country"
    valid = alert.value.first("valid")
    assert valid is not None
    assert isinstance(valid.value, Block)
    assert _tree(valid.value) == (("num_companies", ">", "max_num_companies"),)

    interactions = parse_text(
        (config.GAME / "common/character_interactions/01_additional_interactions.txt").read_text(
            encoding="utf-8-sig"
        )
    )
    assert not interactions.errors
    patronize = interactions.root.first("patronize")
    assert patronize is not None
    assert isinstance(patronize.value, Block)
    possible = patronize.value.first("possible")
    assert possible is not None
    assert isinstance(possible.value, Block)
    owner = possible.value.first("owner")
    assert owner is not None
    assert owner.op == "?="
    assert isinstance(owner.value, Block)
    capacity = owner.value.first("authority")
    assert capacity is not None
    assert isinstance(capacity.value, Scalar)
    assert (capacity.op, capacity.value.unquoted) == (">=", "ROOT.patronize_authority_cost")
