"""Reader aliases retain their complete observation identity across sources."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules, version_contracts
from pdx.parser import parse_text
from pdx.situated import compiler, evidence, pdx_eval
from pdx.situated.schema import EvidenceSpec, EvidenceValue

pytestmark = pytest.mark.unit


def _sources(monkeypatch, first, second=()):
    information = decision_rules.RuleSet(tuple(first), (), "", "", frozenset())
    policy = decision_rules.RuleSet(tuple(second), (), "", "", frozenset())
    adapters = decision_adapters.AdapterSet((), (("other_source", policy),), "")
    monkeypatch.setattr(compiler.decision_rules, "load", lambda: information)
    monkeypatch.setattr(compiler.decision_adapters, "load", lambda: adapters)


_NUMBER = decision_rules.Reader("observation", "legitimacy", "root", "points", "number")
_BOOL = decision_rules.Reader("observation", "is_at_war", "root", "boolean", "boolean")


@pytest.fixture(scope="module")
def frozen_model_and_government_policy():
    source = "common/buildings/07_government.txt"
    return compiler.load_model(), source, dict(decision_adapters.load().policies)[source]


@pytest.mark.parametrize(
    "damage",
    [
        {"argument": "empiricism"},
        {"path": ()},
        {"scope": "target_country"},
        {"parameters": (("TECHNOLOGY", "empiricism"),)},
        {"value_field": "value"},
        {"minimum": 0},
        {"maximum": 1},
        {"unit": "ratio"},
    ],
)
def test_compilation_cannot_replace_reader_after_ir_was_frozen(
    frozen_model_and_government_policy, damage
):
    model, source, policy = frozen_model_and_government_policy
    key = "state_owner_academia_completed"
    changed = replace(
        policy,
        readers=tuple(
            replace(reader, **damage) if reader.key == key else reader for reader in policy.readers
        ),
    )
    with pytest.raises(ValueError, match=r"reader.*身份.*不一致"):
        compiler.compile_policy(changed, source, model)


@pytest.mark.parametrize("path", [("owner", "market"), ("other_country",), ()])
def test_compilation_cannot_replace_actor_path_after_ir_was_frozen(
    frozen_model_and_government_policy, path
):
    model, source, policy = frozen_model_and_government_policy
    changed = replace(policy, actor_path=path)
    with pytest.raises(ValueError, match=r"actor.*路径.*不一致"):
        compiler.compile_policy(changed, source, model)


@pytest.mark.parametrize(
    "damage",
    [
        {"engine": "bureaucracy"},
        {"path": ("owner",)},
        {"argument": "law_serfdom"},
        {"parameters": (("goods", "grain"),)},
        {"value_field": "value"},
        {"kind": "boolean"},
        {"minimum": 0},
        {"maximum": 100},
        {"scope": "target_country"},
        {"unit": "ratio"},
    ],
    ids=lambda damage: next(iter(damage)),
)
def test_same_key_rejects_complete_reader_identity_drift(monkeypatch, damage):
    _sources(monkeypatch, (_NUMBER,), (replace(_NUMBER, **damage),))
    with pytest.raises(ValueError, match=r"observation.*reader.*不一致"):
        compiler._reader_facts(())


def test_same_observation_reused_by_sources_is_legal(monkeypatch):
    _sources(monkeypatch, (_NUMBER,), (_NUMBER, _NUMBER))
    facts = compiler._reader_facts(())
    assert len(facts) == 1
    assert facts[0].trigger == "legitimacy"


def test_flag_and_boolean_units_are_semantically_identical(monkeypatch):
    _sources(monkeypatch, (_BOOL,), (replace(_BOOL, unit="flag"),))
    assert len(compiler._reader_facts(())) == 1


def test_parameter_order_does_not_change_observation(monkeypatch):
    first = replace(_BOOL, parameters=(("goods", "grain"), ("country", "ROOT")))
    _sources(monkeypatch, (first,), (replace(first, parameters=tuple(reversed(first.parameters))),))
    assert len(compiler._reader_facts(())) == 1


def _declared(**changes):
    fact = EvidenceSpec(
        "observation",
        "military",
        "declared_source",
        "root",
        "boolean",
        "flag",
        "consumer",
        "vanilla",
        "is_at_war = yes",
    )
    return replace(fact, **changes)


@pytest.mark.parametrize(
    "damage",
    [
        {"trigger": "in_default = yes"},
        {"trigger": "is_at_war = no"},
        {"kind": "number"},
        {"minimum": 0},
        {"maximum": 1},
    ],
    ids=lambda damage: next(iter(damage)),
)
def test_declared_fact_cannot_shadow_a_different_reader(monkeypatch, damage):
    _sources(monkeypatch, (_BOOL,))
    with pytest.raises(ValueError, match=r"observation.*reader.*不一致"):
        compiler._reader_facts((_declared(**damage),))


def test_declared_fact_can_reuse_same_observation_with_own_provenance(monkeypatch):
    _sources(monkeypatch, (_BOOL,))
    declared = _declared(trigger="is_at_war=yes")
    assert compiler._reader_facts((declared,)) == (declared,)


@pytest.mark.parametrize(
    "damage",
    [
        {"path": ("owner",)},
        {"argument": "law_serfdom"},
        {"parameters": (("goods", "grain"),)},
        {"value_field": "value"},
    ],
    ids=lambda damage: next(iter(damage)),
)
def test_flat_declared_fact_cannot_flatten_structured_reader(monkeypatch, damage):
    _sources(monkeypatch, (replace(_BOOL, **damage),))
    with pytest.raises(ValueError, match=r"observation.*reader.*不一致"):
        compiler._reader_facts((_declared(),))


def test_declared_numeric_limits_must_equal_reader_limits(monkeypatch):
    _sources(monkeypatch, (replace(_NUMBER, minimum=0),))
    declared = _declared(kind="number", unit="points", trigger="legitimacy")
    with pytest.raises(ValueError, match=r"observation.*reader.*不一致"):
        compiler._reader_facts((declared,))
    assert compiler._reader_facts((replace(declared, minimum=0),))[0].minimum == 0


@pytest.mark.parametrize("name", ["stable_legitimacy", "strong_legitimacy"])
def test_legitimacy_threshold_is_a_boolean_fact_not_raw_points(name):
    facts = {fact.id: fact for fact in evidence.load(compiler.FACTS)}
    assert (facts[name].kind, facts[name].unit) == ("boolean", "flag")
    assert facts[name].minimum is facts[name].maximum is None


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    return model, compiler.strategy_overlay(model)


@pytest.mark.parametrize("ig", [False, True, None], ids=["ig_false", "ig_true", "ig_unknown"])
@pytest.mark.parametrize(
    "ongoing", [False, True, None], ids=["ongoing_false", "ongoing_true", "ongoing_unknown"]
)
def test_ongoing_insurrection_and_insurrectionary_ig_are_independent(production, ig, ongoing):
    model, overlays = production
    facts = {fact.id: fact for fact in model.facts}
    assert facts["insurrection"].trigger == "has_insurrectionary_interest_groups = yes"
    assert facts["ongoing_insurrection"].trigger == "any_insurrection_ongoing = yes"
    assert facts["no_insurrection"].trigger == "any_insurrection_ongoing = no"
    engine = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "legitimacy": 80,
        "has_insurrectionary_interest_groups": ig,
        "any_insurrection_ongoing": ongoing,
    }
    # Each assertion uses its actual production predicate, including divergent
    # True/False values; one observation may never fill the other's unknown.
    for name, expected in (("insurrection", ig), ("ongoing_insurrection", ongoing)):
        assert pdx_eval.condition(parse_text(facts[name].trigger).root, engine) is expected
    values = {
        "peace": True,
        "war": False,
        "default": False,
        "no_default": True,
        "no_insurrection": not ongoing if type(ongoing) is bool else None,
        "ongoing_insurrection": ongoing,
        "insurrection": ig,
        "stable_legitimacy": True,
        "strong_legitimacy": True,
        "legitimacy": 80,
    }
    reference = compiler.evaluate_actions(model, values, is_ai=True)
    for field, selected in (
        ("max_progressiveness", ongoing is False),
        ("max_regressiveness", ongoing is True),
    ):
        generated = pdx_eval.select(overlays[field], engine)
        if selected:
            assert reference[field][1] == generated.delta == 5
            assert reference[field][0] == generated.action_id
        else:
            assert field not in reference
            assert generated.delta == 0
            if ongoing is None:
                # Unknown belongs to the local contribution; the joint program
                # still executes its neutral result without inventing a fact.
                assert generated.action_id == f"joint_{field}"
                assert generated.operation == "add"


@pytest.mark.parametrize(
    ("legitimacy", "stable", "strong", "delta"),
    [
        (49, False, False, 0),
        (50, True, False, 4),
        (74.99, True, False, 4),
        (75, True, True, 5),
        (None, None, None, 0),
    ],
)
def test_boolean_threshold_boundaries_and_unknown_match_actual_pdx(
    production, legitimacy, stable, strong, delta
):
    model, overlays = production
    values = {
        "peace": True,
        "war": False,
        "default": False,
        "no_default": True,
        "no_insurrection": True,
        "ongoing_insurrection": False,
        "stable_legitimacy": stable,
        "strong_legitimacy": strong,
        "legitimacy": legitimacy,
    }
    engine = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": legitimacy,
    }
    field = "max_progressiveness"
    reference = compiler.evaluate_actions(model, values, is_ai=True)
    generated = pdx_eval.select(overlays[field], engine)
    assert generated.delta == delta
    if delta:
        assert reference[field] == (f"joint_{field}", delta)
    else:
        assert field not in reference
        assert generated.action_id == f"joint_{field}"
        assert generated.operation == "add"


@pytest.mark.parametrize("bad", [50, 75, 1.0, "yes", None])
def test_raw_points_cannot_impersonate_boolean_legitimacy_fact(production, bad):
    model, _ = production
    action = next(card for card in model.actions if card.id == "reform_progressive_window")
    values = {
        "peace": True,
        "no_insurrection": True,
        "default": False,
        "stable_legitimacy": bad,
        "strong_legitimacy": False,
    }
    assert compiler._action_conditions(action, values) is None


@pytest.mark.parametrize(
    ("name", "engine", "samples"),
    [
        ("bureaucracy_positive", "bureaucracy", [(-0.01, False), (0, False), (0.01, True)]),
        ("literacy_low", "literacy_rate", [(0.49, True), (0.5, False), (0.51, False)]),
        ("stable_legitimacy", "legitimacy", [(49, False), (50, True), (51, True)]),
        ("strong_legitimacy", "legitimacy", [(74, False), (75, True), (76, True)]),
    ],
)
def test_predicate_fact_evidence_retains_truth_not_raw_numeric_units(name, engine, samples):
    fact = next(item for item in evidence.load(compiler.FACTS) if item.id == name)
    assert (fact.kind, fact.unit) == ("boolean", "flag")
    predicate = parse_text(fact.trigger).root
    for raw, expected in [*samples, (None, None)]:
        observed = pdx_eval.condition(predicate, {engine: raw})
        value = EvidenceValue(name, observed, observed is not None, provenance=fact.trigger)
        assert value.value is expected
        assert value.known is (expected is not None)
        assert type(value.value) is bool if value.known else value.value is None


def test_every_declared_predicate_has_boolean_metadata_and_raw_reader_is_numeric():
    facts = evidence.load(compiler.FACTS)
    for fact in facts:
        has_comparison = any(op in fact.trigger for op in ("=", "<", ">"))
        if has_comparison:
            assert fact.kind == "boolean", fact.id
            assert fact.unit in {"flag", "boolean"}, fact.id
        else:
            assert fact.kind in {"number", "ratio"}, fact.id
    raw = {reader.key: reader for reader in decision_rules.load().readers}
    assert raw["bureaucracy"].kind == "number"
    assert raw["bureaucracy"].engine == "bureaucracy"
    if version_contracts.active_version() == "1.15.1":
        assert "literacy" not in raw
        from pdx.situated import network_profile, production_profile

        profile = production_profile.load_profile(production_profile.baseline_root())
        school = next(
            p
            for p in network_profile.compile_profile(profile)
            if p.network.actions[0].definition.consumer_id == "a0-pol-schools"
        )
        literacy = next(f for f in school.network.facts if f.id == "literacy")
        assert (literacy.kind, literacy.unit) == ("ratio", "ratio")
    else:
        assert raw["literacy"].kind == "number"
        assert raw["literacy"].engine == "literacy_rate"


@pytest.mark.parametrize(
    ("kind", "unit"), [("number", "points"), ("ratio", "ratio"), ("boolean", "points")]
)
def test_predicate_metadata_drift_is_rejected_before_production_use(monkeypatch, kind, unit):
    _sources(monkeypatch, ())
    malformed = _declared(kind=kind, unit=unit, trigger="legitimacy >= 50")
    with pytest.raises(ValueError, match="比较结果必须是布尔值"):
        compiler._reader_facts((malformed,))
