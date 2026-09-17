"""本地化提取测试。

为什么单独一个模块、单独一套测试
--------------------------------
本地化**不是** PDX 花括号语法，而是 ``key:版本号 "值"`` 的行式格式。
实测把它交给 :mod:`pdx.parser` 会得到 **0 个顶层键、0 个错误** ——
静默地什么都没解析出来。所以它必须有独立的提取器与独立的测试，
不能靠 PDX 那边的用例覆盖。

这也是覆盖面审计发现的**最大一处遗漏**：``.yml`` 一直挂在
``config.SCRIPTABLE_SUFFIXES`` 里看似被支持，但 ``localization/``
不在 ``SCRIPTABLE_DIRS`` 中，那 2,176 个文件从来没被读过内容，
只被数了个数。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.localization import (
    _category_of,
    extract_localization,
    parse_loc_text,
)

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "localization").is_dir(), reason="游戏目录不可用"
)


# ── 单文件解析 ──────────────────────────────────────────────
def test_语言取自文件头而不是目录名() -> None:
    """``localization/modifiers/`` 这种目录名不是语言码。"""
    lang, keys = parse_loc_text('l_english:\n KEY:0 "Value"\n')
    assert lang == "l_english"
    assert keys == ["KEY"]


def test_版本号不属于键名() -> None:
    """``KEY:0`` 里的 0 是给译者看的新旧标记，不是键的一部分。"""
    _, keys = parse_loc_text('l_english:\n buildings:0 "Buildings"\n law_1:1 "Law"\n')
    assert keys == ["buildings", "law_1"]


def test_值与引号不影响键名() -> None:
    _, keys = parse_loc_text(
        'l_english:\n A:0 "x"\n B:0 "has : colon"\n C:0 no_quotes\n'
    )
    assert keys == ["A", "B", "C"]


def test_注释与空行被跳过() -> None:
    text = 'l_english:\n\n# a comment:0 "x"\n\t\n KEY:0 "v"\n   # indented comment\n'
    _, keys = parse_loc_text(text)
    assert keys == ["KEY"]


def test_语言行带值时不算条目() -> None:
    """``l_english:1 "English"`` 是语言清单，不是数据键。"""
    _, keys = parse_loc_text('l_english:\n l_english:1 "English"\n REAL:0 "v"\n')
    assert keys == ["REAL"]


def test_多个语言段取最后一个() -> None:
    lang, keys = parse_loc_text('l_english:\n A:0 "x"\nl_french:\n B:0 "y"\n')
    assert lang == "l_french"
    assert keys == ["A", "B"]


def test_空文件不报错() -> None:
    lang, keys = parse_loc_text("")
    assert lang == "?"
    assert keys == []


def test_没有语言头时不猜语言() -> None:
    lang, keys = parse_loc_text(' ORPHAN:0 "v"\n')
    assert lang == "?"
    assert keys == ["ORPHAN"]


# ── 分类名 ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("stem", "want"),
    [
        ("buildings_l_english", "buildings"),
        ("law_l_simp_chinese", "law"),
        ("a_b_c_l_french", "a_b_c"),
        ("languages", "languages"),          # 不带 _l_xx 后缀
        ("trigger_localization_l_english", "trigger_localization"),
    ],
)
def test_分类名去掉语言后缀(stem: str, want: str) -> None:
    assert _category_of(stem) == want


# ── 目录级提取 ──────────────────────────────────────────────
def _make_tree(base, spec: dict[str, str]) -> None:
    for rel, body in spec.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def test_目录级提取与跨语言统计(tmp_path) -> None:
    _make_tree(
        tmp_path / "localization",
        {
            "english/buildings_l_english.yml": 'l_english:\n A:0 "a"\n B:0 "b"\n',
            "french/buildings_l_french.yml": 'l_french:\n A:0 "a"\n',
            "english/law_l_english.yml": 'l_english:\n C:0 "c"\n',
        },
    )
    r = extract_localization(tmp_path)
    assert r.files == 3
    assert r.unique_keys == 3
    assert set(r.by_lang) == {"l_english", "l_french"}
    assert r.by_lang["l_english"]["文件"] == 2
    assert r.by_lang["l_french"]["去重键"] == 1
    # 分类按文件名而不是目录名
    assert dict(r.by_category) == {"buildings": 3, "law": 1}


def test_按语言记录键集(tmp_path) -> None:
    _make_tree(
        tmp_path / "localization",
        {
            "english/a_l_english.yml": 'l_english:\n ONLY_EN:0 "x"\n BOTH:0 "y"\n',
            "french/a_l_french.yml": 'l_french:\n BOTH:0 "y"\n',
        },
    )
    r = extract_localization(tmp_path)
    assert r.entries["ONLY_EN"].langs == ("l_english",)
    assert r.entries["BOTH"].langs == ("l_english", "l_french")


def test_非yml文件被忽略(tmp_path) -> None:
    _make_tree(
        tmp_path / "localization",
        {
            "english/a_l_english.yml": 'l_english:\n K:0 "v"\n',
            "english/notes.txt": "not localization",
        },
    )
    assert extract_localization(tmp_path).files == 1


def test_目录不存在时返回空报告(tmp_path) -> None:
    r = extract_localization(tmp_path / "nope")
    assert r.files == 0
    assert r.unique_keys == 0
    assert r.summary()["文件"] == 0


def test_产物格式紧凑且自洽(tmp_path) -> None:
    """``键`` 是排序后的字符串列表；只需语言维度的键单独放在子集里。"""
    _make_tree(
        tmp_path / "localization",
        {
            "english/a_l_english.yml": 'l_english:\n Z:0 "z"\n A:0 "a"\n',
            "french/a_l_french.yml": 'l_french:\n A:0 "a"\n',
        },
    )
    d = extract_localization(tmp_path).to_dict()
    assert d["键"] == ["A", "Z"], "键列表必须排序"
    assert all(isinstance(k, str) for k in d["键"]), "键必须是字符串，不是对象"
    # Z 只有英语有 -> 进子集；A 两种语言都有 -> 不进
    assert d["仅部分语言有的键"] == {"Z": ["l_english"]}


# ── 真实语料 ────────────────────────────────────────────────
@_needs_game
@pytest.mark.integration
def test_真实语料规模符合预期() -> None:
    r = extract_localization(config.GAME)
    assert r.files > 1800, f"只扫到 {r.files} 个文件"
    assert len(r.by_lang) == 11
    assert r.unique_keys > 100_000
    assert not r.errors, f"有解析错误：{r.errors[:3]}"
    assert r.total_size > 100 * 1024 * 1024, "本地化总体积应超过 100 MB"


@_needs_game
@pytest.mark.integration
def test_每个语言都有可观的键数() -> None:
    """11 种语言都应各有一批键；某个语言突然变空说明语种识别坏了。"""
    r = extract_localization(config.GAME)
    for lang, stat in r.by_lang.items():
        assert stat["去重键"] > 50_000, f"{lang} 只有 {stat['去重键']} 个键"
