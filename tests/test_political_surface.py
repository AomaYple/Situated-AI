"""政治候选静态索引的单元与原版集成回归。"""

from __future__ import annotations

import json

import pytest

from pdx import config, political_surface, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes

pytestmark = pytest.mark.unit


_SAMPLE = """
ai_strategy_political_demo = {
    type = political
    revolution_aversion = { value = 75 }
    min_law_chance_to_pass = {
        value = 20
        if = { limit = { has_journal_entry = je_demo } multiply = 0.5 }
    }
    max_progressiveness = { value = 50 }
    max_regressiveness = { value = 25 }
    change_law_chance = {
        value = 2.5
        if = { limit = { any_interest_group = { is_insurrectionary = yes } } add = 7.5 multiply = 3 modulo = 4 }
        if = { limit = { has_enactment_je_or_law_commitment = yes } add = dynamic_value }
    }
    pro_interest_groups = { ig_intelligentsia ig_industrialists }
    anti_interest_groups = { ig_landowners }
    pro_movements = { movement_liberal }
    anti_movements = { movement_reactionary }
    possible = { OR = { has_journal_entry = je_demo always = yes } }
}

ai_strategy_diplomatic_demo = {
    type = diplomatic
    weight = { value = 10 }
}
"""


def test_政治策略索引保留基值条件项和偏好(tmp_path):
    path = tmp_path / "common/ai_strategies/demo.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_SAMPLE, encoding="utf-8", newline="\n")

    strategies = political_surface.read_strategies(tmp_path)

    assert [strategy.name for strategy in strategies] == ["ai_strategy_political_demo"]
    strategy = strategies[0]
    assert strategy.change_law_chance is not None
    assert strategy.change_law_chance.base == 2.5
    assert [term.amount for term in strategy.change_law_chance.contributions] == [
        7.5,
        3.0,
        4.0,
        None,
    ]
    assert strategy.change_law_chance.contributions[3].expression == "dynamic_value"
    assert strategy.change_law_chance.contributions[0].condition_keys == (
        "any_interest_group",
        "is_insurrectionary",
    )
    assert strategy.min_law_chance_to_pass is not None
    assert strategy.min_law_chance_to_pass.contributions[0].operator == "multiply"
    assert strategy.pro_interest_groups == ("ig_intelligentsia", "ig_industrialists")
    assert strategy.anti_interest_groups == ("ig_landowners",)
    assert set(strategy.possible_keys) == {"has_journal_entry", "always"}
    assert len(strategy.change_law_chance.canonical_sha256) == 64
    assert '"key":"modulo"' in strategy.change_law_chance.canonical_ast


def test_非有限数值不冒充动态表达式(tmp_path):
    path = tmp_path / "common/ai_strategies/demo.txt"
    path.parent.mkdir(parents=True)
    path.write_text(
        "ai_strategy_political_demo = { type = political change_law_chance = { value = 1e309 } }\n",
        encoding="utf-8",
        newline="\n",
    )
    summary = political_surface.read_strategies(tmp_path)[0].change_law_chance
    assert summary is not None
    assert summary.base is None
    assert summary.diagnostics


def test_政治策略索引文档和json明确边界(tmp_path):
    path = tmp_path / "common/ai_strategies/demo.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_SAMPLE, encoding="utf-8", newline="\n")
    strategies = political_surface.read_strategies(tmp_path)

    document = political_surface.render(strategies)
    assert "最终候选排名或启动概率" in document
    assert "change_law_chance" in document
    assert "dynamic_value" in document
    assert "AST" in document
    payload = political_surface.as_json(strategies)
    assert payload["strategy_count"] == 1
    assert payload["limits"] == {
        "final_engine_chance": False,
        "candidate_ranking": False,
        "random_memory": False,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "source_sha256" in serialized


def test_政治策略文档写入和漂移检查(tmp_path):
    path = tmp_path / "common/ai_strategies/demo.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_SAMPLE, encoding="utf-8", newline="\n")
    (path.parent / "00_default_strategy.txt").write_text(
        "ai_strategy_default = { change_law_chance = { value = 1 } }\n",
        encoding="utf-8",
        newline="\n",
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    written = political_surface.write_doc(repo, game=tmp_path)
    assert written.read_bytes() == political_surface.build(tmp_path).encode("utf-8")
    assert political_surface.check_doc(repo, game=tmp_path) == ""
    written.write_text("手改\n", encoding="utf-8", newline="\n")
    assert "不一致" in political_surface.check_doc(repo, game=tmp_path)


def test_默认层单独进入索引(tmp_path):
    path = tmp_path / "common/ai_strategies/03_political.txt"
    path.parent.mkdir(parents=True)
    path.write_text(_SAMPLE, encoding="utf-8", newline="\n")
    default = path.parent / "00_default_strategy.txt"
    default.write_text(
        "ai_strategy_default = { change_law_chance = { value = 1 } }\n",
        encoding="utf-8",
        newline="\n",
    )
    result = political_surface.read_default_strategy(tmp_path)
    assert result.change_law_chance is not None
    assert result.change_law_chance.base == 1
    payload = political_surface.as_json(political_surface.read_strategies(tmp_path), result)
    default_payload = payload["default_strategy"]
    assert isinstance(default_payload, dict)
    chance = default_payload["change_law_chance"]
    assert isinstance(chance, dict)
    assert chance["base"] == 1


@pytest.mark.integration
def test_原版政治策略牌数量和关键策略字段():
    if not (config.GAME / political_surface.STRATEGY_DIR).is_dir():
        pytest.skip("没有游戏本体")
    # Nine historical cards remain a separate contract. The two 1.15 cards
    # are radical-leftist choices, not additional universally eligible cards.
    historical_names = {
        "ai_strategy_conservative_agenda",
        "ai_strategy_reactionary_agenda",
        "ai_strategy_progressive_agenda",
        "ai_strategy_egalitarian_agenda",
        "ai_strategy_nationalist_agenda",
        "ai_strategy_maintain_mandate_of_heaven",
        "ai_strategy_tanzimat_reforms",
        "ai_strategy_meiji_restoration",
        "ai_strategy_great_reforms",
    }
    current_names = historical_names | {
        "ai_strategy_consolidation_agenda",
        "ai_strategy_confrontation_agenda",
    }
    selected_version = version_contracts.active_version()
    expected_names = {"1.14.5": historical_names, "1.15.0": current_names}[selected_version]
    assert len(historical_names) == 9
    assert len(current_names) == 11

    # Independently enumerate the real native AST, without the production
    # strategy-file selector or strategy extraction/summary implementation.
    native_cards: dict[str, Block] = {}
    native_sources: dict[str, str] = {}
    for path in sorted((config.GAME / "common/ai_strategies").glob("*.txt")):
        parsed = parse_bytes(path.read_bytes(), path=path.as_posix())
        assert not parsed.errors, (path, parsed.errors)
        for entry in parsed.root.assignments():
            if not isinstance(entry.value, Block):
                continue
            type_fields = entry.value.all("type")
            political_types = [
                field
                for field in type_fields
                if isinstance(field.value, Scalar) and field.value.unquoted == "political"
            ]
            if not political_types:
                continue
            assert len(type_fields) == len(political_types) == 1
            assert entry.op == "="
            assert entry.prefix is None
            assert political_types[0].op == "="
            assert political_types[0].prefix is None
            assert entry.key not in native_cards
            native_cards[entry.key] = entry.value
            native_sources[entry.key] = path.relative_to(config.GAME).as_posix()
    assert set(native_cards) == expected_names
    assert set(native_sources.values()) == {"common/ai_strategies/03_political_strategies.txt"}

    strategies = political_surface.read_strategies(config.GAME)
    by_name = {strategy.name: strategy for strategy in strategies}
    assert len(strategies) == len(expected_names)
    assert set(by_name) == expected_names == set(native_cards)
    if selected_version == "1.15.0":
        for name, chance, aversion in (
            ("ai_strategy_consolidation_agenda", 10, 75),
            ("ai_strategy_confrontation_agenda", 20, 25),
        ):
            possible = native_cards[name].all("possible")
            assert len(possible) == 1
            assert possible[0].op == "="
            assert possible[0].prefix is None
            assert isinstance(possible[0].value, Block)
            clauses = possible[0].value.items
            assert len(clauses) == 1
            guard = clauses[0]
            assert isinstance(guard, Assignment)
            assert guard.key == "has_radical_leftist_government"
            assert guard.op == "="
            assert guard.prefix is None
            assert isinstance(guard.value, Scalar)
            assert guard.value.unquoted == "yes"
            card = by_name[name]
            assert card.possible_keys == ("has_radical_leftist_government",)
            assert card.change_law_chance is not None
            assert card.change_law_chance.base == chance
            assert card.revolution_aversion is not None
            assert card.revolution_aversion.base == aversion
    tanzimat = by_name["ai_strategy_tanzimat_reforms"]
    assert tanzimat.change_law_chance is not None
    assert tanzimat.change_law_chance.base == 100
    assert tanzimat.revolution_aversion is not None
    assert tanzimat.revolution_aversion.base == 25
