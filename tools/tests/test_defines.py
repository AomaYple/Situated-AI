"""defines 提取测试。

为什么单独补这一组
------------------
``defines.py`` 此前是全包覆盖率最低的模块（74%），而且缺口不是零星的 ——
``overlay()`` **整个函数从未被调用过**，``Param`` / ``Namespace`` 的
``to_dict()`` 也一次没跑过。它们不是难测，只是没人测。

defines 对 mod 作者的价值很特殊：它是**唯一一类「按命名空间合并、参数级
覆盖」的数据** —— mod 不需要复制整份原版文件，只写
``NXXX = { KEY = 新值 }`` 即可。``overlay()`` 就是为「写之前先看清会覆盖
什么」而存在的，所以它空着尤其不应该。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.defines import (
    INLINE_LIST,
    NESTED_BLOCK,
    SCALAR,
    DefinesReport,
    Namespace,
    Param,
    _classify,
    extract_all_defines,
    extract_defines,
    overlay,
)
from pdx.parser import parse_text

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common" / "defines").is_dir(), reason="游戏目录不可用"
)


# ── 参数形态判定 ────────────────────────────────────────────
def _params_of(text: str) -> list[Param]:
    """从一段 defines 文本里取出第一个命名空间块的参数列表。"""
    from pdx.model import Block

    pf = parse_text(text, "<t>")
    a = next(x for x in pf.top_assignments if x.is_block)
    assert isinstance(a.value, Block), f"期望块，实得 {type(a.value).__name__}"
    return _classify(a.value)


def test_标量参数() -> None:
    got = _params_of("N = { A = 1.5 }\n")
    assert len(got) == 1
    assert got[0].kind == SCALAR
    assert got[0].value == "1.5"


def test_内联列表参数() -> None:
    got = _params_of("N = { L = { a b c } }\n")
    assert got[0].kind == INLINE_LIST
    assert got[0].elements == 3


def test_嵌套块参数() -> None:
    got = _params_of("N = { B = { X = 1  Y = 2 } }\n")
    assert got[0].kind == NESTED_BLOCK
    assert got[0].elements == 2


def test_空块算嵌套块而不是列表() -> None:
    """``K = { }`` 既无子键也无裸标量 —— 归嵌套块，元素数 0。"""
    got = _params_of("N = { B = { } }\n")
    assert got[0].kind == NESTED_BLOCK
    assert got[0].elements == 0


def test_空值参数() -> None:
    """``KEY =`` 后面什么都没有 —— 记为空标量而不是丢掉。"""
    got = _params_of("N = { A =\n}\n")
    assert got[0].kind == SCALAR
    assert got[0].value == ""


def test_参数顺序与行号保留() -> None:
    got = _params_of("N = {\n  A = 1\n  B = 2\n}\n")
    assert [p.name for p in got] == ["A", "B"]
    assert got[0].line == 2
    assert got[1].line == 3


# ── to_dict ────────────────────────────────────────────────
def test_参数转字典_标量带值() -> None:
    d = Param("A", SCALAR, value="1", line=7).to_dict()
    assert d == {"参数": "A", "形态": SCALAR, "行": 7, "值": "1"}
    assert "元素数" not in d, "标量不该出现元素数"


def test_参数转字典_列表带元素数() -> None:
    d = Param("L", INLINE_LIST, elements=3, line=8).to_dict()
    assert d == {"参数": "L", "形态": INLINE_LIST, "行": 8, "元素数": 3}
    assert "值" not in d, "列表不该出现值"


def test_命名空间转字典() -> None:
    ns = Namespace("NAI", "00_ai.txt", 1, [Param("A", SCALAR, value="1")])
    d = ns.to_dict()
    assert d["命名空间"] == "NAI"
    assert d["参数数"] == 1
    assert d["参数"] == ["A"]
    assert "前置注释" not in d, "没有注释时不该出现该字段"


def test_命名空间转字典_带注释() -> None:
    ns = Namespace("NAI", "00_ai.txt", 1, [], comment="AI 参数")
    assert ns.to_dict()["前置注释"] == "AI 参数"


# ── 报告对象 ────────────────────────────────────────────────
def test_报告去重与合计() -> None:
    r = DefinesReport(
        namespaces=[
            Namespace("NAI", "a.txt", 1, [Param("X", SCALAR)]),
            Namespace("NAI", "b.txt", 1, [Param("Y", SCALAR)]),
            Namespace("NCamera", "c.txt", 1, []),
        ]
    )
    assert r.unique_namespaces == ["NAI", "NCamera"]
    assert r.total_params == 2
    assert len(r.get("NAI")) == 2, "同名命名空间可以出现在多个文件里"
    assert r.get("不存在") == []


# ── 目录级提取 ──────────────────────────────────────────────
def _tree(base, spec: dict[str, str]) -> None:
    for rel, body in spec.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def test_提取命名空间与参数(tmp_path) -> None:
    _tree(tmp_path, {"00_ai.txt": "NAI = {\n A = 1\n B = { x y }\n}\n"})
    r = extract_defines(tmp_path)
    assert r.unique_namespaces == ["NAI"]
    assert r.total_params == 2
    assert r.per_file["00_ai.txt"] == 1
    assert r.param_usage["A"] == 1


def test_变量不算命名空间(tmp_path) -> None:
    """``00_defines.txt`` 顶部有 22 个 ``@变量``。

    混进来会让命名空间数从 75 变成 97 —— 这是真实踩过的错。
    """
    _tree(tmp_path, {"d.txt": "@base = 10\nNAI = { A = @base }\n"})
    r = extract_defines(tmp_path)
    assert r.unique_namespaces == ["NAI"]
    assert len(r.variables) == 1
    assert r.variables[0][0] == "@base"


def test_小写开头的块不算命名空间(tmp_path) -> None:
    _tree(tmp_path, {"d.txt": "lowercase = { A = 1 }\nNAI = { B = 2 }\n"})
    assert extract_defines(tmp_path).unique_namespaces == ["NAI"]


def test_非块值被跳过(tmp_path) -> None:
    _tree(tmp_path, {"d.txt": "NAI = { A = 1 }\nSCALAR_ONLY = 5\n"})
    assert extract_defines(tmp_path).unique_namespaces == ["NAI"]


def test_同名命名空间跨文件被记录(tmp_path) -> None:
    """引擎按命名空间合并、参数级覆盖，与文件名无关。

    证据：``NCamera`` 在 jomini 与 game 两个不同文件名下各声明一次。
    """
    _tree(tmp_path, {"a.txt": "NShared = { A = 1 }\n",
                     "b.txt": "NShared = { B = 2 }\n"})
    r = extract_defines(tmp_path)
    assert r.namespace_files["NShared"] == ["a.txt", "b.txt"]
    assert r.summary()["跨文件重复的命名空间"] == {"NShared": ["a.txt", "b.txt"]}


def test_目录不存在时返回空报告(tmp_path) -> None:
    r = extract_defines(tmp_path / "nope")
    assert r.namespaces == []
    assert r.summary()["命名空间块数"] == 0


# ── overlay：整函数此前从未被调用 ───────────────────────────
def _vanilla() -> DefinesReport:
    return DefinesReport(
        namespaces=[Namespace("NAI", "00_ai.txt", 1, [
            Param("exist_a", SCALAR, value="1"),
            Param("exist_b", SCALAR, value="2"),
        ])]
    )


def _first_detail(got: dict[str, object]) -> dict[str, object]:
    """取出 overlay 结果里第一条明细，顺带把类型收窄。"""
    detail = got["明细"]
    assert isinstance(detail, list)
    assert detail, "明细不该为空"
    item = detail[0]
    assert isinstance(item, dict)
    return item


def test_覆盖预览_全新命名空间() -> None:
    got = overlay(_vanilla(), "NBrand = { X = 1 }\n")
    assert got["命名空间数"] == 1
    item = _first_detail(got)
    assert item["状态"] == "原版不存在（新建）"
    assert item["新增参数"] == ["X"]


def test_覆盖预览_合并已有命名空间() -> None:
    got = overlay(_vanilla(), "NAI = { exist_a = 99  new_c = 3 }\n")
    item = _first_detail(got)
    assert item["状态"] == "与原版合并"
    assert item["覆盖参数"] == ["exist_a"]
    assert item["新增参数"] == ["new_c"]
    assert item["原版参数数"] == 2


def test_覆盖预览_变量与非块被忽略() -> None:
    got = overlay(_vanilla(), "@v = 1\nNotABlock = 2\nNAI = { exist_a = 9 }\n")
    assert got["命名空间数"] == 1, "只有 NAI 是命名空间"


def test_覆盖预览_空输入() -> None:
    assert overlay(_vanilla(), "")["命名空间数"] == 0


# ── 真实语料 ────────────────────────────────────────────────
@_needs_game
@pytest.mark.integration
def test_真实defines的规模符合已核实的数字() -> None:
    """75 个命名空间块 / 50 个去重名 —— verify.py 的断言表钉着同一组数。"""
    r = extract_defines()
    assert len(r.namespaces) == 75
    assert len(r.unique_namespaces) == 50
    files = r.summary()["涉及文件"]
    assert isinstance(files, int)
    assert files > 0


@_needs_game
@pytest.mark.integration
def test_同时提取两层() -> None:
    both = extract_all_defines()
    assert set(both) == {"game", "jomini"}
    assert both["game"].namespaces, "游戏层不该为空"
