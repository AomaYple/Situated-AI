"""Reader proof follows complete logical envelopes and independent authors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_native_parameter_closure import _reader_case

from pdx import decision_adapters, decision_rules, observation_queries
from pdx.situated import engine_scope, programs, supply_program, vanilla_inventory
from pdx.situated.ir import from_rule
from pdx.situated.native_treatments import (
    _Dependencies,
    _implicit_conditions_known,
    _resolve,
    _Sources,
    _supply_enum_projections,
    native_treatments,
)

pytestmark = pytest.mark.unit
METADATA = ".metadata/metadata.json"
DEFAULT = "common/ai_strategies/00_default_strategy.txt"


@pytest.fixture
def supply_enum_case(tmp_path, monkeypatch):
    case = _reader_case("resource", tmp_path, monkeypatch)
    inventory, native, generated, path = case
    adapters = decision_adapters.load()
    old, policy = adapters.policies[0]
    baseline = (
        b"ai_strategy_default={weight={value=10} goods_stances={"
        b"grain={stance=wants_high_supply trigger={has_famine=yes}}}}"
    )
    native.pop(old)
    for name in list(native):
        if name.startswith("common/goods/"):
            native.pop(name)
    native[DEFAULT] = baseline
    evidence = {
        "common/goods/00_goods.txt": b"grain={} glass={} tools={}",
        "common/alert_types/00_alert_types.txt": (
            b"expensive_government_goods_alert={script_context=player_market_goods valid={market_goods_pricier>0.25}}"
        ),
        "common/objective_subgoals/00_subgoals_tutorial.txt": (
            b"sg_change_production_method={trigger={any_scope_state={OR={AND={market={mg:tools={market_goods_delta>=10}}}}}}}"
        ),
    }
    native.update(evidence)
    for name, raw in evidence.items():
        monkeypatch.setitem(
            vanilla_inventory._PARAMETER_EVIDENCE_HASHES, name, hashlib.sha256(raw).hexdigest()
        )
    monkeypatch.setattr(
        engine_scope,
        "strategy_snapshot",
        lambda: json.dumps(
            {"script_hashes": {DEFAULT: hashlib.sha256(baseline).hexdigest()}}
        ).encode(),
    )
    rule = replace(policy.rules[0], field=("ai_strategy_default", "weight"), domain="market")
    policy = replace(
        policy,
        rules=(rule,),
        enabled_domains=frozenset({"market"}),
        native_root="country",
        actor_path=(),
        readers=(replace(policy.readers[0], path=("market", "mg:tools")),),
    )
    adapters = replace(
        adapters,
        sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in native.items()),
        policies=((DEFAULT, policy),),
        supply=decision_adapters.SupplyPlan(DEFAULT, ("glass", "tools"), 0.25),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    assert adapters.supply is not None
    metadata = json.loads(generated[METADATA])
    metadata["consumer_adapters"].update(
        supply_program_generator_sha256=hashlib.sha256(
            Path(supply_program.__file__).read_bytes()
        ).hexdigest(),
        sources=dict(adapters.sources),
        consumers=[
            {
                "source": DEFAULT,
                **decision_rules.contract(policy, owner="consumer_adapters", source=DEFAULT),
            }
        ],
        supply_plan={
            "source": DEFAULT,
            "field": "ai_strategy_default.goods_stances",
            "goods": ["glass", "tools"],
            "price_threshold": 0.25,
            "stance": "wants_high_supply",
            "conditions": [
                "is_ai",
                "existing_market_goods",
                "price_above_threshold",
                "negative_market_goods_delta",
            ],
            "consumer": "vanilla_production_and_trade_planning",
            "behavior_verified": False,
            "limits": "market_aggregate_not_national_import_dependency; active_strategy_overrides_retained; no_forced_trade_or_production_method",
            "consumer_programs": [program.as_dict() for program in adapters.supply.actions()],
        },
    )
    generated.pop(old)
    additions = b" ".join(
        (
            f"{good}={{stance=wants_high_supply trigger={{is_ai=yes exists=market "
            f"market={{exists=mg:{good} mg:{good}={{market_goods_pricier>0.25 "
            "market_goods_delta<0}}}}"
        ).encode()
        for good in ("glass", "tools")
    )
    generated[DEFAULT] = baseline[:-2] + additions + b"}}"
    generated[METADATA] = json.dumps(metadata).encode()
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    return inventory, native, generated, path


def test_complete_supply_enum_projection_has_separate_non_numeric_responsibility(supply_enum_case):
    result = _supply_enum_projections(_dependencies(supply_enum_case))
    assert len(result[DEFAULT]) == 2
    assert {row["field"] for row in result[DEFAULT].values()} == {
        "goods_stances.glass",
        "goods_stances.tools",
    }
    assert all(row["kind"] == "registered_enum_addition" for row in result[DEFAULT].values())
    assert all(row["business_complete"] is False for row in result[DEFAULT].values())


def test_supply_enum_projection_closes_the_original_source_without_numeric_credit(supply_enum_case):
    inventory, native, generated, _ = supply_enum_case
    surface = replace(
        inventory.surfaces[0],
        source=DEFAULT,
        definition="ai_strategy_default",
        field="goods_stances.grain",
        source_line=1,
        parent_field=None,
        parent_source_line=None,
    )
    inventory = replace(inventory, surfaces=(surface,))
    result = native_treatments(inventory, native, generated, production_complete=True)
    row = result["rows"][0]
    assert row["source_protection"]["proven"]
    assert row["source_protection"]["context_closed"]
    assert len(row["source_protection"]["implicit_enum_projections"]) == 2
    assert not row["source_protection"]["implicit_numeric_projections"]
    assert not row["implemented_numeric"]
    assert not row["active_unknown_usage"]


def test_supply_getter_proof_checks_actual_ast_after_a_new_hash(supply_enum_case, monkeypatch):
    inventory, native, generated, path = supply_enum_case
    name = "common/alert_types/00_alert_types.txt"
    native[name] = native[name].replace(b"market_goods_pricier", b"invented_getter")
    monkeypatch.setitem(
        vanilla_inventory._PARAMETER_EVIDENCE_HASHES, name, hashlib.sha256(native[name]).hexdigest()
    )
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    assert not _supply_enum_projections(_dependencies((inventory, native, generated, path)))


@pytest.mark.parametrize(
    "fault",
    [
        "threshold",
        "player",
        "market_guard",
        "good_guard",
        "scope",
        "stance",
        "balance",
        "duplicate",
        "original",
        "extra",
        "metadata",
        "missing_metadata",
        "native_bytes",
        "getter",
        "duplicate_good",
        "duplicate_strategy",
        "program_contract",
        "program_generator",
    ],
)
def test_supply_projection_rejects_incomplete_or_changed_enum_context(supply_enum_case, fault):
    _inventory, native, generated, _ = supply_enum_case
    replacements = {
        "threshold": (b"pricier>0.25", b"pricier>0.5"),
        "player": (b"is_ai=yes", b"is_ai=no"),
        "market_guard": (b"exists=market", b"always=yes"),
        "good_guard": (b"exists=mg:tools", b"always=yes"),
        "scope": (b"market={exists", b"owner={exists"),
        "stance": (b"tools={stance=wants_high_supply", b"tools={stance=export"),
        "balance": (b"delta<0", b"delta>0"),
        "original": (b"has_famine=yes", b"has_famine=no"),
        "duplicate": (b"goods_stances={", b"goods_stances={tools={} "),
        "extra": (b"goods_stances={", b"goods_stances={invented={} "),
    }
    if fault in replacements:
        before, after = replacements[fault]
        assert before in generated[DEFAULT]
        generated[DEFAULT] = generated[DEFAULT].replace(before, after)
    elif fault in {"metadata", "missing_metadata", "program_contract", "program_generator"}:
        document = json.loads(generated[METADATA])
        if fault == "metadata":
            document["consumer_adapters"]["supply_plan"]["behavior_verified"] = True
        elif fault == "missing_metadata":
            document["consumer_adapters"].pop("supply_plan")
        elif fault == "program_generator":
            document["consumer_adapters"]["supply_program_generator_sha256"] = "0" * 64
        else:
            document["consumer_adapters"]["supply_plan"]["consumer_programs"][0][
                "unknown_policy"
            ] = "assume_zero"
        generated[METADATA] = json.dumps(document).encode()
    elif fault == "native_bytes":
        native["common/goods/00_goods.txt"] += b"# drift"
    elif fault == "getter":
        generated["common/alert_types/00_alert_types.txt"] = b"example={}"
    elif fault == "duplicate_good":
        generated["common/goods/duplicate.txt"] = b"tools={}"
    else:
        generated["common/ai_strategies/duplicate.txt"] = b"ai_strategy_default={}"
    assert not _supply_enum_projections(_dependencies(supply_enum_case))


def _dependencies(case):
    inventory, native, generated, _ = case
    return _Dependencies(
        _Sources(native),
        _Sources({**native, **generated}),
        native,
        {**native, **generated},
        inventory.source_hashes,
        production_complete=True,
    )


def _conditions(case):
    deps = _dependencies(case)
    surface = case[0].surfaces[0]
    before, _ = _resolve(deps.native.roots[surface.source], surface.definition, surface.field)
    after, _ = _resolve(deps.effective.roots[surface.source], surface.definition, surface.field)
    assert before is not None
    assert after is not None
    return deps.parameter_conditions(
        before, after, surface.source, surface.definition, surface.field, surface.actor_scope
    )


@pytest.fixture(params=["AND", "OR", "AND_NOT"])
def wrapper_case(request, tmp_path, monkeypatch):
    render = observation_queries.render

    def wrapped(query):
        original = render(query)
        if request.param == "AND_NOT":
            return f"AND = {{ NOT = {{ {original} }} always = yes }}"
        return f"{request.param} = {{ {original} always = yes }}"

    monkeypatch.setattr(observation_queries, "render", wrapped)
    return _reader_case("query", tmp_path, monkeypatch)


def test_full_registered_logical_envelope_closes_exact_query(wrapper_case):
    rows, valid = _conditions(wrapper_case)
    assert valid
    assert next(iter(rows.values()))["status"] == "proven_parameter_reader"


@pytest.mark.parametrize("fault", ["sibling", "query", "scope", "unwrapped", "extra_query"])
def test_envelope_does_not_license_a_matching_leaf_with_different_context(wrapper_case, fault):
    source = wrapper_case[0].surfaces[0].source
    raw = wrapper_case[2][source]
    if fault == "sibling":
        raw = raw.replace(b"always = yes", b"always = no")
    elif fault == "query":
        raw = raw.replace(b"market_access < 1.0", b"market_access < 0.9")
    elif fault == "scope":
        raw = raw.replace(b"ROOT = {", b"scope:target_country = {")
    elif fault == "unwrapped":
        # Same query AST moved outside its registered composite expression.
        raw = b"candidate={weight={value=10 if={limit={ROOT={any_scope_state={market_access<1.0}}} add=2}}}"
    else:
        raw = raw.replace(b"always = yes", b"always = yes any_scope_state={market_access<0.9}")
    assert raw != wrapper_case[2][source]
    wrapper_case[2][source] = raw
    assert not _conditions(wrapper_case)[1]


@pytest.fixture
def information_case(tmp_path, monkeypatch):
    case = _reader_case("resource", tmp_path, monkeypatch)
    inventory, native, generated, path = case
    old = inventory.surfaces[0].source
    adapters = decision_adapters.load()
    old_policy = dict(adapters.policies)[old]
    baseline = b"ai_strategy_default={wanted_construction_output={value=10}}"
    native.pop(old)
    native[DEFAULT] = baseline
    reader = replace(old_policy.readers[0], path=("market", "mg:tools"))
    rule = replace(
        old_policy.rules[0], field=("wanted_construction_output",), operation="multiply", value=1.2
    )
    policy = replace(
        old_policy,
        readers=(reader,),
        rules=(rule,),
        baseline_sha256=hashlib.sha256(baseline).hexdigest(),
        actor_path=(),
        native_root="country",
    )
    compiled = programs.enable(
        replace(
            policy,
            semantic_ir=tuple(
                replace(
                    from_rule(item, source="mod/decisions/information.toml"),
                    origin_priority=item.priority,
                )
                for item in policy.rules
            ),
        ),
        source="mod/decisions/information.toml",
    )
    updated = replace(
        adapters,
        sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in native.items()),
        policies=(),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: updated)
    monkeypatch.setattr(decision_rules, "load", lambda: policy)
    metadata = json.loads(generated[METADATA])
    metadata["consumer_adapters"]["sources"] = dict(updated.sources)
    metadata["consumer_adapters"]["consumers"] = []
    metadata["decision_rules"] = decision_rules.contract(compiled)
    metadata["source_fingerprint"] = {
        "information_rules_source_sha256": policy.source_sha256,
        "information_rules_generator_sha256": hashlib.sha256(
            Path(decision_rules.__file__).read_bytes()
        ).hexdigest(),
    }
    metadata["enabled_modules"] = ["information_rules"]
    metadata["default_field_owners"] = {"wanted_construction_output": "information_rules"}
    generated.pop(old)
    generated[DEFAULT] = (
        b"ai_strategy_default={wanted_construction_output={value=10 if={limit={exists=ROOT ROOT={exists=market market={exists=mg:tools mg:tools={market_goods_pricier<=0.25}}}} multiply=1.2}}}"
    )
    generated[METADATA] = json.dumps(metadata).encode()
    surface = replace(
        inventory.surfaces[0],
        source=DEFAULT,
        definition="ai_strategy_default",
        field="wanted_construction_output",
        actor_scope="country",
        operation="additive_construction_output_target",
    )
    inventory = replace(
        inventory,
        surfaces=(surface,),
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    return inventory, native, generated, path


def test_information_reader_uses_its_complete_independent_contract(information_case):
    rows, valid = _conditions(information_case)
    assert valid
    assert next(iter(rows.values()))["bindings"]


@pytest.mark.parametrize(
    "fault",
    ["missing", "priority", "source", "owner", "field_owner", "extra", "baseline", "module"],
)
def test_information_contract_drift_cannot_borrow_an_adapter_contract(information_case, fault):
    generated = information_case[2]
    metadata = json.loads(generated[METADATA])
    contract = metadata["decision_rules"]
    if fault == "missing":
        metadata.pop("decision_rules")
    elif fault == "priority":
        contract["consumer_programs"]["programs"][0]["groups"][0]["variants"][0][
            "origin_priority"
        ] = 999
    elif fault == "source":
        metadata["source_fingerprint"]["information_rules_source_sha256"] = "f" * 64
    elif fault == "owner":
        contract["field_owners"]["wanted_construction_output"] = "consumer_adapters"
    elif fault == "field_owner":
        metadata["default_field_owners"]["wanted_construction_output"] = "consumer_adapters"
    elif fault == "extra":
        contract["invented_permission"] = True
    elif fault == "baseline":
        contract["baseline_sha256"] = "f" * 64
    else:
        metadata["enabled_modules"] = []
    generated[METADATA] = json.dumps(metadata).encode()
    assert not _conditions(information_case)[1]


@pytest.mark.parametrize("fault", ["missing", "generator", "source"])
def test_even_a_complete_adapter_cannot_authorize_an_information_owned_field(
    information_case, monkeypatch, fault
):
    adapters = decision_adapters.load()
    information = decision_rules.load()
    borrowed = replace(
        information,
        rules=tuple(
            replace(rule, field=("ai_strategy_default", *rule.field)) for rule in information.rules
        ),
    )
    updated = replace(adapters, policies=((DEFAULT, borrowed),))
    monkeypatch.setattr(decision_adapters, "load", lambda: updated)
    metadata = json.loads(information_case[2][METADATA])
    metadata["consumer_adapters"]["consumers"] = [
        {
            "source": DEFAULT,
            **decision_rules.contract(borrowed, owner="consumer_adapters", source=DEFAULT),
        }
    ]
    if fault == "missing":
        metadata.pop("decision_rules")
    else:
        metadata["source_fingerprint"][f"information_rules_{fault}_sha256"] = "f" * 64
    information_case[2][METADATA] = json.dumps(metadata).encode()
    assert not _conditions(information_case)[1]


@pytest.fixture(params=["bounds", "required_known"])
def guarded_resource_case(request, tmp_path, monkeypatch):
    case = _reader_case("resource", tmp_path, monkeypatch)
    source = case[0].surfaces[0].source
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)[source]
    reader = policy.readers[0]
    rule = policy.rules[0]
    if request.param == "bounds":
        reader = replace(reader, minimum=0, maximum=1)
    else:
        rule = replace(rule, required_known_facts=(reader.key,))
    policy = replace(policy, readers=(reader,), rules=(rule,))
    updated = replace(adapters, policies=((source, policy),))
    monkeypatch.setattr(decision_adapters, "load", lambda: updated)
    metadata = json.loads(case[2][METADATA])
    metadata["consumer_adapters"]["consumers"] = [
        {
            "source": source,
            **decision_rules.contract(policy, owner="consumer_adapters", source=source),
        }
    ]
    case[2][METADATA] = json.dumps(metadata).encode()
    terms = [reader.expression("<=", 0.25), *decision_rules._reader_bounds(reader)]
    if request.param == "required_known":
        known = reader.expression(">=", 0)
        terms.append(f"OR = {{ {known} NOT = {{ {known} }} }}")
    statement = decision_rules._scoped_conditions({(reader.scope, reader.path): terms})
    case[2][source] = (
        f"candidate={{ai_value={{value=10 if={{limit={{{statement}}} add=2}}}}}}".encode()
    )
    return case, request.param


def test_exact_reader_bounds_and_required_known_guards_are_authorized(guarded_resource_case):
    case, _kind = guarded_resource_case
    assert _conditions(case)[1]


@pytest.mark.parametrize("fault", ["value", "scope", "guard_to_predicate"])
def test_known_guards_cannot_license_a_new_threshold_or_context(guarded_resource_case, fault):
    case, kind = guarded_resource_case
    source = case[0].surfaces[0].source
    raw = case[2][source]
    if fault == "value":
        raw = raw.replace(b"market_goods_pricier >= 0", b"market_goods_pricier >= 0.1")
    elif fault == "scope":
        raw = raw.replace(b"mg:tools", b"mg:invented")
    elif kind == "required_known":
        raw = raw.replace(
            b"OR = { market_goods_pricier >= 0 NOT = { market_goods_pricier >= 0 } }",
            b"market_goods_pricier >= 0",
        )
    else:
        raw = raw.replace(b"market_goods_pricier >= 0", b"market_goods_pricier > 0")
    assert raw != case[2][source]
    case[2][source] = raw
    assert not _conditions(case)[1]


@pytest.mark.parametrize("fault", [None, "body", "duplicate", "guard"])
def test_native_query_requires_the_complete_original_fragment_despite_inserted_branches(
    tmp_path, monkeypatch, fault
):
    case = _reader_case("query", tmp_path, monkeypatch)
    source = case[0].surfaces[0].source
    fragment = (
        b"if={limit={scope:target_state={NOT={state_region={any_scope_state={is_ai=yes}}}}} add=1}"
    )
    case[1][source] = b"candidate={weight={value=10 " + fragment + b"}}"
    retained = fragment
    if fault == "body":
        retained = fragment.replace(b"add=1", b"add=9")
    elif fault == "guard":
        retained = fragment.replace(b"NOT={state_region", b"OR={state_region")
    elif fault == "duplicate":
        retained += b" " + fragment
    case[2][source] = (
        b"candidate={weight={value=10 if={limit={always=no} add=2} " + retained + b"}}"
    )
    assert _conditions(case)[1] == (fault is None)


@pytest.mark.parametrize("fault", [None, "ancestor_guard", "inner_body", "duplicate", "scope"])
def test_nested_native_fragment_keeps_all_ancestor_guards_and_exact_body(
    tmp_path, monkeypatch, fault
):
    case = _reader_case("query", tmp_path, monkeypatch)
    source = case[0].surfaces[0].source
    inner = b"if={limit={scope:target_state={any_scope_state={is_ai=yes}}} add=1}"
    outer = b"if={limit={always=yes} "
    case[1][source] = b"candidate={weight={value=10 " + outer + inner + b"}}}"
    changed = inner
    if fault == "ancestor_guard":
        outer = b"if={limit={always=no} "
    elif fault == "inner_body":
        changed = inner.replace(b"add=1", b"add=9")
    elif fault == "duplicate":
        changed += b" " + inner
    elif fault == "scope":
        changed = inner.replace(b"scope:target_state", b"scope:target_country")
    case[2][source] = (
        b"candidate={weight={value=10 "
        + outer
        + b"if={limit={always=no} add=2} "
        + changed
        + b"}}}"
    )
    assert _conditions(case)[1] == (fault is None)


@pytest.fixture(params=["laborers", "peasants", "machinists"])
def population_case(tmp_path, monkeypatch, request):
    case = _reader_case("resource", tmp_path, monkeypatch)
    inventory, native, generated, _ = case
    source = inventory.surfaces[0].source
    getter = "common/journal_entries/00_urbanization.txt"
    pop_type = request.param
    definition = f"common/pop_types/{pop_type}.txt"
    native[getter] = (
        b"je_urbanization_events_1={possible={pop_type_percent_country={pop_type=peasants percent>0.6}}}"
    )
    native[definition] = f"{pop_type}={{wage_weight=1}}".encode()
    for name in (getter, definition):
        monkeypatch.setitem(
            vanilla_inventory._PARAMETER_EVIDENCE_HASHES,
            name,
            hashlib.sha256(native[name]).hexdigest(),
        )
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)[source]
    reader = replace(
        policy.readers[0],
        engine="pop_type_percent_country",
        unit="ratio",
        minimum=0,
        maximum=1,
        path=("owner",),
        value_field="percent",
        parameters=(("pop_type", pop_type),),
    )
    policy = replace(policy, readers=(reader,))
    updated = replace(adapters, policies=((source, policy),))
    monkeypatch.setattr(decision_adapters, "load", lambda: updated)
    metadata = json.loads(generated[METADATA])
    metadata["consumer_adapters"]["consumers"] = [
        {
            "source": source,
            **decision_rules.contract(policy, owner="consumer_adapters", source=source),
        }
    ]
    generated[METADATA] = json.dumps(metadata).encode()
    statement = decision_rules._scoped_conditions(
        {
            (reader.scope, reader.path): [
                reader.expression("<=", 0.25),
                *decision_rules._reader_bounds(reader),
            ]
        }
    )
    generated[source] = (
        f"candidate={{ai_value={{value=10 if={{limit={{{statement}}} add=2}}}}}}".encode()
    )
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    return inventory, native, generated, case[3]


def test_exact_population_reader_closes_the_optional_field_condition(population_case):
    assert _conditions(population_case)[1]
    deps = _dependencies(population_case)
    surface = population_case[0].surfaces[0]
    proof = deps.parameter_readers(
        surface.source, surface.definition, surface.field, surface.actor_scope
    )
    node, _ = _resolve(deps.effective.roots[surface.source], surface.definition, surface.field)
    assert node is not None
    assert _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, proof)
    assert not _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, {})
    pop_type = decision_adapters.load().policies[0][1].readers[0].parameters[0][1]
    assert f"common/pop_types/{pop_type}.txt" in proof["native_sources"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "bytes",
        "getter_ast",
        "definition",
        "duplicate",
        "argument",
        "field",
        "scope",
        "extra_parameter",
    ],
)
def test_population_reader_does_not_license_a_name_without_original_context(
    population_case, monkeypatch, fault
):
    native, generated = population_case[1:3]
    source = population_case[0].surfaces[0].source
    getter = "common/journal_entries/00_urbanization.txt"
    pop_type = decision_adapters.load().policies[0][1].readers[0].parameters[0][1]
    definition = f"common/pop_types/{pop_type}.txt"
    if fault == "missing":
        native.pop(definition)
    elif fault == "bytes":
        native[definition] += b"\n# drift"
    elif fault == "getter_ast":
        native[getter] = native[getter].replace(b"percent>0.6", b"value>0.6")
        monkeypatch.setitem(
            vanilla_inventory._PARAMETER_EVIDENCE_HASHES,
            getter,
            hashlib.sha256(native[getter]).hexdigest(),
        )
    elif fault == "definition":
        native[definition] = b"invented={wage_weight=1}"
        monkeypatch.setitem(
            vanilla_inventory._PARAMETER_EVIDENCE_HASHES,
            definition,
            hashlib.sha256(native[definition]).hexdigest(),
        )
    elif fault == "duplicate":
        generated["common/pop_types/duplicate.txt"] = f"{pop_type}={{wage_weight=1}}".encode()
    elif fault == "argument":
        generated[source] = generated[source].replace(
            f"pop_type = {pop_type}".encode(), b"pop_type = invented"
        )
    elif fault == "extra_parameter":
        generated[source] = generated[source].replace(
            f"pop_type = {pop_type}".encode(), f"pop_type = {pop_type} invented = yes".encode()
        )
    elif fault == "field":
        generated[source] = (
            generated[source]
            .replace(b"percent >=", b"value >=")
            .replace(b"percent <=", b"value <=")
        )
    else:
        generated[source] = generated[source].replace(b"owner = {", b"market = {")
    if fault in {"getter_ast", "definition"}:
        inventory, _native, _generated, path = population_case
        population_case = (
            replace(
                inventory,
                source_hashes={
                    name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()
                },
            ),
            native,
            generated,
            path,
        )
    assert not _conditions(population_case)[1]


@pytest.mark.parametrize(
    "source",
    [
        "common/achievements/ep1_sphere_of_influence_achievements.txt",
        "common/achievements/ip4_iberian_twilight_achievements.txt",
    ],
)
@pytest.mark.parametrize("fault", ["missing", "drift"])
def test_country_auxiliary_sources_remain_required_exact_bytes(
    tmp_path, monkeypatch, source, fault
):
    expected = vanilla_inventory._PARAMETER_EVIDENCE_HASHES[source]
    monkeypatch.setattr(vanilla_inventory, "_PARAMETER_EVIDENCE_HASHES", {source: expected})
    if fault == "missing":
        assert vanilla_inventory.parameter_evidence_hashes(tmp_path) == {}
    else:
        path = tmp_path / source
        path.parent.mkdir(parents=True)
        path.write_bytes(b"drifted={}")
        with pytest.raises(ValueError, match="参数原版证据漂移"):
            vanilla_inventory.parameter_evidence_hashes(tmp_path)
