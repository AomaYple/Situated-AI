"""科技联合消费者：局部供给、全局信号隔离与原版科研尾部。"""

from copy import deepcopy
from dataclasses import replace

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit

PRODUCTION = "common/technology/technologies/10_production.txt"
MILITARY = "common/technology/technologies/20_military.txt"
SOCIETY = "common/technology/technologies/30_society.txt"
# Concrete market supply needs remain available without route or fiscal gates.
# Productive-recipe queries are observed through complete native collections;
# these local supply scenarios deliberately use known-empty owned collections.
TARGETS = {
    "steelworking": (
        PRODUCTION,
        "country_goods_tools_balance",
        "country_goods_tools_price",
        "economy",
        1.12,
        1.20,
    ),
    "central_planning": (SOCIETY, "literacy", None, "political", 1.25, 1.25),
    "rifling": (
        MILITARY,
        "country_goods_small_arms_balance",
        "country_goods_small_arms_price",
        "military",
        1.12,
        1.20,
    ),
    "gantry_cranes": (
        MILITARY,
        "country_goods_steamers_balance",
        "country_goods_steamers_price",
        "military",
        1.12,
        1.20,
    ),
}


@pytest.fixture(scope="module")
def policies():
    adapters = decision_adapters.load()
    selected = {}
    for source, policy in adapters.policies:
        names = {target for target, row in TARGETS.items() if row[0] == source}
        if not names:
            continue
        rules = tuple(rule for rule in policy.rules if rule.field[0] in names)
        keys = frozenset(key for rule in rules for key in rule.input_keys())
        selected[source] = replace(
            policy,
            rules=rules,
            readers=tuple(reader for reader in policy.readers if reader.key in keys),
            enabled_domains=frozenset(rule.domain for rule in rules),
            semantic_ir=(),
        )
    model = compiler.load_model()
    return {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in selected.items()
    }


def _values(policy, target, **changes):
    values: dict[str, bool | int | float | None] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    # Known neutral signals exclude legacy route, war and broad coordination branches.
    values.update({reader.key: 0.2 for reader in policy.readers if reader.key.endswith("_price")})
    values["literacy"] = 0.8
    values[TARGETS[target][1]] = 0.3 if target == "central_planning" else -1
    values.update(changes)
    return values


def _factor(policy, target, values, *, ai=True, enabled=None):
    selection = decision_rules.evaluate(policy, values, is_ai=ai, enabled_domains=enabled).get(
        f"{target}.ai_weight"
    )
    return selection[1] if selection else 1


@pytest.mark.parametrize("target", TARGETS)
def test_direct_need_has_local_foundation_without_route_or_fiscal_health(policies, target):
    source, _, _, _, low, _ = TARGETS[target]
    policy = policies[source]
    assert _factor(policy, target, _values(policy, target)) == pytest.approx(low)


@pytest.fixture(scope="module")
def generated(policies):
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    compiled = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in policies.items()
    )
    selected = replace(
        adapters, policies=compiled, initial_values=(), scalar_values=(), supply=None
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled_files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    assert disabled_files == {}
    return inputs, files, disabled_files


def _overlay(text, target):
    field = f"{target}.ai_weight"
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    lines: list[str] = []
    for line in text[begin:end].splitlines()[1:]:
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or not lines[-1].lstrip().startswith("# ")
        ):
            lines.append("# local_research_unknown [test]; retain native")
        lines.append(line)
    return "\n".join(lines)


def _facts(policy, values, *, ai=True):
    root = {"is_ai": ai, "any_scope_state": [], "any_scope_building": []}
    for reader in policy.readers:
        if reader.engine in {"any_scope_state", "any_scope_building"}:
            continue
        assert reader.scope == "root"
        current = root
        for part in reader.path:
            current = current.setdefault(part, {})
        value = values.get(reader.key)
        if reader.argument is not None:
            current.setdefault(reader.engine, {})[(("argument", reader.argument),)] = value
        elif reader.parameters:
            current.setdefault(reader.engine, {})[tuple(sorted(reader.parameters))] = value
        else:
            current[reader.engine] = value
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                value is not None
            )
    return {"ROOT": root}


def _pdx_factor(policies, generated, target, values, *, ai=True, disabled=False):
    source = TARGETS[target][0]
    if disabled:
        # Exercise the real build switch: the source is absent from the emitted
        # overlay, so the engine uses the original untouched definition.
        assert source not in generated[2]
        return 1
    observed = pdx_eval.select(
        _overlay(generated[1][source], target),
        _facts(policies[source], values, ai=ai),
    )
    return observed.delta if observed.operation == "multiply" else 1


CASES = [
    ("foundation", 1.12),
    ("pressure", 1.20),
    ("price_at_threshold", 1.12),
    ("price_below_threshold", 1.12),
    ("price_above_threshold", 1.20),
    ("aux_unknown", 1.12),
    ("aux_nan", 1.12),
    ("aux_bool", 1.12),
    ("core_unknown", 1),
    ("core_nan", 1),
    ("core_inf", 1),
    ("core_bool", 1),
    ("need_before_threshold", 1.12),
    ("need_at_threshold", 1),
    ("need_after_threshold", 1),
    ("normal_borrowing", 1.12),
    ("default", 1.12),
    ("low_literacy", 1.12),
    ("bureaucracy_deficit", 1.12),
    ("unrelated_unknown", 1.12),
    ("candidate_not_completion", 1.12),
    ("player", 1),
    ("disabled", 1),
]


@pytest.mark.integration
@pytest.mark.parametrize("target", ["steelworking", "rifling", "gantry_cranes"])
@pytest.mark.parametrize(("case", "expected"), CASES)
def test_goods_research_full_field_handwritten_reference_and_pdx(
    policies, generated, target, case, expected
):
    source, core, auxiliary, _, _, _ = TARGETS[target]
    policy = policies[source]
    values = _values(policy, target)
    if case in {"pressure", "price_above_threshold"}:
        values[auxiliary] = 0.251
    elif case == "price_at_threshold":
        values[auxiliary] = 0.25
    elif case == "price_below_threshold":
        values[auxiliary] = 0.249
    elif case in {"aux_unknown", "aux_nan", "aux_bool"}:
        values[auxiliary] = {"aux_unknown": None, "aux_nan": float("nan"), "aux_bool": True}[case]
    elif case in {"core_unknown", "core_nan", "core_inf", "core_bool"}:
        values[core] = {
            "core_unknown": None,
            "core_nan": float("nan"),
            "core_inf": float("inf"),
            "core_bool": True,
        }[case]
    elif case in {"need_before_threshold", "need_at_threshold", "need_after_threshold"}:
        values[core] = {
            "need_before_threshold": -0.001,
            "need_at_threshold": 0,
            "need_after_threshold": 0.001,
        }[case]
    elif case == "normal_borrowing":
        values.update(loans=True, debt_ratio=0.1, net_surplus=-1)
    elif case == "default":
        values.update(default=True, loans=True)
    elif case == "low_literacy":
        values.update(literacy=0.01, legitimacy=0, industrial=False)
    elif case == "bureaucracy_deficit":
        values["bureaucracy"] = -100
    elif case == "unrelated_unknown":
        values.update(default=None, loans=None, literacy=None, legitimacy=None, industrial=None)
    elif case == "candidate_not_completion":
        values.update(candidate_selected=True, research_queued=True, technology_completed=False)
    assert _factor(
        policy,
        target,
        values,
        ai=case != "player",
        enabled=frozenset() if case == "disabled" else None,
    ) == pytest.approx(expected)
    assert _pdx_factor(
        policies, generated, target, values, ai=case != "player", disabled=case == "disabled"
    ) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("bureaucracy", "expected"),
    [(-0.001, 1.25), (0, 1.25), (0.001, 1.25), (None, 1.25), (float("nan"), 1.25), (True, 1.25)],
)
def test_administrative_research_signed_need_is_not_a_health_gate(
    policies, generated, bureaucracy, expected
):
    target = "central_planning"
    policy = policies[SOCIETY]
    values = _values(policy, target, bureaucracy=bureaucracy, default=True, loans=True, war=True)
    assert _factor(policy, target, values) == pytest.approx(expected)
    assert _pdx_factor(policies, generated, target, values) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize("target", TARGETS)
def test_local_research_no_world_scan_or_state_mutation_and_isolated_actors(
    policies, generated, target
):
    source, _, _, _, low, _ = TARGETS[target]
    policy = policies[source]
    values = _values(policy, target)
    snapshot = deepcopy(values)
    assert _factor(policy, target, values) == pytest.approx(low)
    assert values == snapshot
    text = _overlay(generated[1][source], target)
    facts = _facts(policy, values)
    facts["other_country"] = deepcopy(facts["ROOT"])
    del facts["ROOT"]
    actual = pdx_eval.select(text, facts)
    assert actual.operation is None or actual.delta == 1
    assert "every_country" not in text
    assert "every_state" not in text


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "signal"),
    [
        ("steelworking", "industrial"),
        ("steelworking", "coord_evidence_need_industry"),
        ("steelworking", "coord_layer_expansion"),
        ("rifling", "war"),
        ("gantry_cranes", "war"),
    ],
)
def test_local_need_does_not_require_retired_route_or_generic_global_signal(
    policies, generated, target, signal
):
    source, core, auxiliary, *_ = TARGETS[target]
    policy = policies[source]
    values = _values(policy, target, **{core: 0, signal: True, "legitimacy": 60})
    for evaluate in (
        lambda facts: _factor(policy, target, facts),
        lambda facts: _pdx_factor(policies, generated, target, facts),
    ):
        assert evaluate(values) == pytest.approx(1)
        assert evaluate(values | {core: -1}) == pytest.approx(1.12)
        assert evaluate(values | {core: -1, auxiliary: None}) == pytest.approx(1.12)
        assert evaluate(values | {core: -1, auxiliary: 0.251}) == pytest.approx(1.20)
        assert evaluate(values | {core: 0, auxiliary: 0.251}) == pytest.approx(1)


@pytest.mark.integration
@pytest.mark.parametrize(("war", "expected"), [(False, 1.20), (True, 1.27)])
def test_existing_navy_and_supply_need_are_independent_contributions(
    policies, generated, war, expected
):
    policy = policies[MILITARY]
    values = _values(policy, "gantry_cranes", own_navy=5, war=war)
    # Supply +.12 joins navy +.08 or wartime navy +.15, then one final bound.
    assert _factor(policy, "gantry_cranes", values) == pytest.approx(expected)
    assert _pdx_factor(policies, generated, "gantry_cranes", values) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("disabled", [False, True])
def test_administrative_research_player_and_real_domain_switch(policies, generated, ai, disabled):
    values = _values(policies[SOCIETY], "central_planning")
    expected = 1.25 if ai and not disabled else 1
    assert _factor(
        policies[SOCIETY],
        "central_planning",
        values,
        ai=ai,
        enabled=frozenset() if disabled else None,
    ) == pytest.approx(expected)
    assert _pdx_factor(
        policies, generated, "central_planning", values, ai=ai, disabled=disabled
    ) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize("target", TARGETS)
def test_optional_future_recipe_cost_is_not_a_current_research_commitment(
    policies, generated, target
):
    source, _, auxiliary, _, _, high = TARGETS[target]
    policy = policies[source]
    values = _values(policy, target)
    if auxiliary is not None:
        values[auxiliary] = 0.3
    expensive_future_recipe = {
        "iron_price": 10,
        "steel_price": 10,
        "hardwood_price": 10,
        "engines_price": 10,
        "coal_price": 10,
        "paper_price": 10,
        "telephones_price": 10,
        "loans": True,
        "default": True,
    }
    # These prices belong to optional PM adoption, not an immediate research
    # payment. The four specific native unlock/recipe/score contracts are
    # checked below. Research qualification, costs and time remain native;
    # these stateless actions introduce no expenditure or lasting commitment.
    for facts in (values, values | expensive_future_recipe):
        assert _factor(policy, target, facts) == pytest.approx(high)
        assert _pdx_factor(policies, generated, target, facts) == pytest.approx(high)


@pytest.mark.integration
def test_real_unlocks_outputs_and_strictly_positive_native_score_contract(generated):
    inputs, files, _ = generated
    recipes = {
        "steelworking": ("common/production_methods/01_industry.txt", "pm_pig_iron", "tools", 60),
        "rifling": ("common/production_methods/01_industry.txt", "pm_rifles", "small_arms", 50),
        "gantry_cranes": (
            "common/production_methods/01_industry.txt",
            "pm_metal_shipbuilding",
            "steamers",
            65,
        ),
    }
    for target, (source, *_rest) in TARGETS.items():
        original = parse_text(inputs[source]).root.first(target)
        output = parse_text(files[source]).root.first(target)
        assert original is not None
        assert output is not None
        assert isinstance(original.value, Block)
        assert isinstance(output.value, Block)
        prerequisites = original.value.first("unlocking_technologies")
        assert prerequisites is not None
        # Whole non-ai_weight subtrees remain byte-token equivalent including qualification.
        assert _tree_without_weight(original.value) == _tree_without_weight(output.value)
        marker = f"information:{target}.ai_weight"
        begin = files[source].index(f"# SITAI BEGIN {marker}")
        end = files[source].index(f"# SITAI END {marker}", begin)
        end = files[source].index("\n", end)
        native = parse_text(files[source][:begin] + files[source][end:]).root.first(target)
        assert native is not None
        assert isinstance(native.value, Block)
        assert _tree_without_weight(original.value, omit_weight=False) == _tree_without_weight(
            native.value, omit_weight=False
        )
        weight = original.value.first("ai_weight")
        assert weight is not None
        assert isinstance(weight.value, Block)
        for assignment in weight.value.assignments():
            if assignment.key == "if":
                assert isinstance(assignment.value, Block)
                numeric = assignment.value.first("add")
                assert numeric is not None
                assert isinstance(numeric.value, Scalar)
                assert float(numeric.value.unquoted) >= 0
            else:
                assert assignment.key == "value"
                assert isinstance(assignment.value, Scalar)
                assert float(assignment.value.unquoted) > 0
        if target in recipes:
            path, method, good, quantity = recipes[target]
            entry = parse_text(inputs[path]).root.first(method)
            assert entry is not None
            assert isinstance(entry.value, Block)
            unlock = entry.value.first("unlocking_technologies")
            assert unlock is not None
            assert isinstance(unlock.value, Block)
            assert [item.unquoted for item in unlock.value.scalars()] == [target]
            block = entry.value.first("building_modifiers")
            assert block is not None
            assert isinstance(block.value, Block)
            scaled = block.value.first("workforce_scaled")
            assert scaled is not None
            assert isinstance(scaled.value, Block)
            produced = scaled.value.first(f"goods_output_{good}_add")
            assert produced is not None
            assert isinstance(produced.value, Scalar)
            assert float(produced.value.unquoted) == quantity
    government = parse_text(inputs["common/production_methods/07_government.txt"]).root
    switchboards = government.first("pm_switch_boards")
    assert switchboards is not None
    assert isinstance(switchboards.value, Block)
    unlock = switchboards.value.first("unlocking_technologies")
    assert unlock is not None
    assert isinstance(unlock.value, Block)
    assert [item.unquoted for item in unlock.value.scalars()] == ["central_planning"]
    for container, field, expected in [
        ("country_modifiers", "country_bureaucracy_add", 100),
        ("building_modifiers", "goods_input_paper_add", 20),
        ("building_modifiers", "goods_input_telephones_add", 5),
    ]:
        modifiers = switchboards.value.first(container)
        assert modifiers is not None
        assert isinstance(modifiers.value, Block)
        scaled = modifiers.value.first("workforce_scaled")
        assert scaled is not None
        assert isinstance(scaled.value, Block)
        value = scaled.value.first(field)
        assert value is not None
        assert isinstance(value.value, Scalar)
        assert float(value.value.unquoted) == expected


def _tree_without_weight(block, *, omit_weight=True):
    return tuple(
        (
            item.key,
            item.op,
            _tree_without_weight(item.value, omit_weight=omit_weight)
            if isinstance(item.value, Block)
            else item.value.unquoted
            if isinstance(item.value, Scalar)
            else None,
        )
        if isinstance(item, Assignment)
        else item.unquoted
        for item in block.items
        if not omit_weight or not isinstance(item, Assignment) or item.key != "ai_weight"
    )
