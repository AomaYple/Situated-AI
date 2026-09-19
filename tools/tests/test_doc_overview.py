"""看守 doc 16 / doc 17 的「一页总览」表 —— 两份此前几乎无人看守的机械数字。

为什么要单独一个文件
-------------------
doc 16 与 doc 17 是知识库里最大的两份手写文档（176 KB / 208 KB），
而 81 条断言里只有 10 条落在它们身上，且都是最显眼的头条数字。
两张 §0 总览表加起来 **62 行**，每行都是机械量 —— 却从来没人核对过。

首次核对的收获：**7 处已经漂了**。

* doc 16 §0 三行的 `.txt` 字节（`diplomatic_plays` 30,897 → 31,798、
  `treaty_articles` 282,306 → 279,785、`war_goal_types` 99,212 → **72,564**），
  外加同页「官方 `.md`」列里 `treaty_articles` 的 25.4 KB → 28.2 KB；
* doc 17 §0 四行的键数（`character_templates` 1,983 → 2,011、
  `technology` 178 → 179、`messages` 472 → 473、`trigger_localization` 1,681 → 1,683），
  其中 `trigger_localization` 还多了一个 1.14.3 新增的 `.txt`。

尤其值得记下来的是：doc 17 §0 的 1,983 **与它自己的断言表矛盾** ——
`chr.templates` 断言早就写着 2,011 并通过了 `v3 verify`。断言与文档正文
永不共振，正是这个仓库反复踩到的那个坑。

口径（两处都写在文档里，这里照抄，不另立一套）
--------------------------------------------
* doc 16：`| # | 目录 | .txt | .md | 合计 | .txt 字节 | 官方 .md | 主要键数 |`
  —— 字节列**只算 `.txt`**（preamble 与列名都写明了）；「官方 `.md`」列是
  该目录内官方 `.md` 的大小（十进制 KB）。
* doc 17：`| # | 目录 | .txt | 顶层定义键 | 官方 .md | 一句话用途 |`
  —— 键数是**顶层块的出现次数**（剥注释 → 花括号深度 0 → `键名 = {`），
  不是去重后的键名数。两者在 `named_colors`（4 vs 1）等目录上不同，
  用错口径会假报一片 —— 实测就是这么踩过来的。

覆盖不到的：doc 04（`04-脚本系统.md`）**没有**这种总览表，它的数字散在
按主题组织的表里，口径各不相同，无法用同一套规则核对。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from pdx import cache, config, docs_mirror
from pdx.model import Block

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

COMMON = config.GAME / "common"


def _require_game() -> None:
    if not COMMON.is_dir():
        pytest.skip("游戏目录不可用")


def _rows_after(lines: list[str], prefix: str) -> list[list[str]]:
    """``prefix`` 开头的表的数据行（跳过表头、分隔线与分组行）。"""
    start = next((i for i, x in enumerate(lines) if x.startswith(prefix)), None)
    assert start is not None, f"找不到表头 {prefix!r} —— §0 的表格结构被改过？"
    out: list[list[str]] = []
    for i in range(start + 2, len(lines)):
        if not lines[i].startswith("|"):
            break
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if row and row[1].startswith("**"):
            continue  # 「外交类 / 军事类」这类分组行
        out.append(row)
    assert out, f"表头 {prefix!r} 下面一行数据都没有 —— 解析退化了"
    return out


def _num(s: str) -> int | None:
    m = re.search(r"[\d][\d,]*", s.replace("**", ""))
    return int(m.group(0).replace(",", "")) if m else None


def _dir(name: str) -> Path:
    return COMMON / name


def _txt_files(name: str) -> list[Path]:
    d = _dir(name)
    return sorted(p for p in d.rglob("*.txt") if p.is_file()) if d.is_dir() else []


def _top_blocks(path: Path) -> int:
    """顶层块的出现次数（doc 17 的口径）。"""
    return sum(
        1
        for a in cache.parse_cached(path).top_assignments
        if not a.is_variable and isinstance(a.value, Block)
    )


def test_doc16_总览表与实测一致() -> None:
    """33 行 × 4 个机械列：`.txt` / `.md` / 合计 / `.txt` 字节。"""
    _require_game()
    lines = (config.DOCS / "16-外交军事与地图.md").read_text(encoding="utf-8").splitlines()
    rows = _rows_after(lines, "| # | 目录 |")
    assert len(rows) == 33, f"§0 应当是 33 行，实际 {len(rows)}"

    bad: list[str] = []
    for row in rows:
        name = row[1].strip("`").strip().rstrip("\\")
        files = [p for p in _dir(name).rglob("*") if p.is_file()]
        txt = [p for p in files if p.suffix == ".txt"]
        actual = {
            2: len(txt),
            3: len(files) - len(txt),
            4: len(files),
            5: sum(p.stat().st_size for p in txt),
        }
        for idx, got in actual.items():
            want = _num(row[idx])
            if want is not None and want != got:
                bad.append(f"{name} 第{idx}列: 文档 {want:,} → 实测 {got:,}")
    assert not bad, "doc 16 §0 总览表与实测不符：\n  " + "\n  ".join(bad)


def test_doc16_官方md列与实测一致() -> None:
    """「官方 `.md`」列：有就写大小（十进制 KB），没有就写 ❌。"""
    _require_game()
    lines = (config.DOCS / "16-外交军事与地图.md").read_text(encoding="utf-8").splitlines()
    bad: list[str] = []
    for row in _rows_after(lines, "| # | 目录 |"):
        name = row[1].strip("`").strip().rstrip("\\")
        cell = row[6]
        mds = [p for p in _dir(name).rglob("*.md") if p.is_file()]
        if not mds:
            if "❌" not in cell:
                bad.append(f"{name}: 文档写「{cell}」但实测没有官方 .md")
            continue
        want = re.search(r"([\d.]+)\s*KB", cell)
        if not want:
            bad.append(f"{name}: 有官方 .md 却没写大小（{cell}）")
            continue
        size = sum(p.stat().st_size for p in mds)
        claimed = float(want.group(1))
        if abs(size / 1000 - claimed) > 0.15:  # 十进制 KB，容差 0.15
            bad.append(f"{name}: 文档 {claimed} KB → 实测 {size:,} B（{size / 1000:.1f} KB）")
    assert not bad, "doc 16 §0 的官方 .md 列与实测不符：\n  " + "\n  ".join(bad)


def test_doc17_总览表与实测一致() -> None:
    """29 行 × 2 个机械列：`.txt` 数、顶层块数。

    ``.txt`` 与键数两列都可能写成多段（``3 + `eras/`1``、``178 + 5``），
    以及一种特殊写法 ``6 个块名（9 处定义）`` —— 后者的**正确值是括号里的 9**
    （块的出现次数），不是前面的 6（去重后的块名数）。照搬「取第一个数字」
    会把这一行误判成漂移。
    """
    _require_game()
    lines = (config.DOCS / "17-角色科技与呈现.md").read_text(encoding="utf-8").splitlines()
    rows = _rows_after(lines, "| # | 目录 |")
    assert len(rows) == 29, f"§0 应当是 29 行，实际 {len(rows)}"

    def intended(cell: str) -> int:
        nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", cell)]
        return nums[-1] if "（" in cell and "处定义" in cell else sum(nums)

    bad: list[str] = []
    for row in rows:
        name = row[1].strip("`").strip().rstrip("\\")
        got_txt = len(_txt_files(name))
        got_keys = sum(_top_blocks(p) for p in _txt_files(name))
        want_txt, want_keys = intended(row[2]), intended(row[3])
        if want_txt != got_txt:
            bad.append(f"{name} .txt: 文档 {row[2]!r} = {want_txt} → 实测 {got_txt}")
        if want_keys != got_keys:
            bad.append(f"{name} 键数: 文档 {row[3]!r} = {want_keys:,} → 实测 {got_keys:,}")
    assert not bad, "doc 17 §0 总览表与实测不符：\n  " + "\n  ".join(bad)


def test_doc17_头条与总览表同源() -> None:
    """头条声明的「N 个 .txt / M 个顶层定义键」必须等于 §0 各行的合计。

    这条防的是「表格改对了、头条忘了改」—— doc 16 就出过这种：它的 33 行
    当时合计 1,965,504，而头条写着 1,962,504，两者从来没对上过。
    """
    _require_game()
    raw = (config.DOCS / "17-角色科技与呈现.md").read_text(encoding="utf-8")
    # 归属标记（``<!--claim:…-->``）会插在数字与量词之间，解析前先剥掉 ——
    # 它是给人看的绑定信息，不该影响正文的**文字**匹配。
    text = re.sub(r"<!--claim:[A-Za-z0-9_.]+-->", "", raw)
    m = re.search(r"共 \*\*(\d[\d,]*) 个 \.txt 文件 / ([\d,]+) 个顶层定义键\*\*", text)
    assert m, "找不到 doc 17 的头条声明 —— 措辞被改过？"
    head_txt = int(m.group(1).replace(",", ""))
    head_keys = int(m.group(2).replace(",", ""))

    lines = text.splitlines()
    rows = _rows_after(lines, "| # | 目录 |")

    def intended(cell: str) -> int:
        nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", cell)]
        return nums[-1] if "（" in cell and "处定义" in cell else sum(nums)

    sum_txt = sum(intended(r[2]) for r in rows)
    sum_keys = sum(intended(r[3]) for r in rows)
    assert (head_txt, head_keys) == (sum_txt, sum_keys), (
        f"头条写 {head_txt:,} .txt / {head_keys:,} 键，"
        f"§0 各行合计 {sum_txt:,} / {sum_keys:,} —— 两处不同源"
    )


def test_doc16_附录九的文件数与字节数与实测一致() -> None:
    """§9 那个 ```text 块（33 个目录 × txt/md/字节）的逐行看守。

    为什么是**测试**而不是生成器：它是**代码块**不是 Markdown 表，
    而 ``v3 tables`` 的替换机制只认「表头 + 分隔线 + 数据行」。
    换载体（改成表格）会动到这份文档的排版风格，而这里要的只是「它不会悄悄过期」——
    逐行重算并比对同样能做到，且与 §0 走同一套口径。

    约定（文档自己的写法）：``txt=N md=M bytes_txt=B``；
    目录里有子目录时写成 ``N(+M)`` / ``B(+C)`` —— 实测只有
    ``terrain_manipulators`` 是这种（2 个文件里 1 个在 ``provinces\\``）。
    """
    _require_game()
    lines = (config.DOCS / "16-外交军事与地图.md").read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, x in enumerate(lines) if x.startswith("## 9. 附：本范围文件数与字节数")), None
    )
    assert start is not None, "找不到 doc 16 §9 的标题 —— 结构被改过？"
    fence = next((i for i in range(start, len(lines)) if lines[i].startswith("```")), None)
    assert fence is not None, "§9 的代码块起始围栏没了"
    rows: list[str] = []
    for line in lines[fence + 1 :]:
        if line.startswith("```"):
            break
        rows.append(line)
    assert len(rows) == 33, f"§9 应当是 33 行，实际 {len(rows)}"

    pat = re.compile(
        r"^(\S+)\s+txt=(\d+)(?:\(\+(\d+)\))?\s+md=(\d+)\s+bytes_txt=(\d+)(?:\(\+(\d+)\))?$"
    )
    bad: list[str] = []
    for line in rows:
        m = pat.match(line)
        if not m:
            bad.append(f"这一行解析不了（格式被改过？）：{line!r}")
            continue
        name, txt, txt_sub, md, size, size_sub = (
            m.group(1),
            int(m.group(2)),
            int(m.group(3) or 0),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6) or 0),
        )
        base = _dir(name)
        top = [p for p in base.iterdir() if p.is_file()] if base.is_dir() else []
        sub = [p for p in base.rglob("*") if p.is_file() and p.parent != base]
        got = (
            len([p for p in top if p.suffix == ".txt"]),
            len([p for p in sub if p.suffix == ".txt"]),
            len([p for p in top + sub if p.suffix == ".md"]),
            sum(p.stat().st_size for p in top if p.suffix == ".txt"),
            sum(p.stat().st_size for p in sub if p.suffix == ".txt"),
        )
        want = (txt, txt_sub, md, size, size_sub)
        if want != got:
            bad.append(f"{name}: 文档 {want} → 实测 {got}")
    assert not bad, "doc 16 §9 的文件数/字节数与实测不符：\n  " + "\n  ".join(bad)


def test_doc08_官方文档篇数与清单一致() -> None:
    """顺带钉住 doc 08 头条里的官方 `.md` 篇数与**入库清单**一致。

    这一条**不需要游戏**也能跑（清单已入库），但放在本文件里与其它
    「总览表看守」成组。
    """
    docs = docs_mirror.entries()
    assert docs, "读不到 research/official-docs.manifest.json"
    text = (config.DOCS / "08-目录全量清单.md").read_text(encoding="utf-8")
    assert f"| **官方 `.md` 合计** | **{len(docs)}**" in text, (
        f"doc 08 的官方 .md 合计与清单（{len(docs)} 篇）不一致"
    )
