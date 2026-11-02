"""LJ08/LJ12/LJ14 的完整消费者竞争、原版保留与具名目标隔离见证。

数值期望手写；生成路径读取完整生产模型和锁定原版。局部静态见证不关闭整条联合链。
"""

import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.integration
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
SUBJECTS = "common/ai_strategies/02_subject_diplomatic_strategies.txt"
INFO = "mod/decisions/information.toml"
GOVERNMENT = "ai_strategy_default.interest_group_government_weight"
NEGOTIATION = "ai_strategy_default.negotiation_chance"
SUBJECT = "ai_strategy_default.subject_value"
OVERLORD = "ai_strategy_default.become_subject_value"
AUTONOMY = "ai_strategy_subject_maintain_autonomy.weight"
SELF = "ai_strategy_subject_strengthen_self.weight"
STATE = "state_value"


def _fields(policy: Any, fields: set[str]) -> Any:
    rules = tuple(r for r in policy.rules if ".".join(r.field) in fields)
    keys = frozenset(key for rule in rules for key in rule.input_keys())
    return replace(
        policy,
        rules=rules,
        readers=tuple(r for r in policy.readers if r.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
    )


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    sources = dict(adapters.policies)
    policies = {
        STRATEGY: _fields(sources[STRATEGY], {GOVERNMENT, NEGOTIATION, SUBJECT, OVERLORD}),
        SUBJECTS: _fields(sources[SUBJECTS], {AUTONOMY, SELF}),
        INFO: _fields(decision_rules.load(), {STATE}),
    }
    policies = {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in policies.items()
    }
    selected = replace(
        adapters,
        policies=tuple((source, policy) for source, policy in policies.items() if source != INFO),
        initial_values=(),
        scalar_values=(),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
    files[INFO] = decision_rules.patch(
        baseline,
        policies[INFO],
        baseline=baseline,
        reader_words=frozenset(decision_adapters.reader_evidence(inputs)),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    inputs[INFO] = baseline
    return policies, inputs, files


def _values(policy: Any, changes: dict[str, object]) -> dict[str, object]:
    values: dict[str, object] = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    # Explicit known observations ensure unrelated higher-priority branches are
    # known false. Individual unknown tests replace exactly one observation.
    values.update(
        default=False,
        war=False,
        loans=False,
        bureaucracy=0,
        legitimacy=40,
        debt_ratio=0,
        net_surplus=0,
        insurrection=False,
        candidate_gdp=10,
        national_gdp=100,
        prospective_subject_population=100,
        prospective_overlord_population=100,
        overlord_relations=0,
        target_relations=0,
        candidate_overlord_war=False,
        target_market_access=0,
        target_port=False,
        fervor=0,
        income=0,
    )
    values.update(changes)
    return values


def _engine(policy: Any, values: dict[str, object], *, is_ai: bool = True) -> dict[str, Any]:
    facts: dict[str, Any] = {"ROOT": {"is_ai": is_ai}}
    for reader in policy.readers:
        if reader.key not in values:
            continue
        scope = "ROOT" if reader.scope == "root" else f"scope:{reader.scope}"
        node = facts.setdefault(scope, {})
        for component in reader.path:
            node = node.setdefault(component, {})
        observed = values[reader.key]
        if reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            node[f"{reader.argument}_active"] = observed
        elif reader.argument is not None or reader.parameters or reader.value_field is not None:
            parameters = dict(reader.parameters)
            if reader.argument is not None:
                parameters["argument"] = reader.argument
            node.setdefault(reader.engine, {})[tuple(sorted(parameters.items()))] = observed
        else:
            node[reader.engine] = observed
        if reader.engine.startswith("sitai_context_"):
            node[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                observed is not None
            )
    return facts


def _overlay(text: str, field: str) -> str:
    start = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", start)
    lines: list[str] = []
    for line in text[start:end].splitlines()[1:]:
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or not lines[-1].lstrip().startswith("# ")
        ):
            lines.append("# unknown_guard [test]; native unchanged")
        lines.append(line)
    return "\n".join(lines)


CASES = [
    (
        STRATEGY,
        GOVERNMENT,
        {"candidate_ig_clout": 0.15, "candidate_ig_approval": 1, "candidate_ig_government": True},
        "lj08_government_local_continuity",
        "add",
        0.5,
    ),
    (
        STRATEGY,
        GOVERNMENT,
        {
            "candidate_ig_clout": 0.25,
            "candidate_ig_approval": 1,
            "candidate_ig_government": True,
            "legitimacy": 60,
        },
        "structural_stable_government_member",
        "add",
        1.05,
    ),
    (
        STRATEGY,
        NEGOTIATION,
        {"candidate_ig_clout": 0.15, "candidate_ig_approval": -1, "radical_share": 0.2},
        "lj08_negotiation_local_political_capacity",
        "multiply",
        1.10,
    ),
    (
        STRATEGY,
        NEGOTIATION,
        {
            "candidate_ig_clout": 0.15,
            "candidate_ig_approval": -1,
            "radical_share": 0.2,
            "default": True,
            "war": True,
            "loans": True,
            "bureaucracy": -1,
        },
        "lj08_negotiation_local_political_capacity",
        "multiply",
        1.10,
    ),
    (
        STRATEGY,
        NEGOTIATION,
        {
            "candidate_ig_clout": 0.2,
            "candidate_ig_approval": -1,
            "radical_share": 0.3,
            "legitimacy": 60,
        },
        "structural_organized_negotiation",
        "multiply",
        1.25,
    ),
    (
        STRATEGY,
        SUBJECT,
        {"candidate_existing_subject": True, "default": True},
        "lj12_existing_subject_insolvency_continuity",
        "add",
        1,
    ),
    (
        STRATEGY,
        SUBJECT,
        {"candidate_existing_subject": False, "default": True},
        "coordinated_overlord_financial_cost",
        "add",
        -5,
    ),
    (
        STRATEGY,
        SUBJECT,
        {"candidate_existing_subject": True},
        "comparative_retain_existing_subject",
        "add",
        3,
    ),
    (
        STRATEGY,
        OVERLORD,
        {"current_overlord_relation": True, "liberty": 80},
        "lj12_existing_overlord_autonomy_cost",
        "add",
        -3,
    ),
    (
        STRATEGY,
        OVERLORD,
        {"current_overlord_relation": True, "liberty": 80, "default": True},
        "lj12_existing_overlord_autonomy_cost",
        "add",
        -3,
    ),
    (
        STRATEGY,
        OVERLORD,
        {"current_overlord_relation": False, "liberty": 80, "default": True},
        "coordinated_subject_debt_option",
        "add",
        3,
    ),
    (
        SUBJECTS,
        AUTONOMY,
        {"liberty": 60, "default": True},
        "lj12_autonomy_insolvency_cost",
        "multiply",
        0.95,
    ),
    (
        SUBJECTS,
        AUTONOMY,
        {"liberty": 60},
        "ai_strategy_subject_maintain_autonomy_weight",
        "multiply",
        1.25,
    ),
    (
        SUBJECTS,
        SELF,
        {"liberty": 60, "bureaucracy": -1},
        "lj12_self_strength_administrative_repair",
        "multiply",
        1.05,
    ),
    (
        SUBJECTS,
        SELF,
        {"liberty": 60, "bureaucracy": 0},
        "ai_strategy_subject_strengthen_self_weight",
        "multiply",
        1.25,
    ),
    (
        INFO,
        STATE,
        {
            "target_owned": False,
            "target_homeland": True,
            "target_cultural_share": 0.3,
            "target_isolated": False,
        },
        "lj14_connected_homeland_foundation",
        "multiply",
        1.05,
    ),
    (
        INFO,
        STATE,
        {
            "target_owned": False,
            "target_homeland": True,
            "target_cultural_share": 0.3,
            "target_isolated": True,
        },
        "lj14_homeland_isolation_cost",
        "multiply",
        0.9,
    ),
    (
        INFO,
        STATE,
        {
            "target_owned": False,
            "target_homeland": True,
            "target_cultural_share": 0.3,
            "target_isolated": False,
            "bureaucracy": -1,
        },
        "lj14_homeland_administrative_cost",
        "multiply",
        0.92,
    ),
    (
        INFO,
        STATE,
        {
            "target_owned": False,
            "target_homeland": True,
            "target_cultural_share": 0.3,
            "target_isolated": False,
            "expansion_route": True,
            "fervor": 20,
            "income": 1,
            "legitimacy": 60,
        },
        "identity_feasible_homeland",
        "multiply",
        1.2,
    ),
]


@pytest.mark.parametrize(("source", "field", "changes", "writer", "operation", "value"), CASES)
def test_complete_field_competition_has_handwritten_outcomes(
    production, source, field, changes, writer, operation, value
):
    policies, _inputs, files = production
    policy = policies[source]
    values = _values(policy, changes)
    actual = pdx_eval.select(_overlay(files[source], field), _engine(policy, values))
    assert (actual.action_id, actual.operation, actual.delta) == (writer, operation, value)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert reference[field] == (writer, value)
    # Selecting or queueing a candidate is not observed current membership,
    # actual administrative capacity, culture share, or market connection.
    annotated = {**values, "candidate_selected": True, "construction_queued": True}
    assert pdx_eval.select(_overlay(files[source], field), _engine(policy, annotated)) == actual


@pytest.mark.parametrize(
    ("source", "field", "changes", "broken"),
    [
        (
            STRATEGY,
            GOVERNMENT,
            {
                "candidate_ig_clout": 0.15,
                "candidate_ig_approval": 1,
                "candidate_ig_government": True,
            },
            "candidate_ig_government",
        ),
        (
            STRATEGY,
            NEGOTIATION,
            {"candidate_ig_clout": 0.15, "candidate_ig_approval": -1, "radical_share": 0.2},
            "candidate_ig_clout",
        ),
        (
            STRATEGY,
            SUBJECT,
            {"candidate_existing_subject": True, "default": True},
            "candidate_existing_subject",
        ),
        (
            STRATEGY,
            OVERLORD,
            {"current_overlord_relation": True, "liberty": 80},
            "current_overlord_relation",
        ),
        (SUBJECTS, AUTONOMY, {"liberty": 60, "default": True}, "liberty"),
        (SUBJECTS, SELF, {"liberty": 60, "bureaucracy": -1}, "bureaucracy"),
        (
            INFO,
            STATE,
            {"target_homeland": True, "target_cultural_share": 0.3},
            "target_cultural_share",
        ),
        (INFO, STATE, {"target_homeland": True, "target_isolated": True}, "target_isolated"),
    ],
)
def test_critical_unknown_and_player_keep_native(production, source, field, changes, broken):
    policies, _inputs, files = production
    policy = policies[source]
    overlay = _overlay(files[source], field)
    values = _values(policy, changes)
    unknown_values = {**values, broken: None}
    actual = pdx_eval.select(overlay, _engine(policy, unknown_values))
    assert actual.operation is None or (
        actual.action_id == "unknown_guard" and actual.delta in {0, 1}
    )
    assert field not in decision_rules.evaluate(policy, unknown_values, is_ai=True)
    player = pdx_eval.select(overlay, _engine(policy, values, is_ai=False))
    assert player.operation is None or (
        player.action_id == "unknown_guard" and player.delta in {0, 1}
    )


def _normalize(node: Any) -> Any:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _normalize(node.value)
    assert isinstance(node, Block)
    return tuple(_normalize(child) for child in node.items)


def test_every_modified_field_retains_all_original_qualification_zero_and_tail_blocks(production):
    _policies, inputs, files = production
    for source, generated in files.items():
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            generated,
            flags=re.DOTALL | re.MULTILINE,
        )
        parsed = parse_text(stripped)
        original = parse_text(inputs[source])
        assert not parsed.errors
        assert not original.errors
        assert _normalize(parsed.root) == _normalize(original.root), source


def test_named_scope_decoys_cannot_replace_real_group_overlord_or_state(production):
    policies, _inputs, files = production
    probes: list[tuple[str, str, dict[str, object], str]] = [
        (
            STRATEGY,
            GOVERNMENT,
            {
                "candidate_ig_clout": 0.15,
                "candidate_ig_approval": 1,
                "candidate_ig_government": True,
            },
            "scope:interest_group",
        ),
        (STRATEGY, OVERLORD, {"current_overlord_relation": True, "liberty": 80}, "scope:overlord"),
        (
            INFO,
            STATE,
            {"target_homeland": True, "target_cultural_share": 0.3},
            "scope:target_state",
        ),
    ]
    for source, field, changes, scope in probes:
        policy = policies[source]
        facts = _engine(policy, _values(policy, changes))
        positive = pdx_eval.select(_overlay(files[source], field), facts)
        assert positive.operation is not None
        facts["other_country"] = facts.pop(scope)
        # The same-looking observation on ROOT or another target is not the
        # selected native scope, even if the candidate is already selected.
        facts["ROOT"]["candidate_selected"] = True
        facts["ROOT"]["construction_queued"] = True
        actual = pdx_eval.select(_overlay(files[source], field), facts)
        assert actual.operation is None or (
            actual.action_id == "unknown_guard" and actual.delta in {0, 1}
        )


def test_political_break_and_identity_cost_exit_do_not_disable_other_domains(production):
    policies, _inputs, files = production
    politics = policies[STRATEGY]
    values = _values(
        politics,
        {
            "candidate_ig_clout": 0.15,
            "candidate_ig_approval": -1,
            "radical_share": 0.2,
            "legitimacy": 20,
        },
    )
    assert NEGOTIATION not in decision_rules.evaluate(politics, values, is_ai=True)
    identity = policies[INFO]
    common = {"target_homeland": True, "target_cultural_share": 0.3}
    cases: list[tuple[dict[str, object], float]] = [
        ({"bureaucracy": -1}, 0.92),
        ({"bureaucracy": 0}, 1.05),
        ({"target_isolated": True}, 0.9),
    ]
    for changes, expected in cases:
        values = _values(identity, {**common, **changes})
        actual = pdx_eval.select(_overlay(files[INFO], STATE), _engine(identity, values))
        assert actual.delta == expected
        assert not any(rule.field == ("wanted_construction_output",) for rule in identity.rules)
