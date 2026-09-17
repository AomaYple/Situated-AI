"""词法分析器差分测试（differential testing）。

思路
----
拿**优化前的实现**当作预言机（见 :mod:`_oracle_lexer`），在真实语料上
把两者的 token 流逐项比对。这比"我读代码觉得一样"强得多：

* 真实语料有 4,400 个文件、数百万 token，覆盖官方脚本的全部古怪写法
* 比对的是 ``(kind, value, line, col)`` 四元组，连行列号都必须一致
* hypothesis 再补上人为构造的边界输入（未闭合引号、孤立反斜杠、BOM 等）

失败时输出**第一个分歧点**及其上下文，而不是把两个 token 列表全打印出来。
"""

from __future__ import annotations

import pytest
from _oracle_lexer import oracle_tuples
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pdx.lexer import tokenize

pytestmark = pytest.mark.unit


def _fields(token) -> tuple[str, str, int, int]:
    """取 token 的四元组。

    刻意不依赖 ``Token`` 可迭代 —— 它现在是 ``@dataclass(slots=True)``
    而不是 ``NamedTuple``，按字段取更稳，也顺带把「字段顺序变了」暴露出来。
    """
    return (token.kind, token.value, token.line, token.col)


def _diff(text: str, path: str = "<str>") -> list[str]:
    """返回分歧描述列表；空列表表示两者完全一致。"""
    want = oracle_tuples(text)
    got = [_fields(t) for t in tokenize(text)]
    if want == got:
        return []

    msgs = [f"{path}: token 数 期望 {len(want)} 实际 {len(got)}"]
    for i in range(max(len(want), len(got))):
        w = want[i] if i < len(want) else None
        g = got[i] if i < len(got) else None
        if w != g:
            lo = max(0, i - 3)
            msgs.append(f"  首个分歧 @ token #{i}")
            msgs.append(f"    期望 {want[lo : i + 1]}")
            msgs.append(f"    实际 {got[lo : i + 1]}")
            break
    return msgs


# ── 手写边界用例：逐条对应词法器里每个分支 ─────────────────
_BOUNDARY = {
    "空串": "",
    "纯空白": "  \t\r\n\v\f  ",
    "BOM 开头": "\ufeffa = 1",
    "BOM 夹在中间": "a\ufeffb = 1",
    "行注释": "a = 1 # 注释 { } =\nb = 2",
    "行尾注释无换行": "a = 1 # tail",
    "注释含引号": 'a = 1 # 他说 "你好\nb = 2',
    "井号在字符串里": 'a = "x # y" # 真注释\nb = 2',
    "字符串转义引号": 'a = "他说 \\"hi\\"" b = 2',
    "字符串转义反斜杠": 'a = "c:\\\\path" b = 2',
    "未闭合引号到行尾": 'a = "abc\nb = 2',
    "未闭合引号到文件尾": 'a = "abc',
    "引号内转义换行": 'a = "x\\\ny" b = 2',
    # ── 跨行字符串：2026-09 修正的语义，详见 lexer._TOKEN_RE 的说明 ──
    # 证据是真实文件 gfx/map/map_object_data/lakes.txt —— 它的
    # transform="..." 从第 10 行一直延续到第 25 行才闭合。
    # 旧实现遇到换行就截断，于是闭引号开启了一段新的"字符串"、
    # 把中间的 } 全吞掉，让 20 个文件误报「块没有闭合」。
    "跨行字符串": 'a = "line1\nline2"\nb = 2',
    "跨行字符串后接赋值": 'transform="1 2 3\n4 5 6"\nname="x"',
    "跨行字符串含花括号": 'a = "x {\n} y"\nb = { c = 1 }',
    "跨行字符串未闭合到文件尾": 'a = "line1\nline2\nline3',
    "只含换行的字符串": 'a = "\n"',
    "末尾孤立反斜杠": 'a = "abc\\',
    "单个问号": "a ? b",
    "问号等号": "a ?= b",
    "全部运算符": "a = b == c != d >= e <= f > g < h",
    "连续运算符": "a==b!=c",
    "花括号紧贴": "a={b={c=1}}",
    "无空格赋值": "a=1",
    "键含连字符": "my-key = 1",
    "键含冒号": "c:SWE = 1",
    "键含点号": "a.b.c = 1",
    "中文键值": "科技 = 蒸汽机",
    "CRLF 换行": "a = 1\r\nb = 2\r\n",
    "只有 CR": "a = 1\rb = 2",
    "深嵌套": "a={" * 40 + "x=1" + "}" * 40,
    "孤立右括号": "}}}",
    "孤立左括号": "{{{",
    "tab 缩进": "\ta = 1\n\t\tb = 2",
    "数字与负数": "a = -1.5e10 b = 0x1F",
    "Unicode 空白 NBSP": "a\u00a0=\u00a01",
    "emoji": "a = 🎉",
    "控制字符": "a = \x01\x02",
    "引号后紧跟原子": 'a = "x"y',
    "空字符串": 'a = ""',
    "值为空引号对": 'a = "" ""',
}


@pytest.mark.parametrize("name", sorted(_BOUNDARY))
def test_边界用例与预言机一致(name: str) -> None:
    """每个词法分支都要和预言机逐 token 对齐。"""
    text = _BOUNDARY[name]
    assert _diff(text, name) == [], f"用例《{name}》与预言机不一致"


# ── 真实语料 ────────────────────────────────────────────────
@pytest.mark.integration
def test_真实语料_抽样与预言机一致(corpus_texts) -> None:
    """默认跑：取排序后等距抽样的 120 个真实文件。

    等距抽样而非取前 N 个 —— 文件按路径排序，前 N 个会全落在
    ``clausewitz/`` 里，完全覆盖不到 ``common/`` 的复杂脚本。
    """
    if not corpus_texts:
        pytest.skip("语料不可用")
    n = len(corpus_texts)
    step = max(1, n // 120)
    sample = corpus_texts[::step]
    for path, text in sample:
        assert _diff(text, path) == [], f"{path} 与预言机不一致"


@pytest.mark.integration
@pytest.mark.slow
def test_真实语料_全量与预言机一致(corpus_texts) -> None:
    """慢速：全部 4,400 个真实文件，逐 token 比对。

    这是最重要的一条 —— 数百万 token 全过一遍，才敢说改写没动语义。
    """
    if not corpus_texts:
        pytest.skip("语料不可用")
    bad: list[str] = []
    for path, text in corpus_texts:
        msgs = _diff(text, path)
        if msgs:
            bad.extend(msgs)
            if len(bad) > 40:
                break
    assert not bad, "以下文件与预言机不一致：\n" + "\n".join(bad)


@pytest.mark.integration
def test_语料token总量记录(corpus_texts) -> None:
    """记录真实语料的 token 规模，作为性能讨论的量化依据。

    这条断言本身很弱（只查非空），价值在于把规模写进测试输出，
    让「快了多少」有分母。
    """
    if not corpus_texts:
        pytest.skip("语料不可用")
    total = sum(len(tokenize(t)) for _, t in corpus_texts)
    print(f"\n真实语料 token 总数：{total:,}（{len(corpus_texts):,} 个文件）")
    assert total > 1_000_000


# ── 模糊测试 ────────────────────────────────────────────────
#: PDX 脚本里真实出现的字符，外加刻意加入的"有毒"字符
_ALPHABET = list("abcXYZ019 \t\n\r{}[]<>=\"'#@$%^&*()+-_.,:;!?/\\|~`\ufeff\u00a0")


@settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(st.text(alphabet=_ALPHABET, max_size=400))
def test_模糊_任意文本与预言机一致(text: str) -> None:
    """随机字符序列：新实现不得在任何输入上偏离预言机。"""
    assert _diff(text) == []


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=300))
def test_模糊_任意Unicode与预言机一致(text: str) -> None:
    """全 Unicode 范围，含代理对之外的任意码位。"""
    assert _diff(text) == []


@settings(max_examples=150, deadline=None)
@given(
    st.lists(
        st.sampled_from(
            [
                "{",
                "}",
                "=",
                "?=",
                "==",
                "!=",
                ">",
                "<",
                ">=",
                "<=",
                '"',
                "\\",
                "#",
                "\n",
                " ",
                "\t",
                "a",
                "1",
                ":",
                "-",
                ".",
                "\ufeff",
                '"x"',
                "#c\n",
                '"a\\"b"',
            ]
        ),
        max_size=120,
    )
)
def test_模糊_结构片段拼接与预言机一致(parts: list[str]) -> None:
    """把 token 级别的片段随机拼接 —— 比纯随机文本更容易撞出边界。"""
    assert _diff("".join(parts)) == []


@settings(max_examples=100, deadline=None)
@given(st.text(alphabet=_ALPHABET, max_size=600))
def test_模糊_不抛异常(text: str) -> None:
    """无论输入多离谱，词法器只能返回 token 列表，不能抛异常。"""
    out = tokenize(text)
    assert out, "至少要有一个 EOF"
    assert out[-1].kind == "EOF"
