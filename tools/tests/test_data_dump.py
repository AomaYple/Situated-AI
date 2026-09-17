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


def test_列表里嵌套块() -> None:
    got = _value_of("a = { x = { y = 1 }  z = { w = 2 } }\n", "a")
    assert got == {"x": {"y": "1"}, "z": {"w": "2"}}


# ── 产物 ────────────────────────────────────────────────────
@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物含值而不只是字段名() -> None:
    """核心断言：随便挑一个条目，必须能看到**值**。"""
    data = to_data_dict()
    rec = data["game"]["common/buildings/08_monuments.txt"]["building_angkor_wat"]
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
    data = to_data_dict()
    assert set(data) == {"game", "jomini", "clausewitz"}
    tops = {k.split("/")[0] for k in data["game"]}
    for must in ("common", "events", "gui", "gfx", "map_data", "dlc"):
        assert must in tops, f"{must} 没有出现在结构化产物里"


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物规模与条目数相称() -> None:
    """防止「产物在但内容空」这种假通过。"""
    data = to_data_dict()
    files = sum(len(v) for v in data.values())
    entries = sum(
        len(body) for root in data.values() for body in root.values()
    )
    assert files > 5_000, f"只覆盖 {files} 个文件"
    assert entries > 30_000, f"只收录 {entries} 个顶层条目"


@_needs_game
@pytest.mark.integration
@pytest.mark.slow
def test_产物可被JSON往返() -> None:
    """必须是纯 JSON 可序列化的结构 —— 不能混进 AST 对象。"""
    data = to_data_dict()
    # 挑 law 目录下真实存在的第一个文件，不写死文件名
    key = next(k for k in data["game"] if k.startswith("common/laws/"))
    sample = data["game"][key]
    blob = json.dumps(sample, ensure_ascii=False)
    assert json.loads(blob) == sample
