"""文档一致性测试。

要解决的问题
------------
这是四份逐文件审计里排第一的发现：**文档写的是 1.14.2 的数字，而游戏早已
升到 1.14.3**。更糟的是没有任何测试能发现它 —— ``tools/pdx/verify.py``
的 39 条断言早就把新值测对了，但断言表与文档正文**永不共振**，
``v3 verify`` 一路报「全绿」，文档里却躺着几十个过期数字。

本文件把两者接起来：断言表说「``on_actions`` 有 264 个键」，
那就到它声称的出处文档里去找这一行；找不到 264、却找到量级接近的
263，就是漂移。

判定规则见 :func:`pdx.verify.find_doc_drift` 的文档。它同时是
``v3 verify`` 的底层实现，所以**命令行与测试用的是同一套逻辑**，
不会出现"测试过了但工具没发现"的分歧。
"""

from __future__ import annotations

import pytest

from pdx import config, verify

pytestmark = pytest.mark.docs

#: 检测器的已知**度量口径错配**。
#:
#: 这些行的共同点是：同一行里并列了好几个不同口径的指标（条目数 / 文件数 /
#: 被引用次数），静态文本无法判断断言要的是哪一个。逐条实测确认过
#: 「文档其实是对的」，因此登记为已知项而不是改文档。
#:
#: 每一条都必须写清理由 —— 没有理由的豁免就是放任漂移。
_KNOWN_METRIC_MIXUPS: dict[str, str] = {
    "14-经济与生产系统.md:1557":
        "52 是 goods 作为字段被引用的次数，不是 goods 条目数（条目数为 53）",
    "14-经济与生产系统.md:1562":
        "同上，52 是引用次数",
    "14-经济与生产系统.md:2081":
        "51 是某字段的引用次数，与 goods 条目数无关",
    "15-政治人口与社会.md:2522":
        "316 描述的是该字段列表长度，与 cultures 目录条目数（317）不同口径",
    "17-角色科技与呈现.md:2428":
        "609 是单个文件 00_game_concepts.txt 内的条目数，目录合计为 612",
    "16-外交军事与地图.md:857":
        "35 是 treaty_articles 的**文件数**，条目数为 34；实测两者确实不同",
    "16-外交军事与地图.md:1466":
        "40 是 war_goal_types 的**文件数**，条目数为 39；实测两者确实不同",
    "16-外交军事与地图.md:3628":
        "33 是使用某字段的条目数，不是目录条目总数",
    "16-外交军事与地图.md:3695":
        "33 是 usage_limit 字段的出现次数，不是目录条目总数",
    "16-外交军事与地图.md:1560":
        "41 指的是官方 .md 里 settings 列表的条目数，非游戏数据条目数",
}


def _key(d: verify.DocDrift) -> str:
    return f"{d.doc}:{d.line}"


def test_没有新增的文档数字漂移() -> None:
    """文档里凡是「锚点 + 数量」的地方，要么与断言表一致，要么在已知清单里。

    这是本文件的核心。任何**新**出现的漂移都会在这里失败，
    并直接指出 文件:行号 与两个数字。
    """
    unexpected = [d for d in verify.find_doc_drift() if _key(d) not in _KNOWN_METRIC_MIXUPS]
    assert not unexpected, (
        f"发现 {len(unexpected)} 处新的文档数字漂移：\n"
        + "\n".join("  " + d.describe() for d in unexpected)
        + "\n\n请把文档里的数字改成实测值；若确认是口径不同，"
        "登记到 _KNOWN_METRIC_MIXUPS 并写明理由。"
    )


def test_已知口径错配清单没有失效() -> None:
    """清单里的条目若不再命中，说明那一行改了 —— 必须同步清理。

    没有这条，豁免清单会慢慢腐烂成一张"永久免检名单"：
    行号漂了、内容改了，条目却还在，等于悄悄放宽了检查。
    """
    found = {_key(d) for d in verify.find_doc_drift()}
    stale = sorted(set(_KNOWN_METRIC_MIXUPS) - found)
    assert not stale, (
        f"以下已知项已不再命中，请从 _KNOWN_METRIC_MIXUPS 中删除：{stale}"
    )


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
    "env.md_total": "锚点只能是 '.md'，长度不足且到处出现",
    "hist.wrappers": "描述里只有 'history'，全库出现上千次",
    "pfx.mods_total": "描述里只有 'mod'，全库出现上千次",
}


def test_抽不出锚点的断言集合没有扩大() -> None:
    """锚点抽取是漂移检测的地基；能抽出的断言不该无故变少。"""
    unable = {
        c.id for c in verify.CLAIMS if c.expected != 0 and not verify.anchors_of(c)
    }
    new = sorted(unable - set(_NO_ANCHOR_CLAIMS))
    assert not new, (
        f"以下断言抽不出锚点，无法参与文档漂移扫描：{new}\n"
        "请把描述改得更具体（含英文标识符），或登记到 _NO_ANCHOR_CLAIMS 并说明理由。"
    )
    stale = sorted(set(_NO_ANCHOR_CLAIMS) - unable)
    assert not stale, f"以下断言现在已能抽出锚点，请从 _NO_ANCHOR_CLAIMS 移除：{stale}"


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
