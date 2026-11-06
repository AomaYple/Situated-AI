"""Exact additions supporting the current consumer batch budget."""

import tomllib
from collections import Counter
from pathlib import Path

import pytest

from pdx import decision_adapters
from pdx.decision_rules import Predicate, Reader, Rule, RuleSet
from pdx.situated import consumer_ports, ports
from pdx.situated.decision_ir import ContextBinding, EvaluationContext

LAW = "common/laws/00_church_and_state.txt"
TECH = "common/technology/technologies/10_production.txt"
SECURITY = "common/laws/00_internal_security.txt"
LOW_RESISTANCE = {"law_national_guard", "law_guaranteed_liberties"}
HIGH_RESISTANCE = {"law_secret_police", "law_extraordinary_commission"}
COUP = {
    f"internal_security_{candidate}_from_{origin}_coup_resistance"
    for origins, candidates in (
        (LOW_RESISTANCE, HIGH_RESISTANCE),
        (HIGH_RESISTANCE, LOW_RESISTANCE),
    )
    for origin in origins
    for candidate in candidates
}
MIXED = "culture_mixed_"
READY = {
    "technology_compression_ignition_labor_ready",
    "technology_compression_ignition_productive_ready",
    "technology_mechanized_workshops_productive_ready",
}
ATHEISM = "culture_law_state_atheism_to_law_total_separation_observed_exposure"


def test_delta_writers_and_readers_match_finite_production_rules():
    policies = dict(decision_adapters.load().policies)
    rules = [
        (s, r)
        for s, p in policies.items()
        for r in p.rules
        if r.id.startswith(MIXED) or r.id in READY or r.id == ATHEISM or r.id in COUP
    ]
    expected_mixed = {
        f"culture_mixed_{law}_to_law_freedom_of_conscience_{kind}"
        for law, kinds in (
            ("law_millet_system", ("benefit", "state_loss", "group_loss")),
            ("law_people_of_the_book", ("benefit", "state_loss")),
        )
        for kind in kinds
    }
    assert {(s, r.id) for s, r in rules} == {(LAW, i) for i in expected_mixed} | {
        (TECH, i) for i in READY
    } | {(LAW, ATHEISM)} | {(SECURITY, i) for i in COUP}
    assert Counter((s, ".".join(r.field), len(r.conditions)) for s, r in rules) == {
        (LAW, "law_freedom_of_conscience.ai_enact_weight_modifier", 6): 5,
        (TECH, "compression_ignition.ai_weight", 1): 2,
        (TECH, "mechanized_workshops.ai_weight", 1): 1,
        (LAW, "law_total_separation.ai_enact_weight_modifier", 3): 1,
        (SECURITY, "law_secret_police.ai_enact_weight_modifier", 4): 2,
        (SECURITY, "law_extraordinary_commission.ai_enact_weight_modifier", 4): 2,
        (SECURITY, "law_national_guard.ai_enact_weight_modifier", 4): 1,
        (SECURITY, "law_national_guard.ai_enact_weight_modifier", 7): 1,
        (SECURITY, "law_guaranteed_liberties.ai_enact_weight_modifier", 4): 1,
        (SECURITY, "law_guaranteed_liberties.ai_enact_weight_modifier", 7): 1,
    }
    facts = {p.fact for _, r in rules for p in r.conditions}
    assert {f for f in facts if f.startswith("technology_use_")} == {
        "technology_use_compression_ignition_labor_ready",
        "technology_use_compression_ignition_productive_ready",
        "technology_use_mechanized_workshops_productive_ready",
    }
    assert {
        f
        for f in facts
        if f in {"culture_channel_benefit_exposure", "culture_shared_group_protection_exposure"}
    } == {"culture_channel_benefit_exposure", "culture_shared_group_protection_exposure"}
    atheism = next(rule for source, rule in rules if rule.id == ATHEISM)
    assert atheism.conditions == (
        Predicate("culture_current_law_state_atheism", "=", True),
        Predicate("culture_current_law_total_separation", "=", False),
        Predicate("culture_atheism_nonstate_exposure", "=", True),
    )
    readers = {reader.key: reader for reader in policies[LAW].readers}
    exposure = readers["culture_atheism_nonstate_exposure"]
    assert (exposure.engine, exposure.scope, exposure.unit, exposure.kind) == (
        "OR",
        "root",
        "boolean",
        "boolean",
    )
    assert exposure.parameters == (("culture_query", "atheism_nonstate_exposure"),)
    # This new name aliases an existing getter observation; it is not a second
    # new origin. The exposure query is the sole additional observation.
    state = readers["culture_current_law_state_atheism"]
    assert any(
        other.key != state.key and ports.reader_signature(other) == ports.reader_signature(state)
        for other in readers.values()
    )
    security_readers = {reader.key: reader for reader in policies[SECURITY].readers}
    coup = security_readers["security_active_coup_positive_resistance"]
    assert (coup.engine, coup.scope, coup.unit, coup.kind) == ("AND", "root", "boolean", "boolean")
    assert coup.parameters == (("security_query", "active_coup_positive_resistance"),)
    for source, rule in rules:
        if source == SECURITY:
            assert rule.contribution_group == "law_security_actual_coup_resistance"
            assert Predicate("home_affairs_investment", ">=", 1) in rule.conditions
            assert (
                Predicate("security_active_coup_positive_resistance", "=", True) in rule.conditions
            )
    for source, field in (
        (TECH, "compression_ignition.ai_weight"),
        (TECH, "mechanized_workshops.ai_weight"),
        (LAW, "law_freedom_of_conscience.ai_enact_weight_modifier"),
        (LAW, "law_total_separation.ai_enact_weight_modifier"),
        *(
            (SECURITY, f"{law}.ai_enact_weight_modifier")
            for law in LOW_RESISTANCE | HIGH_RESISTANCE
        ),
    ):
        assert (
            sum(len(r.conditions) for r in policies[source].rules if ".".join(r.field) == field)
            <= 160
        )


def test_selector_rejects_further_cap_expansion():
    path = Path(__file__).resolve().parents[1] / "mod/decisions/consumer_ports.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert len(consumer_ports.selected_proven_consumers(data)) == 965
    for key in data["hard_cap"]:
        modified = {**data, "hard_cap": {**data["hard_cap"], key: data["hard_cap"][key] + 1}}
        with pytest.raises(ValueError, match="cap"):
            consumer_ports.selected_proven_consumers(modified)


@pytest.mark.parametrize("count", [160, 161])
def test_total_cap_revision_preserves_local_predicate_boundary(count):
    source = "fixture/consumer.txt"
    reader = Reader("known", "is_great_power", "root", "boolean", "boolean")
    rules = tuple(
        Rule(
            f"rule_{i}",
            "economy",
            ("field",),
            i,
            1.1,
            (Predicate("known", "=", True),),
            "test",
            "test",
        )
        for i in range(count)
    )
    policy = RuleSet((reader,), rules, "1" * 64, "2" * 64, frozenset({"economy"}))
    context = EvaluationContext(
        ContextBinding("root", "country", "actor", "fixture/native.txt", 1),
        evidence=("fixture/native.txt:1",),
    )

    def derive_batch():
        return consumer_ports.derive(
            ((source, policy),),
            selected_consumers={(source, "field")},
            contexts={(source, r.id): context for r in rules},
            reader_bindings={
                (source, r.id): (("known", "root", "country", "actor"),) for r in rules
            },
            source_proofs={source: ("fixture/getter.txt:1",)},
            hard_cap={"ports": 4737, "origins": 2290, "uses": 6152, "partitions": 965},
        )

    if count == 161:
        with pytest.raises(ValueError, match="predicate"):
            derive_batch()
    else:
        assert derive_batch().uses_count == 160
