"""Independent literal channel/role oracle through normal adapters and parsed PDX.

All dictionaries and complete law text come from accepted frozen sources. These
are finite static witnesses, without a game model, a Pop model, or fresh capture.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from typing import Any

import pytest
from test_a3_culture import _religious_facts
from test_remaining_joint_consumers import _block, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    observation_queries,
)
from pdx import culture_opportunities as culture
from pdx import religious_channels as channels
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs, resources
from pdx.textio import normalized_text

# Literal accepted fixture, independently transcribed; never sourced from the
# producer's dictionary, category function, effects, or derived rule values.
NAMES = (
    "catholic",
    "protestant",
    "orthodox",
    "oriental_orthodox",
    "sunni",
    "shiite",
    "ibadi",
    "jewish",
    "mahayana",
    "gelugpa",
    "theravada",
    "confucian",
    "hindu",
    "shinto",
    "sikh",
    "animist",
    "atheist",
)
HERITAGES = (
    frozenset(NAMES[:4]),
    frozenset(NAMES[4:7]),
    frozenset({"jewish"}),
    frozenset({"mahayana", "gelugpa", "theravada", "hindu", "sikh"}),
    frozenset({"confucian", "shinto"}),
    frozenset({"animist"}),
    frozenset({"atheist"}),
)
GROUPS = (
    frozenset(NAMES[:8]),
    frozenset({"mahayana", "gelugpa", "theravada", "hindu", "sikh", "confucian", "shinto"}),
    frozenset({"animist"}),
    frozenset({"atheist"}),
)
ORIGINS = ("law_millet_system", "law_people_of_the_book")
MODES = ("channel_benefit_exposure", "shared_group_protection_exposure")


def literal_category(state, observed):
    if state == observed:
        return "state"
    if any({state, observed} <= row for row in HERITAGES):
        return "heritage"
    if any({state, observed} <= row for row in GROUPS):
        return "group"
    return "other"


@pytest.fixture(scope="module")
def compiled_queries():
    return {
        mode: observation_queries.compile_query(
            observation_queries.from_reader("OR", {"culture_query": mode}), culture.frozen_inputs()
        )
        for mode in MODES
    }


@pytest.mark.parametrize("mode", MODES)
def test_complete_17_by_17_literal_partition_and_same_observation(compiled_queries, mode):
    query = parse_text(compiled_queries[mode].expression).root
    _, dictionary = channels.snapshot()
    for state in NAMES:
        for observed in NAMES:
            category = literal_category(state, observed)
            assert dictionary.category(state, observed) == category, (state, observed)
            allowed = category in {"heritage", "other"} if mode == MODES[0] else category == "group"
            for share, acceptance in ((0.1, -1), (0.1, 1), (0.09999, -1), (0.1, 0)):
                facts = _religious_facts(
                    state=state, shares={observed: share}, acceptance={observed: acceptance}
                )
                expected = (
                    allowed
                    and share >= 0.1
                    and (acceptance < 0 if mode == MODES[0] else acceptance > 0)
                )
                assert pdx_eval.condition(query, facts) is expected, (
                    mode,
                    state,
                    observed,
                    share,
                    acceptance,
                    category,
                )


@pytest.mark.parametrize("mode", MODES)
def test_query_unknown_same_country_same_religion_and_no_population_count(compiled_queries, mode):
    query = parse_text(compiled_queries[mode].expression).root
    religion, acceptance = ("protestant", -1) if mode == MODES[0] else ("sunni", 1)
    facts = _religious_facts(shares={religion: 0.1}, acceptance={religion: acceptance})
    assert pdx_eval.condition(query, facts) is True
    facts["religion_percent_country"][(("target", f"rel:{religion}"),)] = None
    assert pdx_eval.condition(query, facts) is None
    facts = _religious_facts(shares={religion: 0.1}, acceptance={religion: None})
    assert pdx_eval.condition(query, facts) is None
    facts = _religious_facts(shares={religion: 0.1}, acceptance={religion: acceptance})
    facts["country_has_state_religion"] = dict.fromkeys(facts["country_has_state_religion"])
    assert pdx_eval.condition(query, facts) is None
    facts = _religious_facts(shares={religion: 0.1}, acceptance={"hindu": acceptance})
    facts["scope:target_country"] = _religious_facts(
        shares={religion: 0.1}, acceptance={religion: acceptance}
    )
    assert pdx_eval.condition(query, facts) is False
    assert pdx_eval.condition(query, {}) is None
    metrics = resources.pdx_metrics(compiled_queries[mode].expression)
    assert metrics["object_scan_sites"] == metrics["persistent_write_sites"] == 0
    assert metrics["assignment_nodes"] <= 500
    assert metrics["block_nodes"] <= 110
    assert metrics["max_depth"] <= 7
    assert len(compiled_queries[mode].expression.encode()) <= 45000
    assert "sha256:" + channels.MANIFEST_SHA256 in "\n".join(compiled_queries[mode].references)
    assert "306" in compiled_queries[mode].runtime_cost
    assert "Pop" not in compiled_queries[mode].expression


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("AND", {"culture_query": MODES[0]}),
        ("OR", {"culture_query": MODES[0], "category": "heritage"}),
        ("OR", {"culture_query": MODES[0], "target": "scope:target_country"}),
        ("OR", {"culture_query": MODES[1], "threshold": "0"}),
        ("OR", {"culture_query": "state_atheism_any_transition"}),
    ],
)
def test_closed_shape_rejects_unreviewed_query_authority(engine, parameters):
    with pytest.raises(ValueError, match="宗教暴露"):
        observation_queries.from_reader(engine, parameters)


def test_manifest_raw_current_dictionary_drift_and_invalid_identity_fail(monkeypatch, tmp_path):
    _, dictionary = channels.snapshot()
    invalid_identities: tuple[Any, ...] = (None, "not_a_religion", "rel:catholic", "scope:religion")
    for invalid in invalid_identities:
        with pytest.raises(ValueError, match="字典外"):
            dictionary.category(invalid, "catholic")
        with pytest.raises(ValueError, match="字典外"):
            dictionary.category("catholic", invalid)
    for source in (channels.RELIGION, channels.HERITAGE, channels.GROUP):
        inputs = culture.frozen_inputs()
        inputs[source] += "\n# drift\n"
        with pytest.raises(ValueError, match="漂移"):
            channels.verify_inputs(inputs)
    raw = channels.MANIFEST.read_bytes()
    path = tmp_path / "manifest.json"
    path.write_bytes(raw + b"\n")
    monkeypatch.setattr(channels, "MANIFEST", path)
    with pytest.raises(ValueError, match="字节漂移"):
        channels.snapshot()
    data = json.loads(raw)
    data["channel_order"] = ["state", "group", "heritage", "other"]
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(channels, "MANIFEST_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="四互斥通道"):
        channels.snapshot()


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    # Real production loader, source-specific policy and shared ScalarProgram.
    # No model, fabricated consumer binding, direct writer, or fresh game read.
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[culture.SOURCE]
    rules = tuple(rule for rule in original.rules if ".".join(rule.field) == culture.FIELD)
    used = {key for rule in rules for key in rule.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=culture.SOURCE)
    decision_interfaces.validate(policy)
    # Existing complete frozen production inputs supply ordinary authority,
    # crisis and typed-law vocabulary. This reads no installation or executable.
    frozen_raw = (
        culture.config.REPO / "research/vanilla-ai/1.15.0/production-inputs.json"
    ).read_bytes()
    frozen = json.loads(frozen_raw)
    inputs = {name: normalized_text(text) for name, text in frozen["inputs"].items()}
    for name, text in inputs.items():
        assert (
            hashlib.sha256(text.encode()).hexdigest()
            == frozen["source_identities"][name]["normalized_sha256"]
        )
    inputs.update(culture.frozen_inputs())
    native = inputs[culture.SOURCE]
    text = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(decision_adapters.reader_evidence(inputs))
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    evidence = tmp_path_factory.mktemp("religion-mixed")
    (evidence / "generated-church-and-state.txt").write_text(text, encoding="utf-8", newline="\n")
    query_metrics = {}
    for mode in MODES:
        expression = culture.render_query(culture.ReligiousExposureQuery(mode))
        query_metrics[mode] = {
            **resources.pdx_metrics(expression),
            "script_bytes": len(expression.encode()),
        }
    receipt = {
        "evidence": "static_normal_adapter_parser_scalar_program_writer_no_model_no_engine",
        "production_input_snapshot_sha256": hashlib.sha256(frozen_raw).hexdigest(),
        "native_law_sha256": hashlib.sha256(native.encode()).hexdigest(),
        "generated_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "generated_metrics": resources.pdx_metrics(text),
        "query_metrics": query_metrics,
        "new_rules": [
            {
                "id": r.id,
                "semantic_role": r.semantic_role,
                "contribution_group": r.contribution_group,
            }
            for r in policy.rules
            if r.id.startswith("culture_mixed_")
        ],
    }
    (evidence / "generated-readback.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return policy, native, text


def witness(
    generated,
    *,
    origin=ORIGINS[0],
    need=True,
    state=True,
    group=True,
    current=None,
    core_unknown=False,
    ai=True,
    authority=300,
    crisis=False,
):
    policy, _native, text = generated
    current = origin if current is None else current
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        for prefix in ("culture_current_", "law_context_current_"):
            if key.startswith(prefix):
                law = key.removeprefix(prefix)
                values[key] = (
                    None
                    if core_unknown
                    else (law == current or (law == culture.ORIGIN and current in culture.VARIANTS))
                )
    values.update(
        authority=authority,
        legitimacy=20 if crisis else 60,
        radical_share=0.3 if crisis else 0,
        insurrection=crisis,
        culture_channel_benefit_exposure=need,
        culture_nonstate_religious_exposure=need,
        culture_state_religious_protection_exposure=state,
        culture_shared_group_protection_exposure=group,
    )
    facts = _facts(policy, values, is_ai=ai)
    facts["ROOT"].update(
        _religious_facts(
            shares={
                "protestant": 0.1 if need else 0,
                "sunni": 0.1 if group else 0,
                "catholic": 0.7 if state else 0,
            },
            acceptance={"protestant": -1, "sunni": 10, "catholic": 25},
        )
    )
    for enabled, name in ((need, "protestant"), (state, "catholic"), (group, "sunni")):
        if enabled is None:
            facts["ROOT"]["religion_percent_country"][(("target", f"rel:{name}"),)] = None
    facts["ROOT"]["any_political_movement"] = []
    actual = pdx_eval.select(_overlay(text, culture.FIELD), facts).delta
    secondary = decision_rules.evaluate(policy, values, is_ai=ai).get(
        culture.FIELD, ("neutral", 0)
    )[1]
    return actual, secondary, facts, values


@pytest.mark.parametrize("origin", ORIGINS)
@pytest.mark.parametrize(
    ("kwargs", "millet", "people"),
    [
        ({}, -2, 2),  # +6 -4 state -4 group (millet only).
        ({"need": False}, -8, -4),
        ({"state": False}, 2, 6),
        ({"group": False}, 2, 2),
        ({"need": False, "state": False}, -4, 0),
        ({"state": False, "group": False}, 6, 6),
        ({"need": False, "group": False, "state": False}, 0, 0),
        ({"need": None}, -8, -4),
        ({"state": None}, -2, 2),  # Existing explicit local conservative state cost.
        ({"group": None}, 2, 2),  # No conservative/group/global penalty.
        ({"need": None, "state": False, "group": None}, 0, 0),
        ({"current": "law_freedom_of_conscience"}, 0, 0),
        ({"core_unknown": True}, 0, 0),
        ({"ai": False}, 0, 0),
        ({"authority": 99}, -10, -6),
        ({"authority": 99, "crisis": True}, -20, -16),
    ],
)
def test_literal_roles_unknown_zero_and_joint_costs(generated, origin, kwargs, millet, people):
    expected = millet if origin == ORIGINS[0] else people
    actual, secondary, *_ = witness(generated, origin=origin, **kwargs)
    assert actual == expected
    assert secondary == expected


@pytest.mark.parametrize(("origin", "entry"), [(ORIGINS[0], -2), (ORIGINS[1], 2)])
def test_enter_adopt_exit_reenter_unknown_and_restored_ast(generated, origin, entry):
    for kwargs, expected in (
        ({}, entry),
        ({"current": "law_freedom_of_conscience"}, 0),
        ({"need": False}, entry - 6),
        ({"need": False, "state": False, "group": False}, 0),
        ({"state": False, "group": False}, 6),
        ({"core_unknown": True}, 0),
        ({}, entry),
    ):
        assert witness(generated, origin=origin, **kwargs)[:2] == (expected, expected)
    policy, native, text = generated
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    _actual, _reference, _facts_value, values = witness(generated, origin=origin)
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]


@pytest.mark.parametrize(("origin", "delta"), [(ORIGINS[0], -2), (ORIGINS[1], 2)])
def test_full_native_numeric_journal_tail_and_player(generated, origin, delta):
    _policy, _native, text = generated
    actual, secondary, facts, _values = witness(generated, origin=origin)
    assert actual == secondary == delta
    facts["ROOT"].update(
        ai_has_enact_weight_modifier_journal_entries=True,
        has_journal_entry={
            (("argument", "je_sick_man_education"),): True,
            (("argument", "je_shinbutsu_bunri"),): False,
        },
    )
    body = _block(
        _block(parse_text(text).root, "law_freedom_of_conscience"), "ai_enact_weight_modifier"
    )
    expression = "\n".join(_render(item) for item in body.assignments())
    projected = (
        "# ACTION full_native [native]; complete locked law\nif = { limit = { always = yes } add = { "
        + expression
        + " } }"
    )
    assert pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta == 1750 + delta
    player = copy.deepcopy(facts)
    player["ROOT"]["is_ai"] = False
    assert pdx_eval.select(projected, {**player["ROOT"], **player}).delta == 1750


def test_exact_four_deltas_and_no_zero_channel_rule(generated):
    culture.verify_inputs(culture.frozen_inputs())
    for origin, expected in zip(ORIGINS, ((-5, 5, -5, 25), (-5, 10, 0, 25)), strict=True):
        assert (
            tuple(
                b - a
                for a, b in zip(
                    culture.EFFECTS[origin], culture.EFFECTS[culture.CANDIDATE], strict=True
                )
            )
            == expected
        )
    derived = culture.derive({})
    new = [r for r in derived["rules"] if r["id"].startswith("culture_mixed_")]
    assert len(new) == 5
    assert sorted(r["semantic_role"] for r in new) == ["benefit", "benefit", "cost", "cost", "cost"]
    assert not any(ORIGINS[1] in r["id"] and r["id"].endswith("group_loss") for r in new)
    group = next(r for r in new if r["id"].endswith("group_loss"))
    assert "conservative_unknown_facts" not in group
    # Category metadata never acts as a second scorer or persistent authority.
    policy, _native, _text = generated
    assert policy.semantic_ir
    assert channels.MANIFEST.read_bytes() in culture.proof_dependency_bytes()
    assert channels.MANIFEST_SHA256 in "\n".join(culture.verify_inputs(culture.frozen_inputs()))


def test_budget_enforced_not_just_reported(monkeypatch):
    monkeypatch.setattr(channels, "MAX_PREDICATES", 0)
    with pytest.raises(ValueError, match="预算"):
        channels.exposure(("heritage", "other"), loss=False)
    with pytest.raises(ValueError, match="只授权"):
        channels.exposure(("state",), loss=True)


def test_repinned_manifest_cannot_rewrite_accepted_native_proof(monkeypatch, tmp_path):
    data = json.loads(channels.MANIFEST.read_bytes())
    data["native"]["exe_sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(channels, "MANIFEST", path)
    monkeypatch.setattr(channels, "MANIFEST_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="完整证明内容漂移"):
        channels.snapshot()
