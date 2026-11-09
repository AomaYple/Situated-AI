"""A1 纯合同边界：拒绝伪造已知值、对象串接和跨次求值复用。"""

from dataclasses import FrozenInstanceError, replace

import pytest

from pdx.situated import core_contracts as c
from pdx.situated.decision_ir import ConsumerIRBundle, ContextBinding, EvaluationContext


def evidence():
    return c.EvidenceRef("common/ai/test.txt", 4)


def fact():
    return c.FactSpec(
        "finance.income",
        "income",
        "number",
        "currency_per_week",
        "country",
        "actor",
        ("finance.consumer",),
        (evidence(),),
    )


def observation(**changes):
    item = c.Observation(
        "finance.income",
        c.EntityKey("country", "FRA"),
        "currency_per_week",
        "known",
        c.TimeIdentity("game_session", 3),
        10.0,
        (evidence(),),
    )
    return replace(item, **changes)


def consumer():
    binding = ContextBinding("root", "country", "actor", "common/ai/test.txt", 4)
    context = EvaluationContext(binding, evidence=("common/ai/test.txt:4",))
    return c.ConsumerSpec(
        "finance.consumer",
        "common/ai/test.txt",
        "test_strategy",
        ("score",),
        context,
        "add",
        "consumer_score",
        0.0,
        (-10.0, 10.0),
        ("preserve_vanilla_tail",),
        "native_score_comparator",
        "native_candidate_set",
        "native_eligibility",
        "native_tie",
        "native_random",
        "native_all_zero",
        "vanilla",
        evidence(),
        "finance.schedule",
    )


def schedule():
    return c.EvaluationSchedule("finance.schedule", "finance.consumer", (evidence(),))


def test_contract_mapping_roundtrip_preserves_typed_immutable_values():
    original = fact()
    decoded = c.FactSpec.from_mapping(original.as_dict())
    assert decoded == original
    with pytest.raises(FrozenInstanceError):
        decoded.id = "changed"
    with pytest.raises(ValueError, match="tuple"):
        replace(original, consumer_ids=["finance.consumer"])


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": 1},
        {"schema_version": 2},
        {"kind": "imaginary"},
        {"minimum": float("nan")},
        {"maximum": float("inf")},
        {"minimum": True},
        {"sources": [{"source": "a", "line": 1, "surprise": 0}]},
    ],
)
def test_strict_mapping_rejects_unknown_schema_enum_and_nonfinite(change):
    data = fact().as_dict()
    data.update(change)
    with pytest.raises(ValueError):
        c.FactSpec.from_mapping(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "ratio"},
        {"value": float("nan")},
        {"value": True},
        {"entity": c.EntityKey("state", "FRA")},
        {"time": c.TimeIdentity("game_session", 2)},
        {"spec_id": "finance.other"},
    ],
)
def test_observation_binding_rejects_wrong_unit_object_time_and_value(changes):
    with pytest.raises(ValueError):
        fact().validate_observation(
            observation(**changes),
            actor=c.EntityKey("country", "FRA"),
            target=None,
            consumer_id="finance.consumer",
            time=c.TimeIdentity("game_session", 3),
        )


@pytest.mark.parametrize("state", ["unknown", "stale", "unsupported"])
def test_missing_or_old_evidence_never_becomes_known_zero(state):
    item = observation(status=state, value=None)
    assert not item.usable_at(c.TimeIdentity("game_session", 3))
    fact().validate_observation(
        item,
        actor=item.entity,
        target=None,
        consumer_id="finance.consumer",
        time=item.time,
    )


def test_invalid_input_fails_instead_of_becoming_unknown():
    with pytest.raises(ValueError, match="invalid"):
        observation(status="invalid")
    with pytest.raises(ValueError, match="known"):
        observation(value=None)
    with pytest.raises(ValueError, match="unknown"):
        observation(status="unknown")


def test_snapshot_is_only_valid_for_exact_consumer_evaluation():
    item = observation()
    snap = c.SituationSnapshot(
        item.entity,
        None,
        "finance.consumer",
        item.time,
        "country",
        (item,),
        "finance.schedule",
    )
    snap.validate((fact(),), schedule())
    assert snap.usable_at(item.time)
    assert not snap.usable_at(c.TimeIdentity("game_session", 4))
    assert schedule().runtime_status == "unknown"
    with pytest.raises(ValueError):
        replace(snap, observations=(observation(time=c.TimeIdentity("other", 3)),))
    with pytest.raises(ValueError):
        replace(schedule(), ttl="monthly")


def test_objective_requires_source_current_baseline_and_real_consumer_wiring():
    base = observation()
    objective = c.InterestSpec(
        "finance.solvency",
        base.entity,
        None,
        (base.spec_id,),
        base.time,
        c.TimeIdentity("game_session", 8),
        base,
        (),
        ("finance.consumer",),
        "known",
    )
    assert isinstance(objective, c.ActorObjectiveSpec)
    with pytest.raises(ValueError):
        replace(objective, source_fact_ids=())
    with pytest.raises(ValueError):
        replace(objective, consumer_ids=())
    with pytest.raises(ValueError):
        replace(objective, deadline=c.TimeIdentity("game_session", 2))
    with pytest.raises(ValueError):
        replace(objective, actor=c.EntityKey("country", "GER"))


def test_consumer_algebra_and_selection_stay_in_one_native_comparison():
    native = consumer()
    candidate = c.EntityKey("country", "FRA")
    witness = c.SelectionWitness(
        native.id,
        (candidate,),
        (candidate,),
        native.comparator,
        ("finance.solvency",),
        native.unknown_policy,
        native.neutral,
        native.tie_break,
        native.random,
        native.all_zero,
        native.baseline,
    )
    witness.validate(native)
    with pytest.raises(ValueError):
        replace(native, operation="multiply")
    with pytest.raises(ValueError):
        replace(witness, consumer_id="military.consumer").validate(native)
    with pytest.raises(ValueError):
        replace(witness, eligible=(c.EntityKey("country", "GER"),))


def test_contract_attachment_keeps_existing_bundle_and_rejects_unmatched_writer():
    bundle = ConsumerIRBundle(1, (), ())
    contracts = c.CoreContracts((fact(),), (consumer(),), (schedule(),))
    attached = c.attach_bundle(bundle, contracts)
    assert attached.bundle is bundle
    assert attached.contracts.consumers[0].id == "finance.consumer"
    assert attached.production_connected is False
    with pytest.raises(ValueError):
        replace(contracts, schedules=())


def test_localization_uses_exact_verified_languages_keys_and_placeholders():
    entries = (
        c.LocalizationEntry(
            "english",
            "sitai_help",
            "$COUNTRY$ help",
            "l_english:",
            "localization/english/sitai_l_english.yml",
        ),
        c.LocalizationEntry(
            "french",
            "sitai_help",
            "$COUNTRY$ aide",
            "l_french:",
            "localization/french/sitai_l_french.yml",
        ),
    )
    contract = c.LocalizationContract(("english", "french"), evidence(), ("sitai_help",), entries)
    assert c.LocalizationContract.from_mapping(contract.as_dict()) == contract
    with pytest.raises(ValueError):
        replace(contract, entries=entries[:1])
    with pytest.raises(ValueError):
        replace(contract, entries=(entries[0], replace(entries[1], text="$OTHER$ aide")))
    with pytest.raises(ValueError):
        replace(contract, languages=("english",))
    with pytest.raises(ValueError):
        replace(entries[0], path="../escape.yml")
