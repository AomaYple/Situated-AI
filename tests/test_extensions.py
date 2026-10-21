"""生产扩展底本、配置边界和市场对称性合同。"""

import re
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import decisions
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_未验收扩展默认停用():
    policy = decisions.load_extensions()
    assert not policy.reform_enabled
    assert not policy.market_enabled
    assert len(decisions.build()) == 5


def test_启用扩展只追加声明字段且原版逐字保留():
    policy = replace(decisions.load_extensions(), reform_enabled=True, market_enabled=True)
    files = decisions.build(extensions=policy)
    patched = files["common/ai_strategies/00_default_strategy.txt"]
    restored = re.sub(
        r"\t\t# SITAI BEGIN [^\n]+\n.*?\t\t# SITAI END [^\n]+\n", "", patched, flags=re.DOTALL
    )
    assert restored == decisions.BASELINE.read_text(encoding="utf-8")
    assert patched.count("# SITAI BEGIN") == 3
    for name, text in files.items():
        assert "\r" not in text
        assert not text.startswith("\ufeff")
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    support = patched.split("# SITAI BEGIN diplomatic_play_support")[1].split("# SITAI END")[0]
    assert "desc = SITAI_MARKET_DEPENDENCE_SUPPORT_REASON" in support
    assert "ROOT.economic_dependence(scope:country)" in support
    assert "subtract" in support


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
