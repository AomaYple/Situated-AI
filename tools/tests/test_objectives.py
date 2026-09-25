"""9 国目标函数表（`pdx.objectives`）的用例。

判据的唯一定义在 `docs/design/exec/阶段5-目标函数表-口径.md`（v3）：形状 §2.1、
档位 §2.2、五条闸门 §4.1、`derive()` §4.1.1、退出码与报告形态 §4.1.2。
这一组用例盯的是**判据真的能判**（阳性对照 + 阴性对照），而不是"表填完了"：

* **反例**（必须判红）：缺 `[objectives]` ⇒ 退出码 2；`tier = 4` ⇒ P2；裸文件名 ⇒ P3；
  别名越界 ⇒ P3；档 0 却给了依据 ⇒ P2；少一个利益项 ⇒ P1；`kind` 与 `derive()` 不符 ⇒ P4。
* **正例**（必须判绿）：盘上真数据 9/9 全绿；`derive()` 九份的输出与口径页 §4.1.1 的
  「9 份逐份跑」那张表逐格一致（`pushed`/`declared`/`opening_card`/`measured_true`/`underivable` 五种都撞到）。
* **两态引用**：形态①（`文件:行`）走 `v3 citations`；形态②（`别名:行`）走别名表 ——
  `01a:269` 这类简称在 `CITATION_RE` 里恒 0 命中，所以这两条路必须各有一条用例。
"""

from __future__ import annotations

import dataclasses
import shutil
from typing import TYPE_CHECKING

import pytest

from pdx import config, doc_tables, objectives

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用（要查原版开局牌与牌面 type）"
)


def _copy_data(tmp_path: Path) -> Path:
    """把盘上 9 份数据源拷进临时目录（**判据一样跑，只是数据可改**）。"""
    data = tmp_path / "data"
    data.mkdir()
    for path in objectives.data_files():
        shutil.copy2(path, data / path.name)
    return data


def _tamper(data: Path, stem: str, old: str, new: str, *, count: int = 1) -> None:
    path = data / f"{stem}.toml"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= count, f"{stem}.toml 里找不到要改的片段：{old[:40]!r}"
    path.write_text(text.replace(old, new, count), encoding="utf-8", newline="\n")


def _problems(report: objectives.Report, entry_id: str) -> list[objectives.Problem]:
    for entry in report.entries:
        if entry.id == entry_id:
            return list(entry.problems)
    raise AssertionError(f"报告里没有 {entry_id}")


def _predicates(report: objectives.Report, entry_id: str) -> set[str]:
    return {problem.predicate for problem in _problems(report, entry_id)}


# ── 两态引用（§2.1）─────────────────────────────────────────


def test_classify_形态1是带后缀的文件引用() -> None:
    form = objectives.classify("mod/data/ru_defeat.toml:85-87")
    assert (form.kind, form.name, form.start, form.end) == (
        "file",
        "mod/data/ru_defeat.toml",
        85,
        87,
    )


def test_classify_形态2是别名() -> None:
    form = objectives.classify("01a:269")
    assert (form.kind, form.name, form.start, form.end) == ("alias", "01a", 269, 269)


def test_classify_裸文件名不是可用的形态() -> None:
    """裸名（`cli.py:987`）**不是**合法的两态之一：它要么 `missing`、要么 `ambiguous`。

    ⚠️ 它不是"认不出来"（`cli.py` 带后缀，`CITATION_RE` 认它），而是**解析不到唯一一行**
    —— 口径页 §4.1.2 ①′ 实测：裸 `cli.py:987` 结论列是 `missing`、退出码 1 ⇒ P3 红。
    """
    form = objectives.classify("cli.py:987")
    assert form.kind == "file"
    assert form.detail in {"missing", "ambiguous", "out_of_range"}


def test_classify_一个字段里两条引用必须判红() -> None:
    """§2.1 硬约束 2：`evidence` 恰好一条引用（`findall` 计数 == 1，不是布尔）。"""
    form = objectives.classify("mod/data/ru_defeat.toml:85 与 mod/data/ru_defeat.toml:148")
    assert form.kind == "file"
    assert "2 条" in form.detail


def test_别名表逐条可解() -> None:
    """别名分支的判据：别名在本表里 + 目标文件存在 + 行号 ≤ 行数（§2.1）。"""
    for alias, rel in objectives.ALIASES.items():
        path = config.REPO / rel
        assert path.is_file(), f"别名 {alias} 指向的文件不存在：{rel}"
        assert objectives.classify(f"{alias}:1").kind == "alias"


# ── 反例：每一条红都要有一条用例（t52 会照这三条撞）──────────


def test_缺objectives判红且退出码是2(tmp_path: Path) -> None:
    """空集 / 缺节 ⇒ **非零（2）** + 点名缺哪一节；不许静默 0（§4.1.2 ③）。"""
    data = _copy_data(tmp_path)
    path = data / "pe_great_game.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("[objectives]")], encoding="utf-8", newline="\n")

    report = objectives.check(data)
    assert report.exit_code() == 2
    assert "P1" in _predicates(report, "pe_great_game")
    assert any("pe_great_game" in item for item in report.prerequisites)


def test_档位越界判红P2(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    _tamper(data, "eg_debt", "tier = 3\nevidence = ", "tier = 4\nevidence = ")

    report = objectives.check(data)
    assert report.exit_code() == 1
    assert "P2" in _predicates(report, "eg_debt")


def test_档0不许有依据(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    _tamper(
        data,
        "ru_defeat",
        'key = "market"\ntier = 0\n',
        'key = "market"\ntier = 0\nevidence = "01a:269"\n',
    )

    report = objectives.check(data)
    assert "P2" in _predicates(report, "ru_defeat")


def test_档0的why必须写明缺什么(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    _tamper(data, "ru_defeat", "**缺**：本仓 9 份里没有任何字段动商路/市场依赖", "没查过这件事")

    report = objectives.check(data)
    assert "P2" in _predicates(report, "ru_defeat")


def test_裸文件名判红P3(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    _tamper(data, "eg_debt", 'evidence = "mod/data/eg_debt.toml:89-91"', 'evidence = "cli.py:987"')

    report = objectives.check(data)
    assert report.exit_code() == 1
    assert "P3" in _predicates(report, "eg_debt")


def test_别名越界判红P3(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    _tamper(data, "sp_empire_remnant", 'evidence = "01a:279"', 'evidence = "01a:99999"')

    report = objectives.check(data)
    assert "P3" in _predicates(report, "sp_empire_remnant")


def test_少一个利益项判红P1(tmp_path: Path) -> None:
    """五个利益项**一条不许少**（§2.1 硬约束 1）—— 判据要能同时说出"多了什么、少了什么"。"""
    data = _copy_data(tmp_path)
    _tamper(data, "bv_alignment", 'key = "market"', 'key = "market_dependence"')

    report = objectives.check(data)
    assert report.exit_code() == 1
    problems = _problems(report, "bv_alignment")
    assert {"P1"} <= {problem.predicate for problem in problems}
    assert any("不在值域" in problem.detail for problem in problems)
    assert any("一条不许少" in problem.detail for problem in problems)


# ── 文件面：口径页 §1 的三种静默写法（t52 的 F1）─────────────


def test_子目录里的toml判红P1(tmp_path: Path) -> None:
    """静默写法之一：子目录里的 `.toml`（`glob` 非递归 + 引擎不枚举子目录）。

    ⚠️ 这条用例守的是**两件事同时成立**：`data_files()` 仍只看到 9 份（所以它是静默的），
    而闸门必须把它点出来 —— 只断言后一句的话，"其实被读到了"这种失败也会绿。
    """
    data = _copy_data(tmp_path)
    nested = data / ".t52probe" / "sub"
    nested.mkdir(parents=True)
    (nested / "zz_probe.toml").write_text("schema_version = 1\n", encoding="utf-8", newline="\n")

    report = objectives.check(data)
    assert len(objectives.data_files(data)) == 9, "它**不会**被读到 —— 这才是静默的含义"
    assert report.exit_code() == 1
    assert any(
        "既不会被 `data_files()` 读到、也不会被引擎读到" in problem.detail
        for entry in report.entries
        for problem in entry.problems
    )


def test_备份后缀判红P1(tmp_path: Path) -> None:
    """静默写法之二：`zz_probe.toml.bak`（以 `.toml` 开头但不是 `.toml` 结尾）。"""
    data = _copy_data(tmp_path)
    (data / "zz_probe.toml.bak").write_text("schema_version = 1\n", encoding="utf-8", newline="\n")

    report = objectives.check(data)
    assert len(objectives.data_files(data)) == 9
    assert report.exit_code() == 1
    assert {problem.predicate for entry in report.entries for problem in entry.problems} == {"P1"}


def test_换扩展名也是同一种静默写法(tmp_path: Path) -> None:
    """静默写法之三：`other.yaml` —— 三类一起判，不是只判前两类。"""
    data = _copy_data(tmp_path)
    (data / "other.yaml").write_text("schema_version: 1\n", encoding="utf-8", newline="\n")

    report = objectives.check(data)
    assert len(objectives.data_files(data)) == 9
    assert report.exit_code() == 1
    assert any(
        "扩展名不是" in problem.detail for entry in report.entries for problem in entry.problems
    )


# ── `derive()` 五条规则（§4.1.1）────────────────────────────


@_needs_game
def test_derive_九份与口径页的四表逐格一致() -> None:
    """口径页 §4.1.1 的「9 份逐份跑」那张表 —— 落盘后逐格成立（五种 kind 都撞到）。"""
    entries, _broken = objectives.load_all()
    got = {entry.id: objectives.derive(entry) for entry in entries}
    assert got == {
        "ru_defeat": "pushed",
        "eg_debt": "declared",
        "sp_empire_remnant": "declared",
        "brz_market_loss": "declared",
        "tr_defeat": "opening_card",
        "au_revolution": "opening_card",
        "cn_intervention": "opening_card",
        "pe_great_game": "measured_true",
        "bv_alignment": "underivable",
    }


@_needs_game
def test_derive_第2条第二分支要读数行里真的有牌名() -> None:
    """`measured_true` 的判据是**读到的**那张牌：把读数行换成不含牌名的一行 ⇒ 不再成立。"""
    entry = objectives.entry_for("pe_great_game")
    assert entry is not None
    obj = entry.objectives
    assert obj is not None
    verdict = obj.verdict
    assert verdict is not None
    tampered = dataclasses.replace(
        entry,
        objectives=dataclasses.replace(
            obj, verdict=dataclasses.replace(verdict, evidence="backlog:1")
        ),
    )
    assert objectives.derive(tampered) == ""


@_needs_game
def test_derive_全不成立时给空串() -> None:
    """三条规则都不成立 ⇒ 空串（= 红），**不许**猜一个默认 kind。"""
    entry = objectives.entry_for("tr_defeat")
    assert entry is not None
    obj = entry.objectives
    assert obj is not None
    verdict = obj.verdict
    assert verdict is not None
    tampered = dataclasses.replace(
        entry,
        objectives=dataclasses.replace(
            obj, verdict=dataclasses.replace(verdict, card="ai_strategy_great_reforms")
        ),
    )
    assert objectives.derive(tampered) == ""


@_needs_game
def test_opening_card_从AI块里取政治那张() -> None:
    """`00_strategy.txt` 整份包在 `AI = { … }` 里；同一个 `c:<TAG>` 块有三张牌，取政治那张。"""
    entries, _broken = objectives.load_all()
    by_id = {entry.id: entry for entry in entries}
    assert objectives.opening_card(by_id["tr_defeat"]) == "ai_strategy_tanzimat_reforms"
    assert objectives.opening_card(by_id["au_revolution"]) == "ai_strategy_conservative_agenda"
    assert (
        objectives.opening_card(by_id["cn_intervention"])
        == "ai_strategy_maintain_mandate_of_heaven"
    )
    assert objectives.opening_card(by_id["pe_great_game"]) == ""
    assert objectives.opening_card(by_id["bv_alignment"]) == ""


@_needs_game
def test_牌面type取自原版() -> None:
    assert objectives.card_type("ai_strategy_tanzimat_reforms") == "political"
    assert objectives.card_type("ai_strategy_agricultural_expansion") == "administrative"


# ── 渲染与登记（P5 的两半）──────────────────────────────────


def test_代价列按W除W加S现算() -> None:
    """代价值**不进表**（§3.4）：表里只有现算的结果；`ru` 现有 1 张权重 40 的牌。"""
    assert objectives.cost_percent(0.0) == "0.0%"
    assert objectives.cost_percent(40.0) == "54.8%"


def test_表的九行十一列且ru的代价是54_8() -> None:
    rows = objectives.table_rows()
    assert len(rows) == 9
    for row in rows:
        assert len(doc_tables.split_row(row)) == 11
    ru = next(row for row in rows if "`ru_defeat`" in row)
    assert ru.rstrip().endswith("54.8% |")


def test_产物里的目标函数小节与数据源一致() -> None:
    """P5 的一半：`mod/sitai_<id>.md` 的小节字符串必须逐字来自渲染器（改数据源就该改产物）。"""
    entry = objectives.entry_for("ru_defeat")
    assert entry is not None
    body = entry.product.read_text(encoding="utf-8")
    assert "\n".join(objectives.section_lines(entry)) in body


def test_宿主页的表与生成结果一致() -> None:
    """P5 的另一半：口径页 §2.3 那 9 行由 `v3 tables` 守（这里直接核对现值）。"""
    spec = objectives.doc_table_specs()[0]
    current = doc_tables.current_rows(objectives.TABLE_DOC, spec)
    assert [doc_tables.split_row(row) for row in current] == [
        doc_tables.split_row(row) for row in spec.rows()
    ]


@_needs_game
def test_盘上九份全绿() -> None:
    """存量读数：P1–P5 全过、退出码 0（落地后这一条就是回归防线）。"""
    report = objectives.check()
    assert report.exit_code() == 0, [p.detail for entry in report.entries for p in entry.problems]
    assert len(report.entries) == 9
    assert report.summary().endswith("退出码 0")
