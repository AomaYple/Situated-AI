"""生产扩展底本、配置边界和市场对称性合同。"""

import re
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import decisions
from pdx.parser import parse_text
from pdx.situated import pdx_eval

pytestmark = pytest.mark.unit


def test_未验收扩展默认停用():
    policy = decisions.load_extensions()
    assert not policy.reform_enabled
    assert not policy.market_enabled
    assert len(decisions.build()) == 5


def test_发布_profile_是唯一生产扩展开关来源():
    policy = decisions.load_extensions(profile="release")
    assert all(
        getattr(policy, f"{name}_enabled")
        for name in ("reform", "market", "security", "economy", "diplomacy")
    )
    assert not hasattr(policy, "subjects_enabled")


def test_未知发布_profile_或模块明确失败(tmp_path):
    source = tmp_path / "extensions.toml"
    text = decisions.EXTENSIONS.read_text(encoding="utf-8")
    source.write_text(
        text.replace(
            'release = ["reform", "market", "security", "economy", "diplomacy"]',
            'release = ["subjects"]',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="profile"):
        decisions.load_extensions(source, profile="release")
    with pytest.raises(ValueError, match="不存在"):
        decisions.load_extensions(profile="missing")


def test_启用扩展只追加声明字段且原版逐字保留():
    policy = replace(decisions.load_extensions(), reform_enabled=True, market_enabled=True)
    files = decisions.build(extensions=policy)
    patched = files["common/ai_strategies/00_default_strategy.txt"]
    restored = re.sub(
        r"\t\t# SITAI BEGIN [^\n]+\n.*?\t\t# SITAI END [^\n]+\n", "", patched, flags=re.DOTALL
    )
    assert restored == decisions.BASELINE.read_text(encoding="utf-8")
    assert patched.count("# SITAI BEGIN") == 5
    for name, text in files.items():
        assert "\r" not in text
        assert not text.startswith("\ufeff")
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    support = patched.split("# SITAI BEGIN diplomatic_play_support")[1].split("# SITAI END")[0]
    assert "desc = SITAI_MARKET_DEPENDENCE_SUPPORT_REASON" in support
    assert "ROOT.economic_dependence(scope:country)" in support
    assert "subtract" in support


def test_关闭经济模块时改革输出不保留跨模块关系():
    """模块开关必须隔离行动关系，而不只是删除顶层消费者字段。"""
    policy = replace(
        decisions.load_extensions(),
        reform_enabled=True,
        economy_enabled=False,
    )
    patched = decisions.build(extensions=policy)["common/ai_strategies/00_default_strategy.txt"]
    reform = patched.split("# SITAI BEGIN change_law_chance", 1)[1].split("# SITAI END", 1)[0]
    assert "# ACTION political_reform" in reform

    enabled = replace(policy, economy_enabled=True)
    enabled_text = decisions.build(extensions=enabled)[
        "common/ai_strategies/00_default_strategy.txt"
    ]
    enabled_reform = enabled_text.split("# SITAI BEGIN change_law_chance", 1)[1].split(
        "# SITAI END", 1
    )[0]
    facts = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": 80,
        "scaled_debt": 0.2,
        "net_total_income": 1,
        "bureaucracy": 1,
        "literacy_rate": 0.3,
    }
    result = pdx_eval.select(reform, facts)
    enabled_result = pdx_eval.select(enabled_reform, facts)
    assert (result.action_id, result.delta) == ("political_reform", 0.5)
    assert (enabled_result.action_id, enabled_result.delta) == ("political_reform", 0.75)


@pytest.mark.parametrize("fiscal_enabled", [False, True])
def test_外交开关隔离aggression消费者和所有权(fiscal_enabled):
    fiscal = replace(decisions.load(), enabled=fiscal_enabled)
    disabled = replace(decisions.load_extensions(), diplomacy_enabled=False)
    disabled_files = decisions.build(fiscal, extensions=disabled)
    disabled_text = disabled_files["common/ai_strategies/00_default_strategy.txt"]
    assert "# ACTION diplomatic_aggression_guard" not in disabled_text

    enabled = replace(disabled, diplomacy_enabled=True)
    enabled_files = decisions.build(fiscal, extensions=enabled)
    enabled_text = enabled_files["common/ai_strategies/00_default_strategy.txt"]
    assert "# ACTION diplomatic_aggression_guard" in enabled_text


@given(
    st.floats(min_value=0, max_value=5, allow_nan=False),
    st.floats(min_value=0, max_value=5, allow_nan=False),
)
def test_交换依赖双方分数符号相反且对称有限(a, b):
    left = decisions.market_delta(a, b, multiplier=5)
    assert left == -decisions.market_delta(b, a, multiplier=5)
    assert -25 <= left <= 25
    assert decisions.market_delta(a, a, multiplier=5) == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 6])
def test_市场未知值与越界不能当零(value):
    with pytest.raises(ValueError):
        decisions.market_delta(value, 0, multiplier=5)


@pytest.mark.parametrize(
    "mutation",
    [
        "enabled = false|enabled = 1",
        "legitimacy = 75|legitimacy = 101",
        "fragile_legitimacy = 25|fragile_legitimacy = 80",
        "bonus = 1.0|bonus = nan",
        "penalty = -0.5|penalty = -1.0",
        "multiplier = 5.0|multiplier = 11",
        "schema_version = 1|schema_version = true",
    ],
)
def test_拒绝不可靠扩展参数(tmp_path, mutation):
    before, after = mutation.split("|")
    path = tmp_path / "extensions.toml"
    path.write_text(
        decisions.EXTENSIONS.read_text(encoding="utf-8").replace(before, after), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        decisions.load_extensions(path)
