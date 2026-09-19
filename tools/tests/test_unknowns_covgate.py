"""未确认清单（`pdx.unknowns`）与覆盖率门禁（`pdx.covgate`）的测试。

两者都是「把口头承诺变成可数事实」的工具，所以测试也盯这一点：
清单**扫得到**、计数**与逐篇扫的结果一致**、门禁的**判定方向不会反**。
"""

from __future__ import annotations

import json

import pytest

from pdx import config, covgate, unknowns

pytestmark = pytest.mark.unit


# ────────────────────────── 未确认清单 ──────────────────────────


def _doc(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_扫出标记与所属章节(tmp_path) -> None:
    doc = _doc(
        tmp_path,
        "04-脚本系统.md",
        "# 大标题\n\n## 12. 覆盖\n\n这句要标 **【未确认】**。\n\n## 13. 清单\n\n还有 **【未确认】**。\n",
    )
    items = unknowns.scan_doc(doc)
    assert [i.line for i in items] == [5, 9]
    assert items[0].section == "12. 覆盖"
    assert items[1].section == "13. 清单"
    assert items[0].where == "04-脚本系统.md:5"


def test_半角方括号不算(tmp_path) -> None:
    """正文里的 ``[未确认]``（半角）不该被当成标记 —— 标记词是全角的。"""
    doc = _doc(tmp_path, "x.md", "这里写 [未确认] 而不是全角。\n")
    assert unknowns.scan_doc(doc) == []


def test_上下文截断(tmp_path) -> None:
    doc = _doc(tmp_path, "x.md", "前缀" * 100 + "【未确认】\n")
    item = unknowns.scan_doc(doc)[0]
    assert len(item.context) == unknowns.CONTEXT_LIMIT


def test_全库计数与逐篇一致() -> None:
    """``counts_by_doc`` 与 ``unverified_items`` 必须同源，否则清单会自相矛盾。"""
    counts = unknowns.counts_by_doc()
    assert sum(counts.values()) == len(unknowns.all_items())
    for doc in counts:
        assert len(unknowns.unverified_items(doc)) == counts[doc]


def test_按篇过滤() -> None:
    assert unknowns.unverified_items("04")
    assert all(i.doc.startswith("04") for i in unknowns.unverified_items("04"))
    assert unknowns.unverified_items("找不到的篇") == []


def test_文档目录就在仓库里() -> None:
    assert unknowns.docs_dir() == config.DOCS
    assert len(unknowns.doc_files()) >= 20


# ────────────────────────── 覆盖率门禁 ──────────────────────────


def test_下限表指向真实模块且有据可依() -> None:
    """下限不能指向空气，也不能是个摆设（0 等于没设）。"""
    assert covgate.FLOORS
    for module, floor in covgate.FLOORS.items():
        path = config.REPO / "tools" / module
        assert path.is_file(), f"下限表里的 {module} 不存在（改名了？）"
        assert 0 < floor <= 100, f"{module} 的下限 {floor} 不像个下限"


def test_读取覆盖率json(tmp_path) -> None:
    payload = {
        "files": {
            "tools/pdx/parser.py": {"summary": {"percent_covered": 97.5, "num_statements": 200}},
            "tools/pdx/cli.py": {"summary": {"percent_covered": 50.0, "num_statements": 800}},
            "tools/tests/test_x.py": {"summary": {"percent_covered": 10.0, "num_statements": 10}},
        }
    }
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rows = covgate.load_coverage(path)
    assert [r.module for r in rows] == ["pdx/cli.py", "pdx/parser.py"], "只算包顶层模块"
    parser = next(r for r in rows if r.module == "pdx/parser.py")
    assert parser.percent == pytest.approx(97.5)
    assert parser.statements == 200


def test_缺少数据时是空表(tmp_path) -> None:
    assert covgate.load_coverage(tmp_path / "没有这个文件.json") == []


def test_判定方向() -> None:
    """低于下限才算不达标；等于下限算达标（边界不能反）。"""
    floor = covgate.FLOORS["pdx/parser.py"]
    below = covgate.ModuleCoverage("pdx/parser.py", floor - 0.1, 100)
    exact = covgate.ModuleCoverage("pdx/parser.py", floor, 100)
    assert not below.ok
    assert exact.ok
    assert covgate.check([below]) == [below]
    assert covgate.check([exact]) == []


def test_未登记下限的模块不参与判定() -> None:
    row = covgate.ModuleCoverage("pdx/没登记.py", 0.0, 10)
    assert row.floor is None
    assert row.ok
    assert covgate.check([row]) == []


def test_下限表缺模块要报出来() -> None:
    rows = [covgate.ModuleCoverage("pdx/parser.py", 99.0, 10)]
    missing = covgate.missing_floors(rows)
    assert "pdx/parser.py" not in missing
    assert "pdx/verify.py" in missing


def test_整体覆盖率按语句加权() -> None:
    rows = [
        covgate.ModuleCoverage("a", 100.0, 900),
        covgate.ModuleCoverage("b", 0.0, 100),
    ]
    assert covgate.total_percent(rows) == pytest.approx(90.0)
    assert covgate.total_percent([]) == 0.0
