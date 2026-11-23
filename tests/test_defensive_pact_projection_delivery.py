"""Independent readback of the defensive-pact fields from the standard ZIP."""

from zipfile import ZipFile
lazy from pathlib import Path

import pytest

from pdx import config, treaty_opportunities
from pdx.model import Assignment, Block, Node, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval

pytestmark = pytest.mark.integration

ARTICLE = "common/treaty_articles/01_defensive_pact.txt"
BEGIN = "# SITAI BEGIN information:defensive_pact.ai.proposal_weight"
END = "# SITAI END information:defensive_pact.ai.proposal_weight"
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
ARMY_BEGIN = "# SITAI BEGIN information:wanted_army_size"
ARMY_END = "# SITAI END information:wanted_army_size"


def _parse(text: str) -> Block:
    parsed = parse_text(text)
    assert not parsed.errors
    return parsed.root


def _child(parent: Block, key: str) -> Block:
    [entry] = parent.all(key)
    assert entry.op == "="
    assert entry.prefix is None
    assert isinstance(entry.value, Block)
    return entry.value


def _ast(node: Node | None) -> object:
    """Keep order, operators, prefixes and quoted literals, ignoring line offsets."""
    if isinstance(node, Block):
        return tuple(_ast(item) for item in node.items)
    if isinstance(node, Assignment):
        return (node.full_key, node.op, _ast(node.value))
    if isinstance(node, Scalar):
        return (node.text, node.quoted)
    return None


@pytest.fixture(scope="module")
def packaged_article(standard_release_package: Path) -> str:
    with ZipFile(standard_release_package) as archive:
        assert archive.namelist().count(ARTICLE) == 1
        return archive.read(ARTICLE).decode("utf-8-sig")


@pytest.fixture
def proposal_overlay(packaged_article: str) -> str:
    assert packaged_article.count(BEGIN) == packaged_article.count(END) == 1
    overlay = packaged_article.split(BEGIN, 1)[1].split(END, 1)[0]
    [overlay_entry] = _parse(overlay).items
    article_ai = _child(_child(_parse(packaged_article), "defensive_pact"), "ai")
    proposal = _child(article_ai, "proposal_weight")
    assert _ast(proposal.items[-1]) == _ast(overlay_entry)
    return overlay


def test_current_installation_matches_frozen_article_and_phase_identities() -> None:
    baseline = treaty_opportunities.verify_game(config.GAME)
    row = baseline["candidates"]["defensive_pact"]
    assert (row["source"], row["kind"], row["cost"]) == (ARTICLE, "mutual", "100")
    assert row["evaluation_scope_evidence"] == ["common/treaty_articles/treaty_articles.md:530"]
    assert row["scope_evidence"] == ["common/treaty_articles/treaty_articles.md:166"]
    assert baseline["contract"]["evaluation_chance"]["target"] == "none"


def test_standard_zip_preserves_all_native_article_nodes_except_one_proposal_suffix(
    packaged_article: str, proposal_overlay: str
) -> None:
    vanilla = _parse((config.GAME / ARTICLE).read_text(encoding="utf-8-sig"))
    packaged = _parse(packaged_article)
    vanilla_ai = _child(_child(vanilla, "defensive_pact"), "ai")
    packaged_ai = _child(_child(packaged, "defensive_pact"), "ai")
    vanilla_screen = _child(vanilla_ai, "evaluation_chance")
    packaged_screen = _child(packaged_ai, "evaluation_chance")

    # An injected partner predicate would fail the whole initial field equality.
    assert _ast(packaged_screen) == _ast(vanilla_screen)
    _child(packaged_ai, "proposal_weight").items.pop()
    assert _ast(packaged) == _ast(vanilla)
    [tail] = _parse(proposal_overlay).items
    assert isinstance(tail, Assignment)
    assert tail.key == "if"
    assert isinstance(tail.value, Block)
    assert tail.value.keys() == ["limit", "multiply"]


def test_standard_zip_proposal_adjustment_uses_the_composing_country_only(
    proposal_overlay: str,
) -> None:
    actor = {
        "is_ai": True,
        "influence": 100,
        "is_diplomatic_play_target": True,
        "is_at_war": False,
        "in_default": False,
    }
    stressed_actor = {
        "is_ai": True,
        "influence": -1,
        "is_diplomatic_play_target": False,
        "is_at_war": True,
        "in_default": True,
    }
    observations = {"ROOT": actor}
    positive = pdx_eval.select(proposal_overlay, observations)
    assert positive.operation == "multiply"
    assert positive.delta == pytest.approx(1.15)
    assert (
        pdx_eval.select(proposal_overlay, {**observations, "scope:other_country": stressed_actor})
        == positive
    )

    reversed_roles = pdx_eval.select(
        proposal_overlay, {"ROOT": stressed_actor, "scope:other_country": actor}
    )
    assert reversed_roles.operation == "multiply"
    assert reversed_roles.delta == pytest.approx(0.50)
    player = pdx_eval.select(
        proposal_overlay,
        {"ROOT": {**actor, "is_ai": False}, "scope:other_country": stressed_actor},
    )
    assert player.operation is None
    assert player.fallback == "vanilla"


def test_standard_zip_leaves_draft_count_out_of_army_target(standard_release_package: Path) -> None:
    with ZipFile(standard_release_package) as archive:
        strategy = archive.read(STRATEGY).decode("utf-8-sig")
    vanilla = (config.GAME / STRATEGY).read_text(encoding="utf-8-sig")
    vanilla_army = _child(_child(_parse(vanilla), "ai_strategy_default"), "wanted_army_size")
    packaged_army = _child(_child(_parse(strategy), "ai_strategy_default"), "wanted_army_size")
    assert strategy.count(ARMY_BEGIN) == strategy.count(ARMY_END) == 1
    overlay = strategy.split(ARMY_BEGIN, 1)[1].split(ARMY_END, 1)[0]
    [addition] = _parse(overlay).items
    assert _ast(packaged_army.items[-1]) == _ast(addition)
    assert _ast(Block(packaged_army.items[:-1])) == _ast(vanilla_army)
    assert "num_defensive_pacts" not in overlay

    # 1836-02-11 Belgian draft control. Raw count and the positive original
    # target gap used to lower this country's target despite the draft phase.
    root = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "net_total_income": -10170.58878,
        "num_defensive_pacts": 1,
        "wanted_army_size_script_value": 25,
        "wanted_marines_size_script_value": 0,
        "army_size": 50,
        "infamy": 0,
    }
    for changes, expected in (({}, 1), ({"is_at_war": True}, 1.08), ({"in_default": True}, 0.85)):
        decision = pdx_eval.select(overlay, {"ROOT": {**root, **changes}})
        assert decision.operation == "multiply"
        assert decision.delta == pytest.approx(expected)
