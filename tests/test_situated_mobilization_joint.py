"""Complete production witnesses keep formation ROOT distinct from its owner."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx import mobilization_opportunities as medical
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, decision_ir, pdx_eval

pytestmark = pytest.mark.integration
SOURCE = "common/mobilization_options/00_mobilization_option.txt"
FIRST = "mobilization_option_first_aid.ai_weight"
FIELD = "mobilization_option_field_hospitals.ai_weight"


@pytest.fixture(scope="module")
def production():
    original = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    # Compile and build the entire actual adapter set, with every competitor.
    policies = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in original.policies
    )
    compiled = replace(original, policies=policies)
    inputs = decision_adapters.read_inputs(original)
    country = country_state.load()
    files, contracts = decision_adapters.build(
        compiled, texts=inputs, country_policy=country, consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        compiled,
        texts=inputs,
        country_policy=country,
        consumer_ir=model.consumer_ir,
        enabled_domains=frozenset(),
    )
    return original, compiled, model, inputs, files, disabled, contracts


def _selection(production, field):
    policy = dict(production[1].policies)[SOURCE]
    program = next(item for item in policy.consumer_programs if ".".join(item.field) == field)
    return policy, pdx_eval.marked_block(production[4][SOURCE], program.action_id)


def _values(changes=None):
    # This is handwritten independently of the production reader renderers.
    result = {
        "mobilization_owner_ai": True,
        "mobilization_war": False,
        "mobilization_default": False,
        "mobilization_fabric_balance": 0,
        "mobilization_fabric_price": 0,
        "mobilization_liquor_balance": 0,
        "mobilization_liquor_price": 0,
        "mobilization_opium_balance": 0,
        "mobilization_opium_price": 0,
        "mobilization_tools_balance": 0,
        "mobilization_tools_price": 0,
    }
    result.update(changes or {})
    return result


def _facts(values, *, is_ai=True):
    owner: dict[str, Any] = {"market": {}}
    for key, engine in (
        ("mobilization_owner_ai", "is_ai"),
        ("mobilization_war", "is_at_war"),
        ("mobilization_default", "in_default"),
    ):
        if key in values:
            owner[engine] = values[key]
    if "mobilization_owner_ai" in values and values["mobilization_owner_ai"] is not None:
        owner["is_ai"] = is_ai
    for good in (
        "fabric",
        "liquor",
        "opium",
        "tools",
        "groceries",
        "meat",
        "wine",
        "sugar",
        "tobacco",
        "automobiles",
        "engines",
        "small_arms",
        "ammunition",
        "fertilizer",
        "oil",
    ):
        entry = {}
        for tier, engine in (("balance", "market_goods_delta"), ("price", "market_goods_pricier")):
            key = f"mobilization_{good}_{tier}"
            if key in values:
                entry[engine] = values[key]
        owner["market"][f"mg:{good}"] = entry
    # Native formation ROOT carries deliberately contradictory country decoys.
    return {"ROOT": {"owner": owner, "is_ai": False, "is_at_war": True, "in_default": True}}


def _factor(selection):
    return selection.delta if selection.operation == "multiply" else 1.0


def test_paid_consumers_keep_explicit_formation_root_owner_context_and_complete_set(
    production,
):
    original, compiled, model, _, files, disabled, _ = production
    assert len(original.policies) == len(compiled.policies)
    assert len(compiled.policies) >= 70
    assert disabled == {}
    policy = dict(compiled.policies)[SOURCE]
    assert policy.native_root == "military_formation"
    assert policy.actor_path == ("owner",)
    assert len(policy.rules) == 72
    assert {".".join(program.field) for program in policy.consumer_programs} == {
        f"{identity}.ai_weight" for identity in medical.CANDIDATE_IDS
    }
    assert files[SOURCE].count("# SITAI BEGIN information:") == 15
    instances = [item for item in model.action_instances if item.source == SOURCE]
    assert len(instances) == 72
    writers = [item for item in model.consumer_ir.writers if item.source == SOURCE]
    assert len(writers) == 72
    for item in (*instances, *writers):
        context = item.evaluation_context
        assert context is not None
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "owner",
            "country",
            "actor",
        )
        assert [
            (binding.name, binding.kind, binding.role) for binding in context.auxiliary_scopes
        ] == [("root", "military_formation", "auxiliary")]
        assert context.targets == ()
        assert any(medical.baseline_sha256() in evidence for evidence in context.evidence)
    for writer in writers:
        assert writer.actor == "owner"
        assert writer.reader_context_bindings
        assert {row[1:] for row in writer.reader_context_bindings} == {
            ("owner", "country", "actor"),
            ("root", "military_formation", "auxiliary"),
        }
    contract = decision_rules.contract(policy, source=SOURCE)
    assert contract["native_root"] == "military_formation"
    assert contract["actor"] == "root_military_formation_owner"
    rule_contracts = contract["rules"]
    assert isinstance(rule_contracts, list)
    for row in rule_contracts:
        assert row["consumer"]["root"] == "military_formation"
        assert (
            row["consumer"]["role"]
            == "vanilla_mobilization_utility_multiplier_before_monetary_cost"
        )


@pytest.mark.parametrize("field", [FIRST, FIELD])
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.0),
        ({"mobilization_war": True}, 1.10),
        ({"mobilization_default": True}, 0.85),
        ({"mobilization_war": True, "mobilization_default": True}, 0.95),
        ({"mobilization_war": None, "mobilization_default": True}, 0.85),
        ({"mobilization_war": True, "mobilization_default": None}, 1.10),
        ({"mobilization_war": None, "mobilization_default": None}, 1.0),
    ],
)
def test_complete_production_independent_country_demand_and_financing(
    production, field, changes, expected
):
    policy, overlay = _selection(production, field)
    values = _values(changes)
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(field, ("native", 1.0))[1] == pytest.approx(expected)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("field", "first_good", "second_good", "other_good"),
    [
        (FIRST, "fabric", "liquor", "opium"),
        (FIELD, "opium", "tools", "fabric"),
    ],
)
@pytest.mark.parametrize(
    ("shortage", "price", "expected"),
    [
        (0, 0.75, 1.0),
        (-1, 0.50, 0.90),
        (-1, 0.50001, 0.80),
        (-1, None, 0.90),
        (None, 0.75, 1.0),
    ],
)
def test_exact_candidate_material_pressure_price_tiers_and_local_unknown(
    production, field, first_good, second_good, other_good, shortage, price, expected
):
    policy, overlay = _selection(production, field)
    values = _values(
        {f"mobilization_{first_good}_balance": shortage, f"mobilization_{first_good}_price": price}
    )
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert reference.get(field, ("native", 1.0))[1] == pytest.approx(expected)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(expected)
    # A different candidate's scarce input cannot become this one's cost.
    values[f"mobilization_{other_good}_balance"] = -100
    values[f"mobilization_{other_good}_price"] = 0.75
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("native", 1.0))[
        1
    ] == pytest.approx(expected)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("field", "goods"), [(FIRST, ("fabric", "liquor")), (FIELD, ("opium", "tools"))]
)
def test_all_independent_costs_join_war_once_and_do_not_multiply_or_double_count(
    production, field, goods
):
    policy, overlay = _selection(production, field)
    values = _values({"mobilization_war": True, "mobilization_default": True})
    for good in goods:
        values[f"mobilization_{good}_balance"] = -1
        values[f"mobilization_{good}_price"] = 0.75
    # 1 + .10 - .15 - .20 - .20 = .55; each .90 tier is superseded by .80.
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[field][1] == pytest.approx(0.55)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(0.55)
    values["mobilization_default"] = None
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[field][1] == pytest.approx(0.70)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(0.70)
    values[f"mobilization_{goods[0]}_price"] = None
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[field][1] == pytest.approx(0.80)
    assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(0.80)


@pytest.mark.parametrize(
    ("field", "goods"), [(FIRST, ("fabric", "liquor")), (FIELD, ("opium", "tools"))]
)
@pytest.mark.parametrize("unknown", ["owner", "first", "second"])
def test_owner_and_each_candidate_core_material_unknown_preserve_entire_native(
    production, field, goods, unknown
):
    policy, overlay = _selection(production, field)
    values = _values({"mobilization_war": True, "mobilization_default": True})
    for good in goods:
        values[f"mobilization_{good}_balance"] = -1
        values[f"mobilization_{good}_price"] = 0.75
    key = (
        "mobilization_owner_ai"
        if unknown == "owner"
        else f"mobilization_{goods[0 if unknown == 'first' else 1]}_balance"
    )
    values[key] = None
    assert (
        decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("native", 1.0))[1] == 1.0
    )
    assert _factor(pdx_eval.select(overlay, _facts(values))) == 1.0


@pytest.mark.parametrize("field", [FIRST, FIELD])
@pytest.mark.parametrize("mutation", ["owner", "market", "good", "player", "decoy", "loans"])
def test_real_owner_paths_players_missing_scopes_and_root_decoys(production, field, mutation):
    policy, overlay = _selection(production, field)
    values = _values({"mobilization_war": True})
    facts = _facts(values)
    expected = 1.0
    if mutation == "owner":
        del facts["ROOT"]["owner"]
    elif mutation == "market":
        del facts["ROOT"]["owner"]["market"]
    elif mutation == "good":
        del facts["ROOT"]["owner"]["market"]["mg:fabric" if field == FIRST else "mg:opium"]
    elif mutation == "player":
        facts["ROOT"]["owner"]["is_ai"] = False
        assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    elif mutation == "decoy":
        del facts["ROOT"]["owner"]
        facts["ROOT"].update(
            is_ai=True,
            is_at_war=True,
            market={"mg:fabric": {"market_goods_delta": -1, "market_goods_pricier": 0.75}},
        )
        facts["other_country"] = _facts(values)["ROOT"]["owner"]
    else:
        facts["ROOT"]["owner"].update(taking_loans=True, scaled_debt=0.10, net_total_income=-1)
        expected = 1.10
    assert _factor(pdx_eval.select(overlay, facts)) == pytest.approx(expected)
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}


def _tree(node):
    if isinstance(node, Scalar):
        return node.text, node.quoted
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def test_whole_18_definition_native_source_keeps_all_qualifications_effects_and_other_weights(
    production,
):
    before = production[3][SOURCE]
    patched = production[4][SOURCE]
    restored = re.sub(
        r"^[ \t]*# SITAI BEGIN information:[^\n]+\n.*?^[ \t]*# SITAI END information:[^\n]+\n?",
        "",
        patched,
        flags=re.MULTILINE | re.DOTALL,
    )
    original, stripped = parse_text(before), parse_text(restored)
    assert not original.errors
    assert not stripped.errors
    assert _tree(original.root) == _tree(stripped.root)
    assert len(list(original.root.assignments())) == 18
    actual = parse_text(patched)
    assert not actual.errors
    for definition in original.root.assignments():
        after = actual.root.first(definition.key)
        assert after is not None
        if definition.key not in medical.CANDIDATE_IDS:
            assert _tree(after) == _tree(definition)
        else:
            assert isinstance(definition.value, Block)
            assert isinstance(after.value, Block)
            for section in definition.value.assignments():
                if section.key != "ai_weight":
                    assert _tree(after.value.first(section.key)) == _tree(section)


@pytest.mark.parametrize(
    "mutation",
    [
        "root",
        "actor",
        "country_reader",
        "wrong_good",
        "partial_market_path",
        "context",
        "candidate",
    ],
)
def test_explicit_formation_types_exact_context_and_reader_identities_fail_closed(
    production, mutation
):
    policy = dict(production[1].policies)[SOURCE]
    model = production[2]
    if mutation == "root":
        with pytest.raises(ValueError, match="ROOT"):
            compiler.compile_policy(replace(policy, native_root="state"), SOURCE, model)
        return
    if mutation == "actor":
        with pytest.raises(ValueError, match="actor"):
            compiler.compile_policy(replace(policy, actor_path=()), SOURCE, model)
        return
    context = next(
        item.evaluation_context for item in model.action_instances if item.source == SOURCE
    )
    assert context is not None
    readers = {reader.key: reader for reader in policy.readers}
    key = "mobilization_fabric_balance"
    field = FIRST
    if mutation == "country_reader":
        readers[key] = replace(readers[key], path=())
    elif mutation == "wrong_good":
        readers[key] = replace(readers[key], path=("owner", "market", "mg:opium"))
    elif mutation == "partial_market_path":
        readers[key] = replace(readers[key], path=("owner", "mg:fabric"))
    elif mutation == "candidate":
        field = "mobilization_option_forced_march.ai_weight"
    else:
        context = decision_ir.EvaluationContext(
            actor_scope=decision_ir.ContextBinding("root", "country", "actor", "fake", 1),
            evidence=("fake:1",),
        )
    with pytest.raises(ValueError, match="动员"):
        compiler.validate_context_readers(
            field,
            context,
            readers,
            (),
            actor_path=("owner",),
            input_keys=(key,),
            source=SOURCE,
            native_root="military_formation",
        )


def test_typed_scope_never_calls_country_getter_on_formation_root(production):
    policy = dict(production[1].policies)[SOURCE]
    reader = next(reader for reader in policy.readers if reader.key == "mobilization_war")
    assert (
        decision_interfaces.reader_scope(reader, ("owner",), native_root="military_formation")
        == "country"
    )
    with pytest.raises(ValueError, match="作用域"):
        decision_interfaces.reader_scope(
            replace(reader, path=()), ("owner",), native_root="military_formation"
        )
    state_policy = next(
        policy
        for source, policy in production[1].policies
        if source.startswith("common/buildings/")
    )
    assert state_policy.native_root == "state"


def test_actual_source_drift_is_rejected_before_adapter_output(production):
    inputs = copy.deepcopy(production[3])
    inputs[SOURCE] += "\n# raw normalized source drift\n"
    with pytest.raises(ValueError, match=r"底本|漂移|指纹"):
        decision_adapters.build(
            production[1],
            texts=inputs,
            country_policy=country_state.load(),
            consumer_ir=production[2].consumer_ir,
        )


@pytest.mark.parametrize(
    ("candidate", "goods"),
    [
        ("extra_supplies", ("groceries",)),
        ("luxurious_supplies", ("meat", "wine")),
        ("chocolate", ("sugar",)),
        ("tobacco", ("tobacco",)),
        ("liquor", ("liquor",)),
        ("opium", ("opium",)),
        ("truck_transport", ("automobiles",)),
        ("rail_transport", ("engines",)),
        ("machinegunners", ("small_arms", "ammunition")),
        ("chemical_weapons", ("fertilizer",)),
        ("flamethrowers", ("oil",)),
        ("motorized_recon", ("automobiles", "oil")),
        ("balloon_recon", ("fabric", "oil")),
    ],
)
def test_every_added_choice_has_independent_need_cost_tiers_unknown_and_exit(
    production, candidate, goods
):
    field = f"mobilization_option_{candidate}.ai_weight"
    policy, overlay = _selection(production, field)
    values = _values(
        {f"mobilization_{good}_{tier}": 0 for good in goods for tier in ("balance", "price")}
    )

    def check(expected):
        assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(field, ("native", 1))[
            1
        ] == pytest.approx(expected)
        assert _factor(pdx_eval.select(overlay, _facts(values))) == pytest.approx(expected)

    check(1)
    values["mobilization_war"] = True
    check(1.10)
    values["mobilization_default"] = True
    check(0.95)
    first = goods[0]
    values[f"mobilization_{first}_balance"] = -1
    check(0.85)
    values[f"mobilization_{first}_price"] = 0.5
    check(0.85)
    values[f"mobilization_{first}_price"] = 0.50001
    check(0.75)
    values[f"mobilization_{first}_price"] = None
    check(0.85)
    values[f"mobilization_{first}_balance"] = None
    check(0.95)
    # 只观察到战争或只观察到成本也有局部结果，不需要健康国家的多重共同门。
    values["mobilization_default"] = None
    check(1.10)
    values["mobilization_war"] = None
    values["mobilization_default"] = True
    check(0.85)
    for good in goods:
        values[f"mobilization_{good}_balance"] = -1
        values[f"mobilization_{good}_price"] = 0.75
    values["mobilization_war"] = True
    check(0.95 - 0.20 * len(goods))
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert _factor(pdx_eval.select(overlay, _facts(values, is_ai=False))) == 1
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    values["mobilization_owner_ai"] = None
    check(1)
