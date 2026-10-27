"""完整候选的隔离、实际生成分支与交付契约；不模拟引擎或宣称行为质量。"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from typing import cast

import pytest

from pdx import decisions, distribution
from pdx.model import Block, Scalar
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_外部配置默认隔离且旧源兼容(tmp_path):
    extra = decisions.load_extensions()
    assert extra.security_enabled is False
    assert extra.security_commitment_bonus == 25
    old = tmp_path / "extensions.toml"
    old.write_text(
        decisions.EXTENSIONS.read_text(encoding="utf-8").split("[security]")[0],
        encoding="utf-8",
    )
    assert decisions.load_extensions(old).security_enabled is False


def test_外部权重直接调用拒绝非法输入且关闭不干预():
    from pdx import decision_security

    for value in (True, "25", float("nan"), float("inf"), -1, 51, 10**1000):
        extra = replace(
            decisions.Extensions(),
            security_enabled=True,
            security_commitment_bonus=cast("float", value),
        )
        with pytest.raises(ValueError, match="外部防御权重"):
            decision_security.support_addition(extra)
    assert decision_security.support_addition(decisions.Extensions()) == ""
    assert "COMMITMENT" not in decision_security.support_addition(
        replace(decisions.Extensions(), security_enabled=True, security_commitment_bonus=0)
    )


def test_外部配置超大整数按配置错误拒绝(tmp_path):
    text = decisions.EXTENSIONS.read_text(encoding="utf-8")
    source = tmp_path / "huge.toml"
    source.write_text(
        text.replace("commitment_bonus = 25", f"commitment_bonus = {10**1000}"),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="外部防御权重"):
        decisions.load_extensions(source)


def test_打包命令只生成唯一正式变体(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pdx.cli import app

    calls = []

    def capture(destination):
        calls.append(destination)
        return destination

    monkeypatch.setattr(distribution, "package", capture)
    runner = CliRunner()
    output = tmp_path / "release.zip"
    result = runner.invoke(app, ["package", "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert calls == [output]


@pytest.mark.parametrize(
    "mutation",
    [
        ("enabled = false", "enabled = 1"),
        ("commitment_bonus = 25", "commitment_bonus = nan"),
        ("commitment_bonus = 25", "commitment_bonus = true"),
        ("threat_bonus = 15", "threat_bonus = -1"),
        ("threat_bonus = 15", "threat_bonus = 51"),
        ("[security]", "[security]\nunknown = 1"),
    ],
)
def test_外部配置拒绝非有限越界和未知字段(tmp_path, mutation):
    text = decisions.EXTENSIONS.read_text(encoding="utf-8")
    before, after = mutation
    assert before in text
    if before == "enabled = false":
        head, tail = text.split("[security]")
        text = head + "[security]" + tail.replace(before, after)
    else:
        text = text.replace(before, after)
    source = tmp_path / "bad.toml"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        decisions.load_extensions(source)


@pytest.mark.integration
def test_正式候选包含所有生产模块且不修改生成源():
    baseline_before = decisions.BASELINE.read_bytes()
    before = decisions.build()
    policy, extra, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    assert set(metadata["enabled_modules"]) == {
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "information_rules",
        "consumer_adapters",
        "country_state",
    }
    assert metadata["status"] == "candidate"
    assert policy.aggression == 0
    assert extra.security_enabled
    assert extra.economy_enabled
    assert extra.diplomacy_enabled
    assert decisions.load_extensions(profile="release") == extra
    assert decisions.build() == before
    assert decisions.BASELINE.read_bytes() == baseline_before
    patched = files["common/ai_strategies/00_default_strategy.txt"]
    assert "# SITAI BEGIN " in patched
    assert "# SITAI END " in patched
    for name, text in files.items():
        if isinstance(text, bytes):
            assert name == distribution.THUMBNAIL_NAME
            assert text.startswith(b"\x89PNG\r\n\x1a\n")
            continue
        assert not text.startswith("\ufeff")
        assert "\r" not in text
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors


def _block(parent, key):
    node = parent.first(key)
    assert node is not None
    assert isinstance(node.value, Block)
    return node.value


def _security_delta(text, *, initiator, commitment, threat, ai=True, complete=True):
    """执行生成支持分支，条件叶子单独注入；不是游戏作用域校准。"""
    block = _block(parse_text("probe = { value = 0\n" + text + "\n}").root, "probe")

    def condition(body):
        result = []
        for node in body.assignments():
            if node.key == "NOT":
                result.append(not condition(node.value))
            elif node.key == "exists":
                assert isinstance(node.value, Scalar)
                result.append(
                    initiator if node.value.unquoted == "scope:is_initiator" else complete
                )
            elif node.key == "ROOT":
                assert node.op == "?="
                result.append(condition(node.value))
            elif node.key == "is_ai":
                result.append(ai)
            elif node.key == "sitai_defense_commitment":
                partner = node.value.first("PARTNER").value.unquoted
                assert partner == ("scope:enemy_country" if initiator else "scope:country")
                result.append(commitment)
            elif node.key == "sitai_neighbor_defense":
                partner = node.value.first("PARTNER").value.unquoted
                opponent = node.value.first("OPPONENT").value.unquoted
                assert partner == ("scope:enemy_country" if initiator else "scope:country")
                assert opponent == ("scope:country" if initiator else "scope:enemy_country")
                result.append(threat)
            else:
                raise AssertionError(f"未实现的生成条件：{node.key}")
        return all(result)

    def execute(body):
        total = 0.0
        selected = False
        for node in body.assignments():
            if node.key in {"if", "else_if", "else"}:
                if node.key == "if":
                    selected = False
                if not selected and (node.key == "else" or condition(_block(node.value, "limit"))):
                    selected = True
                    total += execute(node.value)
            elif node.key == "add":
                value = node.value
                if isinstance(value, Block):
                    amount = value.first("value")
                    assert amount is not None
                    value = amount.value
                assert isinstance(value, Scalar)
                total += float(value.unquoted)
        return total

    return execute(block)


def test_实际外部生成分支防御对称不重复加分且有上下文保护():
    from pdx import decision_security

    for commitment_bonus, threat_bonus in [(25, 15), (5, 20), (0, 0)]:
        extra = replace(
            decisions.load_extensions(),
            security_enabled=True,
            security_commitment_bonus=commitment_bonus,
            security_threat_bonus=threat_bonus,
        )
        text = decision_security.support_addition(extra)
        for commitment, threat, initiator, ai, complete in itertools.product(
            [False, True], repeat=5
        ):
            expected = max(
                commitment_bonus if commitment else 0,
                threat_bonus if threat else 0,
            )
            expected *= -1 if initiator else 1
            if not ai or not complete:
                expected = 0
            assert (
                _security_delta(
                    text,
                    initiator=initiator,
                    commitment=commitment,
                    threat=threat,
                    ai=ai,
                    complete=complete,
                )
                == expected
            )


def test_完整开关关闭清理外部文件且不删用户文件(tmp_path):
    extra = replace(decisions.load_extensions(), security_enabled=True, market_enabled=True)
    active = decisions.build(extensions=extra)
    disabled = decisions.build(
        replace(decisions.load(), enabled=False), extensions=decisions.Extensions()
    )
    decisions.write(tmp_path, active)
    user = tmp_path / "common/scripted_triggers/user.txt"
    user.write_text("# 用户文件\n", encoding="utf-8")
    decisions.write(tmp_path, disabled)
    assert not (tmp_path / "common/scripted_triggers/sitai_security_triggers.txt").exists()
    assert user.exists()
    issues = decisions.check(tmp_path, disabled)
    assert len(issues) == 1
    assert "user.txt" in issues[0]


def test_防御条件真正读取目标条约与敌方战争目标():
    from pdx import decision_security

    tree = parse_text(
        decision_security.triggers()
        .replace("$PARTNER$", "scope:defender")
        .replace("$OPPONENT$", "scope:attacker")
    )
    assert not tree.errors

    def matches(body, context):
        outcomes = []
        for node in body.assignments():
            value = node.value
            if node.key == "OR":
                outcomes.append(
                    any(matches(Block([item]), context) for item in value.assignments())
                )
            elif node.key == "any_scope_treaty":
                outcomes.append(any(matches(value, treaty) for treaty in context["treaties"]))
            elif node.key == "any_scope_article":
                outcomes.append(
                    any(matches(value, {"article": item}) for item in context["articles"])
                )
            elif node.key == "binds":
                outcomes.append(context["partner"] == value.unquoted)
            elif node.key == "has_type":
                outcomes.append(context["article"] == value.unquoted)
            elif node.key == "is_adjacent_to_country":
                outcomes.append(value.unquoted in context["neighbors"])
            elif node.key == "scope:attacker":
                outcomes.append(matches(value, context["attacker"]))
            elif node.key == "play_participant_has_war_goal_of_type_against":
                kind = value.first("type").value.unquoted
                target = value.first("target").value.unquoted
                outcomes.append((kind, target) in context["goals"])
            else:
                raise AssertionError(node.key)
        return all(outcomes)

    commitment = _block(tree.root, "sitai_defense_commitment")
    for partner, article in itertools.product(
        ["scope:defender", "scope:attacker"],
        ["alliance", "defensive_pact", "guarantee_independence", "trade_agreement"],
    ):
        actual = matches(commitment, {"treaties": [{"partner": partner, "articles": [article]}]})
        assert actual == (partner == "scope:defender" and article in {"alliance", "defensive_pact"})
    assert not matches(commitment, {"treaties": []})
    threat = _block(tree.root, "sitai_neighbor_defense")
    for adjacent, kind, target in itertools.product(
        [False, True],
        ["conquer_state", "make_protectorate", "humiliation"],
        ["scope:defender", "scope:attacker"],
    ):
        actual = matches(
            threat,
            {
                "neighbors": {"scope:defender"} if adjacent else set(),
                "attacker": {"goals": [(kind, target)]},
            },
        )
        assert actual == (adjacent and kind != "humiliation" and target == "scope:defender")
