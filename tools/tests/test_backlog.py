"""`pdx.backlog`（还开着的条目）与 `unknowns` 元陈述判定的测试。

这两条口径决定了「还剩多少没解决」这个数字可不可信：

* backlog 必须**只数条目表**（取证手册、配方表不是条目），子标题要继承父节；
* 状态列写「已答」的要算已关，否则清单永远清不干净；
* `unknowns` 必须跳过**元陈述**（「无法确认的一律标注【未确认】」是在说明约定，
  不是在使用标记），否则清单里混进假条目。
"""

from __future__ import annotations

import pytest

from pdx import backlog, unknowns

pytestmark = pytest.mark.unit


def _doc(tmp_path, body: str):
    path = tmp_path / "14-测试.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_条目表按状态列判定已关(tmp_path) -> None:
    path = _doc(
        tmp_path,
        "## 17. 未确认项汇总\n\n"
        "| # | 未确认内容 | 本地证据 | 状态 |\n"
        "| --- | --- | --- | --- |\n"
        "| U1 | 某字段语义 | `v3 evidence x` → 3 处 | **已答**：就是 A |\n"
        "| U2 | 另一件事 | 无 | 待实测 → 配方 B |\n",
    )
    items = backlog.scan_doc(path)
    assert len(items) == 2
    assert items[0].closed
    assert not items[1].closed
    assert sum(1 for i in items if not i.closed) == 1


def test_列表项一律算开着(tmp_path) -> None:
    path = _doc(tmp_path, "## 6. 下一步可做的事\n\n- 实测加载顺序\n- [ ] 精读 changelog\n")
    items = backlog.scan_doc(path)
    assert [i.closed for i in items] == [False, False]
    assert "实测加载顺序" in items[0].text


def test_子标题继承父节(tmp_path) -> None:
    """doc 04 §13 的六张子表在 §13.2–13.7 下，第一版一条都没数到。"""
    path = _doc(
        tmp_path,
        "## 13. 未确认项清单\n\n### 13.1 取证手册\n\n| 类 | 证据 |\n| --- | --- |\n| ① | 原版用法 |\n"
        "\n### 13.2 加载语义\n\n"
        "| # | 未确认内容 | 本地证据 | 状态 |\n| --- | --- | --- | --- |\n"
        "| U1 | 裸同名行为 | 无实例 | 未确认 |\n",
    )
    items = backlog.scan_doc(path)
    assert len(items) == 1, "只应数到条目表里的那一行"
    assert items[0].text == "裸同名行为"


def test_非条目表不计数(tmp_path) -> None:
    path = _doc(
        tmp_path,
        "## 8. 未确认项汇总\n\n"
        "| 配方 | 做法 | 能定什么 |\n| --- | --- | --- |\n| A | 脚本化测试 | 行为 |\n",
    )
    assert backlog.scan_doc(path) == []


def test_同级标题结束本节(tmp_path) -> None:
    path = _doc(
        tmp_path,
        "## 7. 未确认项\n\n- 条目一\n\n## 8. 正文\n\n- 这不是条目\n",
    )
    assert [i.text for i in backlog.scan_doc(path)] == ["条目一"]


def test_真仓库里能数出条目且doc04在列() -> None:
    counts = backlog.counts_by_doc()
    assert counts, "全库不该一条都数不出来"
    assert any(name.startswith("04") for name in counts), "doc 04 §13 是标准样板，必须在列"
    opened, closed = backlog.totals()
    assert opened > 0
    assert opened + closed == len(backlog.all_items())


def test_标记与章节条目是两个不同的集合() -> None:
    """`v3 unverified` 数标记行（含正文里的），`v3 backlog` 数待办章节里的条目。

    两者**有交集但不重合**：正文里也会出现【未确认】（例如某字段语义那一句），
    而旧格式章节里的条目大多不带标记。所以文档里一律说「不要相加」——
    这条测试就是那句口径的可执行版本。
    """
    marked = {(i.doc, i.line) for i in unknowns.all_items()}
    backlogged = {(i.doc, i.line) for i in backlog.all_items()}
    assert marked & backlogged, "总该有交集：改造后的章节里会带标记"
    assert marked - backlogged, "正文里也有标记行，两者不重合"
    assert backlogged - marked, "旧格式章节里的条目不带标记，两者不重合"


# ────────────────────────── 元陈述 ──────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        "> 语法示例尽量逐字引用游戏内置 `.md` 文档；无法确认的内容一律标注 **【未确认】**，不做推测。",
        "凡属上面那条窄问号的，本文档一律标注 **【未确认】**，不凭印象断言。",
        "> 无法由文件证实的内容统一标注 **【未确认】**。",
        "> 本节列出全文所有 **【未确认】** 项，便于后续实测验证。",
    ],
)
def test_元陈述被跳过(line: str) -> None:
    assert unknowns.is_meta_statement(line)


@pytest.mark.parametrize(
    "line",
    [
        "| `after` | 62 | `00_ip3.txt:1012` | **md 无记载，【未确认】** |",
        "**【未确认】**：`$PARAM$` 是否支持默认值。",
        "> 该键确切行为 **【未确认】**。",
        "> **【未确认】（范围已收窄）**：不带前缀的同名键会发生什么。",
    ],
)
def test_真条目不被误杀(line: str) -> None:
    assert not unknowns.is_meta_statement(line)


def test_扫描会应用元陈述判定(tmp_path) -> None:
    path = _doc(
        tmp_path,
        "# 标题\n\n> 无法确认的一律标注 **【未确认】**。\n\n"
        "## 3. 正文\n\n某字段语义 **【未确认】**。\n",
    )
    items = unknowns.scan_doc(path)
    assert [i.line for i in items] == [7]
