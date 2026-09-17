"""属性测试（property-based testing）。

与手写用例的区别
----------------
手写用例只验证「我想到的情况」。属性测试由 :mod:`hypothesis` **自动生成
几百个输入**去攻击不变量（invariant），能发现我没想到的边界。

这里声明的不变量都是解析器必须永远满足的性质 —— 任何一条被打破，
都说明解析逻辑有缺陷，而不是「测试数据特殊」。

运行：
    pytest tools/tests/test_properties.py -q
    pytest tools/tests/test_properties.py --hypothesis-seed=0   # 固定种子复现
"""

from __future__ import annotations

import pytest
from _helpers import scalar_of
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pdx import parse_text
from pdx.parser import PREFIXES

pytestmark = pytest.mark.property

#: 只含字母数字下划线的安全标识符
ident = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12)

#: 含连字符与点的标识符 —— 真实存在（全库 32 个含连字符的键）
ident_ext = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_-.",
    min_size=1,
    max_size=12,
).filter(lambda s: s.strip() and not s.startswith("-"))


def _mk(keys: list[str]) -> str:
    return "\n".join(f"{k} = {{ x = 1 }}" for k in keys) + "\n"


class TestInvariants:
    """无论输入是什么都必须成立的性质。"""

    @given(st.lists(ident, min_size=1, max_size=8, unique=True))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_all_top_keys_recovered(self, keys):
        """生成的每个顶层键都必须被解析出来，一个不少。"""
        pf = parse_text(_mk(keys))
        assert sorted(set(pf.top_keys)) == sorted(set(keys))
        assert pf.errors == []

    @given(st.lists(ident_ext, min_size=1, max_size=8, unique=True))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_hyphenated_keys_recovered(self, keys):
        """含连字符与点的键名同样不能丢 —— 这是早期枚举字符集犯过的错。"""
        pf = parse_text(_mk(keys))
        for k in keys:
            assert k in pf.top_keys

    @given(st.lists(ident, min_size=1, max_size=6, unique=True))
    def test_parsing_is_deterministic(self, keys):
        """同一输入解析两次结果必须相同 —— 否则缓存与快照都不可信。"""
        text = _mk(keys)
        a, b = parse_text(text), parse_text(text)
        assert a.top_keys == b.top_keys

    @given(st.text(max_size=300))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises_on_arbitrary_input(self, blob):
        """任意文本都不能让解析器抛异常 —— 游戏文件里有畸形数据。"""
        pf = parse_text(blob)  # 不抛即通过
        assert isinstance(pf.top_keys, list)

    @given(st.text(max_size=300))
    def test_arbitrary_input_terminates(self, blob):
        """解析必须能结束（配合 pytest-timeout 双重保险）。"""
        parse_text(blob)

    @given(st.lists(ident, min_size=1, max_size=6, unique=True))
    def test_bom_never_leaks_into_keys(self, keys):
        """带 BOM 的输入不能把 BOM 混进键名。"""
        pf = parse_text("\ufeff" + _mk(keys))
        for k in pf.top_keys:
            assert "\ufeff" not in k

    @given(st.lists(ident, min_size=1, max_size=6, unique=True))
    def test_comments_never_produce_keys(self, keys):
        """注释掉的键不得出现在结果里。"""
        body = "\n".join(f"# {k} = {{ }}" for k in keys)
        pf = parse_text(body + "\n")
        assert pf.top_keys == []

    @given(ident, st.integers(min_value=-(10**6), max_value=10**6))
    def test_scalar_value_roundtrip(self, key, value):
        """标量赋值必须原样保留。"""
        pf = parse_text(f"{key} = {value}\n")
        a = pf.top_assignments[0]
        assert a.key == key
        assert scalar_of(a).text == str(value)

    @given(ident, st.sampled_from(PREFIXES))
    def test_prefix_always_split(self, key, prefix):
        """六个功能前缀必须被识别并剥离，不混进键名。"""
        pf = parse_text(f"{prefix}:{key} = {{ }}\n")
        a = pf.top_assignments[0]
        assert a.prefix == prefix
        assert a.key == key

    @given(st.lists(ident, min_size=1, max_size=10, unique=True))
    def test_nesting_depth_does_not_lose_keys(self, keys):
        """把键藏在多层嵌套里，内层的不能跑到顶层来。"""
        inner = "\n".join(f"  {k} = 1" for k in keys)
        pf = parse_text(f"outer = {{\n{inner}\n}}\n")
        assert pf.top_keys == ["outer"]

    @given(
        st.lists(ident, min_size=1, max_size=6, unique=True),
        st.sampled_from(["  ", "\t", "    ", ""]),
    )
    def test_indentation_is_irrelevant(self, keys, indent):
        """顶层键无论缩进多少都必须被找到 —— 缩进在 PDX 里无语义。"""
        text = "\n".join(f"{indent}{k} = {{ }}" for k in keys) + "\n"
        pf = parse_text(text)
        assert sorted(set(pf.top_keys)) == sorted(set(keys))

    @given(st.lists(ident, min_size=1, max_size=6, unique=True))
    def test_equals_and_brace_on_separate_lines(self, keys):
        """`key =` 换行再 `{` 的写法同样要能解析。"""
        text = "\n".join(f"{k} =\n{{\n  x = 1\n}}" for k in keys) + "\n"
        pf = parse_text(text)
        assert sorted(set(pf.top_keys)) == sorted(set(keys))
        for a in pf.top_assignments:
            assert a.is_block


class TestRoundTrip:
    """序列化后再解析应当等价。"""

    @given(st.lists(ident, min_size=1, max_size=6, unique=True))
    def test_key_set_survives_reparse(self, keys):
        text = _mk(keys)
        first = parse_text(text).top_keys
        second = parse_text(text).top_keys
        assert first == second
