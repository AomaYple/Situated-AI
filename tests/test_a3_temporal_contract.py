"""C7: execute parsed production guards over independently authored time traces.

The local expiry clock witnesses the declared days contract; it is not a game
clock, save/reload test or a claim about engine scheduling/performance.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest
from test_observed_relations_feedback import _inputs
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_rules, decisions
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import commitment, compiler, pdx_eval, state
from pdx.situated.schema import EvidenceValue

pytestmark = pytest.mark.integration
INFO = "mod/decisions/information.toml"
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
BALANCE = "economic_vs_government_spending_balance"
WAR_SOURCE = "common/on_actions/00_code_on_actions.txt"


def _block(parent: Block, name: str) -> Block:
    rows = parent.all(name)
    assert len(rows) == 1
    assert isinstance(rows[0].value, Block)
    return rows[0].value


def _scalar(parent: Block, name: str) -> str:
    rows = parent.all(name)
    assert len(rows) == 1
    assert isinstance(rows[0].value, Scalar)
    return rows[0].value.unquoted


def _walk(block: Block, path: tuple[str, ...] = ()):
    for node in block.assignments():
        current = (*path, node.key)
        yield current, node
        if isinstance(node.value, Block):
            yield from _walk(node.value, current)


def _tree(node):
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(child) for child in node.items)


@pytest.fixture(scope="module")
def fiscal():
    policy = decisions.load()
    triggers = parse_text(decisions.triggers(policy)).root
    effect = _block(parse_text(decisions.effects(policy)).root, "sitai_update_fiscal")
    for _relative, text in (
        ("common/scripted_triggers/sitai_fiscal_triggers.txt", decisions.triggers(policy)),
        ("common/scripted_effects/sitai_fiscal_effects.txt", decisions.effects(policy)),
        ("common/on_actions/sitai_fiscal_on_actions.txt", decisions.on_actions(policy)),
    ):
        # These remain an executable compatibility API. Current joint output
        # no longer deploys a state updater without a score consumer.
        assert not parse_text(text).errors
    return policy, triggers, effect


def _fiscal_facts(triggers, *, active=False, **changes):
    facts: dict[str, Any] = {
        "is_ai": True,
        "in_default": False,
        "taking_loans": True,
        "credit": 100,
        "weeks_until_bankruptcy": 25,
        "is_at_war": True,
        "is_diplomatic_play_initiator": False,
        "is_diplomatic_play_target": False,
        "is_diplomatic_play_committed_participant": False,
        "is_diplomatic_play_undecided_participant": False,
        "has_variable": {(("argument", decisions.RISK_VAR),): active},
    }
    facts.update(changes)
    for name in ("sitai_fiscal_entry", "sitai_fiscal_hold", "sitai_external_exposure"):
        facts[name] = pdx_eval.condition(_block(triggers, name), facts)
    return facts


def _update(effect: Block, facts, day: int) -> int | None:
    """Interpret only the exact generated if/set/else/remove expiry contract."""
    branch = _block(effect, "if")
    if pdx_eval.condition(_block(branch, "limit"), facts) is True:
        writer = _block(branch, "set_variable")
        assert _scalar(writer, "name") == "sitai_fiscal_risk"
        assert _scalar(writer, "value") == "1"
        return day + int(_scalar(writer, "days"))
    assert _scalar(_block(effect, "else"), "remove_variable") == "sitai_fiscal_risk"
    return None


@pytest.mark.parametrize(
    ("active", "changes", "expected"),
    [
        (False, {"weeks_until_bankruptcy": 25.999}, True),
        (False, {"weeks_until_bankruptcy": 26}, False),
        (True, {"weeks_until_bankruptcy": 26}, True),
        (True, {"weeks_until_bankruptcy": 51.999}, True),
        (True, {"weeks_until_bankruptcy": 52}, False),
        (False, {"in_default": True, "credit": None, "weeks_until_bankruptcy": None}, True),
        (True, {"weeks_until_bankruptcy": None}, False),
        (True, {"credit": None}, False),
        (True, {"credit": 0}, False),
        (True, {"weeks_until_bankruptcy": -1}, False),
        (True, {"taking_loans": False}, False),
        (True, {"is_ai": False, "in_default": True}, False),
    ],
)
def test_real_fiscal_update_ast_has_asymmetric_entry_exit_and_unknown_cleanup(
    fiscal, active, changes, expected
):
    policy, triggers, effect = fiscal
    facts = _fiscal_facts(triggers, active=active, **changes)
    assert _update(effect, facts, 100) == (162 if expected else None)
    if facts["is_ai"]:
        assert (
            decisions.risk_next(
                active,
                in_default=facts["in_default"],
                taking_loans=facts["taking_loans"],
                credit=facts["credit"],
                weeks=facts["weeks_until_bankruptcy"],
                policy=policy,
            )
            is expected
        )


def test_refresh_trace_stops_at_ttl_and_current_hold_never_trusts_an_old_flag(fiscal):
    policy, triggers, effect = fiscal
    assert (policy.entry_weeks, policy.exit_weeks, policy.ttl_days) == (26, 52, 62)
    expires = _update(effect, _fiscal_facts(triggers), 0)
    assert expires == 62
    # A legal monthly refresh renews the same slot; no counter or new state.
    expires = _update(effect, _fiscal_facts(triggers, active=True, weeks_until_bankruptcy=40), 30)
    assert expires == 92
    for day, expected in ((91, True), (92, False), (1000, False)):
        active = expires is not None and day < expires
        facts = _fiscal_facts(triggers, active=active, weeks_until_bankruptcy=40)
        assert pdx_eval.condition(_block(triggers, decisions.ACTIVE_TRIGGER), facts) is expected
    # Before any update, recovery, unknown inputs or player control suppresses
    # the actual consumer guard even if the engine variable has not expired.
    for changes in (
        {"weeks_until_bankruptcy": 52},
        {"weeks_until_bankruptcy": None},
        {"is_ai": False},
        {"is_at_war": False},
    ):
        facts = _fiscal_facts(triggers, active=True, **changes)
        assert pdx_eval.condition(_block(triggers, decisions.ACTIVE_TRIGGER), facts) is not True
    assert (
        _update(effect, _fiscal_facts(triggers, active=True, weeks_until_bankruptcy=52), 31) is None
    )
    # Re-entry after recovery is legal; the old crisis never blacklists it.
    assert _update(effect, _fiscal_facts(triggers, in_default=True), 200) == 262


def test_fiscal_refresh_is_bound_to_actual_vanilla_hooks_and_disable_has_no_reader(fiscal):
    policy, _, _ = fiscal
    hooks = parse_text(decisions.on_actions(policy)).root
    expected = {"on_monthly_pulse_country", "on_country_default", "on_country_no_longer_default"}
    assert {row.key for row in hooks.assignments()} == {*expected, "sitai_fiscal_update"}
    native = parse_text((config.GAME / WAR_SOURCE).read_text(encoding="utf-8-sig")).root
    for name in expected:
        assert native.first(name) is not None
        child = _block(_block(hooks, name), "on_actions")
        assert [item.unquoted for item in child.items if isinstance(item, Scalar)] == [
            "sitai_fiscal_update"
        ]
    assert (
        _scalar(_block(_block(hooks, "sitai_fiscal_update"), "effect"), "sitai_update_fiscal")
        == "yes"
    )
    disabled = replace(policy, enabled=False)
    assert (
        decisions.triggers(disabled)
        == decisions.effects(disabled)
        == decisions.on_actions(disabled)
        == ""
    )
    assert policy.package.save_compatibility == "new-game-only"


def test_fiscal_legacy_hysteresis_path_is_executable_but_current_joint_consumers_reread_world(
    fiscal,
):
    policy, triggers, _ = fiscal
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    legacy = decisions.patch_default(baseline, policy)
    begin = legacy.index("# SITAI BEGIN diplomatic_play_neutrality")
    end = legacy.index("# SITAI END diplomatic_play_neutrality", begin)
    body = "\n".join(legacy[begin:end].splitlines()[1:])
    # Legacy entrypoint keeps its authored 25-point addition and consumes the
    # finite risk flag; distinguish this from the current joint 8/6 program.
    script = "# ACTION legacy_temporal [fiscal]; isolated actual legacy insertion\n" + body
    for active, weeks, expected in ((True, 40, 25), (False, 40, 0), (True, 52, 0), (True, None, 0)):
        facts = _fiscal_facts(triggers, active=active, weeks_until_bankruptcy=weeks)
        facts[decisions.ACTIVE_TRIGGER] = pdx_eval.condition(
            _block(triggers, decisions.ACTIVE_TRIGGER), facts
        )
        assert pdx_eval.select(script, {"ROOT": facts}).delta == expected
    current = (config.REPO / "mod" / STRATEGY).read_text(encoding="utf-8")
    assert decisions.ACTIVE_TRIGGER not in current
    assert decisions.RISK_VAR not in current
    joint = pdx_eval.marked_block(current, "joint_fiscal_neutrality")
    # Independent crisis reasons: default 8 and war 6 join once capped at 10.
    # An unexpired obsolete variable cannot preserve a recovered preference.
    for default, war, expected in (
        (True, False, 8),
        (True, True, 10),
        (False, True, 6),
        (None, True, 6),
        (False, False, 0),
        (True, False, 8),
    ):
        facts = {
            "is_ai": True,
            "in_default": default,
            "is_at_war": war,
            "has_variable": {(("argument", decisions.RISK_VAR),): True},
        }
        assert pdx_eval.select(joint, {"ROOT": facts}).delta == expected


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    adapters = decision_adapters.load()
    native = decision_adapters.read_inputs(adapters)[WAR_SOURCE]
    assert hashlib.sha256(native.encode()).hexdigest() == dict(adapters.sources)[WAR_SOURCE]
    policy, _ = compiler.compile_policy(decision_rules.load(), INFO, model)
    generated = (config.REPO / "mod" / STRATEGY).read_text(encoding="utf-8")
    actual = pdx_eval.marked_block(generated, "joint_economic_balance")
    lowered = compiler.strategy_overlay(model)[BALANCE]
    assert _tree(parse_text(actual).root) == _tree(parse_text(lowered).root)
    return model, policy, native, generated, actual


def test_native_defeat_memory_has_two_real_country_writers_and_finite_lifetime(production):
    _, policy, native, _, _ = production
    memory = next(reader for reader in policy.readers if reader.key == "war_defeat")
    assert (memory.engine, memory.argument, memory.scope, memory.path) == (
        "has_variable",
        "recently_lost_war",
        "root",
        (),
    )
    parsed = parse_text(native)
    writers = []
    for path, node in _walk(parsed.root):
        if (
            node.key == "set_variable"
            and isinstance(node.value, Block)
            and _scalar(node.value, "name") == "recently_lost_war"
        ):
            writers.append((path, node))
    assert {path for path, _ in writers} == {
        ("on_capitulation", "effect", "set_variable"),
        ("on_lost_war", "effect", "if", "set_variable"),
    }
    assert len(writers) == 2
    for path, node in writers:
        assert isinstance(node.value, Block)
        assert {_scalar(node.value, key) for key in ("days", "value")} == {"1825", "yes"}
        hook = parsed.root.first(path[0])
        assert hook is not None
        roots = [
            text.strip()
            for line, text in parsed.comments
            if line < hook.line and text.strip().startswith("# Root =")
        ]
        assert roots[-1] == "# Root = Country"
    lost = _block(_block(_block(parsed.root, "on_lost_war"), "effect"), "if")
    assert _scalar(_block(lost, "limit"), "exists") == "scope:victim_of_wargoal"


def test_actual_reconstruction_consumer_exits_at_native_expiry_and_reenters(production):
    _, policy, _, generated, _ = production
    text = _overlay(generated, "wanted_construction_output")
    # The event writes at day 10. Engine declared days imply expiry at 1835;
    # after expiry the native has_variable read is false, not stale true.
    for day, observed, expected in (
        (10, True, 1.12),
        (1834, True, 1.12),
        (1835, False, 1),
        (2000, None, 1),
        (3000, True, 1.12),
    ):
        values: dict[str, object] = {
            "war_defeat": observed,
            "default": False,
            "loans": False,
            "population": 100,
            "cost_country_population": 100,
            "net_surplus": 0,
            "industrial_route": False,
            "resource_route": False,
        }
        assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(
            "wanted_construction_output", ("", 1)
        )[1] == pytest.approx(expected), day
        assert pdx_eval.select(text, _facts(policy, values)).delta == pytest.approx(expected), day


def test_same_actual_relation_script_recomputes_gain_exit_unknown_and_recovery(production):
    model, _, _, _, actual = production
    # Independent hand sums: industry .15, low-literacy education -.10 and
    # demand -.025; observed school channel -.025. At literacy saturation,
    # education exits, industry .15 gains the distinct knowledge edge +.025.
    trace: list[tuple[dict[str, object], float]] = [
        ({}, 0.025),
        ({"current_public_schools": True, "schools_present": True}, 0),
        ({"current_public_schools": None, "schools_present": True}, 0.025),
        ({"current_public_schools": False, "schools_present": True}, 0.025),
        (
            {
                "current_public_schools": True,
                "schools_present": True,
                "literacy_low": False,
                "literacy_ready": True,
                "coord_need_education": False,
            },
            0.175,
        ),
        (
            {
                "current_public_schools": True,
                "schools_present": True,
                "literacy_low": None,
                "literacy_ready": None,
                "coord_need_education": None,
            },
            0.15,
        ),
        ({"current_public_schools": True, "schools_present": True}, 0),
        ({}, 0.025),
    ]
    for changes, expected in trace:
        values, facts = _inputs(changes)
        assert compiler.evaluate_actions(model, values, is_ai=True).get(BALANCE, ("", 0))[
            1
        ] == pytest.approx(expected)
        assert pdx_eval.select(actual, {"ROOT": facts}).delta == pytest.approx(expected)
    assert compiler.evaluate_actions(model, {}, is_ai=True).get(BALANCE, ("", 0))[1] == 0
    assert compiler.evaluate_actions(model, {}, is_ai=True, enabled_consumer_fields=set()) == {}


@pytest.mark.parametrize("stale", [False, True])
def test_reference_snapshot_expiry_preserves_provenance_but_never_drives_a_new_known_signal(stale):
    evidence = {
        "debt_ratio": EvidenceValue(
            "debt_ratio", 0.1, True, stale=stale, provenance="old-save-snapshot"
        ),
        "default": EvidenceValue("default", False, True),
        "war": EvidenceValue("war", False, True),
        "income": EvidenceValue("income", 100, True),
    }
    typed = state.derive_typed(evidence)
    foundation = next(signal for signal in typed.capacities if signal.id == "layer_foundation")
    assert foundation.known is (not stale)
    assert foundation.value is (None if stale else True)
    assert foundation.stale is stale
    debt = commitment.derive(
        evidence, {"debt": {"source_fact": "debt_ratio", "unit": "debt_to_credit_ratio"}}
    )[0]
    assert debt.known is (not stale)
    assert debt.value == (None if stale else 0.1)
    assert debt.stale is stale
    # A fresh re-read clears this snapshot condition; there is no learned ban.
    fresh = {**evidence, "debt_ratio": replace(evidence["debt_ratio"], stale=False)}
    assert (
        next(
            signal
            for signal in state.derive_typed(fresh).capacities
            if signal.id == "layer_foundation"
        ).value
        is True
    )


def test_generated_runtime_adds_no_mod_memory_slot_or_relation_latch():
    lock = json.loads((config.REPO / "mod/generation-lock.json").read_text(encoding="utf-8"))
    added: Counter = Counter()
    removed: Counter = Counter()
    write_keys = {
        "set_variable",
        "change_variable",
        "remove_variable",
        "set_global_variable",
        "change_global_variable",
        "remove_global_variable",
        "clamp_variable",
    }

    def writes(text, relative):
        return Counter(
            (relative, path, _tree(node))
            for path, node in _walk(parse_text(text).root)
            if node.key in write_keys
        )

    for relative in lock["files"]:
        if not relative.endswith(".txt") or not relative.startswith(("common/", "events/")):
            continue
        text = (config.REPO / "mod" / relative).read_text(encoding="utf-8-sig")
        current = writes(text, relative)
        native_path = config.GAME / relative
        native = (
            writes(native_path.read_text(encoding="utf-8-sig"), relative)
            if native_path.is_file()
            else Counter()
        )
        added.update(current - native)
        removed.update(native - current)
    # Full effect+ancestor identities distinguish retained original canal/law
    # writes from Mod writers; a new unprefixed variable cannot evade this.
    assert not removed
    assert not added
    assert country_state.contract(country_state.load())["persistent_variables"] == []
