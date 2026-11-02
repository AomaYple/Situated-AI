"""Independent native parsing and hand-calculated root-only treaty tradeoffs."""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

import pytest

from pdx import config, decision_rules
from pdx import treaty_opportunities as treaty
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
DOC = "common/treaty_articles/treaty_articles.md"
GETTER = "common/diplomatic_actions/01_expel_diplomats.txt"


@pytest.fixture(scope="module")
def baseline():
    return treaty.load_baseline()


@pytest.fixture
def raw():
    return {"sources": {}, "readers": {}, "rules": []}


def _source(baseline, identity):
    source = baseline["candidates"][identity]["source"]
    return normalized_text(
        bytes.fromhex(baseline["originals"][source]["bytes"]).decode("utf-8-sig")
    )


def _policy(derived, candidate):
    field = f"{candidate}.ai.proposal_weight"
    rules = [rule for rule in derived["rules"] if rule["field"] == field]
    assert rules
    source = rules[0]["source"]
    keys = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][source],
            "domains": {"diplomacy": True},
            "readers": {key: spec for key, spec in derived["readers"].items() if key in keys},
            "rules": [
                {key: value for key, value in rule.items() if key != "source"} for rule in rules
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=source)


def _patch(baseline, candidate, policy, *, enabled=True):
    text = _source(baseline, candidate)
    return decision_rules.patch(
        text,
        policy,
        baseline=text,
        default_strategy=False,
        reader_words=frozenset(
            {"influence", "is_at_war", "in_default", "is_diplomatic_play_target"}
        ),
        enabled_domains=frozenset({"diplomacy"}) if enabled else frozenset(),
    )


def _overlay(text, candidate):
    start = text.index(f"# SITAI BEGIN information:{candidate}.ai.proposal_weight")
    end = text.index(f"# SITAI END information:{candidate}.ai.proposal_weight", start)
    return "\n".join(text[start:end].splitlines()[1:])


def _facts(changes, *, is_ai=True):
    # These mappings are handwritten; the test does not reuse reader rendering.
    root: dict[str, Any] = {"is_ai": is_ai, "taking_loans": True, "bureaucracy": -500}
    for key, engine in (
        ("treaty_influence", "influence"),
        ("war", "is_at_war"),
        ("default", "in_default"),
        ("is_diplomatic_play_target", "is_diplomatic_play_target"),
    ):
        if key in changes:
            root[engine] = changes[key]
    return {"ROOT": root}


def _joint(raw, baseline, changes, expected, *, candidate="alliance", is_ai=True, enabled=True):
    derived = treaty.derive(raw, baseline)
    policy = _policy(derived, candidate)
    values = {reader.key: changes.get(reader.key) for reader in policy.readers}
    domains = frozenset({"diplomacy"}) if enabled else frozenset()
    result = decision_rules.evaluate(policy, values, is_ai=is_ai, enabled_domains=domains)
    selected = result.get(f"{candidate}.ai.proposal_weight")
    assert (selected[1] if selected else 1.0) == pytest.approx(expected)
    text = _patch(baseline, candidate, policy, enabled=enabled)
    if not enabled:
        assert text == _source(baseline, candidate)
        return
    observations = _facts(changes, is_ai=is_ai)
    actual = pdx_eval.select(_overlay(text, candidate), observations)
    assert (actual.delta if actual.operation == "multiply" else 1.0) == pytest.approx(expected)
    # Proposal candidates and unrelated countries cannot fabricate root facts.
    observations["ROOT"].update(article_selected=True, treaty_signed=True, navy_size=999)
    observations["scope:target_country"] = {"influence": -500, "in_default": True}
    observations["scope:source_country"] = {"is_at_war": True}
    assert pdx_eval.select(_overlay(text, candidate), observations) == actual
    if not is_ai:
        assert actual.operation is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.0),
        ({"is_diplomatic_play_target": True}, 1.15),
        ({"is_diplomatic_play_target": False}, 1.0),
        ({"war": True}, 0.85),
        ({"war": False, "default": False}, 1.0),
        ({"default": True}, 0.85),
        ({"treaty_influence": 150}, 1.0),
        ({"treaty_influence": 149.999}, 0.90),
        ({"treaty_influence": 0}, 0.90),
        ({"treaty_influence": -0.001}, 0.80),
        ({"treaty_influence": None}, 1.0),
        ({"is_diplomatic_play_target": True, "war": True}, 1.0),
        ({"is_diplomatic_play_target": True, "war": True, "treaty_influence": 100}, 0.90),
        (
            {
                "is_diplomatic_play_target": True,
                "war": True,
                "default": True,
                "treaty_influence": -1,
            },
            0.65,
        ),
        ({"war": True, "default": True, "treaty_influence": -1}, 0.50),
        ({"is_diplomatic_play_target": True, "default": None, "treaty_influence": None}, 1.15),
        ({"is_diplomatic_play_target": None, "war": True, "default": None}, 0.85),
        ({"is_diplomatic_play_target": True, "war": None, "default": True}, 1.0),
    ],
)
def test_hand_calculated_benefit_and_cost_jointly_match_patched_pdx(
    raw, baseline, changes, expected
):
    _joint(raw, baseline, changes, expected)


@pytest.mark.parametrize(("is_ai", "enabled"), [(False, True), (True, False), (False, False)])
def test_players_and_disabled_domain_keep_native(raw, baseline, is_ai, enabled):
    _joint(
        raw,
        baseline,
        {"is_diplomatic_play_target": True, "treaty_influence": -1},
        1.0,
        is_ai=is_ai,
        enabled=enabled,
    )


@pytest.mark.parametrize(
    ("candidate", "capacity", "expected"),
    [
        ("alliance", 100, 0.90),
        ("defensive_pact", 100, 1.0),
        ("guarantee_independence", 50, 1.0),
        ("guarantee_independence", 49.99, 0.90),
        ("no_tolls", 20, 0.90),
        ("no_strait_closure", 25, 1.0),
        ("toll_exemption", 20, 1.0),
        ("strait_access", 9.99, 0.90),
        ("strait_access", -1, 0.80),
    ],
)
def test_same_country_faces_exact_candidate_specific_native_cost(
    raw, baseline, candidate, capacity, expected
):
    _joint(raw, baseline, {"treaty_influence": capacity}, expected, candidate=candidate)


@pytest.mark.parametrize(
    "candidate", ["toll_exemption", "no_tolls", "strait_access", "no_strait_closure"]
)
def test_default_and_war_do_not_become_global_nonmilitary_bans(raw, baseline, candidate):
    _joint(
        raw,
        baseline,
        {"default": True, "war": True, "is_diplomatic_play_target": True},
        1.0,
        candidate=candidate,
    )


def _tree(node):
    if isinstance(node, Scalar):
        return node.text, node.quoted
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


@pytest.mark.parametrize(
    "candidate",
    [
        "alliance",
        "defensive_pact",
        "guarantee_independence",
        "toll_exemption",
        "no_tolls",
        "strait_access",
        "no_strait_closure",
    ],
)
def test_real_native_parser_preserves_complete_article_and_ordered_tail(raw, baseline, candidate):
    original = _source(baseline, candidate)
    parsed = parse_text(original)
    assert not parsed.errors
    patched = _patch(baseline, candidate, _policy(treaty.derive(raw, baseline), candidate))
    # Removing only our one writer recovers every original AST node: inputs,
    # ratification, score, source/target logic, actual cost, effect and tail.
    stripped = re.sub(
        r"# SITAI BEGIN information:.*?# SITAI END information:[^\n]*", "", patched, flags=re.DOTALL
    )
    assert _tree(parse_text(stripped).root) == _tree(parsed.root)
    assert patched.count("# SITAI BEGIN information:") == 1
    assert patched.index("# SITAI BEGIN information:") > patched.index("proposal_weight")


@pytest.mark.parametrize(
    ("grievance", "native_zero", "expected"),
    [(0, False, 0.8), (10, False, 1.12), (30, False, 1.76), (30, True, 0.0)],
)
def test_real_strait_native_add_and_terminal_zero_survive_joint_cost(
    raw, baseline, grievance, native_zero, expected
):
    """Supply native predicate/formula outcomes; do not claim to emulate them."""
    candidate = "toll_exemption"
    patched = _patch(baseline, candidate, _policy(treaty.derive(raw, baseline), candidate))
    definition = parse_text(patched).root.first(candidate)
    assert definition is not None
    assert isinstance(definition.value, Block)
    ai = definition.value.first("ai")
    assert ai is not None
    assert isinstance(ai.value, Block)
    weight = ai.value.first("proposal_weight")
    assert weight is not None
    assert isinstance(weight.value, Block)
    cloned = copy.deepcopy(weight.value)
    assert [item.key for item in cloned.assignments()] == ["value", "add", "if", "if"]
    addition = cloned.items[1]
    assert isinstance(addition, Assignment)
    assert isinstance(addition.value, Block)
    formula = addition.value.items[0]
    assert isinstance(formula, Assignment)
    assert isinstance(formula.value, Scalar)
    assert formula.value.unquoted == "strait_toll_grievance_against(scope:source_country)"
    formula.value = Scalar(str(grievance))
    terminal = cloned.items[2]
    assert isinstance(terminal, Assignment)
    assert isinstance(terminal.value, Block)
    limit = terminal.value.first("limit")
    assert limit is not None
    limit.value = Block([Assignment("always", "=", Scalar("yes" if native_zero else "no"))])
    # Independently calculated native (1 + grievance*.04), or final native 0,
    # times one .8 capacity deficit contribution. No native branch is moved.
    facts = _facts({"treaty_influence": -1})
    actual = pdx_eval._numeric_value(Assignment("multiply", "=", cloned), facts)
    assert actual == pytest.approx(expected)


def test_zero_cost_ship_transfer_and_missing_fields_are_not_initialized(raw, baseline):
    derived = treaty.derive(raw, baseline)
    reasons = {row["id"]: row["reason"] for row in derived["uncovered"]}
    assert reasons["ship_transfer"] == "no_role_safe_new_contribution"
    assert baseline["candidates"]["ship_transfer"]["cost"] == "0"
    assert baseline["candidates"]["ship_transfer"]["weight_shape"] == "block"
    assert sum(row["weight_shape"] == "block" for row in baseline["candidates"].values()) == 8
    assert len(derived["covered"]) == 7
    assert len(derived["rules"]) == 21
    assert {row["reason"] for row in derived["uncovered"]} == {
        "no_role_safe_new_contribution",
        "missing_native_proposal_weight",
    }
    assert not {"initial_values", "scalar_values", "actors", "contexts"} & derived.keys()
    assert all(
        spec["scope"] == "root" and "path" not in spec for spec in derived["readers"].values()
    )


def test_influence_getter_has_exact_native_country_path_and_raw_identity(baseline):
    proof = baseline["getter_evidence"]
    assert proof == {
        "engine": "influence",
        "kind": "number",
        "line": 142,
        "path": ["expel_diplomats", "ai", "will_propose", "OR", "AND", "OR", "influence"],
        "scope": "root",
        "source": GETTER,
        "unit": "capacity_balance",
    }
    assert (
        baseline["originals"][GETTER]["sha256"]
        == "c8c7d92a001edd3341897aa34f6265fb0d9f15de02c178d40b1df7ce98a08df3"
    )
    assert (
        baseline["sources"][GETTER]
        == "9bca63b14f0811d7381a658a567a3a84247242157275ed5a85b05857b47622fb"
    )


def test_offline_uses_frozen_originals_and_preserves_inputs(raw, baseline, monkeypatch):
    before = copy.deepcopy((raw, baseline))
    expected = treaty.derive(raw, baseline)

    def forbidden(_game):
        raise AssertionError("offline must not read installation")

    monkeypatch.setattr(treaty, "read_inputs", forbidden)
    assert treaty.load_baseline() == baseline
    assert treaty.derive(raw) == expected
    assert (raw, baseline) == before


@pytest.mark.parametrize("key", ["default", "war", "is_diplomatic_play_target", "treaty_influence"])
def test_complete_reader_identity_rejects_actor_path_drift(raw, baseline, key):
    derived = treaty.derive(raw, baseline)
    raw["readers"] = copy.deepcopy(derived["readers"])
    assert treaty.derive(raw, baseline) == derived
    raw["readers"][key]["path"] = ["owner"]
    with pytest.raises(ValueError, match="reader"):
        treaty.derive(raw, baseline)


def test_source_conflict_and_duplicate_native_definition_fail_closed(raw, baseline):
    source = baseline["candidates"]["alliance"]["source"]
    raw["sources"][source] = "0" * 64
    with pytest.raises(ValueError, match="来源"):
        treaty.derive(raw, baseline)
    inputs = {name: bytes.fromhex(row["bytes"]) for name, row in baseline["originals"].items()}
    inputs["dlc/test/in_game/common/treaty_articles/duplicate.txt"] = (
        b"alliance = { kind = mutual }"
    )
    with pytest.raises(ValueError, match="唯一"):
        treaty._inventory(inputs)


@pytest.mark.parametrize(
    "mutation", ["metadata", "scope", "getter_path", "raw_sha", "original_bytes", "extra_key"]
)
def test_repin_cannot_hide_metadata_or_byte_inconsistency(
    baseline, tmp_path, monkeypatch, mutation
):
    data = copy.deepcopy(baseline)
    if mutation == "metadata":
        data["candidates"]["alliance"]["cost"] = "0"
    elif mutation == "scope":
        data["contract"]["target"] = "country"
    elif mutation == "getter_path":
        data["getter_evidence"]["path"] = ["scope:target_country", "influence"]
    elif mutation == "raw_sha":
        data["originals"][GETTER]["sha256"] = "0" * 64
    elif mutation == "original_bytes":
        data["originals"][GETTER]["bytes"] += "20"
    else:
        data["candidates"]["alliance"]["target_country"] = True
    path = tmp_path / "baseline.json"
    path.write_text(treaty._canonical(data), encoding="utf-8", newline="\n")
    monkeypatch.setattr(treaty, "BASELINE", path)
    monkeypatch.setattr(treaty, "BASELINE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        treaty.load_baseline()


@pytest.mark.parametrize(
    "literal", ["-1", '"10"', "yes", "some_script_value", "{ value = 10 }", "nan", "inf"]
)
def test_unknown_or_malformed_native_cost_never_becomes_zero(baseline, literal):
    inputs = {
        DOC: bytes.fromhex(baseline["originals"][DOC]["bytes"]),
        GETTER: bytes.fromhex(baseline["originals"][GETTER]["bytes"]),
        "common/treaty_articles/test.txt": f"alliance = {{ kind = mutual cost = {literal} ai = {{ proposal_weight = {{ value = 1 }} }} }}".encode(),
    }
    with pytest.raises(ValueError, match="成本"):
        treaty._inventory(inputs)


def _simple_inputs(baseline, text):
    return {
        DOC: bytes.fromhex(baseline["originals"][DOC]["bytes"]),
        GETTER: bytes.fromhex(baseline["originals"][GETTER]["bytes"]),
        "common/treaty_articles/test.txt": text.encode(),
    }


def test_omitted_cost_scalar_empty_and_unreviewed_fields_keep_native(raw, baseline):
    text = """
    alliance = { kind = mutual ai = { proposal_weight = { value = 1 } } }
    defensive_pact = { kind = mutual cost = 100 ai = { proposal_weight = {} } }
    guarantee_independence = { kind = directed cost = 50 ai = { proposal_weight = 1 } }
    ship_transfer = { kind = directed cost = 0 ai = { proposal_weight = { value = 1 } } }
    unknown_article = { kind = mutual cost = 20 ai = { proposal_weight = { value = 1 } } }
    missing = { kind = mutual cost = 20 }
    """
    frozen = treaty._inventory(_simple_inputs(baseline, text))
    assert frozen["candidates"]["alliance"]["cost"] == "0"
    assert frozen["candidates"]["alliance"]["cost_line"] == 0
    derived = treaty.derive(raw, frozen)
    assert derived["covered"] == []
    assert derived["rules"] == []
    assert derived["readers"] == {}
    assert {row["id"]: row["reason"] for row in derived["uncovered"]} == {
        "alliance": "no_role_safe_new_contribution",
        "defensive_pact": "unsupported_scalar_or_empty_weight",
        "guarantee_independence": "unsupported_scalar_or_empty_weight",
        "ship_transfer": "no_role_safe_new_contribution",
        "unknown_article": "no_reviewed_article_policy",
        "missing": "missing_native_proposal_weight",
    }


@pytest.mark.parametrize(
    "text",
    [
        "alliance = { kind = mutual cost = 10 cost = 20 }",
        "alliance = { kind = mutual ai = { proposal_weight = {} proposal_weight = {} } }",
        "alliance = { kind = mutual ai = {} ai = {} }",
        "alliance = { kind = mutual } alliance = { kind = mutual }",
        "alliance = { kind = mutual cost = 10",
    ],
)
def test_ambiguous_or_unparseable_article_identity_is_an_error(baseline, text):
    with pytest.raises(ValueError):
        treaty._inventory(_simple_inputs(baseline, text))


def test_reviewed_mutual_article_cannot_become_directed_by_repinning(raw, baseline):
    frozen = treaty._inventory(
        _simple_inputs(
            baseline,
            "alliance = { kind = directed cost = 10 ai = { proposal_weight = { value = 1 } } }",
        )
    )
    with pytest.raises(ValueError, match="kind"):
        treaty.derive(raw, frozen)


@pytest.mark.parametrize(
    "mutation",
    ["new_file", "missing_file", "tail", "cost", "getter_scope", "scope_doc", "dlc_duplicate"],
)
def test_production_gate_reinventories_full_native_source_set(baseline, tmp_path, mutation):
    for source, row in baseline["originals"].items():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex(row["bytes"]))
    assert treaty.verify_game(tmp_path) == baseline
    source = baseline["candidates"]["alliance"]["source"]
    path = tmp_path / source
    if mutation == "new_file":
        path.with_name("extra.txt").write_text("# additional input\n", encoding="utf-8")
    elif mutation == "missing_file":
        path.unlink()
    elif mutation in {"tail", "cost"}:
        text = path.read_text(encoding="utf-8-sig")
        path.write_text(
            text.replace("add = 3", "add = 4", 1)
            if mutation == "tail"
            else text.replace("cost = 150", "cost = 151", 1),
            encoding="utf-8",
        )
    elif mutation == "getter_scope":
        text = (tmp_path / GETTER).read_text(encoding="utf-8-sig")
        (tmp_path / GETTER).write_text(
            text.replace("influence < 200", "scope:target_country = { influence < 200 }"),
            encoding="utf-8",
        )
    elif mutation == "scope_doc":
        text = (tmp_path / DOC).read_text(encoding="utf-8-sig")
        (tmp_path / DOC).write_text(
            text.replace("root is composing AI country", "root is unknown"), encoding="utf-8"
        )
    else:
        shadow = tmp_path / "dlc/test/in_game/common/treaty_articles/shadow.txt"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("alliance = { kind = mutual }", encoding="utf-8")
    with pytest.raises(ValueError):
        treaty.verify_game(tmp_path)


@pytest.mark.parametrize(
    "mutation", ["direction", "deficit_order", "joint_floor", "unknown", "bool", "nonfinite"]
)
def test_parameters_reject_wrong_direction_or_unbounded_joint_cost(raw, baseline, mutation):
    params: dict[str, object] = dict(treaty.load_parameters())
    if mutation == "direction":
        params["defensive_need_multiplier"] = 0.8
    elif mutation == "deficit_order":
        params["influence_deficit_multiplier"] = 0.95
    elif mutation == "joint_floor":
        params["default_multiplier"] = 0.5
    elif mutation == "unknown":
        params["transport_bonus"] = 1.2
    elif mutation == "bool":
        params["priority_base"] = True
    else:
        params["war_commitment_multiplier"] = float("nan")
    with pytest.raises(ValueError):
        treaty.derive(raw, baseline, parameters=params)


def test_live_installed_sources_match_frozen_originals_when_available(baseline):
    if not (config.GAME / DOC).is_file():
        pytest.skip("locked native installation unavailable; offline evidence covered separately")
    assert treaty.verify_game(config.GAME) == baseline
