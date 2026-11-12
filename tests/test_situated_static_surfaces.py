"""D0 静态政策类型和调用方依赖脚本定义的证据边界。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import version_contracts
from pdx.situated.vanilla_inventory import discover

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def historical_discovery_contract():
    # These synthetic fixtures declare release/1.14.5 and its documentation;
    # installed 1.15 integrations keep their independently selected contract.
    with version_contracts.select_version("1.14.5"):
        yield


PM_DOC = (
    "ai_selection = most_productive # Affects how the AI chooses between PMs. "
    "Current options: most_profitable, most_productive. Default most_profitable\n"
)
STANCE_DOC = (
    "stances = { stance_key ... } # Which regional stances this objective may be drawn for.\n"
)
GRIEVANCE_DOC = (
    "ai = {\nsettles_grievance = no # yes = an AI with an Antagonistic attitude towards "
    "the target may still start a diplomatic play for this war goal\n}\n"
)
SIGNIFICANT_DEMAND_DOC = (
    "## AI / Is Significant Demand\n"
    "AI flag that determines how important AI considers this war goal to be.\n"
    "is_significant_demand = yes\n"
)
TRIGGER_TEMPLATE = (
    "# Example:\n# example_trigger = {\n# x = 100\n# y = 50\n# }\n"
    "# In a script file:\n# effect = {\n# example_trigger = yes\n# }\n"
)
COMPANY_DOC = (
    "# While the AI is trying to form a company (that has passed the ai_will_do, potential "
    "and attainable triggers) it will have increased weight for certain building types in "
    "certain states, which buildings, which states (determined through a trigger) and up "
    "to which level are all specified here\n"
    "# Note that scripting this with an empty state trigger will do nothing, as it would "
    "otherwise result in indiscrimate construction in all states!\n"
    "company_key = { ai_construction_targets = { building_iron_mine = {\n"
    "level = 5\nstate_trigger = { state_region = s:STATE_NORRLAND }\n} } }\n"
)
BUILDING_GROUP_DOC = (
    "# Add a multiplier to the score AI assigns to particular building groups (default 1)\n"
    "# Using this value in other strategies will result in several multiplications\n"
    "building_group_weights = {\n"
    "bg_agriculture = 1.25\n"
    "}\n"
)
COMPANY_SELECTION_DOC = (
    "company_key = {\nai_will_do = {\n"
    "# If this trigger is true, then the AI will potentially select this company as the next "
    "company it will try to form.\n"
    "# To check this trigger, the company must be considered at least 'attainable'\n"
    "# If this trigger is not present, the AI never try to found this company\n"
    "}\n}\n"
)
WARGOAL_SCORE_DOC = (
    "# How much should the AI value a wargoal against another country/state\n"
    "# Using this value in other strategies will function additively\n"
    "# scope:target_country = wargoal target country\n"
    "# scope:target_state = wargoal target state (if any)\n"
    "# scope:diplomatic_play = the diplomatic play (if there is one)\n"
    "wargoal_scores = { conquer_state = { value = 1 } }\n"
)
STRATEGY_PARTIAL_DOC = (
    "# How likely should the AI be to have a particular strategic desire towards another country\n"
    "# Trigger is used for filtering, so if it fails score will always be 0 from this strategy\n"
    "# Using this value in other strategies will function additively\n"
    "# scope:target_country = target country\n"
    "secret_goal_scores = { none = { score = { value = 1 } } }\n"
    "# How should the AI plan for production and trade of specific goods\n"
    "# Using a different value in a strategy will override this value\n"
    "goods_stances = { small_arms = { stance = wants_high_supply } }\n"
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _game(tmp_path: Path) -> Path:
    for name, text in (
        ("caligula_branch", "release/1.14.5"),
        ("caligula_rev", "fixture"),
        ("clausewitz_branch", "fixture"),
        ("clausewitz_rev", "fixture"),
    ):
        _write(tmp_path, f"{name}.txt", text)
    game = tmp_path / "game"
    _write(game, "common/ai_strategic_region_stance_types/known.txt", "stance_known = {}\n")
    return game


@pytest.mark.parametrize(
    ("directory", "body", "doc_name", "doc", "operation"),
    [
        (
            "production_method_groups",
            "ai_selection = most_productive",
            "production_method_groups.md",
            PM_DOC,
            "ai_selection_policy",
        ),
        (
            "production_method_groups",
            "ai_selection = most_profitable",
            "production_method_groups.md",
            PM_DOC,
            "ai_selection_policy",
        ),
        (
            "ai_regional_objectives",
            "stances = { stance_known }",
            "ai_regional_objectives.md",
            STANCE_DOC,
            "objective_stance_eligibility",
        ),
        (
            "war_goal_types",
            "ai = { settles_grievance = yes }",
            "war_goal_types.md",
            GRIEVANCE_DOC,
            "grievance_start_permission",
        ),
        (
            "war_goal_types",
            "ai = { settles_grievance = no }",
            "war_goal_types.md",
            GRIEVANCE_DOC,
            "grievance_start_permission",
        ),
        (
            "war_goal_types",
            "ai = { is_significant_demand = yes }",
            "war_goal_types.md",
            SIGNIFICANT_DEMAND_DOC,
            "significant_demand_flag",
        ),
        (
            "war_goal_types",
            "ai = { is_significant_demand = no }",
            "war_goal_types.md",
            SIGNIFICANT_DEMAND_DOC,
            "significant_demand_flag",
        ),
    ],
)
def test_documented_static_policy_has_no_runtime_country_target(
    tmp_path, directory, body, doc_name, doc, operation
) -> None:
    game = _game(tmp_path)
    _write(game, f"common/{directory}/policy.txt", f"policy = {{ {body} }}\n")
    _write(game, f"common/{directory}/{doc_name}", doc)
    result = discover(game=game)
    row = next(item for item in result.surfaces if item.definition == "policy")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "global",
        "none",
        operation,
        "indirect",
    )
    assert row.legal
    assert row.getter is None
    assert "静态" in row.getter_note
    assert "不是国家脚本 getter" in row.getter_note
    assert row.status == "pending"
    assert row.responsibility_step == "D4.06"
    assert row.surface_id not in result.unknown_scopes


@pytest.mark.parametrize(
    ("directory", "body", "doc_name", "doc"),
    [
        ("production_method_groups", "ai_selection = 1", "production_method_groups.md", PM_DOC),
        (
            "production_method_groups",
            "ai_selection = most_invented",
            "production_method_groups.md",
            PM_DOC,
        ),
        (
            "production_method_groups",
            'ai_selection = "most_productive"',
            "production_method_groups.md",
            PM_DOC,
        ),
        (
            "production_method_groups",
            "ai_selection = { value = most_productive invented = yes }",
            "production_method_groups.md",
            PM_DOC,
        ),
        (
            "production_method_groups",
            "ai_selection != most_productive",
            "production_method_groups.md",
            PM_DOC,
        ),
        (
            "production_method_groups",
            "ai_selection = most_productive",
            "production_method_groups.md",
            "",
        ),
        (
            "production_method_groups",
            "ai_selection = most_productive",
            "production_method_groups.md",
            "ai_selection = most_productive # Affects how the AI chooses between PMs\n",
        ),
        (
            "ai_regional_objectives",
            "stances = stance_known",
            "ai_regional_objectives.md",
            STANCE_DOC,
        ),
        ("ai_regional_objectives", "stances = {}", "ai_regional_objectives.md", STANCE_DOC),
        (
            "ai_regional_objectives",
            "stances = { stance_missing }",
            "ai_regional_objectives.md",
            STANCE_DOC,
        ),
        (
            "ai_regional_objectives",
            "stances = { stance_known invented = yes }",
            "ai_regional_objectives.md",
            STANCE_DOC,
        ),
        (
            "ai_regional_objectives",
            "stances = { stance_known { stance_known } }",
            "ai_regional_objectives.md",
            STANCE_DOC,
        ),
        (
            "ai_regional_objectives",
            'stances = { "stance_known" }',
            "ai_regional_objectives.md",
            STANCE_DOC,
        ),
        ("ai_regional_objectives", "stances = { stance_known }", "ai_regional_objectives.md", ""),
        ("war_goal_types", "ai = { settles_grievance = 1 }", "war_goal_types.md", GRIEVANCE_DOC),
        (
            "war_goal_types",
            "ai = { is_significant_demand = 1 }",
            "war_goal_types.md",
            SIGNIFICANT_DEMAND_DOC,
        ),
        (
            "war_goal_types",
            "ai = { settles_grievance = maybe }",
            "war_goal_types.md",
            GRIEVANCE_DOC,
        ),
        (
            "war_goal_types",
            "ai = { settles_grievance = { value = yes } }",
            "war_goal_types.md",
            GRIEVANCE_DOC,
        ),
        ("war_goal_types", "ai = { settles_grievance = yes }", "war_goal_types.md", ""),
        (
            "war_goal_types",
            "ai = { is_significant_demand = yes }",
            "war_goal_types.md",
            "",
        ),
        (
            "war_goal_types",
            "ai = { settles_grievance = yes }",
            "war_goal_types.md",
            "ai = { settles_grievance = no }\n",
        ),
    ],
)
def test_static_policy_rejects_missing_contract_wrong_type_and_extra_structure(
    tmp_path, directory, body, doc_name, doc
) -> None:
    game = _game(tmp_path)
    _write(game, f"common/{directory}/policy.txt", f"policy = {{ {body} }}\n")
    if doc:
        _write(game, f"common/{directory}/{doc_name}", doc)
    result = discover(game=game)
    rows = [item for item in result.surfaces if item.definition == "policy"]
    assert rows
    for row in rows:
        assert row.capability == "pending"
        assert not row.legal
        assert row.surface_id in result.unknown_scopes
        assert row.getter is None


@pytest.mark.parametrize(
    "body",
    [
        "ai = { is_significant_demand = maybe }",
        "ai = { is_significant_demand = { value = yes } }",
        "ai = { is_significant_demand = yes is_significant_demand = no }",
        'ai = { is_significant_demand = "yes" }',
        "ai = { is_significant_demand != yes }",
    ],
)
def test_significant_demand_rejects_non_scalar_duplicate_and_extra_nodes(tmp_path, body) -> None:
    game = _game(tmp_path)
    _write(game, "common/war_goal_types/policy.txt", f"policy = {{ {body} }}\n")
    _write(game, "common/war_goal_types/war_goal_types.md", SIGNIFICANT_DEMAND_DOC)
    result = discover(game=game)
    rows = [item for item in result.surfaces if item.definition == "policy"]
    assert rows
    target_rows = [item for item in rows if item.field == "ai.is_significant_demand"]
    assert target_rows
    assert all(item.capability == "pending" and not item.legal for item in target_rows)
    assert all(item.surface_id in result.unknown_scopes for item in target_rows)


@pytest.mark.parametrize(
    "doc",
    [
        SIGNIFICANT_DEMAND_DOC.replace("## AI / Is Significant Demand", "## Other Flag"),
        SIGNIFICANT_DEMAND_DOC.replace("AI flag that determines how important", "AI flag"),
        SIGNIFICANT_DEMAND_DOC.replace("is_significant_demand = yes", "other_flag = yes"),
    ],
)
def test_significant_demand_requires_each_field_documentation_component(tmp_path, doc) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/war_goal_types/policy.txt",
        "policy = { ai = { is_significant_demand = yes } }\n",
    )
    _write(game, "common/war_goal_types/war_goal_types.md", doc)
    row = next(item for item in discover(game=game).surfaces if item.definition == "policy")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )
    assert not row.legal
    assert not row.scope_evidence


def test_static_policy_does_not_grant_unknown_sibling_or_duplicate_legal_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/war_goal_types/policy.txt",
        "policy = { ai = { settles_grievance = yes invented = yes } }\n"
        "duplicate = { ai = { settles_grievance = yes settles_grievance = no } }\n",
    )
    _write(game, "common/war_goal_types/war_goal_types.md", GRIEVANCE_DOC)
    result = discover(game=game)
    known = next(
        row
        for row in result.surfaces
        if row.definition == "policy" and row.field == "ai.settles_grievance"
    )
    assert known.legal
    rejected = [
        row
        for row in result.surfaces
        if row.definition == "duplicate" or row.field == "ai.invented"
    ]
    assert len(rejected) == 3
    assert all(row.capability == "pending" and not row.legal for row in rejected)
    assert result.discovered_count == 4


@pytest.mark.parametrize(
    "definition",
    [
        "policy != { ai_selection = most_productive }",
        "INJECT:policy = { ai_selection = most_productive }",
    ],
)
def test_static_policy_does_not_assume_prefixed_or_comparison_definition_semantics(
    tmp_path, definition
) -> None:
    game = _game(tmp_path)
    _write(game, "common/production_method_groups/policy.txt", definition + "\n")
    _write(game, "common/production_method_groups/production_method_groups.md", PM_DOC)
    result = discover(game=game)
    row = next(item for item in result.surfaces if item.definition == "policy")
    assert row.capability == "pending"
    assert not row.legal


@pytest.mark.parametrize(
    "body",
    ["always = yes", "scope:actor = { always = no }", "this = $TARGET$"],
)
def test_scripted_trigger_template_supports_only_caller_dependent_definition_observation(
    tmp_path, body
) -> None:
    game = _game(tmp_path)
    _write(game, "common/scripted_triggers/00_scripted_triggers.txt", TRIGGER_TEMPLATE)
    _write(game, "common/scripted_triggers/observed.txt", f"ai_predicate = {{ {body} }}\n")
    result = discover(game=game)
    row = next(item for item in result.surfaces if item.definition == "ai_predicate")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "caller_scope",
        "caller_derived",
        "read",
        "observation",
    )
    assert not row.legal
    assert row.getter is None
    assert "调用方" in row.getter_note
    assert row.scope_evidence == ("common/scripted_triggers/00_scripted_triggers.txt:1",)
    assert row.surface_id not in result.unknown_scopes
    assert result.legal_count == 0


@pytest.mark.parametrize(
    ("template", "definition"),
    [
        ("", "ai_predicate = { always = yes }"),
        (
            TRIGGER_TEMPLATE.replace("# example_trigger = yes", "# invented = yes"),
            "ai_predicate = { always = yes }",
        ),
        (TRIGGER_TEMPLATE.replace("# ", ""), "ai_predicate = { always = yes }"),
        (TRIGGER_TEMPLATE, "ai_predicate = yes"),
        (TRIGGER_TEMPLATE, "ai_predicate != { always = yes }"),
    ],
)
def test_scripted_trigger_definition_observation_requires_original_template_and_block(
    tmp_path, template, definition
) -> None:
    game = _game(tmp_path)
    if template:
        _write(game, "common/scripted_triggers/00_scripted_triggers.txt", template)
    _write(game, "common/scripted_triggers/observed.txt", definition + "\n")
    result = discover(game=game)
    row = next(item for item in result.surfaces if item.definition == "ai_predicate")
    assert row.capability == "pending"
    assert row.getter is None
    assert row.actor_scope == row.target_scope == "unknown"
    assert row.surface_id in result.unknown_scopes


def _company_game(tmp_path: Path, body: str, doc: str = COMPANY_DOC) -> Path:
    game = _game(tmp_path)
    _write(game, "common/buildings/known.txt", "building_known = {}\n")
    _write(game, "common/company_types/companies.md", doc)
    _write(game, "common/company_types/known.txt", f"company_known = {{ {body} }}\n")
    return game


def test_company_construction_level_is_static_limit_not_a_dynamic_score(tmp_path) -> None:
    game = _company_game(
        tmp_path,
        "ai_construction_targets = { building_known = { level = 5 "
        "state_trigger = { state_region = s:STATE_KNOWN } } } "
        "ai_weight = { value = 1 } ai_will_do = { always = yes }",
    )
    result = discover(game=game)
    rows = {row.field: row for row in result.surfaces if row.definition == "company_known"}
    row = rows["ai_construction_targets.building_known.level"]
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "global",
        "none",
        "construction_level_cap",
        "indirect",
    )
    assert row.legal
    assert row.getter is None
    assert "静态" in row.getter_note
    assert getattr(row, "parent_field", None) is None
    assert rows["ai_weight"].capability == "pending"
    assert rows["ai_will_do"].capability == "pending"


def test_company_internal_predicates_keep_every_frontier_identity_and_parent_link(tmp_path) -> None:
    game = _company_game(
        tmp_path,
        "ai_construction_targets = { building_known = { level = 5\n"
        "state_trigger = { has_state_trait = trait_known any_scope_building = { "
        "is_building_type = building_known level >= 5 } } } }",
    )
    result = discover(game=game)
    rows = [row for row in result.surfaces if row.definition == "company_known"]
    assert len(rows) == 4
    assert {row.field for row in rows} == {
        "ai_construction_targets.building_known.level",
        "ai_construction_targets.building_known.state_trigger.has_state_trait",
        "ai_construction_targets.building_known.state_trigger.any_scope_building.is_building_type",
        "ai_construction_targets.building_known.state_trigger.any_scope_building.level",
    }
    internal = [row for row in rows if ".state_trigger." in row.field]
    assert len(internal) == 3
    for row in internal:
        assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
            "parent_field_scope",
            "parent_derived",
            "read",
            "observation",
        )
        assert row.parent_field == "ai_construction_targets.building_known.state_trigger"
        assert row.parent_source_line == 2
        assert "common/company_types/known.txt:2" in row.scope_evidence
        assert not row.legal
        assert row.getter is None
        assert "表达式" in row.getter_note
        assert row.surface_id not in result.unknown_scopes
    payload = result.as_dict()
    serialized = [item for item in payload["surfaces"] if item["parent_field"]]
    assert len(serialized) == 3
    assert all(item["parent_source_line"] == 2 for item in serialized)


def test_company_state_trigger_parent_stays_pending_without_outer_scope_contract(tmp_path) -> None:
    game = _company_game(
        tmp_path,
        "ai_construction_targets = { building_known = { level = 5 "
        "state_trigger = { OR = { state_region = s:STATE_KNOWN } } } }",
    )
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.field.endswith(".state_trigger"))
    assert row.capability == "pending"
    assert row.actor_scope == row.target_scope == "unknown"
    assert getattr(row, "parent_field", None) is None
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    ("body", "doc"),
    [
        ("ai_construction_targets = { building_known = { level = 5 state_trigger = {} } }", ""),
        (
            "ai_construction_targets = { building_known = { level = 5 state_trigger = {} } }",
            COMPANY_DOC.replace("up to which level", "invented level semantics"),
        ),
        (
            "ai_construction_targets = { building_known = { level = 5 state_trigger = {} } }",
            COMPANY_DOC.replace("state_trigger = {", "invented_trigger = {"),
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = { value = 5 } "
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = -1 "
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = 1.5 "
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                'ai_construction_targets = { building_known = { level = "5" '
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } invented = yes } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_missing = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai = { ai_construction_targets = { building_known = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets != { building_known = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } } }"
            ),
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } state_trigger = {} } }"
            ),
            COMPANY_DOC,
        ),
        (
            "ai_construction_targets = { building_known = { level = 5 state_trigger = yes } }",
            COMPANY_DOC,
        ),
        (
            (
                "ai_construction_targets = { building_known = { level = 5 "
                "state_trigger = { state_region = s:STATE_KNOWN } } "
                "building_known = { level = 5 state_trigger = {} } }"
            ),
            COMPANY_DOC,
        ),
    ],
)
def test_company_construction_rejects_bad_documentation_parent_shape_and_level_type(
    tmp_path, body, doc
) -> None:
    result = discover(game=_company_game(tmp_path, body, doc))
    rows = [row for row in result.surfaces if row.definition == "company_known"]
    assert rows
    assert all(row.capability == "pending" and not row.legal for row in rows)
    assert all(getattr(row, "parent_field", None) is None for row in rows)


def _building_group_game(tmp_path: Path, entry: str, doc: str = BUILDING_GROUP_DOC) -> Path:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n" + doc + "}\n",
    )
    _write(
        game,
        "common/ai_strategies/active.txt",
        f"ai_strategy_active = {{ building_group_weights = {{ {entry} }} }}\n",
    )
    _write(game, "common/building_groups/known.txt", "bg_agriculture = {}\nbg_known = {}\n")
    return game


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Inf", "yes", '"1.25"', "{ value = 1.25 }"])
def test_building_group_weight_rejects_non_positive_or_non_scalar_values(tmp_path, value) -> None:
    game = _building_group_game(tmp_path, f"bg_known = {value}")
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.definition == "ai_strategy_active")
    assert row.capability == "pending"
    assert row.actor_scope == row.target_scope == "unknown"
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    ("entry", "doc"),
    [
        ("bg_missing = 1.25", BUILDING_GROUP_DOC),
        ("bg_known = 1.25", "building_group_weights = { bg_agriculture = 1.25 }\n"),
        ("bg_known = 1.25", BUILDING_GROUP_DOC.replace("default 1", "invented default")),
        (
            "bg_known = 1.25",
            BUILDING_GROUP_DOC.replace("several multiplications", "function additively"),
        ),
        (
            "bg_known = 1.25",
            BUILDING_GROUP_DOC.replace("building_group_weights =", "invented_weights ="),
        ),
        ("bg_known = 1.25 invented = 1.5", BUILDING_GROUP_DOC),
        ("bg_known = 1.25 { 1.5 }", BUILDING_GROUP_DOC),
        ("bg_known != 1.25", BUILDING_GROUP_DOC),
        ("bg_known = 1.25 bg_known = 1.5", BUILDING_GROUP_DOC),
    ],
)
def test_building_group_weight_requires_declared_group_documentation_and_map_shape(
    tmp_path, entry, doc
) -> None:
    game = _building_group_game(tmp_path, entry, doc)
    result = discover(game=game)
    rows = [row for row in result.surfaces if row.definition == "ai_strategy_active"]
    assert rows
    assert all(row.capability == "pending" and not row.legal for row in rows)


@pytest.mark.parametrize("value", ["0.25", "1.25", "1.5", "2.0"])
def test_building_group_weight_is_static_multiplier_without_runtime_target(tmp_path, value) -> None:
    game = _building_group_game(tmp_path, f"bg_known = {value}")
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.field == "building_group_weights.bg_known")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "global",
        "none",
        "building_group_score_multiplier",
        "indirect",
    )
    assert row.legal
    assert row.getter is None
    assert "不是国家脚本 getter" in row.getter_note
    assert row.surface_id not in result.unknown_scopes


@pytest.mark.parametrize(
    ("field", "description", "operation"),
    [
        (
            "pro_interest_groups",
            "Which IGs should the AI try to put in power",
            "preferred_government_interest_groups",
        ),
        (
            "anti_interest_groups",
            "Which IGs should the AI try to avoid putting in power",
            "avoided_government_interest_groups",
        ),
    ],
)
def test_static_interest_group_lists_do_not_become_runtime_government_scores(
    tmp_path, field, description, operation
) -> None:
    game = _game(tmp_path)
    _write(game, "common/interest_groups/known.txt", "ig_known = {}\n")
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        f"ai_strategy_default = {{\n# {description}\n"
        "# Using this value in other strategies will function additively\n"
        f"{field} = {{}}\n}}\n",
    )
    _write(
        game,
        "common/ai_strategies/active.txt",
        f"ai_strategy_active = {{ {field} = {{ ig_known }} }}\n",
    )
    result = discover(game=game)
    rows = [row for row in result.surfaces if row.field == field]
    assert len(rows) == 2
    assert all(
        (row.actor_scope, row.target_scope, row.operation, row.capability)
        == ("global", "none", operation, "indirect")
        for row in rows
    )
    assert all(row.getter is None and row.legal for row in rows)
    assert all("不是国家脚本 getter" in row.getter_note for row in rows)


@pytest.mark.parametrize(
    ("body", "description", "merge"),
    [
        (
            "pro_interest_groups = { ig_missing }",
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        (
            "pro_interest_groups = { ig_known value = 1 }",
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        (
            'pro_interest_groups = { "ig_known" }',
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        (
            "pro_interest_groups = { { ig_known } }",
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        (
            "pro_interest_groups = ig_known",
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        (
            "pro_interest_groups != { ig_known }",
            "Which IGs should the AI try to put in power",
            "additively",
        ),
        ("pro_interest_groups = { ig_known }", "Which IGs should the AI avoid", "additively"),
        (
            "pro_interest_groups = { ig_known }",
            "Which IGs should the AI try to put in power",
            "multiplicatively",
        ),
    ],
)
def test_static_interest_group_lists_reject_unknown_keys_shapes_and_neighbor_contracts(
    tmp_path, body, description, merge
) -> None:
    game = _game(tmp_path)
    _write(game, "common/interest_groups/known.txt", "ig_known = {}\n")
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        f"ai_strategy_default = {{\n# {description}\n"
        f"# Using this value in other strategies will function {merge}\n"
        "pro_interest_groups = {}\n}\n",
    )
    _write(game, "common/ai_strategies/active.txt", f"ai_strategy_active = {{ {body} }}\n")
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.definition == "ai_strategy_active")
    assert row.capability == "pending"
    assert not row.legal


def test_company_selection_trigger_records_operation_without_inventing_outer_scopes(
    tmp_path,
) -> None:
    game = _company_game(tmp_path, "ai_will_do = { always = yes }", COMPANY_SELECTION_DOC)
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.definition == "company_known")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "predicate",
        "pending",
    )
    assert row.scope_evidence
    assert row.getter is None
    assert not row.legal
    assert row.responsibility_step == "D0.03"
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    ("body", "doc"),
    [
        ("ai_will_do = 1", COMPANY_SELECTION_DOC),
        ("ai_will_do != {}", COMPANY_SELECTION_DOC),
        ("ai_will_do = {} ai_will_do = {}", COMPANY_SELECTION_DOC),
        ("ai_will_do = {}", COMPANY_SELECTION_DOC.replace("ai_will_do =", "possible =")),
        ("ai_will_do = {}", COMPANY_SELECTION_DOC.replace("If this trigger is true", "If true")),
        (
            "ai_will_do = {}",
            COMPANY_SELECTION_DOC.replace("ai_will_do = {", "possible = {").replace(
                "}\n}\n", "}\nai_will_do = {}\n}\n"
            ),
        ),
        ("ai_will_do = {}", COMPANY_SELECTION_DOC.replace("at least 'attainable'", "available")),
    ],
)
def test_company_selection_partial_contract_rejects_neighbor_docs_and_bad_fields(
    tmp_path, body, doc
) -> None:
    result = discover(game=_company_game(tmp_path, body, doc))
    row = next(row for row in result.surfaces if row.definition == "company_known")
    assert row.capability == "pending"
    assert row.operation == "declared_field"
    assert not row.scope_evidence
    assert not row.legal


def test_wargoal_scores_record_documented_targets_but_keep_missing_actor_pending(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n" + WARGOAL_SCORE_DOC + "}\n",
    )
    _write(
        game,
        "common/ai_strategies/active.txt",
        "ai_strategy_active = { wargoal_scores = { conquer_state = { value = 2 } } }\n",
    )
    result = discover(game=game)
    assert len(result.surfaces) == 4
    assert {row.field for row in result.surfaces} == {
        "wargoal_scores",
        "wargoal_scores.conquer_state",
    }
    for row in result.surfaces:
        assert row.actor_scope == "unknown"
        # Full map/entry identity and engine context must be proven together;
        # partial comments cannot license a parent container or numeric child.
        assert row.target_scope == "unknown"
        assert row.operation == "declared_field"
        assert row.scope_evidence == ()
        assert row.capability == "pending"
        assert row.getter is None
        assert not row.legal
        assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    "doc",
    [
        WARGOAL_SCORE_DOC.replace(
            "scope:target_country = wargoal target country", "target country"
        ),
        WARGOAL_SCORE_DOC.replace("(if any)", ""),
        WARGOAL_SCORE_DOC.replace("(if there is one)", ""),
        WARGOAL_SCORE_DOC.replace("wargoal_scores =", "secret_goal_scores ="),
        WARGOAL_SCORE_DOC.replace("How much should the AI value a wargoal", "How much to value"),
    ],
)
def test_wargoal_target_contract_does_not_transfer_neighbor_or_incomplete_comments(
    tmp_path, doc
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n" + doc + "}\n",
    )
    _write(
        game,
        "common/ai_strategies/active.txt",
        "ai_strategy_active = { wargoal_scores = { conquer_state = { value = 2 } } }\n",
    )
    result = discover(game=game)
    row = next(row for row in result.surfaces if row.definition == "ai_strategy_active")
    assert row.actor_scope == row.target_scope == "unknown"
    assert row.capability == "pending"
    assert not row.legal


@pytest.mark.parametrize(
    "body",
    [
        "wargoal_scores = 1",
        "wargoal_scores != { conquer_state = { value = 2 } }",
        "wargoal_scores = { conquer_state != { value = 2 } }",
        "wargoal_scores = { conquer_state = 2 }",
        "wargoal_scores = {} wargoal_scores = { conquer_state = { value = 2 } }",
        "wargoal_scores = { conquer_state = { value = 1 } conquer_state = { value = 2 } }",
    ],
)
def test_wargoal_partial_targets_require_ordinary_unique_map_and_expression(tmp_path, body) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n" + WARGOAL_SCORE_DOC + "}\n",
    )
    _write(game, "common/ai_strategies/active.txt", f"ai_strategy_active = {{ {body} }}\n")
    result = discover(game=game)
    rows = [row for row in result.surfaces if row.definition == "ai_strategy_active"]
    assert rows
    assert all(row.actor_scope == row.target_scope == "unknown" for row in rows)
    assert all(row.capability == "pending" and not row.legal for row in rows)


def test_strategy_partial_target_or_override_docs_do_not_invent_actor_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n" + STRATEGY_PARTIAL_DOC + "}\n",
    )
    _write(
        game,
        "common/ai_strategies/active.txt",
        "ai_strategy_active = { secret_goal_scores = { none = { score = { value = 2 } } } "
        "goods_stances = { small_arms = { stance = wants_high_supply } } }\n",
    )
    result = discover(game=game)
    rows = [item for item in result.surfaces if item.definition == "ai_strategy_active"]
    assert rows
    assert all(item.actor_scope == "unknown" for item in rows)
    assert all(item.capability == "pending" and not item.legal for item in rows)
    assert {item.operation for item in rows} == {"declared_field", "override_value"}
    assert {row.field for row in rows if row.operation == "declared_field"} == {
        "secret_goal_scores",
        "secret_goal_scores.none",
        "secret_goal_scores.none.score",
    }
