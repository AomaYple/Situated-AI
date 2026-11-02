"""Hand-calculated equipment material tradeoffs and native-script preservation."""

import copy
import hashlib
import json
from typing import Any

import pytest

from pdx import config, decision_rules, equipment_opportunities
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit
SOURCE = "common/ship_modifications/ships.txt"
GOODS = "common/goods/goods.txt"
HELPER = "common/script_values/ai_script_values.txt"
DOC = "common/ship_modifications/ship_modifications.md"
FORMULA_DOC = "common/script_values/script_values.md"
NATIVE = """
ship_a = {
 type = armor
 construction_goods = { goods_input_steel_add = 4 goods_input_coal_add = 2 }
 materiel_goods = { goods_input_coal_add = 1 }
 unlocking_technologies = { steelworking }
 incompatible_with = ship_b
 ai_weight = { value = 2 multiply = ship_mod_market_multiplier multiply = native_doctrine }
}
ship_b = {
 type = gun
 construction_goods = { goods_input_artillery_add = 3 }
 ai_weight = { value = 2 multiply = ship_mod_market_multiplier multiply = native_doctrine }
}
ship_zero = {
 type = armor
 construction_goods = { goods_input_steel_add = 1 }
 ai_weight = { value = 0 multiply = ship_mod_market_multiplier }
}
ship_negative = {
 type = armor
 construction_goods = { goods_input_steel_add = 1 }
 ai_weight = { value = -2 multiply = ship_mod_market_multiplier }
}
ship_tail = {
 type = armor
 construction_goods = { goods_input_steel_add = 1 }
 ai_weight = {
  value = 2 multiply = ship_mod_market_multiplier multiply = native_doctrine
  if = { limit = { always = yes } multiply = 0 }
 }
}
ship_local = {
 type = propulsion
 construction_goods = { goods_input_electricity_add = 1 }
 ai_weight = { value = 1 multiply = ship_mod_market_multiplier }
}
ship_missing = { type = armor }
ship_scalar = { type = armor ai_weight = 1 }
ship_empty = { type = armor ai_weight = { value = 1 multiply = ship_mod_market_multiplier } }
ship_unproved = { type = armor ai_weight = { value = 1 } }
"""


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "game"
    inputs = {
        SOURCE: NATIVE,
        GOODS: "steel = {}\ncoal = {}\nartillery = {}\nelectricity = { local = yes }\n",
        DOC: "# [Default = 1] How important is this ship type to build for AI\n"
        "# root - country\nai_weight = fixed_point\n",
        FORMULA_DOC: "# Formulas\nThese allow everything in the scope you're currently in.\n",
        # This fixture's formula result is explicitly reset to 1; doctrine is .5.
        HELPER: 'ship_mod_market_multiplier = { value = "ship_modification_market_demand_ratio(scope:ship_modification_type)" value = 1 }\n'
        "native_doctrine = { value = 0.5 }\n",
        "events/unrelated.txt": "event = {}\n",
    }
    for source, text in inputs.items():
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def baseline(game, tmp_path, monkeypatch):
    monkeypatch.setattr(equipment_opportunities, "BASELINE", tmp_path / "baseline.json")
    path = equipment_opportunities.write_baseline(game)
    monkeypatch.setattr(
        equipment_opportunities, "BASELINE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    return equipment_opportunities.load_baseline()


@pytest.fixture
def raw():
    return {"sources": {}, "readers": {}, "rules": []}


def _policy(derived, candidate):
    rules = [row for row in derived["rules"] if row["field"] == f"{candidate}.ai_weight"]
    keys = {condition["fact"] for row in rules for condition in row["conditions"]}
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][SOURCE],
            "domains": {"military": True},
            "readers": {key: spec for key, spec in derived["readers"].items() if key in keys},
            "rules": [
                {key: value for key, value in row.items() if key != "source"} for row in rules
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=SOURCE)


def _patched(policy, *, enabled=True):
    words = frozenset(
        {"market", "in_default", "market_goods_pricier", "market_goods_delta"}
        | {f"mg:{good}" for good in ("steel", "coal", "artillery")}
    )
    return decision_rules.patch(
        NATIVE,
        policy,
        baseline=NATIVE,
        default_strategy=False,
        reader_words=words,
        enabled_domains=frozenset({"military"}) if enabled else frozenset(),
    )


def _observations(changes, *, is_ai=True):
    # Handwritten engine mappings do not call the production reader renderer.
    root: dict[str, Any] = {
        "is_ai": is_ai,
        "taking_loans": True,
        "bureaucracy": -10,
        "literacy_rate": 0.01,
        "market": {},
    }
    for good in ("steel", "coal", "artillery"):
        observation = {}
        for suffix, engine in (
            ("price", "market_goods_pricier"),
            ("balance", "market_goods_delta"),
        ):
            key = f"country_goods_{good}_{suffix}"
            if key in changes:
                observation[engine] = changes[key]
        if observation:
            root["market"][f"mg:{good}"] = observation
    if "default" in changes:
        root["in_default"] = changes["default"]
    return {"ROOT": root}


def _overlay(text, candidate):
    field = f"{candidate}.ai_weight"
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _joint(raw, baseline, changes, expected, *, candidate="ship_a", is_ai=True, enabled=True):
    derived = equipment_opportunities.derive(raw, baseline)
    policy = _policy(derived, candidate)
    values = {reader.key: changes.get(reader.key) for reader in policy.readers}
    reference = decision_rules.evaluate(
        policy,
        values,
        is_ai=is_ai,
        enabled_domains=frozenset({"military"}) if enabled else frozenset(),
    ).get(f"{candidate}.ai_weight")
    assert (reference[1] if reference else 1.0) == pytest.approx(expected)
    text = _patched(policy, enabled=enabled)
    if not enabled:
        assert text == NATIVE
        return
    actual = pdx_eval.select(_overlay(text, candidate), _observations(changes, is_ai=is_ai))
    assert (actual.delta if actual.operation == "multiply" else 1.0) == pytest.approx(expected)
    if not is_ai:
        assert actual.operation is None
        assert actual.fallback == "vanilla"
    facts = _observations(changes, is_ai=is_ai)
    facts["ROOT"].update(candidate_selected=True, construction_queued=True)
    facts["other_country"] = {"market": {"mg:steel": {"market_goods_pricier": -0.5}}}
    assert pdx_eval.select(_overlay(text, candidate), facts) == actual


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.0),
        ({"country_goods_steel_price": -0.1, "country_goods_steel_balance": 0}, 1.08),
        ({"country_goods_steel_price": -0.099, "country_goods_steel_balance": 0}, 1.0),
        ({"country_goods_steel_price": -0.5, "country_goods_steel_balance": -1}, 0.90),
        ({"country_goods_coal_balance": -1}, 0.90),
        ({"country_goods_coal_price": 0.25, "country_goods_coal_balance": -1}, 0.90),
        ({"country_goods_coal_price": 0.250001, "country_goods_coal_balance": -1}, 0.80),
        ({"country_goods_coal_price": 0.5, "country_goods_coal_balance": 0}, 1.0),
        ({"country_goods_coal_price": None, "country_goods_coal_balance": 0}, 1.0),
        ({"default": True}, 0.85),
        (
            {
                "country_goods_steel_price": -0.5,
                "country_goods_steel_balance": 0,
                "country_goods_coal_price": 0.5,
                "country_goods_coal_balance": -1,
            },
            0.88,
        ),
        (
            {
                "country_goods_steel_price": -0.5,
                "country_goods_steel_balance": 0,
                "country_goods_coal_price": 0.5,
                "country_goods_coal_balance": -1,
                "default": True,
            },
            0.73,
        ),
        (
            {
                "country_goods_steel_price": -0.5,
                "country_goods_steel_balance": 0,
                "country_goods_coal_price": -0.5,
                "country_goods_coal_balance": 0,
            },
            1.08,
        ),
        (
            {
                "country_goods_steel_price": 0.5,
                "country_goods_steel_balance": -1,
                "country_goods_coal_price": 0.5,
                "country_goods_coal_balance": -1,
            },
            0.80,
        ),
        (
            {"country_goods_steel_price": -0.5, "country_goods_steel_balance": 0, "default": None},
            1.08,
        ),
        (
            {"country_goods_coal_price": 0.5, "country_goods_coal_balance": -1, "default": None},
            0.80,
        ),
    ],
)
def test_handwritten_material_joint_values_match_actual_patched_pdx(
    raw, baseline, changes, expected
):
    _joint(raw, baseline, changes, expected)


def test_different_candidate_materials_produce_different_preferences(raw, baseline):
    changes = {
        "country_goods_steel_price": -0.5,
        "country_goods_steel_balance": 0,
        "country_goods_coal_price": -0.5,
        "country_goods_coal_balance": 0,
        "country_goods_artillery_price": 0.5,
        "country_goods_artillery_balance": -1,
    }
    _joint(raw, baseline, changes, 1.08, candidate="ship_a")
    _joint(raw, baseline, changes, 0.80, candidate="ship_b")


@pytest.mark.parametrize(("is_ai", "enabled"), [(False, True), (True, False), (False, False)])
def test_player_and_disabled_paths_preserve_native(raw, baseline, is_ai, enabled):
    _joint(
        raw,
        baseline,
        {"country_goods_steel_price": -0.5, "country_goods_steel_balance": 0, "default": True},
        1.0,
        is_ai=is_ai,
        enabled=enabled,
    )


def _tree(node):
    if isinstance(node, Scalar):
        return node.text, node.quoted
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def _fixture_native_score(block, facts):
    """Interpret patched AST with this fixture's explicit constant helper results."""
    cloned = copy.deepcopy(block)

    def substitute(current):
        for item in current.assignments():
            if isinstance(item.value, Block):
                substitute(item.value)
            elif item.key == "multiply" and isinstance(item.value, Scalar):
                constants = {"ship_mod_market_multiplier": "1", "native_doctrine": "0.5"}
                if item.value.text in constants:
                    item.value = Scalar(constants[item.value.text])

    substitute(cloned)
    return pdx_eval._numeric_value(Assignment("multiply", "=", cloned), facts)


@pytest.mark.parametrize(
    ("candidate", "expected"), [("ship_zero", 0), ("ship_negative", -2.16), ("ship_tail", 0)]
)
def test_native_zero_nonpositive_and_tail_are_not_revived(raw, baseline, candidate, expected):
    derived = equipment_opportunities.derive(raw, baseline)
    text = _patched(_policy(derived, candidate))
    before = parse_text(NATIVE).root
    after = parse_text(text).root
    for identity in ("ship_missing", "ship_scalar", "ship_local"):
        assert _tree(before.first(identity)) == _tree(after.first(identity))
    definition = after.first(candidate)
    assert definition is not None
    assert isinstance(definition.value, Block)
    weight = definition.value.first("ai_weight")
    assert weight is not None
    assert isinstance(weight.value, Block)
    facts = _observations({"country_goods_steel_price": -0.5, "country_goods_steel_balance": 0})
    assert _fixture_native_score(weight.value, facts) == pytest.approx(expected)
    start = text.index(f"# SITAI BEGIN information:{candidate}.ai_weight")
    end_marker = f"# SITAI END information:{candidate}.ai_weight"
    end = text.index(end_marker, start) + len(end_marker)
    # Qualification, materials, ordered helper calls and zero tail all remain.
    assert _tree(parse_text(text[:start] + text[end:]).root) == _tree(before)


def test_exact_material_roles_and_no_missing_or_scalar_initialization(raw, baseline):
    candidate = baseline["candidates"]["ship_a"]
    assert candidate["construction_goods"] == {"coal": "2", "steel": "4"}
    assert candidate["materiel_goods"] == {"coal": "1"}
    derived = equipment_opportunities.derive(raw, baseline)
    rows = [row for row in derived["rules"] if row["field"] == "ship_a.ai_weight"]
    assert len(rows) == 7  # two goods, not three construction/materiel occurrences
    assert len({row["id"] for row in rows}) == 7
    assert {row["id"]: row["reason"] for row in derived["uncovered"]} == {
        "ship_empty": "no_ordinary_material_goods",
        "ship_local": "no_ordinary_material_goods",
        "ship_missing": "missing_native_ai_weight",
        "ship_scalar": "unsupported_scalar_or_unproved_dynamic_block",
        "ship_unproved": "unsupported_scalar_or_unproved_dynamic_block",
    }
    assert "initial_values" not in derived
    assert "scalar_values" not in derived
    assert not any(
        token in key
        for key in derived["readers"]
        for token in ("war", "loan", "literacy", "bureaucracy")
    )


def test_offline_load_never_rereads_game_and_input_maps_remain_unchanged(
    raw, baseline, monkeypatch
):
    before = copy.deepcopy((raw, baseline))
    expected = equipment_opportunities.derive(raw, baseline)

    def forbidden(_game):
        raise AssertionError("offline load must not read game sources")

    monkeypatch.setattr(equipment_opportunities, "read_inputs", forbidden)
    assert equipment_opportunities.load_baseline() == baseline
    assert equipment_opportunities.derive(raw) == expected
    assert (raw, baseline) == before


@pytest.mark.parametrize("key", ["country_goods_steel_price", "default"])
def test_reader_signature_drift_is_rejected(raw, baseline, key):
    derived = equipment_opportunities.derive(raw, baseline)
    raw["readers"] = copy.deepcopy(derived["readers"])
    assert equipment_opportunities.derive(raw, baseline) == derived
    raw["readers"][key]["path"] = ["owner"]
    with pytest.raises(ValueError, match="reader"):
        equipment_opportunities.derive(raw, baseline)


def test_source_merge_drift_is_rejected(raw, baseline):
    raw["sources"][SOURCE] = "0" * 64
    with pytest.raises(ValueError, match="来源"):
        equipment_opportunities.derive(raw, baseline)


@pytest.mark.parametrize(
    "mutation",
    [
        "new_file",
        "removed_file",
        "new_definition",
        "changed_amount",
        "weight_tail",
        "duplicate",
        "dlc_shadow",
        "helper_shadow",
        "goods_flag",
    ],
)
def test_live_gate_reinventories_full_source_set_and_ast(game, baseline, mutation):
    assert equipment_opportunities.verify_game(game) == baseline
    path = game / SOURCE
    if mutation == "new_file":
        (path.parent / "new.txt").write_text("# extra native source\n", encoding="utf-8")
    elif mutation == "removed_file":
        path.unlink()
    elif mutation == "new_definition":
        path.write_text(NATIVE + "\nnew_mod = { type = armor }\n", encoding="utf-8")
    elif mutation == "changed_amount":
        path.write_text(
            NATIVE.replace("goods_input_steel_add = 4", "goods_input_steel_add = 5"),
            encoding="utf-8",
        )
    elif mutation == "weight_tail":
        path.write_text(
            NATIVE.replace("multiply = native_doctrine", "multiply = 0", 1), encoding="utf-8"
        )
    elif mutation in {"duplicate", "dlc_shadow"}:
        shadow = (
            path
            if mutation == "duplicate"
            else game / "dlc/test/in_game/common/ship_modifications/shadow.txt"
        )
        shadow.parent.mkdir(parents=True, exist_ok=True)
        shadow.write_text(NATIVE + "\nship_a = { type = armor }\n", encoding="utf-8")
    elif mutation == "helper_shadow":
        (game / HELPER).with_name("new.txt").write_text(
            "ship_mod_market_multiplier = { value = 1 }\n", encoding="utf-8"
        )
    else:
        (game / GOODS).write_text(
            "steel = { local = yes }\ncoal = {}\nartillery = {}\nelectricity = { local = yes }\n",
            encoding="utf-8",
        )
    with pytest.raises(ValueError):
        equipment_opportunities.verify_game(game)


def test_repinning_source_hash_does_not_hide_changed_ast_materials(game, baseline, monkeypatch):
    path = game / SOURCE
    changed = NATIVE.replace("goods_input_steel_add = 4", "goods_input_steel_add = 99")
    path.write_text(changed, encoding="utf-8")
    baseline["sources"][SOURCE] = hashlib.sha256(changed.encode()).hexdigest()
    frozen = equipment_opportunities.BASELINE
    frozen.write_text(equipment_opportunities._canonical(baseline), encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        equipment_opportunities, "BASELINE_SHA256", hashlib.sha256(frozen.read_bytes()).hexdigest()
    )
    assert equipment_opportunities.load_baseline() == baseline
    with pytest.raises(ValueError, match="AST"):
        equipment_opportunities.verify_game(game)


@pytest.mark.parametrize(
    "mutation",
    ["canonical", "identity", "duplicate_line", "negative_material", "role", "ordinary_union"],
)
def test_offline_identity_and_structural_faults_fail_closed(baseline, monkeypatch, mutation):
    path = equipment_opportunities.BASELINE
    if mutation == "identity":
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ValueError, match="身份"):
            equipment_opportunities.load_baseline()
        return
    if mutation == "canonical":
        text = json.dumps(baseline)
    else:
        if mutation == "duplicate_line":
            baseline["candidates"]["ship_b"]["line"] = baseline["candidates"]["ship_a"]["line"]
        elif mutation == "negative_material":
            baseline["candidates"]["ship_a"]["construction_goods"]["steel"] = "-1"
        elif mutation == "role":
            baseline["contract"]["target_role"] = "actor"
        else:
            baseline["candidates"]["ship_a"]["ordinary_goods"] = ["artillery", "coal", "steel"]
        text = equipment_opportunities._canonical(baseline)
    path.write_text(text, encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        equipment_opportunities, "BASELINE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    with pytest.raises(ValueError):
        equipment_opportunities.load_baseline()


@pytest.mark.parametrize("source", [DOC, FORMULA_DOC, HELPER])
def test_country_dynamic_scope_requires_both_documentation_and_native_formula(game, source):
    path = game / source
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("country", "state")
        .replace("the scope you're currently in", "unproved context")
        .replace(
            "ship_modification_market_demand_ratio(scope:ship_modification_type)",
            "unrelated_formula",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        equipment_opportunities.write_baseline(game)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("opportunity_price_threshold", 0),
        ("pressure_price_threshold", -1),
        ("opportunity_multiplier", 1),
        ("scarcity_multiplier", 1),
        ("pressure_multiplier", 0.95),
        ("default_multiplier", True),
        ("priority_base", 0),
    ],
)
def test_bad_parameters_fail(raw, baseline, key, value):
    with pytest.raises(ValueError):
        equipment_opportunities.derive(
            raw, baseline, parameters={**equipment_opportunities.load_parameters(), key: value}
        )


def test_actual_frozen_denominator_and_budgets_are_explicit():
    baseline = equipment_opportunities.load_baseline()
    derived = equipment_opportunities.derive({"sources": {}, "readers": {}, "rules": []})
    assert len(baseline["candidates"]) == 271
    assert len(derived["covered"]) == 263
    assert len(derived["uncovered"]) == 8
    assert {row["reason"] for row in derived["uncovered"]} == {"missing_native_ai_weight"}
    assert baseline["contract"]["documented_type"] == "fixed_point"
    assert baseline["contract"]["supported_shape"] == "block"
    assert len(derived["rules"]) == 1517
    assert len(derived["readers"]) == 39
    for field in {rule["field"] for rule in derived["rules"]}:
        rules = [rule for rule in derived["rules"] if rule["field"] == field]
        assert len(rules) <= 32
        assert sum(len(rule["conditions"]) for rule in rules) <= 160


@pytest.mark.integration
def test_actual_game_full_source_and_ast_verification():
    assert (
        equipment_opportunities.verify_game(config.GAME) == equipment_opportunities.load_baseline()
    )
