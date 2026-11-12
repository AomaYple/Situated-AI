"""D9 首批三个真实局部切片：手写结果与完整作用域生产 PDX。"""

from dataclasses import replace
from functools import cache
from typing import Any, cast

import pytest

from pdx import (
    country_state,
    decision_adapters,
    decision_rules,
    production_inputs,
    version_contracts,
)
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit
INDUSTRY = "common/buildings/01_industry.txt"
MINES = "common/buildings/03_mines.txt"
GOV = "common/buildings/07_government.txt"
TECH = "common/technology/technologies/10_production.txt"
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
INFO = "information"
FIELDS = {
    INDUSTRY: {"building_tooling_workshop.ai_value", "building_furniture_manufactory.ai_value"},
    MINES: {"building_iron_mine.ai_value"},
    GOV: {"building_government_administration.ai_value", "building_university.ai_value"},
    TECH: {"mechanical_tools.ai_weight"},
    STRATEGY: {"ai_strategy_default.institution_scores.institution_health_system"},
    INFO: {
        "institution_scores.institution_social_security",
        "institution_scores.institution_schools",
    },
}
PM_IRON = "pm_active_building_iron_mine_pm_picks_and_shovels_building_iron_mine"
PM_TOOLS = "pm_active_building_tooling_workshop_pm_pig_iron"
PM_FURNITURE = "pm_active_building_furniture_manufactory_pm_lathe"
BASES = {
    "building_iron_mine.ai_value": 1000,
    "building_tooling_workshop.ai_value": 2000,
    "building_furniture_manufactory.ai_value": 1000,
    "building_government_administration.ai_value": 1000,
    "building_university.ai_value": 2000,
    "mechanical_tools.ai_weight": 1,
    "institution_scores.institution_social_security": 10,
    "institution_scores.institution_schools": 10,
    "ai_strategy_default.institution_scores.institution_health_system": 10,
}


def _subset(policy, fields):
    rules = tuple(r for r in policy.rules if ".".join(r.field) in fields)
    used_keys = frozenset(key for rule in rules for key in rule.input_keys())
    readers = tuple(reader for reader in policy.readers if reader.key in used_keys)
    return replace(
        policy,
        rules=rules,
        readers=readers,
        enabled_domains=frozenset(r.domain for r in rules),
        semantic_ir=(),
    )


@pytest.fixture(scope="module")
def legacy_policies():
    adapters = decision_adapters.load()
    selected = tuple((s, _subset(p, FIELDS[s])) for s, p in adapters.policies if s in FIELDS)
    info = _subset(decision_rules.load(), FIELDS[INFO])
    return dict((*selected, (INFO, info)))


@pytest.fixture(scope="module")
def policies(legacy_policies):
    """Production references use the same compilation boundary as generated PDX."""
    model = compiler.load_model()
    return {
        source: compiler.compile_policy(
            policy, "mod/decisions/information.toml" if source == INFO else source, model
        )[0]
        for source, policy in legacy_policies.items()
    }


def _values(policy, **changes):
    values: dict[str, Any] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update({r.key: 0.2 for r in policy.readers if r.key.endswith("_price")})
    values.update(
        average_sol=7,
        sol=7,
        population=1,
        legitimacy=49,
        net_surplus=-1,
        state_owner_literacy=0.3,
        literacy=0.3,
    )
    values.update(changes)
    return values


def _scores(policies, changes, fields):
    result = []
    for source, field in fields:
        policy = policies[source]
        if (
            version_contracts.active_version() == "1.15.1"
            and field == "institution_scores.institution_schools"
            and policy.consumer_programs
        ):
            from pdx.situated import action_network

            result.append(
                10
                + action_network.evaluate_network(
                    _current_school(),
                    {k: v for k, v in _school_facts(changes).items() if k != "ai"},
                ).total
            )
            continue
        selected = decision_rules.evaluate(policy, _values(policy, **changes), is_ai=True).get(
            field
        )
        result.append(BASES[field] * (selected[1] if selected else 1))
    return tuple(result)


LJ01_FIELDS = (
    (MINES, "building_iron_mine.ai_value"),
    (INDUSTRY, "building_tooling_workshop.ai_value"),
    (INDUSTRY, "building_furniture_manufactory.ai_value"),
)
LJ01_INPUTS = {
    PM_IRON: True,
    PM_TOOLS: True,
    PM_FURNITURE: True,
    "state_owner_iron_price": 0.6,
    "state_owner_iron_balance": -1,
    "state_owner_tools_price": 0.6,
    "state_owner_tools_balance": -1,
    "state_owner_furniture_price": 0.3,
    "state_owner_furniture_balance": -1,
}
LJ01_CASES = [
    # Observed active output +.20 and its actual input -.20 cancel for iron
    # and tools. Furniture has only generic supply +.12 against input -.20.
    ({}, (1000, 2000, 920)),
    (
        {
            "state_owner_iron_price": 0.2,
            "state_owner_iron_balance": 0,
            "state_owner_tools_price": 0.3,
        },
        (1000, 2400, 1120),
    ),
    (
        {
            "state_owner_iron_price": 0.2,
            "state_owner_iron_balance": 0,
            "state_owner_tools_price": 0.2,
            "state_owner_tools_balance": 0,
        },
        (1000, 2000, 1200),
    ),
    ({"state_owner_default": True}, (850, 1700, 770)),
    # Losing the workshop recipe removes only its observed output/cost tiers;
    # its independently known market supply opportunity remains +.12.
    ({PM_TOOLS: None}, (1000, 2240, 920)),
    ({PM_TOOLS: False}, (1000, 2240, 920)),
]


@pytest.mark.parametrize(("changes", "expected"), LJ01_CASES)
def test_lj01_iron_tools_industry_actual_supply_feedback(policies, changes, expected):
    assert _scores(policies, {**LJ01_INPUTS, **changes}, LJ01_FIELDS) == pytest.approx(expected)


LJ03_FIELDS = (
    (INFO, "institution_scores.institution_schools"),
    (GOV, "building_university.ai_value"),
    (TECH, "mechanical_tools.ai_weight"),
)
LJ03_INPUTS = {
    "state_owner_academia_completed": True,
    "country_goods_tools_price": 0.3,
    "country_goods_tools_balance": -1,
    "pm_active_building_university_pm_scholastic_education": True,
}
LJ03_CASES = [
    ({}, (11, 2400, 1.2)),
    ({"literacy": 0.5, "state_owner_literacy": 0.5}, (10, 2000, 1.2)),
    ({"state_owner_paper_price": 0.6, "state_owner_paper_balance": -1}, (11, 1900, 1.2)),
    (
        {"state_owner_academia_completed": None, "literacy": None, "state_owner_literacy": None},
        # Unknown literacy exits school/university needs; the independently
        # observed tools market shortage retains its own 1.2 research tier.
        (10, 2000, 1.2),
    ),
    ({"country_goods_tools_price": 0.2, "country_goods_tools_balance": 0}, (11, 2400, 1)),
]


# A new additive school consumer changes only the school component. Keep both
# literal tables: the 1.15.1 policy is not asserted equivalent to the old multiplier.
LJ03_CURRENT_CASES = [
    ({}, (12, 2400, 1.2)),
    ({"literacy": 0.5, "state_owner_literacy": 0.5}, (10, 2000, 1.2)),
    ({"state_owner_paper_price": 0.6, "state_owner_paper_balance": -1}, (12, 1900, 1.2)),
    (
        {"state_owner_academia_completed": None, "literacy": None, "state_owner_literacy": None},
        (10, 2000, 1.2),
    ),
    ({"country_goods_tools_price": 0.2, "country_goods_tools_balance": 0}, (12, 2400, 1)),
]


def _lj03_cases():
    return LJ03_CURRENT_CASES if version_contracts.active_version() == "1.15.1" else LJ03_CASES


@pytest.mark.parametrize(("changes", "expected"), _lj03_cases())
def test_lj03_actual_education_capacity_changes_research_without_blocking_industry(
    policies, changes, expected
):
    assert _scores(policies, {**LJ03_INPUTS, **changes}, LJ03_FIELDS) == pytest.approx(expected)


LJ04_FIELDS = (
    (GOV, "building_government_administration.ai_value"),
    (INFO, "institution_scores.institution_social_security"),
    (STRATEGY, "ai_strategy_default.institution_scores.institution_health_system"),
)
LJ04_CASES = [
    ({"bureaucracy": -1, "state_owner_bureaucracy": -1}, (1250, 9.8, 8)),
    ({"bureaucracy": 0, "state_owner_bureaucracy": 0}, (1000, 10.8, 10)),
    ({"bureaucracy": 1, "state_owner_bureaucracy": 1}, (1000, 10.8, 10)),
    (
        {
            "bureaucracy": -1,
            "state_owner_bureaucracy": -1,
            "default": True,
            "state_owner_default": True,
        },
        # Under default the known base repair +.05 joins financing -.25.
        # Welfare .08 need joins -.10 administration and -.20 financing;
        # health joins -.20 administration and -.25 financing.
        (800, 7.8, 5.5),
    ),
    ({"bureaucracy": None, "state_owner_bureaucracy": None}, (1000, 10.8, 10)),
    ({"bureaucracy": 0, "state_owner_bureaucracy": 0, "average_sol": 8}, (1000, 10, 10)),
]


@pytest.mark.parametrize(("changes", "expected"), LJ04_CASES)
def test_lj04_only_actual_administrative_balance_advances_welfare(policies, changes, expected):
    assert _scores(policies, changes, LJ04_FIELDS) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("chain", "changes", "expected"),
    [
        ("LJ01", {}, (1120, 2240, 1120)),
        ("LJ01", {PM_TOOLS: None}, (1120, 2240, 1120)),
        (
            "LJ03",
            {
                "state_owner_academia_completed": None,
                "literacy": None,
                "state_owner_literacy": None,
            },
            (10, 2000, 1.2),
        ),
        (
            "LJ04",
            {
                "bureaucracy": -1,
                "state_owner_bureaucracy": -1,
                "default": True,
                "state_owner_default": True,
            },
            (1050, 8.5, 7.5),
        ),
    ],
)
def test_raw_ruleset_legacy_priority_and_unknown_are_separate_from_production(
    legacy_policies, chain, changes, expected
):
    fields, inputs = {
        "LJ01": (LJ01_FIELDS, LJ01_INPUTS),
        "LJ03": (LJ03_FIELDS, LJ03_INPUTS),
        "LJ04": (LJ04_FIELDS, {}),
    }[chain]
    assert all(not policy.consumer_programs for policy in legacy_policies.values())
    assert _scores(legacy_policies, {**inputs, **changes}, fields) == pytest.approx(expected)


@pytest.mark.parametrize("chain", ["LJ01", "LJ03", "LJ04"])
def test_candidate_selection_never_changes_real_chain_inputs(policies: Any, chain: str) -> None:
    fields, values = {
        "LJ01": (LJ01_FIELDS, LJ01_INPUTS),
        "LJ03": (LJ03_FIELDS, LJ03_INPUTS),
        "LJ04": (LJ04_FIELDS, {"bureaucracy": -1, "state_owner_bureaucracy": -1}),
    }[chain]
    values = cast("dict[str, Any]", values)
    before = _scores(policies, values, fields)
    assert (
        _scores(
            policies, {**values, "candidate_selected": True, "construction_queued": True}, fields
        )
        == before
    )


@pytest.mark.integration
def test_lj03_academia_completion_is_a_parameterized_reader_and_native_qualification(policies):
    reader = next(r for r in policies[GOV].readers if r.key == "state_owner_academia_completed")
    assert (reader.engine, reader.argument, reader.scope, reader.path, reader.kind) == (
        "has_technology_researched",
        "academia",
        "root",
        ("owner",),
        "boolean",
    )
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    native_entry = parse_text(inputs[GOV]).root.first("building_university")
    assert native_entry is not None
    assert isinstance(native_entry.value, Block)
    native = native_entry.value
    unlocking = native.first("unlocking_technologies")
    assert unlocking is not None
    assert isinstance(unlocking.value, Block)
    assert [v.unquoted for v in unlocking.value.scalars()] == ["academia"]
    tech = parse_text(inputs["common/technology/technologies/30_society.txt"]).root
    assert tech.first("academia") is not None


@pytest.fixture(scope="module")
def generated(policies):
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    sources = tuple((source, policy) for source, policy in policies.items() if source != INFO)
    fields = {(s, r.field) for s, p in sources for r in p.rules}
    selected = replace(
        adapters,
        policies=sources,
        initial_values=tuple(i for i in adapters.initial_values if (i.source, i.field) in fields),
        scalar_values=tuple(row for row in adapters.scalar_values if row in fields),
        supply=None,
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _ = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
    files[INFO] = decision_rules.patch(
        baseline,
        policies[INFO],
        baseline=baseline,
        reader_words=frozenset(decision_adapters.reader_evidence(inputs)),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source="mod/decisions/information.toml",
    )
    return inputs, files


def _overlay(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return text[begin:end]


def _engine_facts(policy, values, *, is_ai=True):
    # These are actual scoped reader observations. Parameterized queries keep
    # their technology/building/method identity; no selector result is an input.
    root: dict[str, Any] = {"any_scope_state": [], "any_scope_building": []}
    for reader in policy.readers:
        if reader.engine in {"any_scope_state", "any_scope_building"}:
            continue
        current = root
        assert reader.scope == "root"
        for part in reader.path:
            current = current.setdefault(part, {})
        observed = values.get(reader.key)
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            query = current.setdefault(reader.engine, {})
            query.setdefault(params["building_type"], {})[params["production_method"]] = observed
        elif reader.argument is not None or reader.parameters:
            params = dict(reader.parameters)
            if reader.argument is not None:
                params["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(params.items()))] = observed
            if reader.engine == "has_variable" and (reader.argument or "").startswith(
                "sitai_route_"
            ):
                current[f"{reader.argument}_active"] = observed
        else:
            current[reader.engine] = observed
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                observed is not None
            )
    actor = root.setdefault("owner", {}) if policy.actor_path else root
    actor["is_ai"] = is_ai
    return {"ROOT": root}


@pytest.mark.parametrize(
    ("source", "key", "other_argument"),
    [
        (GOV, "state_owner_academia_completed", "empiricism"),
        (STRATEGY, "current_public_health", "law_type:law_charitable_health_system"),
    ],
)
def test_engine_observations_keep_parameter_queries_independent(
    policies, source, key, other_argument
):
    policy = policies[source]
    reader = next(r for r in policy.readers if r.key == key)
    other = replace(reader, key="other_observation", argument=other_argument)
    policy = replace(policy, readers=(reader, other))
    for observed in (False, None):
        facts = _engine_facts(policy, {key: True, other.key: observed})
        prefix = "ROOT = { " + " ".join(f"{part} = {{" for part in reader.path)
        suffix = " }" * (1 + len(reader.path))
        for argument, expected in (
            (reader.argument, True),
            (other_argument, observed),
            ("unobserved_identity", None),
        ):
            condition = parse_text(f"{prefix} {reader.engine} = {argument}{suffix}").root
            assert pdx_eval.condition(condition, facts) is expected


def _pdx_scores(policies, generated, changes, fields, *, is_ai=True):
    _, files = generated
    scores = []
    for source, field in fields:
        values = _values(policies[source], **changes)
        if (
            version_contracts.active_version() == "1.15.1"
            and field == "institution_scores.institution_schools"
        ):
            from test_network_profile import _parsed, _score

            from pdx.situated import network_profile

            assert field not in {".".join(rule.field) for rule in policies[source].rules}
            school_facts = _school_facts(changes, is_ai=is_ai)
            rendered = network_profile.render_program(
                _current_school(), available=tuple(key for key in school_facts if key != "ai")
            )
            scores.append(10 + _score(_parsed(rendered), school_facts))
            continue
        overlay = _overlay(files[source], field)
        actual = pdx_eval.select(overlay, _engine_facts(policies[source], values, is_ai=is_ai))
        factor = actual.delta if actual.operation == "multiply" else 1
        scores.append(BASES[field] * factor)
    return tuple(scores)


@pytest.mark.integration
@pytest.mark.parametrize(("changes", "expected"), LJ01_CASES)
def test_lj01_actual_generated_pdx_supply_and_recipe_scopes(policies, generated, changes, expected):
    assert _pdx_scores(
        policies, generated, {**LJ01_INPUTS, **changes}, LJ01_FIELDS
    ) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(("changes", "expected"), _lj03_cases())
def test_lj03_actual_generated_pdx_completed_knowledge_and_literacy(
    policies, generated, changes, expected
):
    assert _pdx_scores(
        policies, generated, {**LJ03_INPUTS, **changes}, LJ03_FIELDS
    ) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(("changes", "expected"), LJ04_CASES)
def test_lj04_actual_generated_pdx_real_administrative_capacity(
    policies, generated, changes, expected
):
    assert _pdx_scores(policies, generated, changes, LJ04_FIELDS) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize("chain", ["LJ01", "LJ03", "LJ04"])
def test_chain_players_and_uncompleted_candidates_keep_native_inputs(
    policies: Any, generated: Any, chain: str
) -> None:
    fields, values = {
        "LJ01": (LJ01_FIELDS, LJ01_INPUTS),
        "LJ03": (LJ03_FIELDS, LJ03_INPUTS),
        "LJ04": (LJ04_FIELDS, {"bureaucracy": -1, "state_owner_bureaucracy": -1}),
    }[chain]
    values = cast("dict[str, Any]", values)
    before = _pdx_scores(policies, generated, values, fields)
    assert (
        _pdx_scores(policies, generated, {**values, "candidate_selected": True}, fields) == before
    )
    assert _pdx_scores(policies, generated, values, fields, is_ai=False) == tuple(
        BASES[f] for _, f in fields
    )


@pytest.mark.integration
def test_lj01_other_state_and_country_methods_never_repair_this_states_inputs(policies, generated):
    policy = policies[MINES]
    values = _values(policy, **{**LJ01_INPUTS, PM_TOOLS: False})
    facts = _engine_facts(policy, values)
    decoy = {"is_production_method_active": {"building_tooling_workshop": {"pm_pig_iron": True}}}
    facts["other_state"] = decoy
    facts["ROOT"]["owner"]["other_state"] = decoy
    facts["ROOT"]["owner"]["is_production_method_active"] = decoy["is_production_method_active"]
    # Flat facts and other owners cannot override the actual ROOT state.
    facts.update(decoy)
    facts["other_country"] = {"in_default": False, **decoy}
    actual = pdx_eval.select(_overlay(generated[1][MINES], "building_iron_mine.ai_value"), facts)
    # The local mine's observed output +.20 cancels its tools input -.20;
    # an unrelated workshop cannot create another local repair bonus.
    assert actual.delta == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("bureaucracy", "expected"),
    [(-0.001, (1250, 9.8, 8)), (0, (1000, 10.8, 10)), (0.001, (1000, 10.8, 10))],
)
@pytest.mark.integration
def test_lj04_signed_capacity_zero_is_distinct_from_unknown_and_deficit(
    policies, generated, bureaucracy, expected
):
    values = {"bureaucracy": bureaucracy, "state_owner_bureaucracy": bureaucracy}
    assert _scores(policies, values, LJ04_FIELDS) == pytest.approx(expected)
    assert _pdx_scores(policies, generated, values, LJ04_FIELDS) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("literacy", "expected"),
    [
        (0.499, 1.2),
        (0.5, 1.2),
        (0.501, 1.2),
        # Literacy is not a proxy for having adopted this technology's recipe.
        # Its unknown value does not erase a known tools market shortage.
        (-1, 1.2),
        (None, 1.2),
        (float("nan"), 1.2),
        (float("inf"), 1.2),
    ],
)
@pytest.mark.integration
def test_lj03_real_absorption_capacity_has_ratio_and_finite_boundaries(
    policies, generated, literacy, expected
):
    values = {**LJ03_INPUTS, "literacy": literacy}
    fields = ((TECH, "mechanical_tools.ai_weight"),)
    assert _scores(policies, values, fields) == pytest.approx((expected,))
    assert _pdx_scores(policies, generated, values, fields) == pytest.approx((expected,))


def _tree(node):
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def _entry(text, name):
    entry = parse_text(text).root.first(name)
    assert entry is not None
    assert isinstance(entry.value, Block)
    return entry.value


@pytest.mark.integration
def test_lj01_positive_recipe_flows_and_unrelated_mine_definition_remain_native(generated):
    inputs, files = generated
    rows = production_inputs.recipes(
        inputs,
        (
            ("building_tooling_workshop", "pm_pig_iron"),
            ("building_furniture_manufactory", "pm_lathe"),
        ),
    )
    flows = {
        row["method"]: {(g["kind"], g["good"]): g["quantity"] for g in row["goods"]} for row in rows
    }
    assert flows["pm_pig_iron"][("input", "iron")] > 0
    assert flows["pm_pig_iron"][("output", "tools")] > 0
    assert flows["pm_lathe"][("input", "tools")] > 0
    assert flows["pm_lathe"][("output", "furniture")] > 0
    assert _tree(_entry(inputs[MINES], "building_coal_mine")) == _tree(
        _entry(files[MINES], "building_coal_mine")
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source", "definition", "changed_field"),
    [(GOV, "building_university", "ai_value"), (TECH, "mechanical_tools", "ai_weight")],
)
def test_lj03_actual_building_and_technology_qualifications_stay_native(
    generated, source, definition, changed_field
):
    inputs, files = generated
    native = _entry(inputs[source], definition)
    output = _entry(files[source], definition)
    assert tuple(
        _tree(item)
        for item in native.items
        if not isinstance(item, Assignment) or item.key != changed_field
    ) == tuple(
        _tree(item)
        for item in output.items
        if not isinstance(item, Assignment) or item.key != changed_field
    )
    # No new condition grants an unavailable university or completed PM.
    assert "set_variable" not in files[source]


@pytest.mark.integration
def test_all_depth_links_disabled_retain_exact_native_and_source_selection_cannot_mutate_state(
    policies, generated
):
    inputs, _ = generated
    adapters = decision_adapters.load()
    disabled, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert disabled == {}
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
    assert (
        decision_rules.patch(
            baseline, policies[INFO], baseline=baseline, enabled_domains=frozenset()
        )
        == baseline
    )
    for policy in policies.values():
        assert all("selected" not in r.key and "queued" not in r.key for r in policy.readers)
    values = {
        **LJ03_INPUTS,
        "state_owner_academia_completed": False,
        "candidate_selected": True,
        "construction_queued": True,
    }
    # Observed existing university PM plus prepared paper supports 1.2;
    # the false academia observation cannot be repaired by a queued intention.
    # Native unlocking_technologies continues to decide actual availability.
    assert _scores(policies, values, ((GOV, "building_university.ai_value"),)) == (2400,)
    assert _pdx_scores(policies, generated, values, ((GOV, "building_university.ai_value"),)) == (
        2400,
    )


@cache
def _current_school():
    from pdx.situated import network_profile, production_profile

    assert version_contracts.active_version() == "1.15.1"
    profile = production_profile.load_profile(production_profile.baseline_root())
    return next(
        program
        for program in network_profile.compile_profile(profile)
        if program.network.actions[0].definition.consumer_id == "a0-pol-schools"
    )


def _school_facts(changes, *, is_ai=True):
    facts = {
        "ai": is_ai,
        "literacy": 0.3,
        "population": 1,
        "bureaucracy": 0,
        "net-surplus": -1,
        "default": False,
        "school-agenda": False,
        **{
            ("net-surplus" if key == "net_surplus" else key): value
            for key, value in changes.items()
            if key
            in {"literacy", "population", "bureaucracy", "net_surplus", "default", "school-agenda"}
            and value is not None
        },
    }
    for key, value in changes.items():
        if value is None:
            facts.pop("net-surplus" if key == "net_surplus" else key, None)
    return facts


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 11),
        ({"literacy": 0.5, "state_owner_literacy": 0.5}, 10),
        ({"state_owner_paper_price": 0.6, "state_owner_paper_balance": -1}, 11),
        (
            {
                "state_owner_academia_completed": None,
                "literacy": None,
                "state_owner_literacy": None,
            },
            10,
        ),
        ({"country_goods_tools_price": 0.2, "country_goods_tools_balance": 0}, 11),
    ],
)
def test_historical_school_lj03_multiplier_contract(version, changes, expected):
    from test_full_information import _evaluate_script, _generated_rule_blocks

    with version_contracts.select_version(version):
        policy = decision_rules.load()
        values = _values(policy, **changes)
        field = "institution_scores.institution_schools"
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        assert 10 * (selected[1] if selected else 1) == expected
        engine = {
            r.engine + (":" + r.argument if r.argument else ""): values.get(r.key)
            for r in policy.readers
        }
        assert (
            10 * _evaluate_script(_generated_rule_blocks(policy).blocks[field], engine) == expected
        )
