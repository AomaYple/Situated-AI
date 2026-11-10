"""D9 strict links witnessed against their actual generated PDX branches.

These checks establish local source-to-writer traceability only.  They do not
claim that the game engine executes the generated branches as observed here.
"""

from __future__ import annotations

import hashlib
import math
import operator as comparison_ops
from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules, policy_audit
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, joint_chain_contract, pdx_eval

if TYPE_CHECKING:
    from pdx.situated.joint_chain_contract import ChainReaderSpec

pytestmark = pytest.mark.integration
INFO = joint_chain_contract.INFO_SOURCE


@pytest.fixture(scope="module")
def generated():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    inputs = decision_adapters.read_inputs(adapters)
    compiled, _report = compiler.compile_sources(
        decision_rules.load(), adapters, config_model=model
    )
    adapters = replace(adapters, policies=compiled[1:])
    files, _ = decision_adapters.build(
        adapters,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    info_policy = compiled[0][1]
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
    info_text = decision_rules.patch(
        baseline,
        info_policy,
        baseline=baseline,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    policies = {INFO: info_policy, **dict(adapters.policies)}
    evidence = joint_chain_contract.build_strict(model.consumer_ir, policies)
    return policies, files, info_text, evidence


def _facts(
    policy: Any,
    values: dict[str, object],
    *,
    is_ai: bool = True,
    decoys: dict[str, object] | None = None,
) -> dict[str, Any]:
    root: dict[str, Any] = {}
    facts: dict[str, Any] = {"ROOT": root}
    for reader in policy.readers:
        # Absent aliases must not overwrite the selected reader's actual engine observation.
        if reader.key not in values:
            continue
        current = root if reader.scope == "root" else facts.setdefault(f"scope:{reader.scope}", {})
        for part in reader.path:
            current = current.setdefault(part, {})
        value = values.get(reader.key)
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(params["building_type"], {})[
                params["production_method"]
            ] = value
        elif reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            current[f"{reader.argument}_active"] = value
        elif reader.argument is not None or reader.parameters or reader.value_field is not None:
            parameters = dict(reader.parameters)
            if reader.argument is not None:
                parameters["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(parameters.items()))] = value
        else:
            current[reader.engine] = value
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                value is not None
            )
    actor = root.setdefault("owner", {}) if policy.actor_path else root
    actor["is_ai"] = is_ai
    if decoys:
        root.update(decoys)
    return facts


def _source_text(source: str, files: dict[str, str], info_text: str, rule_id: str) -> str:
    text = info_text if source == INFO else files[source]
    if f"# {rule_id} [" in text:
        return text
    scalar = files["common/script_values/sitai_adapter_values.txt"]
    assert f"# {rule_id} [" in scalar
    return scalar


def _branch(text: str, rule_id: str) -> str:
    return pdx_eval.marked_block(text, rule_id, path=rule_id)


def _scalar(value: Scalar) -> object:
    text = value.unquoted
    if text in {"yes", "no"}:
        return text == "yes"
    try:
        return float(text)
    except ValueError:
        return text


def _normalize_ast(node: Any) -> Any:
    if isinstance(node, Scalar):
        return _scalar(node)
    if isinstance(node, Assignment):
        return node.key, node.op, _normalize_ast(node.value)
    assert isinstance(node, Block)
    return tuple(sorted((_normalize_ast(child) for child in node.items), key=repr))


def _expected_limit_ast(item: Any) -> tuple[Any, ...]:
    root: dict[str, Any] = {"predicates": [], "scopes": {}}

    def add(path: tuple[str, ...], predicate: tuple[Any, ...]) -> None:
        group = root
        for component in path:
            group = group["scopes"].setdefault(component, {"predicates": [], "scopes": {}})
        group["predicates"].append(predicate)

    def path(reader: ChainReaderSpec) -> tuple[str, ...]:
        return (("ROOT",) if reader.scope == "root" else (f"scope:{reader.scope}",)) + reader.path

    def predicate(reader: Any, operator: str, value: object) -> tuple[Any, ...]:
        if isinstance(value, dict):
            value = value["fact_reference"]
        if reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            result = (f"{reader.argument}_active", operator, True)
            return ("NOT", "=", (result,)) if value is False else result
        if reader.engine == "is_production_method_active":
            return (
                reader.engine,
                operator,
                tuple(sorted((key, "=", parameter) for key, parameter in reader.parameters)),
            )
        if reader.value_field is not None:
            return (
                reader.engine,
                "=",
                tuple(
                    sorted(
                        [(key, "=", parameter) for key, parameter in reader.parameters]
                        + [(reader.value_field, operator, value)],
                        key=repr,
                    )
                ),
            )
        if reader.argument is not None:
            result = (reader.engine, "=", reader.argument)
            if value is False:
                return "NOT", "=", (result,)
            return result
        return reader.engine, operator, value

    for fact, operator, value in item.spec.condition_semantics:
        reader = next(reader for reader in item.spec.readers if reader.key == fact)
        add(path(reader), predicate(reader, operator, value))
    for key in item.spec.required_known_facts:
        reader = next(reader for reader in item.spec.readers if reader.key == key)
        positive = predicate(reader, "=", True)
        add(
            path(reader),
            ("OR", "=", tuple(sorted((positive, ("NOT", "=", (positive,))), key=repr))),
        )
    for reader in item.spec.readers:
        if reader.minimum is not None:
            add(path(reader), predicate(reader, ">=", reader.minimum))
        if reader.maximum is not None:
            add(path(reader), predicate(reader, "<=", reader.maximum))
    actor_path = ("ROOT", "owner") if item.spec.actor == "owner" else ("ROOT",)
    add(actor_path, ("is_ai", "=", True))

    def render(group: dict[str, Any]) -> tuple[Any, ...]:
        children = list(group["predicates"])
        for name, child in group["scopes"].items():
            children.append(("exists", "=", name))
            children.append((name, "=", render(child)))
        return tuple(sorted(children, key=repr))

    return render(root)


def _cases(policy: Any, rule: Any) -> dict[str, dict[str, object]]:
    positive, _candidates = policy_audit._fixture(policy, rule)
    return {"positive": dict(positive)}


def _opposite_value(operator: str, value: object) -> object:
    if operator == "=":
        if isinstance(value, bool):
            return not value
        assert isinstance(value, (int, float))
        return float(value) + 1
    if operator == ">":
        return value
    if operator == ">=":
        assert isinstance(value, (int, float))
        return float(value) - 1
    if operator == "<":
        return value
    if operator == "<=":
        assert isinstance(value, (int, float))
        return float(value) + 1
    raise AssertionError(f"No local witness inversion is defined for operator {operator!r}")


def test_local_links_preserve_each_condition_unknown_and_player_boundary(generated) -> None:
    policies, files, info_text, evidence = generated
    assert len(evidence) == 31
    assert not any(item.spec.field == "colonial_interest_ratio" for item in evidence)
    assert {item.spec.chain_id for item in evidence} == {
        "LJ01",
        "LJ02",
        "LJ03",
        "LJ04",
        "LJ05",
        "LJ06",
        "LJ07",
        "LJ08",
        "LJ09",
        "LJ10",
        "LJ11",
        "LJ12",
        "LJ13",
        "LJ14",
    }
    for item in evidence:
        policy = policies[item.spec.source]
        rule = next(rule for rule in policy.rules if rule.id == item.spec.rule_id)
        text = _branch(_source_text(item.spec.source, files, info_text, rule.id), rule.id)
        generated_marker = f"# ACTION {rule.id} [generated]"
        assert generated_marker in text
        generated_branch = text.split(generated_marker, 1)[1]
        parsed = parse_text(generated_branch, path=rule.id)
        assert not parsed.errors
        branch = parsed.root.first("if") or parsed.root.first("else_if")
        assert branch is not None
        assert isinstance(branch.value, Block)
        limit = branch.value.first("limit")
        assert limit is not None
        assert isinstance(limit.value, Block)
        assert _normalize_ast(limit.value) == _expected_limit_ast(item), item.spec.link_id
        semantic_facts = (
            *tuple(fact for fact, _operator, _value in item.spec.condition_semantics),
            *joint_chain_contract._EXPECTED_REFERENCE_FACTS.get(item.spec.rule_id, ()),
            *item.spec.required_known_facts,
        )
        assert semantic_facts == tuple(reader.key for reader in item.spec.readers)
        cases = _cases(policy, rule)
        positive = pdx_eval.select(text, _facts(policy, cases["positive"]), path=rule.id)
        assert positive.action_id == rule.id
        assert positive.operation == "add"
        assert positive.delta == pytest.approx(
            rule.value - (1.0 if rule.operation == "multiply" else 0.0)
        )
        for fact, operator, value in item.spec.condition_semantics:
            opposite = (
                cases["positive"]["native_marine_capacity"]
                if isinstance(value, dict)
                else _opposite_value(operator, value)
            )
            broken_values = {**cases["positive"], fact: opposite}
            broken = pdx_eval.select(text, _facts(policy, broken_values), path=rule.id)
            assert broken.operation is None, (item.spec.link_id, fact, operator, value)
            assert broken.delta == 0, (item.spec.link_id, fact, operator, value)
        for key in item.spec.required_known_facts:
            for known in (False, True):
                known_values = {**cases["positive"], key: known}
                observed = pdx_eval.select(text, _facts(policy, known_values), path=rule.id)
                assert observed == positive, (item.spec.link_id, key, known)
        for reader in item.spec.readers:
            unknown_values = {**cases["positive"], reader.key: None}
            unknown = pdx_eval.select(text, _facts(policy, unknown_values), path=rule.id)
            assert unknown.operation is None, (item.spec.link_id, reader.key)
            assert unknown.delta == 0, (item.spec.link_id, reader.key)
            assert unknown.fallback in {"unknown", "vanilla"}
        player = pdx_eval.select(text, _facts(policy, cases["positive"], is_ai=False), path=rule.id)
        assert player.action_id != rule.id
        assert player.fallback == "vanilla"
        decoys = {
            "candidate_selected": True,
            "construction_queued": True,
            "other_state": {"is_production_method_active": {"building_iron_mine": {}}},
            "other_country": {"is_production_method_active": {"building_iron_mine": {}}},
        }
        unrelated = pdx_eval.select(
            text, _facts(policy, cases["positive"], decoys=decoys), path=rule.id
        )
        assert unrelated == positive
        for reader in item.spec.readers:
            if reader.engine not in {"is_production_method_active", "has_technology_researched"}:
                continue
            incomplete_values = {**cases["positive"], reader.key: False}
            incomplete = pdx_eval.select(
                text, _facts(policy, incomplete_values, decoys=decoys), path=rule.id
            )
            assert incomplete.operation is None
            assert incomplete.delta == 0


def test_local_link_receipt_does_not_close_any_full_d9_chain(generated) -> None:
    _policies, _files, _info_text, evidence = generated
    contract = joint_chain_contract.strict_contract(evidence)
    assert contract["status"] == "observed_static_only"
    assert contract["locally_witnessed_chains"] == [f"LJ{i:02d}" for i in range(1, 15)]
    assert contract["pending_chain_closure"] == [f"LJ{index:02d}" for index in range(1, 15)]
    assert contract["pending_uncovered_chains"] == []


DEFAULT_STRATEGY = "common/ai_strategies/00_default_strategy.txt"
FLEET = "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
SHIP = "ai_strategy_default.ship_construction_output_multiplier"
CONSCRIPT = "ai_strategy_default.conscript_battalion_ratio"


def _complete_values(policy: Any, field: str, changes: dict[str, object]) -> dict[str, object]:
    rules = policy.groups()[tuple(field.split("."))]
    keys = {key for rule in rules for key in rule.input_keys()}
    values: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else max(reader.minimum or 0, 0)
        for reader in policy.readers
        if reader.key in keys
    }
    values.update(
        {
            "default": False,
            "war": False,
            "loans": False,
            "bureaucracy": 0,
            "legitimacy": 60,
            "debt_ratio": 0.1,
            "net_surplus": 0,
            "income": 1,
            "bankruptcy_horizon": 100,
            "industrial_route": False,
            "expansion_route": False,
            "war_defeat": False,
            "navy": 30,
            "gdp": 1,
            "gold_reserves": 0,
            "infamy": 0,
        }
    )
    values.update(changes)
    return values


def _complete_overlay(files: dict[str, str], info_text: str, source: str, field: str) -> str:
    text = info_text if source == INFO else files[source]
    marker = f"# SITAI BEGIN information:{field}"
    if marker not in text:
        text = files["common/script_values/sitai_adapter_values.txt"]
    begin = text.index(marker)
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


# Values and expected winners are authored independently of the rule evaluator.
REMAINING_CASES: list[tuple[str, str, dict[str, object], str | None, float]] = [
    (INFO, "wanted_construction_output", {"default": True}, "fiscal_construction_guard", 0.75),
    (
        INFO,
        "wanted_construction_output",
        {"loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 10},
        "liquidity_construction_guard",
        0.85,
    ),
    (
        INFO,
        "wanted_construction_output",
        {"loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 30},
        None,
        1,
    ),
    (
        INFO,
        "wanted_construction_output",
        {"war_defeat": True},
        "remaining_reconstruction_need",
        1.12,
    ),
    (INFO, "wanted_construction_output", {"war_defeat": False}, None, 1),
    (
        INFO,
        "wanted_construction_output",
        {"war_defeat": True, "war": True},
        "remaining_reconstruction_need",
        1.12,
    ),
    (
        INFO,
        "wanted_construction_output",
        {"war_defeat": True, "default": True},
        "fiscal_construction_guard",
        0.87,
    ),
    (
        INFO,
        "wanted_construction_output",
        {"war_defeat": True, "bureaucracy": -1},
        "remaining_reconstruction_need",
        1.12,
    ),
    (
        INFO,
        "wanted_construction_output",
        {"war_defeat": True, "bureaucracy": None},
        "remaining_reconstruction_need",
        1.12,
    ),
    (
        DEFAULT_STRATEGY,
        SHIP,
        {"default": True},
        "military_capacity_ship_default_cost",
        0.85,
    ),
    (
        DEFAULT_STRATEGY,
        SHIP,
        {"loans": True, "debt_ratio": 0.5, "bankruptcy_horizon": 10},
        "military_capacity_ship_liquidity_cost",
        0.9,
    ),
    (DEFAULT_STRATEGY, SHIP, {"war": True}, None, 1.10),
    (
        DEFAULT_STRATEGY,
        CONSCRIPT,
        {"war": True, "own_army": 1, "small_arms_price": 0.6, "small_arms_balance": -1},
        "military_capacity_conscript_need",
        1.10,
    ),
    (
        DEFAULT_STRATEGY,
        CONSCRIPT,
        {"war": True, "own_army": 1, "small_arms_price": 0.6, "small_arms_balance": 0},
        None,
        1.10,
    ),
    (
        DEFAULT_STRATEGY,
        CONSCRIPT,
        {"war": False, "small_arms_price": 0.6, "small_arms_balance": -1},
        None,
        1,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": True, "navy": 1, "steamers_price": 0.3, "steamers_balance": -1},
        "structural_wartime_supply_escort",
        1.25,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": True, "navy": 1, "steamers_price": 0.3, "steamers_balance": 0},
        "structural_wartime_supply_price_escort",
        1.1,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": True, "navy": 1, "steamers_price": 0.2, "steamers_balance": -1},
        "structural_wartime_supply_balance_escort",
        1.1,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": True, "navy": 0, "steamers_price": 0.3, "steamers_balance": -1},
        None,
        1,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": True, "navy": 1, "steamers_price": None, "steamers_balance": -1},
        None,
        1.1,
    ),
    (
        DEFAULT_STRATEGY,
        FLEET,
        {"war": False, "navy": 1, "steamers_price": 0.3, "steamers_balance": -1},
        None,
        1,
    ),
    (INFO, "wanted_navy_size", {"navy": 0, "gold_reserves": 100}, "navy_existing_capacity", 1.1),
    (INFO, "wanted_navy_size", {"navy": 0, "gold_reserves": 99}, None, 1),
    (
        INFO,
        "wanted_navy_size",
        {"navy": 0, "gold_reserves": 100, "default": True},
        "naval_peacetime_budget",
        0.8,
    ),
]


@pytest.mark.parametrize(("source", "field", "changes", "writer", "factor"), REMAINING_CASES)
def test_remaining_local_links_use_complete_field_priority_and_handwritten_outcome(
    generated, source, field, changes, writer, factor
):
    policies, files, info_text, _evidence = generated
    # This witness evaluates only the generated overlay. Native qualification,
    # terminal zero and tail preservation are checked by dedicated AST contracts
    # in test_situated_external_supply_escort and depth_politics_subject_identity.
    policy = policies[source]
    values = _complete_values(policy, field, changes)
    overlay = _complete_overlay(files, info_text, source, field)
    facts = _facts(policy, values)
    actual = pdx_eval.select(overlay, facts)
    identity = "program_" + hashlib.sha256(f"{source}:{field}".encode()).hexdigest()[:16]
    assert actual.action_id == identity
    assert actual.operation == "multiply"
    assert actual.delta == pytest.approx(factor)
    # No completion credit can be fabricated from selection or queued construction.
    facts["ROOT"]["candidate_selected"] = True
    facts["ROOT"]["construction_queued"] = True
    facts["other_country"] = {"navy_size": 100, "gold_reserves": 1000000}
    assert pdx_eval.select(overlay, facts) == actual
    player = pdx_eval.select(overlay, _facts(policy, values, is_ai=False))
    assert player == pdx_eval.PdxDecision(None, None, 0.0, "vanilla")


def test_war_defeat_chain_uses_original_expiring_memory_not_a_new_permanent_flag(generated):
    policies, _files, _text, evidence = generated
    memory = next(reader for reader in policies[INFO].readers if reader.key == "war_defeat")
    assert (memory.engine, memory.argument, memory.scope, memory.path) == (
        "has_variable",
        "recently_lost_war",
        "root",
        (),
    )
    links = [item for item in evidence if item.spec.rule_id == "remaining_reconstruction_need"]
    assert len(links) == 1
    assert links[0].spec.refresh == "consumer"
    assert (
        links[0].spec.completion_state
        == "native_recently_lost_war_memory_independent_reconstruction_need"
    )
    assert all(item.spec.max_hops <= 2 for item in evidence)
    vanilla = decision_adapters.read_inputs(decision_adapters.load())[
        "common/on_actions/00_code_on_actions.txt"
    ]
    _assert_memory_source_contract(vanilla)


def _assert_memory_source_contract(text: str) -> None:
    parsed = parse_text(text)
    assert not parsed.errors
    writes: list[tuple[tuple[str, ...], Assignment, tuple[Block, ...]]] = []

    def walk(block: Block, path: tuple[str, ...], limits: tuple[Block, ...]) -> None:
        for assignment in block.assignments():
            if not isinstance(assignment.value, Block):
                continue
            ancestors = (*path, assignment.key)
            active_limits = limits
            if assignment.key == "if":
                candidates = assignment.value.all("limit")
                assert len(candidates) == 1
                limit = candidates[0]
                assert limit.op == "="
                assert limit.prefix is None
                assert isinstance(limit.value, Block)
                active_limits = (*limits, limit.value)
            names = assignment.value.all("name")
            if assignment.key == "set_variable" and any(
                isinstance(name.value, Scalar) and name.value.unquoted == "recently_lost_war"
                for name in names
            ):
                writes.append((ancestors, assignment, active_limits))
            walk(assignment.value, ancestors, active_limits)

    walk(parsed.root, (), ())
    assert {path for path, _assignment, _limits in writes} == {
        ("on_capitulation", "effect", "set_variable"),
        ("on_lost_war", "effect", "if", "set_variable"),
    }
    assert len(writes) == 2
    for path, assignment, limits in writes:
        assert assignment.op == "="
        assert assignment.prefix is None
        assert isinstance(assignment.value, Block)
        assert {child.key for child in assignment.value.assignments()} == {"name", "days", "value"}
        assert len(assignment.value.items) == 3
        for key, expected in (("name", "recently_lost_war"), ("days", "1825"), ("value", "yes")):
            children = assignment.value.all(key)
            assert len(children) == 1
            child = children[0]
            assert child.op == "="
            assert child.prefix is None
            assert isinstance(child.value, Scalar)
            assert not child.value.quoted
            assert child.value.text == expected
        hooks = parsed.root.all(path[0])
        assert len(hooks) == 1
        hook = hooks[0]
        assert hook.op == "="
        assert hook.prefix is None
        assert isinstance(hook.value, Block)
        effects = hook.value.all("effect")
        assert len(effects) == 1
        assert effects[0].op == "="
        assert effects[0].prefix is None
        # Root contract is the last explicit Root declaration before the hook,
        # allowing the original shared war-hook documentation block.
        root_notes = [
            comment.strip()
            for line, comment in parsed.comments
            if line < hook.line and comment.strip().startswith("# Root =")
        ]
        assert root_notes[-1] == "# Root = Country"
        if path[0] == "on_capitulation":
            assert limits == ()
        else:
            assert len(limits) == 1
            assert len(limits[0].items) == 1
            exists = limits[0].first("exists")
            assert exists is not None
            assert exists.op == "="
            assert exists.prefix is None
            assert isinstance(exists.value, Scalar)
            assert exists.value.text == "scope:victim_of_wargoal"
            assert any(
                line < hook.line
                and comment.strip()
                == (
                    "# scope:victim_of_wargoal = set if a war goal was enforced against this country at any point"
                )
                for line, comment in parsed.comments
            )


def _source_net(policy, field, values):
    """Independent complete-field check from source predicates and declared causes."""
    readers = {reader.key: reader for reader in policy.readers}
    operations = {
        "=": comparison_ops.eq,
        "<": comparison_ops.lt,
        "<=": comparison_ops.le,
        ">": comparison_ops.gt,
        ">=": comparison_ops.ge,
    }

    def known(key):
        reader, value = readers[key], values.get(key)
        if reader.kind == "boolean":
            return type(value) is bool
        return (
            type(value) in (int, float)
            and math.isfinite(value)
            and (reader.minimum is None or value >= reader.minimum)
            and (reader.maximum is None or value <= reader.maximum)
        )

    def applies(rule):
        if any(not known(key) for key in rule.required_known_facts):
            return False
        for predicate in rule.conditions:
            right = predicate.value
            if isinstance(right, decision_rules.FactReference):
                if not known(right.key):
                    return False
                right = values[right.key]
            if not known(predicate.fact) or not operations[predicate.op](
                values[predicate.fact], right
            ):
                return False
        return True

    groups = defaultdict(list)
    for rule in policy.rules:
        if ".".join(rule.field) == field:
            groups[(rule.contribution_group, rule.value >= 1)].append(rule)
    lower = max(0.5, 1 + sum(min(0, *(r.value - 1 for r in g)) for g in groups.values()))
    upper = min(1.5, 1 + sum(max(0, *(r.value - 1 for r in g)) for g in groups.values()))
    net = 1.0
    for (_cause, positive), group in groups.items():
        amounts = [r.value - 1 for r in group if r.domain in policy.enabled_domains and applies(r)]
        if amounts:
            net += max(amounts) if positive else min(amounts)
    return max(lower, min(upper, net))


_REMAINING_STRICT_WRITERS = {
    "fiscal_construction_guard",
    "liquidity_construction_guard",
    "military_capacity_ship_default_cost",
    "remaining_reconstruction_need",
    "military_capacity_conscript_need",
    "structural_wartime_supply_escort",
    "structural_wartime_supply_price_escort",
    "structural_wartime_supply_balance_escort",
    "navy_existing_capacity",
}


def test_every_added_link_breaks_each_predicate_and_unknown_reader_in_its_complete_field(generated):
    policies, files, info_text, evidence = generated
    witnessed = set()
    for source, field, changes, writer, factor in REMAINING_CASES:
        if writer not in _REMAINING_STRICT_WRITERS or writer in witnessed:
            continue
        witnessed.add(writer)
        policy = policies[source]
        values = _complete_values(policy, field, changes)
        overlay = _complete_overlay(files, info_text, source, field)
        positive = pdx_eval.select(overlay, _facts(policy, values))
        assert positive.operation == "multiply"
        assert positive.delta == pytest.approx(factor)
        local = _branch(_source_text(source, files, info_text, writer), writer)
        isolated = pdx_eval.select(local, _facts(policy, values))
        assert isolated.action_id == writer
        assert isolated.operation == "add"
        rule = next(rule for rule in policy.rules if rule.id == writer)
        assert isolated.delta == pytest.approx(rule.value - 1.0)
        link = next(item for item in evidence if item.spec.rule_id == writer)
        for fact, operator, value in link.spec.condition_semantics:
            broken = {**values, fact: _opposite_value(operator, value)}
            actual = pdx_eval.select(local, _facts(policy, broken))
            assert actual.action_id != writer or actual.operation is None, (
                writer,
                fact,
                "predicate",
            )
            complete = pdx_eval.select(overlay, _facts(policy, broken))
            assert complete.operation == "multiply"
            assert complete.action_id == positive.action_id
            assert complete.delta == pytest.approx(_source_net(policy, field, broken))
            unknown = {**values, fact: None}
            actual = pdx_eval.select(local, _facts(policy, unknown))
            assert actual.action_id != writer or actual.operation is None, (writer, fact, "unknown")
            complete = pdx_eval.select(overlay, _facts(policy, unknown))
            assert complete.operation == "multiply"
            assert complete.action_id == positive.action_id
            assert complete.delta == pytest.approx(_source_net(policy, field, unknown))
    assert witnessed == _REMAINING_STRICT_WRITERS


_MEMORY_FIXTURE = """# Root = Country
on_capitulation = { effect = {
 set_variable = { name = recently_lost_war days = 1825 value = yes }
} }
# Root = Country
# scope:victim_of_wargoal = set if a war goal was enforced against this country at any point
on_lost_war = { effect = { if = {
 limit = { exists = scope:victim_of_wargoal }
 set_variable = { name = recently_lost_war days = 1825 value = yes }
} } }
"""


def test_memory_source_contract_accepts_exact_handwritten_hook_fixture():
    _assert_memory_source_contract(_MEMORY_FIXTURE)


@pytest.mark.parametrize(
    "mutation",
    ["moved_hook", "missing_victim", "wrong_value", "wrong_root", "wrong_days", "duplicate_value"],
)
def test_memory_source_contract_rejects_moved_or_unqualified_write(mutation):
    changed = {
        "moved_hook": _MEMORY_FIXTURE.replace("on_lost_war", "on_won_war"),
        "missing_victim": _MEMORY_FIXTURE.replace(
            "limit = { exists = scope:victim_of_wargoal }", "limit = { always = yes }"
        ),
        "wrong_value": _MEMORY_FIXTURE.replace("value = yes", "value = no", 1),
        "wrong_root": _MEMORY_FIXTURE.replace("# Root = Country", "# Root = State", 1),
        "wrong_days": _MEMORY_FIXTURE.replace("days = 1825", "days = 100", 1),
        "duplicate_value": _MEMORY_FIXTURE.replace("value = yes", "value = yes value = yes", 1),
    }[mutation]
    with pytest.raises(AssertionError):
        _assert_memory_source_contract(changed)
