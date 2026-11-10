"""R2 native adapters: literal expectations and an independent generated-AST witness.

The interpreter below understands the emitted PDX subset directly. It does not
call the network evaluator, specializer, reader renderer or expression evaluator.
These are static semantic witnesses, not evidence of engine execution.
"""

from __future__ import annotations

import itertools
import re
from typing import TYPE_CHECKING

import pytest

from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import action_network as net
from pdx.situated import network_profile as adapter
from pdx.situated import production_profile as native
from pdx.situated.profile_configuration import DOMAINS, ProfileConfiguration

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

ROAD = "a0-econ-road"
SCHOOL = "a0-pol-schools"
DIPLOMACY = "a0-dip-relations"


def _block(value: object) -> Block:
    assert isinstance(value, Block)
    return value


def _scalar(value: object) -> str:
    assert isinstance(value, Scalar)
    return value.text


def _parsed(text: str) -> Block:
    parsed = parse_text(text, "independent-r2-witness")
    assert not parsed.errors
    return parsed.root


def _marker(consumer: str) -> str:
    return (
        rf"\n\t# SITAI POLICY 1\.15\.0 BEGIN {re.escape(consumer)}\n"
        rf"(?P<body>[\s\S]*?)\t# SITAI POLICY 1\.15\.0 END {re.escape(consumer)}\n"
    )


def _overlay(text: str, consumer: str) -> Block:
    matches = list(re.finditer(_marker(consumer), text))
    assert len(matches) == 1
    return _parsed(matches[0].group("body"))


def _consumer(text: str, *keys: str) -> Block:
    body = _parsed(text)
    for key in keys:
        entry = body.first(key)
        assert entry is not None
        body = _block(entry.value)
    return body


def _comparison(actual: object, op: str, expected: object) -> bool:
    assert actual is not None, "generated AST read an unavailable fact"
    if op == "=":
        return actual == expected
    if op == "!=":
        return actual != expected
    assert isinstance(actual, (float, int))
    assert isinstance(expected, (float, int))
    if op == "<":
        return actual < expected
    if op == "<=":
        return actual <= expected
    if op == ">":
        return actual > expected
    if op == ">=":
        return actual >= expected
    raise AssertionError(f"unexpected PDX comparison {op}")


def _condition(block: Block, facts: dict[str, object], scope: str = "actor") -> bool:
    results = []
    for item in block.assignments():
        if item.key in {"AND", "OR", "NOT"}:
            values = [
                _condition(Block([child]), facts, scope)
                for child in _block(item.value).assignments()
            ]
            result = any(values) if item.key == "OR" else all(values)
            results.append(not result if item.key == "NOT" else result)
        elif item.key == "always":
            results.append(_scalar(item.value) == "yes")
        elif item.key == "exists":
            assert scope == "state"
            target = _scalar(item.value)
            assert target in {"country", "scope:country"}
            existence = "actor_exists" if target == "scope:country" else "owner_exists"
            results.append(bool(facts.get(existence, True)))
        elif item.key == "country":
            assert scope == "state"
            results.append(
                bool(facts.get("owner_exists", True))
                and _condition(_block(item.value), facts, "owner")
            )
        elif item.key == "scope:target_country":
            assert scope == "actor"
            results.append(_condition(_block(item.value), facts, "target"))
        elif item.key == "scope:country":
            assert scope == "state"
            assert item.op in {"=", "?="}
            results.append(
                bool(facts.get("actor_exists", True))
                and _condition(_block(item.value), facts, "actor")
            )
        elif item.key == "is_ai":
            assert scope in {"actor", "owner"}
            ai = facts["ai"] if scope == "actor" else facts["owner_ai"]
            results.append(_comparison(ai, item.op, _scalar(item.value) == "yes"))
        elif item.key in {"relative_infrastructure", "literacy_rate", "bureaucracy", "influence"}:
            fact, expected_scope = {
                "relative_infrastructure": ("infrastructure", "state"),
                "literacy_rate": ("literacy", "actor"),
                "bureaucracy": ("bureaucracy", "actor"),
                "influence": ("influence", "actor"),
            }[item.key]
            assert scope == expected_scope
            results.append(_comparison(facts.get(fact), item.op, float(_scalar(item.value))))
        elif item.key == "has_journal_entry":
            assert scope == "actor"
            journal = _scalar(item.value)
            if journal == "je_tp_pool_educational_reform":
                results.append(_comparison(facts.get("school-agenda"), item.op, True))
            else:
                assert journal in {
                    "je_lands_of_anarchy",
                    "je_tp_pool_develop_capital",
                    "je_tp_fav_parochial",
                }
                assert item.op == "="
                journals = facts.get("journals", ())
                assert isinstance(journals, (tuple, list, set, frozenset))
                results.append(journal in journals)
        elif item.key == "is_capital":
            assert scope == "state"
            results.append(
                _comparison(facts.get("capital", False), item.op, _scalar(item.value) == "yes")
            )
        elif item.key == "has_variable":
            assert scope == "actor"
            assert _scalar(item.value) == "tp_fav_home_state"
            variables = facts.get("variables", ())
            assert isinstance(variables, (tuple, list, set, frozenset))
            results.append("tp_fav_home_state" in variables)
        elif item.key == "var:tp_fav_home_state":
            assert scope == "actor"
            assert item.op == "?="
            assert _scalar(item.value) == "root"
            results.append(bool(facts.get("home_state", False)))
        elif item.key in {"has_decree", "in_default"}:
            fact, expected_scope, token = {
                "has_decree": ("road-present", "state", "decree_road_maintenance"),
                "in_default": ("default", "actor", "yes"),
            }[item.key]
            assert scope == expected_scope
            assert _scalar(item.value) == token
            results.append(_comparison(facts.get(fact), item.op, True))
        elif item.key == "has_attitude":
            assert scope == "actor"
            parameters = {
                entry.key: _scalar(entry.value) for entry in _block(item.value).assignments()
            }
            assert parameters == {"who": "scope:target_country", "attitude": "protective"}
            results.append(_comparison(facts.get("protective"), item.op, True))
        elif item.key == "has_diplomatic_pact":
            assert scope == "target"
            parameters = {
                entry.key: _scalar(entry.value) for entry in _block(item.value).assignments()
            }
            assert parameters == {"who": "root", "type": "support_separatism"}
            results.append(_comparison(facts.get("target-interference"), item.op, True))
        else:
            raise AssertionError(f"unexpected generated PDX predicate {item.key}")
    return all(results)


def _score(
    block: Block, facts: dict[str, object], scope: str = "actor", initial: float = 0
) -> float:
    """Interpret numeric AST statements in their actual source order."""
    value = initial
    for item in block.assignments():
        if item.key == "limit":
            continue
        if item.key == "if":
            body = _block(item.value)
            limit = body.first("limit")
            assert limit is not None
            if _condition(_block(limit.value), facts, scope):
                value = _score(body, facts, scope, value)
        elif item.key == "add":
            value += (
                _score(item.value, facts, scope)
                if isinstance(item.value, Block)
                else float(_scalar(item.value))
            )
        elif item.key == "multiply":
            # PDX's multiplicative block starts at the neutral factor 1.
            # Keeping this lowering here makes the witness usable for shared
            # residual/replacement contracts without importing product code.
            factor = (
                _score(item.value, facts, scope, 1.0)
                if isinstance(item.value, Block)
                else float(_scalar(item.value))
            )
            value *= factor
        elif item.key == "value":
            value = float(_scalar(item.value))
        elif item.key == "min":
            value = max(value, float(_scalar(item.value)))
        elif item.key == "max":
            value = min(value, float(_scalar(item.value)))
        else:
            raise AssertionError(f"unexpected generated numeric statement {item.key}")
    return value


@pytest.fixture(scope="module")
def profile():
    return native.load_profile(native.BASELINE_ROOT)


@pytest.fixture(scope="module")
def programs(profile):
    return {
        item.network.actions[0].definition.consumer_id: item
        for item in adapter.compile_profile(profile)
    }


@pytest.fixture(scope="module")
def generated(profile):
    return adapter.build(profile)


def _witness(
    programs, generated, profile, consumer: str, facts: Mapping[str, object], expected: float
):
    row = next(item for item in profile.declarations if item.id == consumer)
    root = _overlay(generated[row.source.removeprefix("game/")], consumer)
    assert net.evaluate_network(programs[consumer], dict(facts)).total == expected, facts
    scope = "state" if consumer == ROAD else "actor"
    assert _score(root, {**facts, "ai": True}, scope) == expected, facts
    assert _score(root, {**facts, "ai": False}, scope) == 0, facts


def test_road_literal_tiers_boundaries_recovery_and_actor_guard(profile, programs, generated):
    for infrastructure, active in itertools.product(
        (0.0, 0.249, 0.25, 0.499, 0.5, 0.749, 0.75, 1.3), (False, True)
    ):
        # Independent policy oracle: same relief effect takes one strongest tier.
        expected = (
            4
            if infrastructure < 0.25
            else 2
            if infrastructure < 0.5
            else -2
            if active and infrastructure >= 0.75
            else 0
        )
        facts = {"infrastructure": infrastructure, "road-present": active}
        _witness(programs, generated, profile, ROAD, facts, expected)
    root = _overlay(generated["common/decrees/00_decree.txt"], ROAD)
    assert (
        _score(
            root,
            {"ai": True, "actor_exists": False, "infrastructure": 0.1, "road-present": False},
            "state",
        )
        == 0
    )


@pytest.mark.parametrize(
    ("actor_ai", "owner_ai", "actor_exists", "owner_exists", "expected"),
    [
        (True, False, True, True, 4),
        (False, True, True, True, 0),
        (True, False, True, False, 4),
        (False, True, True, False, 0),
        (True, True, False, True, 0),
        (False, True, False, True, 0),
    ],
)
def test_road_named_actor_guard_never_uses_state_owner(
    generated, actor_ai, owner_ai, actor_exists, owner_exists, expected
):
    text = generated["common/decrees/00_decree.txt"]
    root = _overlay(text, ROAD)
    assert (
        _score(
            root,
            {
                "ai": actor_ai,
                "owner_ai": owner_ai,
                "actor_exists": actor_exists,
                "owner_exists": owner_exists,
                "infrastructure": 0.1,
                "road-present": False,
            },
            "state",
        )
        == expected
    )


@pytest.mark.parametrize(
    ("infrastructure", "active", "journals", "capital", "native_value", "generated_value"),
    [
        (0.1, False, (), False, 325, 329),
        (0.4, False, (), False, 225, 227),
        (0.8, True, (), False, 125, 123),
        (0.1, False, ("je_tp_pool_develop_capital",), True, 1987.5, 1993.5),
        (
            0.1,
            False,
            ("je_tp_pool_develop_capital", "je_tp_fav_parochial"),
            True,
            5231.25,
            5240.25,
        ),
        (1.3, False, (), True, 0, 0),
        (1.3, False, ("je_lands_of_anarchy",), True, 1000, 1000),
        (
            1.3,
            False,
            ("je_tp_pool_develop_capital", "je_tp_fav_parochial"),
            True,
            4500,
            4500,
        ),
        (
            1.3,
            False,
            ("je_lands_of_anarchy", "je_tp_pool_develop_capital", "je_tp_fav_parochial"),
            True,
            6750,
            6750,
        ),
    ],
)
def test_complete_road_native_tail_literal_values(
    generated, infrastructure, active, journals, capital, native_value, generated_value
):
    """Witness complete native arithmetic, including additions after zeroing.

    The two native multipliers can amplify insertion +4 into final delta +9.
    A zero multiplier cancels the insertion but does not cancel journal additions
    later in the original source. These are static AST semantics, not an engine run.
    """
    baseline = _consumer(
        (native.BASELINE_ROOT / "game/common/decrees/00_decree.txt").read_text(
            encoding="utf-8-sig"
        ),
        "decree_road_maintenance",
        "ai_weight",
    )
    production = _consumer(
        generated["common/decrees/00_decree.txt"], "decree_road_maintenance", "ai_weight"
    )
    facts = {
        "ai": True,
        "infrastructure": infrastructure,
        "road-present": active,
        "capital": capital,
        "journals": journals,
        "variables": ("tp_fav_home_state",),
        "home_state": True,
    }
    assert _score(baseline, facts, "state") == native_value
    assert _score(production, facts, "state") == generated_value
    assert _score(production, {**facts, "ai": False}, "state") == native_value


def test_complete_road_player_identity_and_effective_delta_envelope(generated):
    original = _consumer(
        (native.BASELINE_ROOT / "game/common/decrees/00_decree.txt").read_text(
            encoding="utf-8-sig"
        ),
        "decree_road_maintenance",
        "ai_weight",
    )
    production = _consumer(
        generated["common/decrees/00_decree.txt"], "decree_road_maintenance", "ai_weight"
    )
    deltas = []
    journal_ids = (
        "je_lands_of_anarchy",
        "je_tp_pool_develop_capital",
        "je_tp_fav_parochial",
    )
    for infrastructure, active, capital, journal_flags, home, variable in itertools.product(
        (0.1, 0.4, 0.8, 1.3),
        (False, True),
        (False, True),
        itertools.product((False, True), repeat=3),
        (False, True),
        (False, True),
    ):
        facts = {
            "ai": True,
            "infrastructure": infrastructure,
            "road-present": active,
            "capital": capital,
            "journals": tuple(
                journal
                for journal, present in zip(journal_ids, journal_flags, strict=True)
                if present
            ),
            "variables": ("tp_fav_home_state",) if variable else (),
            "home_state": home,
        }
        retained = _score(original, facts, "state")
        assert _score(production, {**facts, "ai": False}, "state") == retained
        delta = _score(production, facts, "state") - retained
        assert -9 <= delta <= 9
        deltas.append(delta)
    # The conservative envelope is +/-9; this declared policy's negative tier
    # reaches -4.5, rather than falsely implying that -9 is reachable.
    assert min(deltas) == -4.5
    assert max(deltas) == 9


def test_school_complete_costs_and_agenda_residual(profile, programs, generated):
    for literacy, bureaucracy, default, agenda in itertools.product(
        (0.2, 0.349, 0.35, 0.8), (-1, 0, 100), (False, True), (False, True)
    ):
        expected = (
            (2 if literacy < 0.35 else 0)
            - (2 if bureaucracy < 0 else 0)
            - (2 if default else 0)
            + (1 if literacy < 0.35 and agenda else 0)
        )
        _witness(
            programs,
            generated,
            profile,
            SCHOOL,
            {
                "literacy": literacy,
                "bureaucracy": bureaucracy,
                "default": default,
                "school-agenda": agenda,
            },
            expected,
        )


def test_diplomacy_actual_influence_and_observed_target_pact(profile, programs, generated):
    for protective, influence, interference in itertools.product(
        (False, True), (-50, 199, 200, 500), (False, True)
    ):
        expected = (
            (2 if protective else 0)
            - (2 if influence < 200 else 0)
            - (1 if protective and interference else 0)
        )
        _witness(
            programs,
            generated,
            profile,
            DIPLOMACY,
            {"protective": protective, "influence": influence, "target-interference": interference},
            expected,
        )


@pytest.mark.parametrize(
    ("consumer", "facts", "missing", "expected"),
    [
        (ROAD, {"infrastructure": 0.1, "road-present": False}, "infrastructure", 0),
        (ROAD, {"infrastructure": 0.1, "road-present": False}, "road-present", 4),
        (ROAD, {"infrastructure": 0.8, "road-present": True}, "road-present", 0),
        (
            SCHOOL,
            {"literacy": 0.2, "bureaucracy": -1, "default": False, "school-agenda": True},
            "bureaucracy",
            0,
        ),
        (
            SCHOOL,
            {"literacy": 0.2, "bureaucracy": 10, "default": False, "school-agenda": True},
            "default",
            0,
        ),
        (
            SCHOOL,
            {"literacy": 0.2, "bureaucracy": 10, "default": False, "school-agenda": True},
            "literacy",
            0,
        ),
        (
            SCHOOL,
            {"literacy": 0.2, "bureaucracy": 10, "default": False, "school-agenda": True},
            "school-agenda",
            2,
        ),
        (
            DIPLOMACY,
            {"protective": True, "influence": 500, "target-interference": True},
            "target-interference",
            2,
        ),
        (
            DIPLOMACY,
            {"protective": True, "influence": 500, "target-interference": True},
            "influence",
            0,
        ),
        (
            DIPLOMACY,
            {"protective": True, "influence": 500, "target-interference": True},
            "protective",
            0,
        ),
    ],
)
def test_unknown_required_cost_withdraws_group_optional_context_keeps_base(
    programs, consumer, facts, missing, expected
):
    program = programs[consumer]
    available = tuple(fact.id for fact in program.network.facts if fact.id != missing)
    known = {name: value for name, value in facts.items() if name != missing}
    # Both omitted and explicit unknown observations have the same reference result.
    assert net.evaluate_network(program, known).total == expected
    assert net.evaluate_network(program, {**known, missing: None}).total == expected
    rendered = _parsed(adapter.render_program(program, available=available))
    scope = "state" if consumer == ROAD else "actor"
    assert _score(rendered, {**known, "ai": True}, scope) == expected


def test_clamp_is_applied_once_after_netting_real_generated_contributions(profile, tmp_path: Path):
    source = tmp_path / "bounded-network.toml"
    source.write_text(
        adapter.SOURCE.read_text(encoding="utf-8")
        .replace("[-4.0, 4.0]", "[-1.0, 1.0]")
        .replace("[-3.0, 3.0]", "[-1.0, 1.0]"),
        encoding="utf-8",
    )
    programs = {
        item.network.actions[0].definition.consumer_id: item
        for item in adapter.compile_profile(profile, source=source)
    }
    generated = adapter.build(profile, source=source)
    for consumer, facts, expected in (
        (ROAD, {"infrastructure": 0.1, "road-present": False}, 1),
        (ROAD, {"infrastructure": 0.8, "road-present": True}, -1),
        (SCHOOL, {"literacy": 0.2, "bureaucracy": -1, "default": False, "school-agenda": False}, 0),
        (SCHOOL, {"literacy": 0.2, "bureaucracy": 0, "default": False, "school-agenda": True}, 1),
        (SCHOOL, {"literacy": 0.8, "bureaucracy": -1, "default": True, "school-agenda": False}, -1),
        (DIPLOMACY, {"protective": True, "influence": 100, "target-interference": False}, 0),
        (DIPLOMACY, {"protective": True, "influence": 500, "target-interference": False}, 1),
        (DIPLOMACY, {"protective": False, "influence": 100, "target-interference": False}, -1),
    ):
        _witness(programs, generated, profile, consumer, facts, expected)
    for row in profile.declarations:
        root = _overlay(generated[row.source.removeprefix("game/")], row.id)
        addition = root.first("add")
        if addition is None:
            outer = root.first("if")
            assert outer is not None
            addition = _block(outer.value).first("add")
        assert addition is not None
        operations = list(_block(addition.value).assignments())
        assert [item.key for item in operations[-2:]] == ["min", "max"]
        assert sum(item.key == "min" for item in operations) == 1
        assert sum(item.key == "max" for item in operations) == 1


def test_generation_changes_only_three_exact_overlays_and_retains_all_native_content(
    profile, generated
):
    expected = {row.source.removeprefix("game/") for row in profile.declarations}
    assert set(generated) == expected
    # Independent byte/text excision: do not let strip_policy verify its own insertion.
    for row in profile.declarations:
        output = generated[row.source.removeprefix("game/")]
        restored, count = re.subn(_marker(row.id), "", output)
        assert count == 1
        assert restored == (native.BASELINE_ROOT / row.source).read_text(encoding="utf-8-sig")
        # Parse the complete file independently and locate the exact physical
        # consumer. A marker anywhere else in the file cannot satisfy this.
        consumer = _parsed(output)
        for key in (row.definition, *row.field):
            entry = consumer.first(key)
            assert entry is not None
            consumer = _block(entry.value)
        assignments = list(consumer.assignments())
        inserted = assignments[1] if row.id == ROAD else assignments[-1]
        assert inserted.key == ("add" if row.id == SCHOOL else "if")
        # This subtree belongs to the physical consumer selected above, rather
        # than merely being a marker elsewhere in a generated file.
        body = _block(inserted.value)
        if row.id != SCHOOL:
            assert body.first("limit") is not None
            addition = body.first("add")
            assert addition is not None
            body = _block(addition.value)
        contributions = list(body.all("if"))
        assert contributions
        for contribution in contributions:
            assert _block(contribution.value).first("limit") is not None
        # Only the depth-zero school body distributes the AI predicate across
        # terms. Its country readers are valid for players too; the independent
        # witness evaluates every limit conjunct without assuming short-circuit.
        player_facts: dict[str, object] = {"ai": False}
        if row.id == SCHOOL:
            player_facts.update(
                literacy=0.2, bureaucracy=-1, default=True, **{"school-agenda": True}
            )
        assert _score(Block([inserted]), player_facts, "state" if row.id == ROAD else "actor") == 0
        keys = [entry.key for entry in body.assignments()]
        assert keys[0] == "value"
        assert keys[-2:] == ["min", "max"]
    # The road overlay precedes the original zero multiplier. Original journal
    # additions and multipliers after it must also remain in their source order.
    road = generated["common/decrees/00_decree.txt"]
    assert (
        road.index("SITAI POLICY")
        < road.index("relative_infrastructure >= 1.25")
        < road.index("multiply = 0")
    )
    assert "common/ai_strategies/03_political_strategies.txt" not in generated
    native.verify_baseline()


def _depth(block: Block) -> int:
    children = [item.value for item in block.assignments() if isinstance(item.value, Block)]
    children.extend(item for item in block.items if isinstance(item, Block))
    return max((1 + _depth(child) for child in children), default=0)


def test_generated_consumers_respect_the_frozen_additional_depth_budget(profile, generated):
    expected = {ROAD: (4, 5), SCHOOL: (0, 3), DIPLOMACY: (4, 6)}
    for row in profile.declarations:
        original = (native.BASELINE_ROOT / row.source).read_text(encoding="utf-8-sig")
        rewritten = generated[row.source.removeprefix("game/")]
        before = _depth(_consumer(original, row.definition, *row.field))
        after = _depth(_consumer(rewritten, row.definition, *row.field))
        assert (before, after) == expected[row.id]
        assert after - before <= 3


def test_build_rejects_parseable_deep_renderer_output(profile, monkeypatch):
    # Simulate a renderer regression after semantic compilation. Both the PDX
    # parser and native byte restoration accept it; the independent output
    # budget must still prevent build from returning a release candidate.
    condition = "always = yes"
    for _ in range(8):
        condition = "AND = { " + condition + " }"
    output = "add = { value = 0 if = { limit = { " + condition + " } add = 1 } min = -4 max = 4 }\n"
    monkeypatch.setattr(adapter, "render_program", lambda _program: output)
    with pytest.raises(ValueError, match="A0-BUDGET-LOCAL-ONLY block depth exceeded"):
        adapter.build(profile)


@pytest.mark.parametrize(
    "configuration",
    [
        ProfileConfiguration(core=False),
        ProfileConfiguration(domains=frozenset()),
        ProfileConfiguration(mode="neutral"),
    ],
)
def test_core_or_all_domains_disabled_restore_original_native_files(profile, configuration):
    outputs = adapter.build(profile, configuration=configuration)
    assert adapter.compile_profile(profile, configuration=configuration) == ()
    for row in profile.declarations:
        assert outputs[row.source.removeprefix("game/")] == (
            native.BASELINE_ROOT / row.source
        ).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("disabled", DOMAINS)
def test_each_domain_switch_restores_its_native_consumer_only(profile, disabled):
    configuration = ProfileConfiguration(domains=frozenset(DOMAINS) - {disabled})
    outputs = adapter.build(profile, configuration=configuration)
    programs = adapter.compile_profile(profile, configuration=configuration)
    assert len(programs) == 2
    for row in profile.declarations:
        text = outputs[row.source.removeprefix("game/")]
        if row.domain == disabled:
            assert text == (native.BASELINE_ROOT / row.source).read_text(encoding="utf-8-sig")
            assert f"SITAI POLICY 1.15.0 BEGIN {row.id}" not in text
        else:
            assert len(re.findall(_marker(row.id), text)) == 1
