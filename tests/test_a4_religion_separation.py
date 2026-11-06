"""Literal oracle through actual adapters, ScalarPrograms and independent PDX."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

import pytest
from religion_separation_reference import NAMES, category, score
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
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs, resources
from pdx.textio import normalized_text

FIELD = "law_total_separation.ai_enact_weight_modifier"
PREFIX = "culture_law_freedom_of_conscience_to_law_total_separation_"


@pytest.fixture(scope="module")
def candidate():
    return culture


@pytest.fixture(scope="module")
def generated(candidate, tmp_path_factory):
    # Real complete loader first; filter one existing consumer only after load.
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[candidate.SOURCE]
    rules = tuple(r for r in original.rules if ".".join(r.field) == FIELD)
    keys = {k for rule in rules for k in rule.input_keys()}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in keys),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=candidate.SOURCE)
    decision_interfaces.validate(policy)
    programs.validate(policy)
    frozen_raw = (
        candidate.config.REPO / "research/vanilla-ai/1.15.0/production-inputs.json"
    ).read_bytes()
    frozen = json.loads(frozen_raw)
    inputs = {name: normalized_text(text) for name, text in frozen["inputs"].items()}
    for name, text in inputs.items():
        assert (
            hashlib.sha256(text.encode()).hexdigest()
            == frozen["source_identities"][name]["normalized_sha256"]
        )
    inputs.update(candidate.frozen_inputs())
    native = inputs[candidate.SOURCE]
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
    evidence = tmp_path_factory.mktemp("religion-separation")
    (evidence / "generated.txt").write_text(text, encoding="utf-8", newline="\n")
    (evidence / "readback.json").write_text(
        json.dumps(
            {
                "evidence": "static_real_adapter_program_pdx_no_model_no_engine",
                "frozen_production_sha256": hashlib.sha256(frozen_raw).hexdigest(),
                "generated_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "generated_metrics": resources.pdx_metrics(text),
                "query_metrics": {
                    mode: {
                        **resources.pdx_metrics(
                            candidate.render_query(candidate.ReligiousExposureQuery(mode))
                        ),
                        "bytes": len(
                            candidate.render_query(candidate.ReligiousExposureQuery(mode)).encode()
                        ),
                    }
                    for mode in ("separation_group_other_exposure", "stable_nonatheist_identity")
                },
                "new_rules": [r.id for r in policy.rules if r.id.startswith(PREFIX)],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return policy, native, text


def witness(
    generated,
    *,
    state="catholic",
    law="law_freedom_of_conscience",
    need=True,
    protection=True,
    authority=300,
    crisis=False,
    ai=True,
    heritage=False,
):
    policy, _, text = generated
    values: dict[str, object] = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        for prefix in ("culture_current_", "law_context_current_"):
            if key.startswith(prefix):
                values[key] = None if law is None else key.removeprefix(prefix) == law
    values.update(
        authority=authority,
        legitimacy=20 if crisis else 60,
        radical_share=0.3 if crisis else 0,
        insurrection=crisis,
        culture_separation_group_other_exposure=need,
        culture_stable_nonatheist_identity=None
        if state is None
        else state in NAMES and state != "atheist",
        culture_state_religious_protection_exposure=protection,
    )
    facts = _facts(policy, values, is_ai=ai)
    religion = _religious_facts(
        state=state,
        shares={
            "sunni": 0.1 if need else 0,
            "catholic": 0.8 if protection else 0,
            "protestant": 0.1 if heritage else 0,
        },
        acceptance={"sunni": -1, "catholic": 20, "protestant": -10},
    )
    if state is None:
        religion["country_has_state_religion"] = dict.fromkeys(
            religion["country_has_state_religion"]
        )
    if need is None:
        religion["religion_percent_country"][(("target", "rel:sunni"),)] = None
    if protection is None:
        religion["religion_percent_country"][(("target", "rel:catholic"),)] = None
    facts["ROOT"].update(religion)
    facts["ROOT"]["any_political_movement"] = []
    actual = pdx_eval.select(_overlay(text, FIELD), facts).delta
    reference = decision_rules.evaluate(policy, values, is_ai=ai).get(FIELD, ("neutral", 0))[1]
    return actual, reference, facts


def test_closed_delta_and_no_duplicate_old_rules(candidate):
    # Frozen pre-candidate rule fingerprints preserve every prior rule contract.
    # New pair IDs/readers are asserted separately below.
    previous = {
        "culture_freedom_of_conscience_observed_religious_exposure": "051f88bbcd7f3448825b87090fa5e7f3b796900d26621203458aada766225fcc",
        "culture_multicultural_observed_ethnostate_exposure": "9f7d464ee61c4c7ef6c207a464de8a0e79766fe9cd4e70c2f241b2ff1ac62caf",
        "culture_law_state_religion_to_law_freedom_of_conscience_state_protection_loss": "a3a0c23237408ee5057060ba30173c62a7682100e73287f31bf18fde3e14dc9f",
        "culture_law_caesaropapism_to_law_freedom_of_conscience_observed_exposure": "5d0f66e6f4bc8fb37f4625b282d1ee50ba5fc83ef325cd75e4837e19fd30dcc3",
        "culture_law_caesaropapism_to_law_freedom_of_conscience_state_protection_loss": "de73c1edb4367600d99e2d921c8464584c139c91d155beee4c29f974f98273e2",
        "culture_law_state_religion_to_law_total_separation_observed_exposure": "39ce3b926785698d9fd703beb0a9adb1d150bb342c5051d44cb747cac72c8bab",
        "culture_law_state_religion_to_law_total_separation_state_protection_loss": "fd0306d311673ae5a506c5dced850d5a4e68e2822dc4dd6f4160ffe3584f43c2",
        "culture_law_caesaropapism_to_law_total_separation_observed_exposure": "55a44bcc0578718caadc27162ffd66e475bb60d858d9ba9c7c9e31ee025c5572",
        "culture_law_caesaropapism_to_law_total_separation_state_protection_loss": "6f9cd95f3e9a382ea7723446b8eb5a7ce509779dc771b47b02bbad20c1934242",
        "culture_law_millet_system_to_law_total_separation_observed_exposure": "724a45eaac21390a4d974f27bf9f61d9b9aa85f52d490a654d99fe9ca1a09744",
        "culture_law_millet_system_to_law_total_separation_state_protection_loss": "4ef53ff99857c351ce5871df43c5931593f30d731837403432097c80d4b74ab4",
        "culture_law_people_of_the_book_to_law_total_separation_observed_exposure": "adde3ea879dabe5d8470f461539c1777382593c83c3e5fc4f29b813e9fa8f5b7",
        "culture_law_people_of_the_book_to_law_total_separation_state_protection_loss": "c935995f21e1d213782ffd6d17826c671e03ca3612370d06d589b5fa6a2fa85d",
        "culture_mixed_law_millet_system_to_law_freedom_of_conscience_benefit": "c6040d1ccbbec37db611f5a5d75bcc04e26d0cb25c16e89b41285342b17847d5",
        "culture_mixed_law_millet_system_to_law_freedom_of_conscience_state_loss": "f060bef68719bd1275f918dedf57e1ae49480e2f3077beed307d83ffac713261",
        "culture_mixed_law_millet_system_to_law_freedom_of_conscience_group_loss": "48d054f2f73c0634806212c43eef4f96c82b1f2bd1842a01c35b2fc676d94728",
        "culture_mixed_law_people_of_the_book_to_law_freedom_of_conscience_benefit": "645cbe9b06a2465648a8c71068474a9d14524be8698f467c03bdbca52b7e4522",
        "culture_mixed_law_people_of_the_book_to_law_freedom_of_conscience_state_loss": "5648aa4936e21f3ae72e44878c4585450abd1996545277cfac9e862e9f5355af",
        "culture_law_state_atheism_to_law_total_separation_observed_exposure": "1337d2ddc13672a93b012dd405a987d115e957fc8e51548b8a21901ee6a3e759",
    }
    after = candidate.derive({})
    new = {r["id"]: r for r in after["rules"]}
    assert set(new) - set(previous) == {PREFIX + "benefit", PREFIX + "state_loss"}
    assert all(
        hashlib.sha256(
            json.dumps(new[key], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        == digest
        for key, digest in previous.items()
    )
    assert {
        key
        for key in after["readers"]
        if key.startswith("culture_separation_") or key == "culture_stable_nonatheist_identity"
    } == {
        "culture_separation_group_other_exposure",
        "culture_stable_nonatheist_identity",
    }
    assert tuple(
        b - a
        for a, b in zip(
            candidate.EFFECTS["law_freedom_of_conscience"],
            candidate.EFFECTS["law_total_separation"],
            strict=True,
        )
    ) == (-5, 0, 10, 15)
    added = [row for key, row in new.items() if key.startswith(PREFIX)]
    assert sorted(r["semantic_role"] for r in added) == ["benefit", "cost"]
    assert all(len(r["conditions"]) == 4 for r in added)
    assert all(
        any(c["fact"] == "culture_stable_nonatheist_identity" for c in r["conditions"])
        for r in added
    )


def test_all_17_by_17_query_identities_and_literal_zero_channels(candidate):
    compiled = observation_queries.compile_query(
        observation_queries.from_reader("OR", {"culture_query": "separation_group_other_exposure"}),
        candidate.frozen_inputs(),
    )
    tree = parse_text(compiled.expression).root
    for state in NAMES:
        for observed in NAMES:
            for share, acceptance in ((0.1, -1), (0.09999, -1), (0.1, 0), (0.1, 1)):
                facts = _religious_facts(
                    state=state, shares={observed: share}, acceptance={observed: acceptance}
                )
                expected = (
                    category(state, observed) in {"group", "other"}
                    and share >= 0.1
                    and acceptance < 0
                )
                assert pdx_eval.condition(tree, facts) is expected, (
                    state,
                    observed,
                    share,
                    acceptance,
                )
    assert "306" in compiled.runtime_cost
    assert candidate.religious_channels.MANIFEST_SHA256 in "\n".join(compiled.references)


@pytest.mark.parametrize("state", [*NAMES, None, "unregistered"])
def test_explicit_identity_guard_never_accepts_unknown_or_atheist(candidate, state):
    tree = parse_text(
        candidate.render_query(candidate.ReligiousExposureQuery("stable_nonatheist_identity"))
    ).root
    facts = _religious_facts(state=state)
    if state is None:
        facts["country_has_state_religion"] = dict.fromkeys(facts["country_has_state_religion"])
    assert pdx_eval.condition(tree, facts) is (
        None if state is None else state in NAMES and state != "atheist"
    )


def test_query_same_country_religion_unknown_and_source_drift(candidate):
    tree = parse_text(
        candidate.render_query(candidate.ReligiousExposureQuery("separation_group_other_exposure"))
    ).root
    facts = _religious_facts(shares={"sunni": 0.2}, acceptance={"hindu": -1})
    facts["scope:target_country"] = _religious_facts(
        shares={"sunni": 0.2}, acceptance={"sunni": -1}
    )
    assert pdx_eval.condition(tree, facts) is False
    facts = _religious_facts()
    facts["religion_percent_country"][(("target", "rel:sunni"),)] = None
    assert pdx_eval.condition(tree, facts) is None
    for source in candidate.SOURCES:
        inputs = candidate.frozen_inputs()
        inputs[source] += "\n# drift\n"
        with pytest.raises(ValueError, match="漂移"):
            candidate.compile_query(
                candidate.ReligiousExposureQuery("separation_group_other_exposure"), inputs
            )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"need": False},
        {"protection": False},
        {"need": False, "protection": False},
        {"need": None},
        {"protection": None},
        {"need": None, "protection": False},
        {"state": None},
        {"state": "atheist"},
        {"state": "unregistered"},
        {"law": None},
        {"law": "law_total_separation"},
        {"ai": False},
        {"authority": 99},
        {"authority": 100},
        {"authority": None},
        {"authority": 99, "crisis": True},
        {"state": None, "authority": 99},
        {"state": "atheist", "authority": 99},
        {"need": None, "protection": None},
        {"need": False, "protection": False, "heritage": True},
    ],
)
def test_actual_adapter_program_pdx_literal_joined_costs(generated, kwargs):
    expected = score(
        **{
            "state": "catholic",
            "law": "law_freedom_of_conscience",
            "need": True,
            "protection": True,
            **{key: value for key, value in kwargs.items() if key != "heritage"},
        }
    )
    actual, secondary, _ = witness(generated, **kwargs)
    assert actual == secondary == expected


@pytest.mark.parametrize(
    ("state", "observed", "acceptance", "expected"),
    [
        ("catholic", "catholic", -1, 0),
        ("catholic", "catholic", 1, -4),
        ("catholic", "protestant", -1, 0),
        ("catholic", "sunni", -1, 6),
        ("catholic", "hindu", -1, 6),
        ("hindu", "shinto", -1, 6),
        ("shinto", "confucian", -1, 0),
        ("animist", "atheist", -1, 6),
        ("atheist", "catholic", -1, 0),
    ],
)
def test_literal_category_through_real_complete_program(
    generated, state, observed, acceptance, expected
):
    _actual, _secondary, facts = witness(generated, state=state, need=False, protection=False)
    facts["ROOT"].update(
        _religious_facts(state=state, shares={observed: 0.1}, acceptance={observed: acceptance})
    )
    assert pdx_eval.select(_overlay(generated[2], FIELD), facts).delta == expected


@pytest.mark.parametrize(
    "current", ["law_state_atheism", "law_millet_system", "law_people_of_the_book"]
)
def test_other_origins_cannot_borrow_new_pair_core(candidate, current):
    rules = [r for r in candidate.derive({})["rules"] if r["id"].startswith(PREFIX)]
    assert all(
        any(
            c == {"fact": "culture_current_law_freedom_of_conscience", "op": "=", "value": True}
            for c in rule["conditions"]
        )
        for rule in rules
    )
    assert current != "law_freedom_of_conscience"


def test_lifecycle_player_off_complete_native_tail(generated):
    for kwargs in (
        {},
        {"law": "law_total_separation"},
        {"need": False},
        {"need": False, "protection": False},
        {"state": None},
        {},
    ):
        actual, secondary, _ = witness(generated, **kwargs)
        assert (
            actual
            == secondary
            == score(
                **{
                    "state": "catholic",
                    "law": "law_freedom_of_conscience",
                    "need": True,
                    "protection": True,
                    **kwargs,
                }
            )
        )
    policy, native, text = generated
    assert (
        decision_rules.patch(
            native, policy, baseline=native, default_strategy=False, enabled_domains=frozenset()
        )
        == native
    )
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(stripped)] == [
        (t.kind, t.value) for t in tokenize(native)
    ]
    _, _, facts = witness(generated)
    facts["ROOT"].update(ai_has_enact_weight_modifier_journal_entries=True)
    body = _block(_block(parse_text(text).root, "law_total_separation"), "ai_enact_weight_modifier")
    expr = "\n".join(_render(row) for row in body.assignments())
    projected = (
        "# ACTION full_native [native]; candidate=total\nif = { limit = { always = yes } add = { "
        + expr
        + " } }"
    )
    assert pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta == 752
    facts["ROOT"]["is_ai"] = False
    assert pdx_eval.select(projected, {**facts["ROOT"], **facts}).delta == 750
    for program in policy.consumer_programs:
        assert len(program.variants) >= 1
        assert program.lower <= program.upper
        body = _overlay(text, ".".join(program.field))
        assert len(re.findall(r"(?m)^\t{3}min = ", body)) == 1
        assert len(re.findall(r"(?m)^\t{3}max = ", body)) == 1


def test_full_activation_parent_and_actual_category_repin_rejected(candidate, monkeypatch):
    inputs = candidate.frozen_inputs()
    text = inputs[candidate.SOURCE]
    marker = "law_freedom_of_conscience = {"
    start = text.index(marker)
    end = text.index("law_total_separation = {", start)
    altered = (
        text[:start]
        + text[start:end].replace(
            "set_state_religion = root.country_definition.religion",
            "set_state_religion = rel:atheist",
        )
        + text[end:]
    )
    inputs[candidate.SOURCE] = altered
    data = candidate.load()
    data["sources"][candidate.SOURCE] = hashlib.sha256(altered.encode()).hexdigest()
    monkeypatch.setattr(candidate, "load", lambda: data)
    with pytest.raises(ValueError, match="激活父结构"):
        candidate.verify_inputs(inputs)


def test_new_query_resource_budget_and_closed_authority(candidate, monkeypatch):
    query = candidate.render_query(
        candidate.ReligiousExposureQuery("separation_group_other_exposure")
    )
    metrics = resources.pdx_metrics(query)
    assert metrics["object_scan_sites"] == metrics["persistent_write_sites"] == 0
    assert metrics["max_depth"] <= 7
    monkeypatch.setattr(candidate.religious_channels, "MAX_PREDICATES", 0)
    with pytest.raises(ValueError, match="预算"):
        candidate.render_query(candidate.ReligiousExposureQuery("separation_group_other_exposure"))
    for settings in (
        {"culture_query": "separation_group_other_exposure", "target": "scope:target_country"},
        {"culture_query": "stable_nonatheist_identity", "religion": "catholic"},
    ):
        with pytest.raises(ValueError, match="宗教暴露"):
            candidate.query_from_reader("OR", settings)
