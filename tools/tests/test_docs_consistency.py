"""文档一致性测试。

要解决的问题
------------
这是四份逐文件审计里排第一的发现：**文档写的是 1.14.2 的数字，而游戏早已
升到 1.14.3**。更糟的是没有任何测试能发现它 —— ``tools/pdx/verify.py``
的断言早就把新值测对了，但断言表与文档正文**永不共振**，
``v3 verify`` 一路报「全绿」，文档里却躺着几十个过期数字。

本文件把两者接起来：断言表说「``on_actions`` 有 264 个键」，
那就到它声称的出处文档里去找这一行；找不到 264、却找到量级接近的
263，就是漂移。

判定规则见 :func:`pdx.verify.find_doc_drift` 的文档。**``v3 verify`` 现在
真的会跑它**（``verify.unknown_doc_drift``，失败即退出码 1），所以命令行与
测试用的是同一套判据，不会出现「测试过了但工具没发现」的分歧。

> 早先这句「同时是 v3 verify 的底层实现」是**假的** —— 那时
> ``find_doc_drift`` 只被本文件调用，``v3 verify`` 从未跑过漂移扫描，
> 于是「工具全绿、文档过期」这个最要命的失效模式一直敞着。
> 现在两边共用 ``verify.unknown_doc_drift`` 与 ``verify.KNOWN_METRIC_MIXUPS``。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pdx import config, verify

pytestmark = pytest.mark.docs

#: 已知度量口径错配的清单**在 `pdx.verify` 里** —— 命令行与测试共用一份。
#: 本地别名只为让下面的用例读起来短一些。
_KNOWN_METRIC_MIXUPS = verify.KNOWN_METRIC_MIXUPS
_key = verify.drift_key


def test_没有新增的文档数字漂移() -> None:
    """文档里凡是「锚点 + 数量」的地方，要么与断言表一致，要么在已知清单里。

    这是本文件的核心。任何**新**出现的漂移都会在这里失败，
    并直接指出 文件:行号 与两个数字。判据与 ``v3 verify`` 完全相同。
    """
    unexpected = verify.unknown_doc_drift()
    assert not unexpected, (
        f"发现 {len(unexpected)} 处新的文档数字漂移：\n"
        + "\n".join("  " + d.describe() for d in unexpected)
        + "\n\n请把文档里的数字改成实测值；若确认是口径不同，"
        "登记到 pdx.verify.KNOWN_METRIC_MIXUPS 并写明理由。"
    )


def test_已知口径错配清单没有失效() -> None:
    """清单里的条目若不再命中，说明那一行改了 —— 必须同步清理。

    没有这条，豁免清单会慢慢腐烂成一张"永久免检名单"：
    行号漂了、内容改了，条目却还在，等于悄悄放宽了检查。
    """
    found = {_key(d) for d in verify.find_doc_drift()}
    stale = sorted(set(_KNOWN_METRIC_MIXUPS) - found)
    assert not stale, f"以下已知项已不再命中，请从 pdx.verify.KNOWN_METRIC_MIXUPS 中删除：{stale}"


def test_命令行的判据与测试同源() -> None:
    """``v3 verify`` 用的必须是 ``unknown_doc_drift``，不能各写一套。

    这条防的是「测试全绿但工具没发现」—— 那正是这个仓库最要命的失效模式，
    而且**真实发生过**：``find_doc_drift`` 曾经只被测试调用，
    ``v3 verify`` 一路报全绿而文档已经过期。
    """
    assert verify.unknown_doc_drift() == [
        d for d in verify.find_doc_drift() if verify.drift_key(d) not in _KNOWN_METRIC_MIXUPS
    ]


def test_合成文档里的漂移确实会被抓到(tmp_path: Path) -> None:
    """把「检测器真的能失败」也测了 —— 否则它只是个永远返回空表的装饰品。

    造一份只含 ``on_actions`` 断言出处文档的目录，正文里写 263（真值 264），
    断言 ``unknown_doc_drift`` 能报出来。
    """
    claim = next(c for c in verify.CLAIMS if c.id == "scr.on_actions")
    (tmp_path / claim.doc).write_text(
        f"# 合成文档\n\n{claim.text.split()[0]} 有 263 个键\n", encoding="utf-8"
    )
    hits = verify.unknown_doc_drift(tmp_path)
    assert any(d.claim.id == claim.id and d.found == 263 for d in hits), (
        f"合成文档里的 263 没被抓到，检测器可能已失效：{[d.describe() for d in hits]}"
    )


def test_合成文档里写对的值不会被报(tmp_path: Path) -> None:
    """反向：写对了就不该报。防止检测器退化成「凡有数字皆漂移」。"""
    claim = next(c for c in verify.CLAIMS if c.id == "scr.on_actions")
    (tmp_path / claim.doc).write_text(
        f"# 合成文档\n\n{claim.text.split()[0]} 有 {claim.expected} 个键\n", encoding="utf-8"
    )
    hits = [d for d in verify.unknown_doc_drift(tmp_path) if d.claim.id == claim.id]
    assert not hits, [d.describe() for d in hits]


def test_范围声明没有被悄悄改回全量() -> None:
    """仓库**刻意不再自称「全量」**，这条守住那个决定。

    背景：「全量解析」只在文件维度成立且可证伪（136 个目录逐文件覆盖，
    有引擎日志背书）；而「所有与 mod 开发相关的信息」没有边界、无法证伪 ——
    继续那样说会让读者把「没提取到」误当成「不存在」。

    测的是**承诺的措辞本身**，不是「某个词有没有出现」：
    想改回全量的人会先看到这条失败，从而读到 `tools/README.md` 的
    「已知边界」一节。刻意不去禁词 —— README 正是**引用了**那句无边界的
    说法来否定它，禁词会把正确的写法也一起禁掉（第一版就这么错过）。
    """
    boundary = (config.REPO / "tools" / "README.md").read_text(encoding="utf-8")
    assert "为什么不再自称「全量」" in boundary, "tools/README.md 的边界说明被删了"
    assert "能回答哪些任务" in boundary, "边界一节必须正面列出「能回答什么」"
    assert "不能**回答" in boundary, "边界一节必须列出「不能回答什么」"

    root = (config.REPO / "README.md").read_text(encoding="utf-8")
    assert "不说自己「全量」" in root, "根 README 应显式声明不说「全量」"
    assert "已知边界" in root, "根 README 应把读者指向边界一节"


def test_每条断言的出处文档都存在() -> None:
    """``claim.doc`` 必须指向真实存在的文档。

    断言表里写错文件名时，漂移检测会静默跳过那条 —— 那是最隐蔽的失效。
    """
    missing = [c.id for c in verify.CLAIMS if not (config.DOCS / c.doc).is_file()]
    assert not missing, f"以下断言的出处文档不存在：{missing}"


def test_每条断言的检查类型都已实现() -> None:
    """``claim.kind`` 必须在 ``_CHECKS`` 里有对应实现，否则核验时会报未知类型。"""
    unknown = sorted({c.kind for c in verify.CLAIMS} - set(verify._CHECKS))
    assert not unknown, f"以下检查类型没有实现：{unknown}"


def test_断言id唯一() -> None:
    ids = [c.id for c in verify.CLAIMS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"断言 id 重复：{dupes}"


#: 抽不出锚点、因而无法参与文档漂移扫描的断言。
#:
#: 它们的描述里只有通用词 —— 这些词在全库出现上千次，拿来做定位依据
#: 会满屏误报，反而淹没真信号。这些断言**仍由 ``v3 verify`` 实测核验**
#: （那才是权威检查），只是不在文档正文里做文本比对。
#:
#: 显式列出而不是「抽不到就跳过」—— 否则哪天锚点抽取退化了，
#: 大片断言会静默退出检查而没人发现。下面每条都写明为什么无法定位。
_NO_ANCHOR_CLAIMS: dict[str, str] = {
    "ai.fields_doc03": "描述「共 60 个字段」里只有中文；数字在同一节的小标题上",
    "ai.mult_doc10": "描述「计入相乘共 2 个」纯中文；它在一条 `>` 引用块里",
    "ai.scalars_doc10": "描述「另有 4 个标量字段」纯中文，同上",
    "ai.strategies_doc03": "描述「共 35 个策略」纯中文；策略清单在下一行才出现",
    "chr.roles_doc17": "描述「共 10 个角色定义」纯中文；目录名不在描述里",
    "dip.regions_doc16": "描述「共 165 个地理区域」纯中文（目录名 geographic_regions 未写进描述）",
    "docs.common_md_doc07": "描述里只有 '.md'，长度不足且到处出现",
    "hist.files_doc11": "描述「共 1153 个文件」纯中文，'history' 在上一行的标题里",
    "hist.subdirs_doc11": "描述「history 22 个子目录」里的 'history' 全库出现上千次",
    "loc.lang_dirs_doc06": "描述「13 个子目录」纯中文；'localization' 未写进描述",
    "pol.movements_doc15": "描述「共 39 个运动」纯中文；目录名未写进描述",
    "script.bars_doc04": "描述「共 42 个进度条」纯中文；目录名未写进描述",
    "script.buttons_doc04": "描述「共 218 个按钮」纯中文；目录名未写进描述",
    "script.event_defs_doc04": "描述「共 2264 个事件定义」纯中文；'events' 太通用",
    "script.event_fields_doc04": "描述「共 26 个不同键」纯中文，没有可定位的标识符",
    "script.lists_doc04": "描述「5 个列表」纯中文；目录名未写进描述",
    "script.rules_doc04": "描述「共 18 个规则」纯中文；目录名未写进描述",
    "env.common_dirs": "描述里只有 'common'，全库出现上千次",
    "env.common_all": "同上，'common' 太通用",
    "def.blocks": "描述里只有 'defines'，全库出现上千次",
    "def.namespaces": "同上，'defines' 太通用",
    "def.param_total": "同上，'defines' 太通用；它写在 §0.4 的纯中文表格里"
    "（`| 参数条目总数 | **3488** |`），没有可定位的英文标识符",
    "def.param_names": "同上，'defines' 太通用",
    "env.common_dirs_direct": "描述里只有 'common'，全库出现上千次；"
    "它由 v3 verify 实测核验，且与 env.common_dirs 互为**独立口径**的交叉验证",
    "env.md_total": "锚点只能是 '.md'，长度不足且到处出现",
    "docs.total_bytes": "doc 07 的总字节数写在一张纯中文表格里（`| 总字节数 | **232,980** |`），"
    "没有任何可定位的英文标识符；它由 v3 verify 实测核验，"
    "内容时效性另由 test_docs_mirror.py 用 sha256 逐篇比对本体看守",
    "hist.wrappers": "描述里只有 'history'，全库出现上千次",
    "pfx.mods_total": "描述里只有 'mod'，全库出现上千次",
    "chr.overview_keys_doc17": "描述「29 个目录的顶层定义键合计」纯中文；期望值 11,705 的容差是 ±117，"
    "而 doc 17 里另有若干 11,6xx 的逐目录键数 —— 文本扫描只会把它们全报成漂移。"
    "这个数字本来就由 test_doc_overview.py 独立看守（它解析 §0 表的 29 行再求和）",
    "eco.buy_package_entries": "描述「买包条目数」纯中文；唯一可用的锚点 'buy_packages' "
    "在该节与 1 / 2 / 15 等同量级数字相撞（同批断言已进 TEXT_SCAN_EXEMPT），"
    "而它本身与 eco.buy_package_categories / wealth1 / fields 互为交叉验证",
}


def test_抽不出锚点的断言集合没有扩大() -> None:
    """锚点抽取是漂移检测的地基；能抽出的断言不该无故变少。"""
    unable = {c.id for c in verify.CLAIMS if c.expected != 0 and not verify.anchors_of(c)}
    new = sorted(unable - set(_NO_ANCHOR_CLAIMS))
    assert not new, (
        f"以下断言抽不出锚点，无法参与文档漂移扫描：{new}\n"
        "请把描述改得更具体（含英文标识符），或登记到 _NO_ANCHOR_CLAIMS 并说明理由。"
    )
    stale = sorted(set(_NO_ANCHOR_CLAIMS) - unable)
    assert not stale, f"以下断言现在已能抽出锚点，请从 _NO_ANCHOR_CLAIMS 移除：{stale}"


def test_主动豁免清单都是真存在的断言() -> None:
    """``verify.TEXT_SCAN_EXEMPT`` 不能指向已删除或改名的断言。

    这是「有锚点、但锚点退化」的那一类：锚点是从文件名碎片
    （`txt` / `shaders` / `graphics`）里抽出来的，配上很小的期望值，
    扫描会命中几十上百处无关数字 —— 实测一次报了 222 处，
    把真信号彻底淹没。它们由 `test_defines_tables.py` 直接比对
    生成器输出看守，比文本扫描强得多。

    豁免必须写明理由，且必须真的还在断言表里 —— 否则清单会腐烂成空头名单。
    """
    ids = {c.id for c in verify.CLAIMS}
    missing = sorted(set(verify.TEXT_SCAN_EXEMPT) - ids)
    assert not missing, f"TEXT_SCAN_EXEMPT 指向不存在的断言：{missing}"
    for cid, reason in verify.TEXT_SCAN_EXEMPT.items():
        assert reason.strip(), f"{cid} 的豁免没写理由"


def test_漂移检测覆盖了足够多的断言() -> None:
    """记录有多少条断言真正参与了漂移扫描。

    这条断言本身很弱，价值在于把「覆盖率」写进测试输出：
    如果某次改动让锚点抽取大面积失效，这个数字会掉下来。
    """
    checkable = [
        c
        for c in verify.CLAIMS
        if c.expected != 0 and verify.anchors_of(c) and (config.DOCS / c.doc).is_file()
    ]
    print(f"\n参与漂移扫描的断言：{len(checkable)} / {len(verify.CLAIMS)} 条")
    assert len(checkable) >= 25, f"只有 {len(checkable)} 条参与扫描，锚点抽取可能退化了"


# ── 哈希：数字漂移扫描的盲区 ─────────────────────────────────
#: 40 位十六进制串 = 本仓库会写进文档的修订哈希形态。
_HEX40 = re.compile(r"\b[0-9a-f]{40}\b")


def _docs_and_indexes() -> list[Path]:
    """所有应当被核对的 markdown：知识库正文 + 两份 README。"""
    return [
        *sorted(config.DOCS.glob("*.md")),
        config.REPO / "README.md",
        config.REPO / "tools" / "README.md",
    ]


@pytest.mark.integration
def test_文档里的修订哈希必须与本体一致() -> None:
    """**补上数字漂移扫描的盲区。**

    这条是被真实事故逼出来的：doc 08 的两处修订哈希停在 1.14.3 之前的
    ``6c9b008f…`` / ``f57eec9a…``，而本体早已是 ``bf52e8ef…`` / ``1ce8c96b…``。
    漂移扫描对它**完全无感** —— ``_STANDALONE_NUM_RE`` 要求数字两侧不是
    字母数字，而哈希是**一整个**字母数字串，永远匹配不到；它又没有回归到
    任何一条断言上，于是两个错值在那里躺了一整个游戏版本，
    而那一节还自称「判断当前装的是哪个版本的**最权威依据**」。

    做法很直白：文档里出现的每一个 40 位十六进制串，都必须等于本机
    ``caligula_rev.txt`` / ``clausewitz_rev.txt`` 里的值之一。
    写了哈希却对不上，只能是抄错了或者抄旧了。
    """
    if not (config.ROOT / "caligula_rev.txt").is_file():
        pytest.skip("游戏目录不可用")
    known = {v for v in config.game_version().values() if v}
    assert len(known) >= 2, f"读到的版本指纹不完整：{known}"

    bad: list[str] = []
    for md in _docs_and_indexes():
        if not md.is_file():
            continue
        for n, line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
            bad.extend(
                f"{md.name}:{n} 写着 {h} —— 本体里没有这个修订号\n    {line.strip()[:100]}"
                for h in _HEX40.findall(line)
                if h not in known
            )
    assert not bad, "文档里有对不上本体的修订哈希：\n  " + "\n  ".join(bad)


def test_哈希扫描本身有效() -> None:
    """上一条测试的**元测试**：确保它真的会抓错，而不是永远绿。

    一条「扫全库、从不失败」的检查比没有检查更糟：它会让人以为有看守。
    """
    assert _HEX40.findall("| 修订 | `bf52e8efe8f45334a3fbd421cc9e06d51077c045` |") == [
        "bf52e8efe8f45334a3fbd421cc9e06d51077c045"
    ]
    assert _HEX40.findall("`6c9b008f4beb17850ee29bfb162bdbdeb3a450ce`") == [
        "6c9b008f4beb17850ee29bfb162bdbdeb3a450ce"
    ]
    # 短哈希（文档里也用 ``bf52e8ef…`` 这种省略写法）不该被当成完整修订号
    assert _HEX40.findall("`bf52e8ef…`") == []


# ── 字节数：文档里「文件名 + 字节」的表格行 ───────────────────
def _table_header_of(lines: list[str], n: int) -> list[str] | None:
    """第 ``n`` 行（1 基）所属表格的表头单元格。往上最近的「下一行是分隔线」的行。"""
    for j in range(n - 2, max(-1, n - 60), -1):
        if lines[j].startswith("|") and j + 1 < len(lines) and lines[j + 1].startswith("|-"):
            return [c.strip() for c in lines[j].strip().strip("|").split("|")]
    return None


def _file_size_index() -> dict[str, set[int]]:
    """``文件名 → {字节数, …}``，覆盖游戏三个内容根 + binaries + Workshop。

    **刻意不含用户数据目录**：那里的 ``pdx_settings.json``、``logs\\*`` 是
    运行期状态，一直在变，钉它等于给自己找一个永远报红的检查
    （doc 08 §16 不纳入生成器，也是同一个理由）。
    """
    index: dict[str, set[int]] = {}
    for base in (
        config.GAME,
        config.JOMINI,
        config.CLAUSEWITZ,
        config.ROOT / "binaries",
        config.WORKSHOP,
    ):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            try:
                if p.is_file():
                    index.setdefault(p.name, set()).add(p.stat().st_size)
            except OSError:
                continue
    return index


@pytest.mark.integration
def test_文档里声明的文件字节数必须与真实文件一致() -> None:
    """按**表头里「字节」所在的列号**核对每一行。

    这条是被三次误报磨出来的，也真抓到了东西：doc 08 的 ``victoria3.exe``
    （97,128,568 → 97,292,920）、doc 03 的三个原版 ``ai_strategies`` 文件、
    doc 17 的 ``00_trigger_localization.txt``（294,479 → 294,446）——
    都是 1.14.3 更新改过、而文档没跟着改的字节数。

    两个前车之鉴（决定了实现方式）：

    * 不能假定「第 2 列就是字节」——doc 04/05 的第 2 列是**条目数**，
      照那个写会假报一片；
    * 也不能固定取第 2 列 —— doc 17 的表是 ``| 文件 | 定义数 | 字节 |``。
      所以要**按表头定位列号**。
    """
    if not config.GAME.is_dir():
        pytest.skip("游戏目录不可用")
    index = _file_size_index()
    assert len(index) > 10_000, f"只索引到 {len(index)} 个文件名，游戏树可能没读到"

    checked = 0
    bad: list[str] = []
    for md in sorted(config.DOCS.glob("*.md")):
        lines = md.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, start=1):
            if not line.startswith("|"):
                continue
            row = [c.strip() for c in line.strip().strip("|").split("|")]
            header = _table_header_of(lines, n)
            if not header:
                continue
            cols = [i for i, h in enumerate(header) if h in {"字节", "B"}]
            if not cols or cols[0] >= len(row):
                continue
            name = row[0].strip("`").strip()
            if "/" in name or "\\" in name:
                continue
            digits = re.sub(r"[^\d]", "", row[cols[0]])
            sizes = index.get(name)
            # <100 的多半是别的量；找不到同名文件说明它不在游戏树里（如 mod 文件）
            if not digits or not sizes or int(digits) < 100:
                continue
            checked += 1
            if int(digits) not in sizes:
                actual = ", ".join(f"{s:,}" for s in sorted(sizes)[:3])
                bad.append(f"{md.name}:{n} `{name}` 文档 {int(digits):,} → 实际 {actual}")
    print(f"\n核对了 {checked} 行声明为字节数的表格行")
    assert checked >= 50, f"只核对了 {checked} 行 —— 表头定位可能退化了"
    assert not bad, "文档里的字节数与真实文件不符：\n  " + "\n  ".join(bad)
