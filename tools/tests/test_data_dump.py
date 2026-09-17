"""结构化转储测试：确认产物里存的是**信息**而不是名字。

背景
----
这是第二层「全量」审计发现的缺口。第一层审的是「哪些文件被解析」，
第二层审的是「被解析的文件里信息是不是都提出来了」—— 后者此前不达标：

``building_angkor_wat`` 在原文件里有 ``building_group = bg_monuments``、
``potential = { state_region = s:STATE_CAMBODIA }`` 这样的**值**，
而产物里只剩 15 个字段名 ``['background', 'building_group', 'potential', …]``。
mod 作者据此无法回答「默认值是多少」「这个块里能写什么」。

:func:`pdx.analyze.dump_node` 把 AST 还原成纯数据，本文件锁住它的表示法。
"""

from __future__ import annotations

import json

import pytest

from pdx import config
from pdx.analyze import dump_node, to_data_dict
from pdx.parser import parse_text

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用"
)


def _value_of(text: str, key: str):
    pf = parse_text(text, "<t>")
    a = next(x for x in pf.top_assignments if x.key == key)
    return dump_node(a.value)


# ── 表示法 ──────────────────────────────────────────────────
def test_标量原样保留() -> None:
    """不做类型推断 —— yes/1/foo 在语法层没有区别，语义由使用处决定。"""
    assert _value_of("a = yes\n", "a") == "yes"
    assert _value_of("a = 1.5\n", "a") == "1.5"
    assert _value_of('a = "带 空格 的"\n', "a") == '"带 空格 的"'


def test_空块是空字典() -> None:
    assert _value_of("a = { }\n", "a") == {}


def test_具名块是嵌套字典() -> None:
    assert _value_of("a = { b = 1  c = 2 }\n", "a") == {"b": "1", "c": "2"}


def test_纯标量块是列表() -> None:
    """PDX 的列表写法 ``key = { a b c }``。"""
    assert _value_of("a = { x y z }\n", "a") == ["x", "y", "z"]


def test_混合块保留顺序() -> None:
    """既有具名赋值又有裸标量时用列表，顺序有意义。"""
    got = _value_of("a = { p  q = 1  r }\n", "a")
    assert got == ["p", {"q": "1"}, "r"]


def test_空值是None() -> None:
    assert _value_of("a =\n", "a") is None


def test_功能前缀保留在键名上() -> None:
    """``REPLACE:foo`` 的语义与 ``foo`` 完全不同，前缀不能丢。"""
    pf = parse_text("a = { REPLACE:b = 1 }\n", "<t>")
    a = next(x for x in pf.top_assignments if x.key == "a")
    assert dump_node(a.value) == {"REPLACE:b": "1"}


def test_任意深度都能还原() -> None:
    text = "a = { b = { c = { d = { e = 1 } } } }\n"
    assert _value_of(text, "a") == {"b": {"c": {"d": {"e": "1"}}}}


def test_重复键不被覆盖() -> None:
    """PDX 允许同级重复键，实测全库有 1,299 个顶层条目如此。

    直接建成字典会静默覆盖成最后一个 —— 那是实打实的信息丢失。
    检测到重复时退回保序列表，重数与顺序都保住。
    """
    got = _value_of("a = { b = 1  b = 2  b = 3 }\n", "a")
    assert got == [{"b": "1"}, {"b": "2"}, {"b": "3"}], "三个 b 必须都在"


def test_重复键在顶层也保留() -> None:
    pf = parse_text("x = 1\nx = 2\n", "<t>")
    keys = [a.key for a in pf.top_assignments]
    assert keys.count("x") == 2, "解析器本身不该去重"
    # 产物侧：一个文件块里出现重复键时同样要保序保数
    from pdx.analyze import dump_node as dn
    block = pf.root
    got = dn(block)
    assert got == [{"x": "1"}, {"x": "2"}]


def test_列表里嵌套块() -> None:
    got = _value_of("a = { x = { y = 1 }  z = { w = 2 } }\n", "a")
    assert got == {"x": {"y": "1"}, "z": {"w": "2"}}


# ── 产物 ────────────────────────────────────────────────────
@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物含值而不只是字段名() -> None:
    """核心断言：随便挑一个条目，必须能看到**值**。"""
    data = to_data_dict()["数据"]
    body = data["game"]["common/buildings/08_monuments.txt"]
    # 文件顶层正常时是字典
    assert isinstance(body, dict)
    rec = body["building_angkor_wat"]
    # 字段名存在
    assert "building_group" in rec
    # **值**存在 —— 这正是此前缺失的东西
    assert rec["building_group"] == "bg_monuments"
    assert rec["potential"] == {"state_region": "s:STATE_CAMBODIA"}
    assert rec["city_gfx_interactions"]["size"] == "5"
    assert rec["production_method_groups"] == ["pmg_base_building_angkor_wat"]


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物覆盖全部三个内容根与全部脚本目录() -> None:
    data = to_data_dict()["数据"]
    assert set(data) == {"game", "jomini", "clausewitz"}
    tops = {k.split("/")[0] for k in data["game"]}
    for must in ("common", "events", "gui", "gfx", "map_data", "dlc"):
        assert must in tops, f"{must} 没有出现在结构化产物里"


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物规模与条目数相称() -> None:
    """防止「产物在但内容空」这种假通过。"""
    data = to_data_dict()["数据"]
    files = sum(len(v) for v in data.values())
    entries = sum(
        len(body) for root in data.values() for body in root.values()
    )
    assert files > 5_000, f"只覆盖 {files} 个文件"
    assert entries > 30_000, f"只收录 {entries} 个顶层条目"


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_文件层级的重复键也不被压掉() -> None:
    """实测 european.txt 顶层有 383 个同名的 variation。

    这条防的是一个具体的 bug：dump_node 里做了重复检测，但 to_data_dict
    在文件层级**又自己写了一遍字典推导式**绕过了它，于是顶层重复照样被压。
    """
    data = to_data_dict()["数据"]
    key = "gfx/portraits/accessory_variations/european.txt"
    body = data["game"][key]
    assert isinstance(body, list), "顶层有重复键时必须退回保序列表"
    names = [
        next(iter(x)) for x in body if isinstance(x, dict)
    ]
    assert names.count("variation") > 300, (
        f"variation 只保留了 {names.count('variation')} 个，重复键被压掉了"
    )


# ── 位置索引与注释 ──────────────────────────────────────────
def test_条目索引记录行号() -> None:
    from pdx.analyze import build_entry_index
    pf = parse_text("\n\na = 1\n\nb = 2\n", "<t>")
    idx = build_entry_index(pf)
    assert idx["a"]["行"] == 3
    assert idx["b"]["行"] == 5


def test_注释归给下方最近的条目() -> None:
    """PDX 的书写惯例：说明写在被说明的条目上方。"""
    from pdx.analyze import build_entry_index
    pf = parse_text(
        "# 属于 a 的说明\na = 1\n\n# 属于 b 的说明\n# 第二行\nb = 2\n", "<t>"
    )
    idx = build_entry_index(pf)
    assert idx["a"]["注释"] == ["属于 a 的说明"]
    assert idx["b"]["注释"] == ["属于 b 的说明", "第二行"]


def test_没有注释时索引里不带注释字段() -> None:
    """不塞空列表 —— 索引有 7.7 万条目，空字段也是体积。"""
    from pdx.analyze import build_entry_index
    idx = build_entry_index(parse_text("a = 1\n", "<t>"))
    assert idx["a"] == {"行": 1}


def test_词法器收集注释但不改变token流() -> None:
    """注释收集是**可选出参**，token 流必须一字不变。"""
    from pdx.lexer import tokenize
    text = 'a = "x # 不是注释" # 真注释\nb = 2\n'
    plain = [(t.kind, t.value, t.line, t.col) for t in tokenize(text)]
    comments: list[tuple[int, str]] = []
    withc = [(t.kind, t.value, t.line, t.col) for t in tokenize(text, comments)]
    assert plain == withc, "收集注释不能影响 token 流"
    assert comments == [(1, "# 真注释")]


def test_字符串里的井号不算注释() -> None:
    from pdx.lexer import tokenize
    comments: list[tuple[int, str]] = []
    tokenize('a = "x # y"\n', comments)
    assert comments == []


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_真实语料里能取到条目注释() -> None:
    """注释此前被整体丢弃；现在必须真能取到内容而不只是空壳。"""
    data = to_data_dict()
    idx = data["索引"]["game"]["common/buildings/08_monuments.txt"]
    with_comment = {k: v for k, v in idx.items() if "注释" in v}
    assert with_comment, "这份文件里应当有带注释的条目"
    for v in with_comment.values():
        assert isinstance(v["注释"], list)
        assert v["注释"], "注释不能是空列表"


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_表格数据被解析() -> None:
    """adjacencies.csv 定义海峡连通性，mod 改地图必动它。

    它不是 PDX 语法，此前落在所有范围之外 —— 既没被 PDX 解析器处理，
    也没有专用读取器。
    """
    from pdx.tabular import extract_tables

    r = extract_tables(config.GAME)
    assert r.tables, "应当至少解析出一个表格"
    t = next(x for x in r.tables if x.rel.endswith("adjacencies.csv"))
    assert t.delimiter == ";"
    assert "From" in t.columns
    assert "Comment" in t.columns
    assert t.row_count > 200
    assert not r.errors
    # 行式与列式必须自洽
    d = t.to_dict()
    assert d["行数"] == t.row_count
    cols = d["列"]
    assert isinstance(cols, dict)
    assert len(cols["From"]) == t.row_count


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物可被JSON往返() -> None:
    """必须是纯 JSON 可序列化的结构 —— 不能混进 AST 对象。"""
    data = to_data_dict()["数据"]
    # 挑 law 目录下真实存在的第一个文件，不写死文件名
    key = next(k for k in data["game"] if k.startswith("common/laws/"))
    sample = data["game"][key]
    blob = json.dumps(sample, ensure_ascii=False)
    assert json.loads(blob) == sample
