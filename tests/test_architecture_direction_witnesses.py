"""Separate S2 cost/saturation and S3 observed-world feedback witnesses.

Each expected output is handwritten. Actual release fields and generated
security helpers are interpreted independently, including complete native AST
preservation; existing card records cannot sign these direction requirements.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any, cast
from weakref import ref

import pytest
import test_architecture_explicit_witnesses as explicit
from test_architecture_all_consumer_witnesses import _json_observation, _units
from test_situated_joint_witnesses import _facts

from pdx import config, decision_adapters, decision_rules, decisions, distribution
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import audit, compiler, pdx_eval
from pdx.situated.native_treatments import _digest, _resolve
from pdx.situated.support_program import SupportObservation

pytest_plugins = ("tools.ci.architecture_witness_capture",)
pytestmark = pytest.mark.integration
RAIL = "common/buildings/11_private_infrastructure.txt"
RAIL_FIELD = ("building_railway", "ai_value")
RAIL_PM = "pm_active_building_railway_pm_early_trains"
HELPERS = "common/scripted_triggers/sitai_security_triggers.txt"
COST = "cost_saturation_unknown_counterexamples"
FEEDBACK = "observed_feedback_opportunity_cost"


def _release_candidate_evidence():
    policy, extensions, files = distribution.package_inputs(include_engineering_metadata=True)
    # Audit the complete real release output before retaining only the three
    # physical consumers used below. The raw engineering metadata dies here.
    continuous = audit._production_continuous_bindings(files)
    assert len(continuous) == 1
    return (
        policy,
        extensions,
        files[explicit.SOURCE],
        {path: files[path] for path in (RAIL, HELPERS)},
        continuous[0].writer.program,
    )


def _disabled_candidate_evidence(policy, extensions):
    disabled = decisions.build(
        replace(policy, enabled=False),
        extensions=replace(
            extensions,
            reform_enabled=False,
            market_enabled=False,
            security_enabled=False,
            economy_enabled=False,
            diplomacy_enabled=False,
        ),
    )
    # Preserve the original optional railway fallback without carrying unused
    # disabled output or its metadata into the reference-model construction.
    return disabled[explicit.SOURCE], {RAIL: disabled[RAIL]} if RAIL in disabled else {}


@pytest.fixture(scope="module")
def candidate():
    policy, extensions, built, files, support = _release_candidate_evidence()
    disabled, disabled_files = _disabled_candidate_evidence(policy, extensions)
    model = compiler.load_model()
    raw = dict(decision_adapters.load().policies)[RAIL]
    compiled = compiler.compile_policy(raw, RAIL, model)[0]
    original = (config.GAME / RAIL).read_text(encoding="utf-8-sig")
    return {
        "built": built,
        "files": files,
        "baseline": decisions.baseline_path().read_text(encoding="utf-8"),
        "disabled": disabled,
        "disabled_files": disabled_files,
        "model": model,
        "support": support,
        "raw": raw,
        "rail_policy": compiled,
        "rail_original": original,
    }


@pytest.mark.unit
@pytest.mark.parametrize("disabled_rail", [False, True])
def test_candidate_releases_full_outputs_before_the_next_heavy_stage(
    monkeypatch, tmp_path, disabled_rail
):
    """Both complete builds/audit execute without retaining either large mapping."""

    class Output(dict):
        pass

    class MetadataText(str):
        pass

    package = decisions.PackageContract(
        "3.3.0", "released", "vanilla-1.15.1", "new-game-only", ("windows",), "fixture"
    )
    policy = decisions.Policy(True, "1.15.1", "baseline", 1, 1, 1, 1, 1, package)
    extensions = decisions.Extensions(
        reform_enabled=True,
        market_enabled=True,
        security_enabled=True,
        economy_enabled=True,
        diplomacy_enabled=True,
    )
    references: dict[str, Any] = {}
    support = object()
    raw = object()
    original = tmp_path / RAIL
    original.parent.mkdir(parents=True)
    original.write_text("actual native rail", encoding="utf-8-sig")
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("actual baseline", encoding="utf-8")

    def release(**kwargs):
        assert kwargs == {"include_engineering_metadata": True}
        metadata = MetadataText("complete engineering metadata")
        output = Output(
            {
                explicit.SOURCE: "actual production",
                RAIL: "actual production rail",
                HELPERS: "actual production helpers",
                ".metadata/metadata.json": metadata,
                "unused.txt": "full production output",
            }
        )
        references["release"] = ref(output)
        references["raw_metadata"] = ref(metadata)
        return policy, extensions, output

    def continuous(output):
        assert output is references["release"]()
        assert output[".metadata/metadata.json"] == "complete engineering metadata"
        assert output["unused.txt"] == "full production output"
        references["audited"] = True
        return (SimpleNamespace(writer=SimpleNamespace(program=support)),)

    def disabled(selected, *, extensions):
        assert references["release"]() is None, "full release output survives into disabled build"
        assert references["raw_metadata"]() is None, "raw metadata survives into disabled build"
        assert references["audited"] is True
        assert selected == replace(policy, enabled=False)
        assert all(
            getattr(extensions, name) is False
            for name in (
                "reform_enabled",
                "market_enabled",
                "security_enabled",
                "economy_enabled",
                "diplomacy_enabled",
            )
        )
        output = Output({explicit.SOURCE: "actual disabled", "unused.txt": "full disabled output"})
        if disabled_rail:
            output[RAIL] = "actual disabled rail"
        references["disabled"] = ref(output)
        return output

    def model():
        assert references["release"]() is None, "full release output survives into model load"
        assert references["disabled"]() is None, "full disabled output survives into model load"
        return "actual model"

    def compile_policy(selected, path, selected_model):
        assert selected is raw
        assert path == RAIL
        assert selected_model == "actual model"
        return ("actual compiled rail",)

    monkeypatch.setattr(distribution, "package_inputs", release)
    monkeypatch.setattr(audit, "_production_continuous_bindings", continuous)
    monkeypatch.setattr(decisions, "build", disabled)
    monkeypatch.setattr(compiler, "load_model", model)
    monkeypatch.setattr(compiler, "compile_policy", compile_policy)
    monkeypatch.setattr(decision_adapters, "load", lambda: SimpleNamespace(policies=((RAIL, raw),)))
    monkeypatch.setattr(decisions, "baseline_path", lambda: baseline)
    monkeypatch.setattr(config, "GAME", tmp_path)
    result = cast("Any", candidate).__wrapped__()
    assert result == {
        "built": "actual production",
        "files": {RAIL: "actual production rail", HELPERS: "actual production helpers"},
        "baseline": "actual baseline",
        "disabled": "actual disabled",
        "disabled_files": {RAIL: "actual disabled rail"} if disabled_rail else {},
        "model": "actual model",
        "support": support,
        "raw": raw,
        "rail_policy": "actual compiled rail",
        "rail_original": "actual native rail",
    }
    assert result["disabled_files"].get(RAIL, result["rail_original"]) == (
        "actual disabled rail" if disabled_rail else "actual native rail"
    )


def _record(witness, requirement, consumer, role, observations, expected, reference, actual):
    assert expected == reference == actual
    assert requirement in {COST, FEEDBACK}
    witness(
        evidence_ids=["a2.direction." + requirement],
        case_id=f"direction.{requirement}.{role}.{observations.get('case', 'boundary')}",
        role=role,
        input={"requirement": requirement, **_json_observation(observations)},
        expected=expected,
        reference=reference,
        generated=actual,
        production=[
            "mod/decisions/adapters.toml",
            "mod/decisions/extensions.toml",
            "src/pdx/situated/compiler.py",
            "src/pdx/situated/support_program.py",
            "src/pdx/decision_security.py",
            "src/pdx/decision_adapters.py",
            "src/pdx/decisions.py",
            "src/pdx/distribution.py",
        ],
        consumers=[consumer],
    )


def _node(text, definition, field):
    parsed = parse_text(text)
    assert not parsed.errors
    node, state = _resolve(parsed.root, definition, field)
    assert state == "found"
    assert node is not None
    return node


def _rail_overlay(text):
    import re

    matches = re.findall(
        r"(?ms)^\s*# SITAI BEGIN information:building_railway.ai_value\n(.*?)^\s*# SITAI END information:building_railway.ai_value\n",
        text,
    )
    assert len(matches) == 1
    return matches[0]


def _rail_native(text):
    import re

    stripped = re.sub(
        r"(?ms)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
    )
    return _digest(_node(stripped, *RAIL_FIELD).value)


def _rail_values(policy, changes):
    # Explicit physical observations: no active PM unless the scenario says so.
    values = {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}
    values.update(changes)
    return values


def test_s2_actual_railway_costs_saturation_and_unknowns_have_distinct_six_roles(
    candidate, architecture_witness
):
    built = candidate["files"][RAIL]
    installed = (decisions.product_path() / RAIL).read_text(encoding="utf-8-sig")
    consumer = {
        "path": (decisions.product_path().relative_to(config.REPO) / RAIL).as_posix(),
        "definition": RAIL_FIELD[0],
        "field": RAIL_FIELD[1],
    }
    assert _digest(_node(installed, *RAIL_FIELD).value) == _digest(_node(built, *RAIL_FIELD).value)
    overlay = _rail_overlay(installed)
    policy = candidate["rail_policy"]
    need = {"state_infrastructure": -1}
    prepared = {**need, RAIL_PM: True}
    coal = {"state_owner_coal_balance": -1, "state_owner_coal_price": 0.6}
    engines = {"state_owner_engines_balance": -1, "state_owner_engines_price": 0.6}
    # Same demand group chooses 1.20 over 1.10. Two real goods deduct .20
    # each from the neutral envelope rather than multiplying .8*.8.
    cases = (
        ("positive", "repair_without_existing_recipe", {**need, RAIL_PM: None}, 1.10),
        ("positive", "observed_recipe_is_prepared", prepared, 1.20),
        ("negative", "one_actual_input_cost", {**prepared, **coal}, 0.90),
        ("negative", "both_inputs_independent", {**prepared, **coal, **engines}, 0.70),
        (
            "negative",
            "default_cost_also_participates",
            {**prepared, **coal, **engines, "state_owner_default": True},
            0.55,
        ),
        (
            "negative",
            "repair_need_removed_final_floor",
            {**prepared, **coal, **engines, "state_owner_default": True, "state_infrastructure": 0},
            0.50,
        ),
        (
            "unknown",
            "one_unknown_cost_keeps_other_and_default",
            {
                **prepared,
                **coal,
                **engines,
                "state_owner_default": True,
                "state_owner_coal_balance": None,
            },
            0.75,
        ),
        (
            "unknown",
            "unknown_pm_does_not_fabricate_recipe_costs",
            {**prepared, **coal, **engines, RAIL_PM: None},
            1.10,
        ),
        (
            "unknown",
            "unknown_preparation_keeps_local_need",
            {**prepared, "state_owner_coal_balance": None},
            1.10,
        ),
        (
            "negative",
            "different_recipe_does_not_pay_coal",
            {**need, "pm_active_building_railway_pm_electric_trains": True, **coal},
            1.20,
        ),
        (
            "positive",
            "transport_preparation_and_observed_postwar_repair_share_final_ceiling",
            {
                **prepared,
                "state_local_transportation_price": 0.6,
                "state_devastation": 0.3,
                "state_owner_war": False,
                "state_owner_war_defeat": True,
            },
            1.45,
        ),
    )
    for role, label, changes, expected in cases:
        values = _rail_values(candidate["raw"], changes)
        engine = _facts(candidate["raw"], values)
        reference = decision_rules.evaluate(policy, values, is_ai=True).get(".".join(RAIL_FIELD))
        actual = pdx_eval.select(overlay, engine)
        assert reference is not None
        assert actual.operation == "multiply"
        _record(
            architecture_witness,
            COST,
            consumer,
            role,
            {"case": label, "values": values, "engine": engine},
            _units("multiply", expected),
            _units("multiply", reference[1]),
            _units("multiply", actual.delta),
        )
    # Explicit parsed final floor and ceiling, after every contribution.
    parsed = parse_text(overlay)
    branch = parsed.root.first("if")
    assert branch is not None
    assert isinstance(branch.value, Block)
    numeric = branch.value.first("multiply")
    assert numeric is not None
    assert isinstance(numeric.value, Block)
    final = list(numeric.value.assignments())[-2:]
    # Local transport demand and postwar repair now have independent benefits;
    # their joint consumer keeps one final .50..1.45 envelope.
    assert [(item.key, _scalar(item)) for item in final] == [("min", "0.5"), ("max", "1.45")]
    positive = _rail_values(candidate["raw"], prepared)
    player = pdx_eval.select(overlay, _facts(candidate["raw"], positive, is_ai=False))
    _record(
        architecture_witness,
        COST,
        consumer,
        "player",
        {"is_ai": False, "values": positive},
        {"contribution": False},
        {"contribution": bool(decision_rules.evaluate(policy, positive, is_ai=False))},
        {"contribution": player.operation is not None},
    )
    disabled = candidate["disabled_files"].get(RAIL, candidate["rail_original"])
    _record(
        architecture_witness,
        COST,
        consumer,
        "disabled",
        {"enabled_domains": []},
        {"contribution": False, "native_ast": _rail_native(candidate["rail_original"])},
        {
            "contribution": bool(
                decision_rules.evaluate(policy, positive, is_ai=True, enabled_domains=frozenset())
            ),
            "native_ast": _rail_native(candidate["rail_original"]),
        },
        {
            "contribution": "# SITAI BEGIN information:building_railway.ai_value" in disabled,
            "native_ast": _rail_native(disabled),
        },
    )
    _record(
        architecture_witness,
        COST,
        consumer,
        "native_tail",
        {"remove_only_declared_overlays": True},
        {"complete_native_ast": _rail_native(candidate["rail_original"])},
        {"complete_native_ast": _rail_native(built)},
        {"complete_native_ast": _rail_native(installed)},
    )


def _scalar(item):
    assert isinstance(item.value, Scalar)
    return item.value.unquoted


def _all(states):
    return False if any(state is False for state in states) else None if None in states else True


def _any(states):
    return True if any(state is True for state in states) else None if None in states else False


def _helper_condition(block, current, world, parameters):
    """Strict independent interpreter of the two actual helper ASTs only.

    No production helper boolean is supplied as input. Collections contain
    real treaty/article observations; wrong binds/targets remain distinct.
    Unknown collections or member observations remain three-valued.
    """
    states = []
    for item in block.items:
        assert isinstance(item, Assignment)
        assert item.op == "="
        assert item.prefix is None
        key = item.key
        if key in {"any_scope_treaty", "any_scope_article"}:
            assert isinstance(item.value, Block)
            members = current.get(key)
            state = (
                None
                if members is None
                else _any(
                    [_helper_condition(item.value, member, world, parameters) for member in members]
                )
            )
        elif key == "OR":
            assert isinstance(item.value, Block)
            state = _any(
                [
                    _helper_condition(Block([child]), current, world, parameters)
                    for child in item.value.items
                ]
            )
        elif key in {"binds", "has_type", "is_adjacent_to_country"}:
            expected = parameters.get(_scalar(item), _scalar(item))
            actual = current.get(key)
            state = None if actual is None else expected in actual
        elif key == "play_participant_has_war_goal_of_type_against":
            assert isinstance(item.value, Block)
            expected = {
                child.key: parameters.get(_scalar(child), _scalar(child))
                for child in item.value.assignments()
            }
            assert set(expected) == {"type", "target"}
            goals = current.get(key)
            state = None if goals is None else (expected["type"], expected["target"]) in goals
        elif key == "$OPPONENT$":
            assert isinstance(item.value, Block)
            opponent = world.get(parameters[key])
            state = (
                None
                if opponent is None
                else _helper_condition(item.value, opponent, world, parameters)
            )
        else:
            raise AssertionError(f"unregistered security-helper statement: {key}")
        states.append(state)
    return _all(states)


def _world(
    *,
    treaty=False,
    threat=False,
    adjacent=True,
    partner="scope:country",
    opponent="scope:enemy_country",
    unknown_treaty=False,
    unknown_goals=False,
    wrong_treaty=False,
    wrong_goal=False,
):
    other = opponent
    treaties = []
    if treaty or wrong_treaty:
        treaties.append(
            {
                "binds": [other if wrong_treaty else partner],
                "any_scope_article": [{"has_type": ["defensive_pact"]}],
            }
        )
    # A trade article cannot count as a defensive commitment even when bound.
    treaties.append({"binds": [partner], "any_scope_article": [{"has_type": ["trade_agreement"]}]})
    goals = [("conquer_state", other if wrong_goal else partner)] if threat or wrong_goal else []
    return {
        "ROOT": {
            "any_scope_treaty": None if unknown_treaty else treaties,
            "is_adjacent_to_country": [partner] if adjacent else [],
        },
        partner: {"play_participant_has_war_goal_of_type_against": []},
        opponent: {
            "play_participant_has_war_goal_of_type_against": None if unknown_goals else goals
        },
    }


def _world_observation(
    helpers,
    world,
    *,
    initiator,
    country_dependence,
    enemy_dependence,
    expected_commitment,
    expected_neighbor,
    is_ai=True,
):
    partner, opponent = (
        ("scope:enemy_country", "scope:country")
        if initiator
        else ("scope:country", "scope:enemy_country")
    )
    parameters = {"$PARTNER$": partner, "$OPPONENT$": opponent}
    commitment = helpers.first("sitai_defense_commitment")
    neighbor = helpers.first("sitai_neighbor_defense")
    assert commitment is not None
    assert neighbor is not None
    assert isinstance(commitment.value, Block)
    assert isinstance(neighbor.value, Block)
    actual_commitment = _helper_condition(commitment.value, world["ROOT"], world, parameters)
    actual_neighbor = _helper_condition(neighbor.value, world["ROOT"], world, parameters)
    assert actual_commitment is expected_commitment
    assert actual_neighbor is expected_neighbor
    return SupportObservation(
        is_ai,
        True,
        initiator,
        country_dependence,
        enemy_dependence,
        actual_commitment,
        actual_neighbor,
    )


def test_s3_world_feedback_recomputes_completed_commitments_threats_and_opportunity_cost(
    candidate, architecture_witness
):
    field = "diplomatic_play_support"
    installed = explicit._disk(candidate, field)
    overlay = explicit._overlay(installed, field)
    helper_built = candidate["files"][HELPERS]
    helper_disk = (decisions.product_path() / HELPERS).read_text(encoding="utf-8-sig")
    parsed = parse_text(helper_disk)
    assert not parsed.errors
    assert _digest(parsed.root) == _digest(parse_text(helper_built).root)
    consumer = {"path": explicit.PATH, "definition": explicit.DEFINITION, "field": field}
    # Market opportunity cost is always (country-enemy)*5. Changes below are
    # current world observations, not a remembered card/route/completion flag.
    cases = (
        ("negative", "before_defensive_treaty_completed", _world(), False, 1, 3, False, False, -10),
        (
            "positive",
            "after_defensive_treaty_completed",
            _world(treaty=True),
            False,
            1,
            3,
            True,
            False,
            15,
        ),
        (
            "positive",
            "neighbor_faces_real_conquest",
            _world(threat=True),
            False,
            1,
            3,
            False,
            True,
            5,
        ),
        (
            "negative",
            "threat_removed_recomputes",
            _world(threat=False),
            False,
            1,
            3,
            False,
            False,
            -10,
        ),
        (
            "negative",
            "wrong_partner_treaty_and_goal",
            _world(wrong_treaty=True, wrong_goal=True),
            False,
            1,
            3,
            False,
            False,
            -10,
        ),
        (
            "negative",
            "conquest_without_adjacency",
            _world(threat=True, adjacent=False),
            False,
            1,
            3,
            False,
            False,
            -10,
        ),
        (
            "unknown",
            "unknown_commitment_keeps_known_threat",
            _world(threat=True, unknown_treaty=True),
            False,
            1,
            3,
            None,
            True,
            5,
        ),
        (
            "unknown",
            "unknown_threat_keeps_known_commitment",
            _world(treaty=True, unknown_goals=True),
            False,
            1,
            3,
            True,
            None,
            15,
        ),
        (
            "unknown",
            "unknown_economics_keeps_real_threat",
            _world(threat=True),
            False,
            None,
            3,
            False,
            True,
            15,
        ),
        (
            "positive",
            "changed_market_dependence_revalues_cost",
            _world(treaty=True),
            False,
            3,
            1,
            True,
            False,
            35,
        ),
        (
            "negative",
            "initiator_opponent_defense_direction",
            _world(threat=True, partner="scope:enemy_country", opponent="scope:country"),
            True,
            1,
            3,
            False,
            True,
            -25,
        ),
    )
    for role, label, world, initiator, country, enemy, commitment, neighbor, expected in cases:
        observed = _world_observation(
            parsed.root,
            world,
            initiator=initiator,
            country_dependence=country,
            enemy_dependence=enemy,
            expected_commitment=commitment,
            expected_neighbor=neighbor,
        )
        engine = explicit._support_facts(observed)
        reference = candidate["support"].evaluate(observed).value
        actual = pdx_eval.select(overlay, engine)
        assert actual.operation == "add"
        _record(
            architecture_witness,
            FEEDBACK,
            consumer,
            role,
            {
                "case": label,
                "world": world,
                "observation": asdict(observed),
                "engine": engine,
                "helper_sha256": hashlib.sha256(helper_disk.encode()).hexdigest(),
            },
            _units("add", expected),
            _units("add", reference),
            _units("add", actual.delta),
        )
    player = SupportObservation(False, True, False, 3, 1, True, False)
    _record(
        architecture_witness,
        FEEDBACK,
        consumer,
        "player",
        {"observation": asdict(player)},
        {"contribution": False},
        {"contribution": bool(candidate["support"].evaluate(player).value)},
        {
            "contribution": pdx_eval.select(overlay, explicit._support_facts(player)).operation
            is not None
        },
    )
    baseline = explicit._field(candidate["baseline"], field)
    _record(
        architecture_witness,
        FEEDBACK,
        consumer,
        "disabled",
        {"enabled_modules": []},
        {"contribution": False, "native_ast": baseline},
        {
            "contribution": bool(
                decisions.diplomatic_play_support_addition(decisions.Extensions())
            ),
            "native_ast": baseline,
        },
        {
            "contribution": f"# SITAI BEGIN {field}\n" in candidate["disabled"],
            "native_ast": explicit._field(candidate["disabled"], field),
        },
    )
    _record(
        architecture_witness,
        FEEDBACK,
        consumer,
        "native_tail",
        {"remove_only_declared_overlays": True},
        {"complete_native_ast": baseline},
        {
            "complete_native_ast": explicit._field(
                explicit._MARKED.sub("\n", candidate["built"]), field
            )
        },
        {"complete_native_ast": explicit._field(explicit._MARKED.sub("\n", installed), field)},
    )
