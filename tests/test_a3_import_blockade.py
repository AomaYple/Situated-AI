"""Actual import/blockade observations, exact scopes and one mission envelope."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import replace

import pytest

from pdx import config, decision_adapters, decision_interfaces, decision_rules, observation_queries
from pdx import import_blockade_opportunities as exposure
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
VALUE_SOURCE = "common/script_values/sitai_adapter_values.txt"
VALUE_NAME = "sitai_adapter_fleet_supply_weight"
PROGRAM = (
    "program_" + hashlib.sha256(f"{exposure.SOURCE}:{exposure.FIELD}".encode()).hexdigest()[:16]
)


@pytest.fixture(scope="module")
def frozen():
    return exposure.frozen_inputs()


def test_exact_native_full_sources_current_installation_and_scope_proofs(frozen):
    actual = {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in exposure.SOURCES
    }
    assert frozen == actual
    refs = exposure.verify_inputs(frozen)
    assert f"{exposure.TRADE}:28" in refs
    assert f"{exposure.OPIUM}:38" in refs
    assert f"{exposure.ALERTS}:344" in refs
    for mode, engine, expected in (
        (
            "arms_import_volume",
            "market",
            "market = { mg:small_arms = { market_goods_imports >= 5 } }",
        ),
        (
            "arms_import_reliance",
            "market",
            "market = { market_imports_reliance = { goods = small_arms value > 0.25 } }",
        ),
        ("owned_state_blockade", "any_scope_state", "any_scope_state = { blockade_level > 0 }"),
    ):
        query = observation_queries.from_reader(engine, {exposure.QUERY_PARAMETER: mode})
        compiled = observation_queries.compile_query(query, frozen)
        assert compiled.expression == expected
        assert compiled.actor == "country"
        assert compiled.kind == "boolean"
        assert compiled.world_scans == 0
        assert "unknown" in compiled.unknown_policy
        assert set(observation_queries.required_sources(query)) == exposure.SOURCES
        assert set(dict(compiled.source_hashes)) == exposure.SOURCES
        assert compiled.local_collections == (
            ("owned_states",) if mode == "owned_state_blockade" else ("country_market",)
        )


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_market", {exposure.QUERY_PARAMETER: "arms_import_reliance"}),
        ("market", {exposure.QUERY_PARAMETER: "owned_state_blockade"}),
        ("any_scope_state", {exposure.QUERY_PARAMETER: "arms_import_volume"}),
        ("market", {exposure.QUERY_PARAMETER: "arms_import_volume", "goods": "opium"}),
        (
            "market",
            {exposure.QUERY_PARAMETER: "arms_import_reliance", "target": "scope:target_country"},
        ),
        ("market", {exposure.QUERY_PARAMETER: "arms_import_reliance", "threshold": "0"}),
    ],
)
def test_reader_rejects_foreign_market_free_goods_threshold_and_wrong_scope(engine, parameters):
    with pytest.raises(ValueError, match="精确"):
        exposure.query_from_reader(engine, parameters)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (exposure.TRADE, "type = country_event", "type = state_event"),
        (
            exposure.TRADE,
            "target = prev goods = small_arms value > 0.25",
            "target = root goods = small_arms value > 0.25",
        ),
        (exposure.TRADE, "goods = wine value >= 0.1", "target = prev goods = wine value >= 0.1"),
        (exposure.OPIUM, "market_goods_imports >= 200", "market_goods_exports >= 200"),
        (exposure.ALERTS, "script_context = player_state", "script_context = player_country"),
        (exposure.PULSE, "blockade_level >= 1", "blockade_level >= 0.1"),
    ],
)
def test_resigned_hash_does_not_hide_semantic_ast_role_or_getter_drift(
    frozen, monkeypatch, source, old, new
):
    changed = dict(frozen)
    assert old in changed[source]
    changed[source] = changed[source].replace(old, new)
    with pytest.raises(ValueError, match="来源漂移"):
        exposure.verify_inputs(changed)
    data = exposure.load()
    data["sources"][source] = hashlib.sha256(changed[source].encode()).hexdigest()
    monkeypatch.setattr(exposure, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        exposure.verify_inputs(changed)


@pytest.fixture(scope="module")
def generated():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[exposure.SOURCE]
    derived = exposure.derive(tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8")))
    selected_rules = tuple(r for r in original.rules if ".".join(r.field) == exposure.FIELD)
    assert {r["id"] for r in derived["rules"]} <= {r.id for r in selected_rules}
    used = {p.fact for r in selected_rules for p in r.conditions}
    policy = replace(
        original,
        rules=selected_rules,
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
        enabled_domains=frozenset({"military"}),
    )
    decision_interfaces.validate(policy)
    policy = programs.enable(policy, source=exposure.SOURCE)
    selected = replace(
        adapters,
        sources=tuple(sorted({**dict(adapters.sources), **derived["sources"]}.items())),
        policies=((exposure.SOURCE, policy),),
        initial_values=(),
        supply=None,
        scalar_values=tuple(
            r
            for r in adapters.scalar_values
            if r[0] == exposure.SOURCE and ".".join(r[1]) == exposure.FIELD
        ),
    )
    inputs = decision_adapters.read_inputs(selected)
    files, report = decision_adapters.build(selected, texts=inputs)
    overlay = pdx_eval.marked_block(files[VALUE_SOURCE], PROGRAM)
    return policy, selected, inputs, files, overlay, report


def _values(*, imports=5, reliance=0.26, states=None, war=True, navy=1, price=0, balance=0):
    if states is None:
        blockaded = None
    elif any(
        type(s.get("blockade_level")) in {int, float} and s["blockade_level"] > 0 for s in states
    ):
        blockaded = True
    elif any(s.get("blockade_level") is None for s in states):
        blockaded = None
    else:
        blockaded = False
    values = {
        "war": war,
        "navy": navy,
        "steamers_price": price,
        "steamers_balance": balance,
        "import_blockade_arms_import_volume": None if imports is None else imports >= 5,
        "import_blockade_arms_import_reliance": None if reliance is None else reliance > 0.25,
        "import_blockade_owned_state_blockade": blockaded,
    }
    facts = {
        "ROOT": {
            "is_ai": True,
            "is_at_war": war,
            "navy_size": navy,
            "market": {
                "mg:small_arms": {"market_goods_imports": imports},
                "mg:steamers": {"market_goods_pricier": price, "market_goods_delta": balance},
                "market_imports_reliance": {(("goods", "small_arms"),): reliance},
            },
            "any_scope_state": states,
        }
    }
    return values, facts


CASES = [
    ({}, 1.12),
    ({"imports": 4.999}, 1),
    ({"reliance": 0.25}, 1),
    ({"imports": None}, 1),
    ({"reliance": None}, 1),
    ({"states": []}, 1.12),
    ({"states": [{}]}, 1.12),
    ({"states": [{"blockade_level": 0}]}, 1.12),
    ({"states": [{"blockade_level": 0.001}]}, 1.18),
    ({"imports": 0, "states": [{"blockade_level": 0.5}]}, 1.18),
    ({"imports": None, "reliance": None, "states": [{"blockade_level": 1}]}, 1.18),
    ({"states": [{}, {"blockade_level": 0.5}]}, 1.18),
    ({"states": [{"blockade_level": 0.5}], "price": 0.3, "balance": -1}, 1.25),
    ({"states": [{"blockade_level": 0.5}], "price": 0.3}, 1.18),
    ({"imports": None, "reliance": None, "states": None, "price": 0.3, "balance": -1}, 1.25),
    ({"war": False, "states": [{"blockade_level": 1}]}, 1),
    ({"navy": 0, "states": [{"blockade_level": 1}]}, 1),
    ({"war": None, "states": [{"blockade_level": 1}]}, 1),
    ({"navy": None, "states": [{"blockade_level": 1}]}, 1),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_handwritten_reference_and_actual_adapter_pdx_same_cause_envelope(
    generated, changes, expected
):
    policy, _, _, _, overlay, _ = generated
    values, facts = _values(**changes)
    result = decision_rules.evaluate(policy, values, is_ai=True).get(exposure.FIELD)
    assert (result[1] if result else 1) == pytest.approx(expected)
    actual = pdx_eval.select(overlay, facts)
    assert actual.delta == pytest.approx(expected)
    assert 0 * actual.delta == 0
    assert len(policy.consumer_programs) == 1
    assert len(policy.consumer_programs[0].groups) == 1


def test_foreign_state_market_owner_and_goods_decoys_cannot_supply_actual_observation(generated):
    policy, _, _, _, overlay, _ = generated
    values, facts = _values(imports=0, reliance=0, states=[])
    facts["scope:target_country"] = _values(states=[{"blockade_level": 1}])[1]["ROOT"]
    facts["ROOT"]["owner"] = _values(states=[{"blockade_level": 1}])[1]["ROOT"]
    facts["ROOT"]["market"]["mg:opium"] = {"market_goods_imports": 10000}
    facts["ROOT"]["market"]["market_imports_reliance"][(("goods", "opium"),)] = 1
    facts["ROOT"]["any_market"] = [_values(states=[{"blockade_level": 1}])[1]["ROOT"]["market"]]
    assert pdx_eval.select(overlay, facts).delta == 1
    assert decision_rules.evaluate(policy, values, is_ai=True).get(exposure.FIELD) is None


def _tree(value):
    if isinstance(value, Block):
        return [(a.key, a.op, _tree(a.value)) for a in value.assignments()]
    assert isinstance(value, Scalar)
    return value.unquoted


def _fleet(text):
    root = parse_text(text).root
    for key in ("ai_strategy_default", "fleet_compositions"):
        assignment = root.first(key)
        assert assignment is not None
        assert isinstance(assignment.value, Block)
        root = assignment.value
    return root


def test_full_native_fleets_qualification_zero_disable_and_unknown_preserved(generated):
    policy, selected, inputs, files, overlay, _ = generated
    restored = files[exposure.SOURCE].replace(
        f"protect_supply = {VALUE_NAME}", "protect_supply = 1.0"
    )
    assert _tree(_fleet(restored)) == _tree(_fleet(inputs[exposure.SOURCE]))
    assert "set_variable" not in files[VALUE_SOURCE]
    assert "any_market" not in overlay
    assert "any_country" not in overlay
    disabled, _ = decision_adapters.build(selected, texts=inputs, enabled_domains=frozenset())
    assert disabled == {}
    values, facts = _values(states=[{"blockade_level": 1}])
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    facts["ROOT"]["is_ai"] = False
    assert pdx_eval.select(overlay, facts).delta == 0
    facts["ROOT"] = None
    assert pdx_eval.select(overlay, facts).fallback in {"unknown", "vanilla"}


def test_frozen_derivation_offline_and_current_loader_single_writer(monkeypatch, tmp_path):
    raw = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    expected = exposure.derive(raw)
    monkeypatch.setattr(config, "GAME", tmp_path / "no-installation")
    assert exposure.derive(raw) == expected
    assert len(expected["rules"]) == 2
    assert len(expected["covered"]) == 1
    assert {r.get("contribution_group", "") for r in expected["rules"]} == {""}
    assert all(r["semantic_role"] == "benefit" for r in expected["rules"])
    loaded = decision_adapters.load()
    policy = dict(loaded.policies)[exposure.SOURCE]
    assert {r["id"] for r in expected["rules"]} <= {r.id for r in policy.rules}
    assert (
        sum(
            (s == exposure.SOURCE and ".".join(f) == exposure.FIELD)
            for s, f, _ in decision_adapters.writes(loaded)
        )
        == 1
    )


def test_actual_compiler_and_consumer_ir_keep_new_observations_in_shared_writer(generated):
    policy, selected, inputs, _, _, _ = generated
    model = compiler.load_model()
    assert model.consumer_ir is not None
    lowered, _ = compiler.compile_policy(policy, exposure.SOURCE, model)
    selected = replace(selected, policies=((exposure.SOURCE, lowered),))
    files, _ = decision_adapters.build(selected, texts=inputs, consumer_ir=model.consumer_ir)
    overlay = pdx_eval.marked_block(files[VALUE_SOURCE], PROGRAM)
    for changes, expected in (
        ({}, 1.12),
        ({"states": [{"blockade_level": 0.5}]}, 1.18),
        ({"states": [{"blockade_level": 0.5}], "price": 0.3, "balance": -1}, 1.25),
    ):
        values, facts = _values(**changes)
        assert pdx_eval.select(overlay, facts).delta == pytest.approx(expected)
        assert decision_rules.evaluate(lowered, values, is_ai=True)[exposure.FIELD][
            1
        ] == pytest.approx(expected)
    assert len(lowered.consumer_programs) == 1
    assert len(lowered.consumer_programs[0].groups) == 1
