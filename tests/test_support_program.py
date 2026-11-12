"""Continuous support consumers share typed semantics and independent AST witnesses."""

from dataclasses import replace

import pytest

from pdx import decisions, version_contracts
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.situated.support_program import SupportObservation, SupportProgram

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_support_metadata_identifies_selected_independent_context(version):
    with version_contracts.select_version(version):
        source = SupportProgram.from_extensions(decisions.Extensions()).as_dict()["native_source"]
    if version == "1.14.5":
        assert source == "research/vanilla-ai/1.14.5/00_default_strategy.txt:180-188"
    else:
        assert source == ";".join(
            f"research/vanilla-ai/1.15.0/00_default_strategy.txt:{line}" for line in (210, 211, 212)
        )


def _facts(observation: SupportObservation) -> dict[str, object | None]:
    partner, opponent = (
        ("scope:enemy_country", "scope:country")
        if observation.initiator
        else ("scope:country", "scope:enemy_country")
    )
    return {
        "ROOT": {
            "is_ai": observation.is_ai,
            "economic_dependence": {
                (("argument", "scope:country"),): observation.country_dependence,
                (("argument", "scope:enemy_country"),): observation.enemy_dependence,
            },
            "sitai_defense_commitment": {(("PARTNER", partner),): observation.commitment},
            "sitai_neighbor_defense": {
                tuple(sorted((("PARTNER", partner), ("OPPONENT", opponent)))): observation.neighbor
            },
        },
        "scope:country": {} if observation.has_sides else None,
        "scope:enemy_country": {} if observation.has_sides else None,
        "scope:is_initiator": observation.initiator,
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 5),
        ({"commitment": None}, -5),
        ({"neighbor": None}, 5),
        ({"commitment": None, "neighbor": None}, -20),
        ({"country_dependence": None}, 25),
        ({"enemy_dependence": None}, 25),
        ({"country_dependence": None, "commitment": None}, 15),
        ({"initiator": None}, -20),
        ({"is_ai": False}, 0),
        ({"is_ai": None}, 0),
        ({"has_sides": False}, 0),
        ({"has_sides": None}, 0),
        ({"country_dependence": 5, "enemy_dependence": 0}, 50),
        ({"initiator": True, "country_dependence": 0, "enemy_dependence": 5}, -50),
    ],
)
def test_support_program_hand_calculated_local_terms(changes, expected):
    program = SupportProgram.from_extensions(
        replace(
            decisions.Extensions(),
            market_enabled=True,
            security_enabled=True,
        )
    )
    observation = replace(
        SupportObservation(
            is_ai=True,
            has_sides=True,
            initiator=False,
            country_dependence=0,
            enemy_dependence=4,
            commitment=True,
            neighbor=True,
        ),
        **changes,
    )
    assert program.evaluate(observation).value == expected
    assert pdx_eval.select(program.render(), _facts(observation)).delta == expected


@pytest.mark.parametrize(
    "getter",
    [
        "ROOT.economic_dependence(scope:target_country)",
        "scope:country.economic_dependence(ROOT)",
        "ROOT.gdp",
        "ROOT.economic_dependence(scope:country).bad",
    ],
)
def test_support_program_rejects_unregistered_quoted_getters(getter):
    program = SupportProgram.from_extensions(replace(decisions.Extensions(), market_enabled=True))
    text = program.render().replace("ROOT.economic_dependence(scope:country)", getter)
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="getter"):
        pdx_eval.select(text, {})


@pytest.mark.parametrize("bad", [True, "1", float("nan"), float("inf"), {}, -1, 6, 10**1000])
def test_support_program_rejects_wrong_economic_observation_types(bad):
    program = SupportProgram.from_extensions(replace(decisions.Extensions(), market_enabled=True))
    facts = {
        "ROOT": {
            "is_ai": True,
            "economic_dependence": {
                (("argument", "scope:country"),): bad,
                (("argument", "scope:enemy_country"),): 0,
            },
        },
        "scope:country": {},
        "scope:enemy_country": {},
    }
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="有限数值"):
        pdx_eval.select(program.render(), facts)


def test_support_program_does_not_default_unknown_numeric_to_zero():
    observation = SupportObservation(
        is_ai=True, has_sides=True, initiator=False, country_dependence=None, enemy_dependence=4
    )
    program = SupportProgram.from_extensions(replace(decisions.Extensions(), market_enabled=True))
    assert program.evaluate(observation).value == 0
    assert pdx_eval.select(program.render(), _facts(observation)).delta == 0
    assert SupportProgram.from_extensions(decisions.Extensions()).render() == ""


def test_support_program_parameters_bind_the_actual_two_sides():
    program = SupportProgram.from_extensions(replace(decisions.Extensions(), security_enabled=True))
    observation = SupportObservation(
        is_ai=True, has_sides=True, initiator=False, commitment=True, neighbor=False
    )
    facts = _facts(observation)
    root = facts["ROOT"]
    assert isinstance(root, dict)
    root["sitai_defense_commitment"] = {(("PARTNER", "scope:enemy_country"),): True}
    root["sitai_neighbor_defense"] = {
        (("OPPONENT", "scope:country"), ("PARTNER", "scope:enemy_country")): True
    }
    assert pdx_eval.select(program.render(), facts).delta == 0
    facts["scope:is_initiator"] = True
    assert pdx_eval.select(program.render(), facts).delta == -25


@pytest.mark.parametrize("value", [True, 1, {}, "yes"])
def test_support_program_initiator_exists_has_exact_boolean_contract(value):
    if value is True:
        assert (
            pdx_eval.condition(
                parse_text("exists = scope:is_initiator").root, {"scope:is_initiator": value}
            )
            is True
        )
    else:
        program = SupportProgram.from_extensions(
            replace(decisions.Extensions(), security_enabled=True)
        )
        facts = _facts(SupportObservation(is_ai=True, has_sides=True))
        facts["scope:is_initiator"] = value
        with pytest.raises(pdx_eval.UnsupportedPdxError, match="布尔"):
            pdx_eval.select(program.render(), facts)


def test_support_program_local_unknown_and_absolute_reason():
    result = decisions.merge_diplomatic_play_support(
        market=3, security={"commitment": None, "neighbor": -15}
    )
    assert result == decisions.SupportArbitration(-12, ("market", "neighbor"))
    assert (
        decisions.merge_diplomatic_play_support(
            market=-3, security={"commitment": -25, "neighbor": -15}
        ).value
        == -28
    )
    assert decisions.merge_diplomatic_play_support(market=25, security={"a": 50}).value == 50


@pytest.mark.parametrize("initiator", [False, True])
def test_support_program_clamps_actual_combined_overflow_once(initiator):
    program = SupportProgram.from_extensions(
        replace(
            decisions.Extensions(),
            market_enabled=True,
            security_enabled=True,
            security_commitment_bonus=50,
        )
    )
    observation = SupportObservation(
        True, True, initiator, 0 if initiator else 5, 5 if initiator else 0, True, True
    )
    expected = -50 if initiator else 50  # Raw contribution is respectively -75 or 75.
    assert program.evaluate(observation).value == expected
    assert pdx_eval.select(program.render(), _facts(observation)).delta == expected


@pytest.mark.parametrize("missing", ["ROOT", "scope:country", "scope:enemy_country"])
def test_support_program_each_missing_core_scope_returns_to_vanilla(missing):
    program = SupportProgram.from_extensions(
        replace(
            decisions.Extensions(),
            market_enabled=True,
            security_enabled=True,
        )
    )
    facts = _facts(SupportObservation(True, True, False, 5, 0, True, True))
    facts[missing] = None
    assert pdx_eval.select(program.render(), facts).delta == 0


@pytest.mark.parametrize(("initiator", "expected"), [(False, 5), (True, -45)])
def test_support_program_cancellation_and_direction(initiator, expected):
    program = SupportProgram.from_extensions(
        replace(decisions.Extensions(), market_enabled=True, security_enabled=True)
    )
    observation = SupportObservation(
        is_ai=True,
        has_sides=True,
        initiator=initiator,
        country_dependence=0,
        enemy_dependence=4,
        commitment=True,
        neighbor=True,
    )
    assert program.evaluate(observation).value == expected
    facts = {
        "ROOT": {
            "is_ai": True,
            "economic_dependence": {
                (("argument", "scope:country"),): 0,
                (("argument", "scope:enemy_country"),): 4,
            },
            "sitai_defense_commitment": {
                (("PARTNER", "scope:enemy_country" if initiator else "scope:country"),): True
            },
            "sitai_neighbor_defense": {
                tuple(
                    sorted(
                        (
                            ("PARTNER", "scope:enemy_country" if initiator else "scope:country"),
                            ("OPPONENT", "scope:country" if initiator else "scope:enemy_country"),
                        )
                    )
                ): True
            },
        },
        "scope:country": {},
        "scope:enemy_country": {},
        "scope:is_initiator": initiator,
    }
    assert pdx_eval.select(program.render(), facts).delta == expected


@pytest.fixture
def historical_support_assembly():
    # This unit checks assembly against its original frozen source. Current
    # installed-source proof and complete release assembly have separate gates.
    with version_contracts.select_version("1.14.5"):
        yield


def test_support_program_is_a_real_production_writer(historical_support_assembly):
    import json
    import re

    extra = replace(decisions.Extensions(), market_enabled=True, security_enabled=True)
    files = decisions.build(extensions=extra)
    metadata = json.loads(files[".metadata/metadata.json"])
    bundle = metadata["situated_actions"]["consumer_ir"]
    writers = [w for w in bundle["writers"] if w["kind"] == "support_program"]
    assert len(writers) == 1
    assert bundle["support_program_writer_count"] == 1
    assert writers[0]["program"]["consumer_max_delta"] == 50
    assert bundle["field_owners"]["diplomatic_play_support"] == "situated_kernel"
    assert metadata["default_field_owners"]["diplomatic_play_support"] == "situated_kernel"
    source = files["common/ai_strategies/00_default_strategy.txt"]
    restored = re.sub(
        r"\t\t# SITAI BEGIN [^\n]+\n.*?\t\t# SITAI END [^\n]+\n", "", source, flags=re.DOTALL
    )
    assert restored.encode() == decisions.baseline_path().read_bytes()
    overlay = source.split("# SITAI BEGIN diplomatic_play_support\n", 1)[1].split(
        "\t\t# SITAI END diplomatic_play_support", 1
    )[0]
    assert overlay == SupportProgram.from_extensions(extra).render()
    assert overlay.splitlines().count("\t\t\tadd = {") == 1
    assert overlay.count("min = -50") == overlay.count("max = 50") == 1
    for reason in (
        "SITAI_SUPPORT_BALANCE_REASON",
        "SITAI_MARKET_DEPENDENCE_SUPPORT_REASON",
        "SITAI_SECURITY_COMMITMENT_REASON",
        "SITAI_SECURITY_NEIGHBOR_REASON",
    ):
        localized_files = [
            localized for path, localized in files.items() if "sitai_decisions_l_" in path
        ]
        assert localized_files
        assert all(reason in localized for localized in localized_files)
    for observation, expected in (
        (SupportObservation(True, True, False, 0, 4, True, True), 5),
        (SupportObservation(True, True, True, 0, 4, True, True), -45),
        (SupportObservation(True, True, False, None, 4, True, True), 25),
        (SupportObservation(True, True, False, 0, 4, None, None), -20),
    ):
        assert pdx_eval.select(overlay, _facts(observation)).delta == expected
