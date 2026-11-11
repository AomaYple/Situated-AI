"""Native evidence for the remaining society observations, not delivery acceptance.

The tests prove a reachable IG-law-support path and distinguish actual pop
automobile consumption from supply and non-pop input. They do not manufacture
a script getter for the latter or claim that absence in this search proves an
engine limitation.
"""

import hashlib
from typing import Any

import pytest

from pdx import config, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
COMMUNISM = "common/journal_entries/00_communism.txt"
IDEOLOGIES = "common/ideologies/00_ig_ideologies.txt"
UNIONS = "common/interest_groups/00_trade_unions.txt"
POWER = "common/laws/00_distribution_of_power.txt"
GOVERNANCE = "common/laws/00_governance_principles.txt"
ECONOMY = "common/laws/01_economic_system.txt"
SOCIETY = "common/technology/technologies/30_society.txt"
GOODS = "common/goods/00_goods.txt"
URBAN = "common/production_methods/06_urban_center.txt"
MOBILIZATION = "common/mobilization_options/00_mobilization_option.txt"
NEEDS = "common/pop_needs/00_pop_needs.txt"


@pytest.fixture(scope="module")
def roots() -> dict[str, Block]:
    result = {}
    for source in (
        COMMUNISM,
        IDEOLOGIES,
        UNIONS,
        POWER,
        GOVERNANCE,
        ECONOMY,
        SOCIETY,
        GOODS,
        URBAN,
        MOBILIZATION,
        NEEDS,
    ):
        parsed = parse_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        assert not parsed.errors
        result[source] = parsed.root
    return result


def _child(block: Block, key: str) -> Block:
    entries = block.all(key)
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.op, entry.prefix) == ("=", None)
    assert isinstance(entry.value, Block)
    return entry.value


def _scalar(block: Block, key: str) -> str:
    entries = block.all(key)
    assert len(entries) == 1
    assert (entries[0].op, entries[0].prefix) == ("=", None)
    assert isinstance(entries[0].value, Scalar)
    return entries[0].value.unquoted


def _list(block: Block, key: str) -> tuple[str, ...]:
    items = _child(block, key).items
    assert all(isinstance(item, Scalar) for item in items)
    return tuple(item.unquoted for item in items if isinstance(item, Scalar))


def _shape(block: Block) -> Any:
    result = []
    for entry in block.items:
        assert isinstance(entry, Assignment)
        assert entry.prefix is None
        value = entry.value
        assert isinstance(value, (Block, Scalar))
        result.append(
            (entry.key, entry.op, _shape(value) if isinstance(value, Block) else value.unquoted)
        )
    return tuple(result)


@pytest.mark.parametrize(
    ("source", "raw_hash", "normalized_hash"),
    [
        (
            COMMUNISM,
            "0089230769d47d3aa2ef89394c408262f09861cee499c8954804fe812824d640",
            "fbe2ce3af236a3f49e146f445ba56957952ac910b68022cc0f69e94e8010072f",
        ),
        (
            IDEOLOGIES,
            "4c8bc020d2d1060795e5a615b850736b731a31193862399363ec2e1829639b05",
            "2e3f1940ebe12e8a36230f57710a81f7b14e84b221438ed41c9b6cffdf7277d4",
        ),
        (
            UNIONS,
            "37e3a3a9821cefdea0c54cc6352fbf6cef84a3ebca12d94bbe6167f047ca0da6",
            "b1759c80f901533b7b83495da8958a2f13edb88be7c007ccd1e5af798bd66c43",
        ),
    ],
)
def test_new_ig_evidence_sources_match_actual_locked_original_bytes(
    source, raw_hash, normalized_hash
):
    current_hashes = {
        COMMUNISM: (
            "181a9dd06a69f50a7964736b2714cdb733a7c78305cd0ea84c73322042335559",
            "107fa64a7e5587d8459eab2404b504b06042d1fffb7a8918eb49b5a4654512c2",
        ),
        IDEOLOGIES: (
            "c2ef71fe0b3f880e84be534bcaee21335902a23747105365544a8c210c2f3e00",
            "9637ce7b900e671af5880f1876be7b086e913d9caf5031aae84e3bf080f2c660",
        ),
        UNIONS: (
            "fbbd35b8b436b8d092406f8635fbe29004482ba688ce7f4f7ef55048bca33833",
            "dd11f29ac662a390d0ddeafe5de5e6e63ef91fd7b885892670fa6b3c89896201",
        ),
    }
    if version_contracts.is_115():
        raw_hash, normalized_hash = current_hashes[source]
    raw = (config.GAME / source).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == raw_hash
    assert (
        hashlib.sha256(normalized_text(raw.decode("utf-8-sig")).encode()).hexdigest()
        == normalized_hash
    )


def test_country_has_complete_exact_law_stance_interest_group_collection_consumer(roots):
    country = _child(roots[COMMUNISM], "je_communism_1")
    if version_contracts.is_115():
        outcomes = [
            item.value
            for item in country.all("outcome")
            if isinstance(item.value, Block)
            and _scalar(item.value, "header") == "je_standard_completion_header"
        ]
        assert len(outcomes) == 1
        effect = _child(outcomes[0], "effect")
        branches = _child(effect, "else").all("if")
        support = [
            item.value
            for item in branches
            if isinstance(item.value, Block)
            and _child(item.value, "limit").all("any_interest_group")
        ]
        assert len(support) == 1
        limit = _child(support[0], "limit")
        random_limit = _child(_child(support[0], "random_interest_group"), "limit")
        assert _shape(random_limit) == _shape(_child(limit, "any_interest_group"))
    else:
        limit = _child(_child(_child(_child(country, "on_fail"), "else"), "if"), "limit")
    assert _shape(_child(limit, "any_interest_group")) == (
        (
            "law_stance",
            "=",
            (("law", "=", "law_type:law_council_republic"), ("value", ">", "neutral")),
        ),
    )


def test_trade_unions_exist_before_anarchism_and_populist_stance_is_versioned(roots):
    unions = _child(roots[UNIONS], "ig_trade_unions")
    assert _shape(_child(unions, "enable")) == (("always", "=", "yes"),)
    assert "ideology_populist" in _list(unions, "ideologies")
    populist = _child(
        _child(roots[IDEOLOGIES], "ideology_populist"), "lawgroup_distribution_of_power"
    )
    current = version_contracts.is_115()
    assert _scalar(populist, "law_anarchy") == ("neutral" if current else "approve")
    # The current neutral anarchy stance also disproves using an ideology
    # label as positive support. Read actual law_stance rather than inferring
    # the final stance or substituting law_enactment_stance.
    assert _scalar(populist, "law_universal_suffrage") == (
        "approve" if current else "strongly_approve"
    )


def test_anarchy_research_unlock_and_cooperative_ownership_are_different_requirements(roots):
    anarchy = _child(roots[POWER], "law_anarchy")
    assert _list(anarchy, "unlocking_technologies") == ("anarchism",)
    assert _list(anarchy, "unlocking_laws") == ("law_cooperative_ownership",)
    cooperative = _child(roots[ECONOMY], "law_cooperative_ownership")
    assert cooperative.first("unlocking_technologies") is None
    assert _list(cooperative, "unlocking_laws") == ("law_council_republic", "law_corporate_state")
    assert _list(_child(roots[GOVERNANCE], "law_council_republic"), "unlocking_technologies") == (
        "socialism",
    )
    assert _list(_child(roots[GOVERNANCE], "law_corporate_state"), "unlocking_technologies") == (
        "corporatism",
    )


@pytest.mark.parametrize("technology", ["socialism", "corporatism"])
def test_cooperative_governance_technology_chain_does_not_require_anarchism(roots, technology):
    society = roots[SOCIETY]

    def dependencies(key: str, seen: set[str]) -> None:
        if key in seen:
            return
        seen.add(key)
        entry = society.first(key)
        # These routes stay within the actual society graph; an unobserved
        # external dependency would invalidate this reachability witness.
        assert entry is not None
        definition = _child(society, key)
        if definition.first("unlocking_technologies"):
            for parent in _list(definition, "unlocking_technologies"):
                dependencies(parent, seen)

    seen: set[str] = set()
    dependencies(technology, seen)
    assert "anarchism" not in seen


def test_future_authority_side_effect_is_not_a_research_payment(roots):
    anarchy = _child(roots[POWER], "law_anarchy")
    assert _scalar(_child(anarchy, "modifier"), "country_authority_mult") == "-0.5"
    technology = _child(roots[SOCIETY], "anarchism")
    assert technology.first("modifier") is None
    assert _list(technology, "unlocking_technologies") == ("egalitarianism",)


def test_paved_roads_effect_is_pop_consumption_infrastructure_not_car_supply(roots):
    paved = _child(roots[SOCIETY], "paved_roads")
    assert _shape(_child(paved, "modifier")) == (
        ("state_infrastructure_from_automobiles_consumption_add", "=", "0.25"),
    )
    automobile = _child(roots[GOODS], "automobiles")
    assert _scalar(automobile, "pop_consumption_can_add_infrastructure") == "yes"


@pytest.mark.parametrize(
    ("source", "definition", "path", "value"),
    [
        (URBAN, "pm_public_motor_carriages", ("building_modifiers", "workforce_scaled"), "1"),
        (MOBILIZATION, "mobilization_option_truck_transport", ("upkeep_modifier",), "0.5"),
        (MOBILIZATION, "mobilization_option_motorized_recon", ("upkeep_modifier",), "1"),
    ],
)
def test_positive_total_car_consumption_has_real_non_pop_counterexamples(
    roots, source, definition, path, value
):
    block = _child(roots[source], definition)
    for key in path:
        block = _child(block, key)
    assert _scalar(block, "goods_input_automobiles_add") == value


@pytest.mark.parametrize("need", ["popneed_free_movement", "popneed_leisure"])
def test_pop_need_membership_does_not_force_positive_automobile_consumption(roots, need):
    definition = _child(roots[NEEDS], need)
    automobile_entries = []
    for entry in definition.all("entry"):
        assert isinstance(entry.value, Block)
        if _scalar(entry.value, "goods") == "automobiles":
            automobile_entries.append(entry.value)
    assert len(automobile_entries) == 1
    assert _scalar(automobile_entries[0], "min_supply_share") == "0.0"
