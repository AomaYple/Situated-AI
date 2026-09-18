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
