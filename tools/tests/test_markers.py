"""归属标记的看守：标记指向真断言、数字与期望一致、`--fix` 幂等。

为什么单开一个文件
----------------
``v3 verify`` 的断言只回答「游戏里到底有多少」，而正文里那个数字**由谁负责**
原先没人管：文本来回扫描只能靠「锚点词 + 量级接近」猜，同一行有两个同量级数字
就分不清（这正是 ``KNOWN_METRIC_MIXUPS`` 那 10 条纠缠的来路）。

归属标记把「猜」换成「绑定」：``205<!--claim:dip.group_files-->``。
本文件守着这套绑定的三条不变量 —— 它们同时也是 ``v3 verify`` 每次都会跑的两条检查
（这里再测一遍，是为了让「检查器自己坏掉」也变成红的）。
"""

from __future__ import annotations

import pytest

from pdx import config, markers, verify

#: 标记覆盖率的下限（只许涨，不许跌）。
#:
#: 迁移完成时 231 条断言里有 198 条拿到标记；随后把三张手写表接进生成器
#: （doc 07 §0 官方文档统计、doc 05 §0.4 全局规模、doc 09 §4 领域对应字段），
#: 又补了 12 处正文标记 → **210 / 234**。
#:
#: **这个数字只能涨**：新加的可复算数字应当顺手加标记，而不是让覆盖率慢慢烂回去。
MARKER_FLOOR = 210

#: **刻意不打标记**的断言：``claim_id → 理由``。三类，每一条都已经有人看守：
#:
#: * **生成表拥有**：数字在由 ``v3 tables`` 生成的表里 —— 标记会被整表重写抹掉，
#:   那里不该有标记；表格每次重算就是它们的看守。
#: * **本机 mod 快照**：统计对象是本机订阅的 Workshop mod（机器相关），
#:   对应的表在 ``NOT_GENERATED`` 里，换台机器就变。
#: * **数值不在正文**：断言按**字节**钉（唯一没有歧义的量），正文写的是 MB，
#:   正文里没有这个数、自然没有位置挂标记。
MARKER_NOT_NEEDED: dict[str, str] = {
    # ── 生成表拥有 ───────────────────────────────────────
    "script.lists_doc04": "doc 04 §0.2 目录规模表由 v3 tables 生成",
    "defines.script_values_blocks": "同上（该表的一行）",
    "env.common_txt": "doc 08 的 common 主表由 v3 tables 生成",
    "env.common_all": "同上",
    "tree.game": "doc 08 的全局总数表由 v3 tables 生成",
    "tree.game_dirs": "同上",
    "docs.total_bytes": "doc 07 §0 统计总览由 v3 tables 生成（从入库清单现算）",
    "def.namespaces": "doc 05 §0.4 全局规模表由 v3 tables 生成",
    "def.param_names": "同上",
    "ai.script_values_doc09": "doc 09 §4 领域对应字段表由 v3 tables 生成",
    "ai.strategy_refs_doc09": "同上",
    # ── 本机 mod 快照（机器相关）─────────────────────────
    "pfx.mods_total": "统计本机 23 个 Workshop mod 的前缀用量（NOT_GENERATED 那张表）",
    "pfx.replace_or_create": "同上",
    "pfx.inject": "同上",
    "pfx.try_inject": "同上",
    "pfx.try_replace": "同上",
    "pfx.replace": "同上",
    "pfx.inject_or_create": "同上",
    # ── 数值不在正文里 ───────────────────────────────────
    "tree.game_bytes": "doc 08 正文写 17,055.76 MB，断言按字节钉；正文没有这个数",
    "tree.binaries_bytes": "同上（260.95 MB）",
    "tree.gfx_bytes": "同上（9,690.00 MB）",
}


def test_没有标记的断言都有理由() -> None:
    """覆盖率不是靠「尽量多打标记」，而是靠**每个没标记的都答得出为什么**。

    两个方向都查：有断言没标记又没登记 → 红；登记了却已经拿到标记 → 红（清单腐烂）。
    """
    bound = {cid for ids in verify.marker_ids_by_doc().values() for cid in ids}
    unmarked = {c.id for c in verify.CLAIMS if isinstance(c.expected, int) and c.id not in bound}
    missing = sorted(unmarked - set(MARKER_NOT_NEEDED))
    assert not missing, (
        "以下断言既没有归属标记、也没有登记理由：\n  "
        + "\n  ".join(missing)
        + "\n给它加标记，或写进 MARKER_NOT_NEEDED 说明为什么不需要。"
    )
    stale = sorted(set(MARKER_NOT_NEEDED) - unmarked)
    assert not stale, f"以下断言已经拿到标记（或已删除），请从 MARKER_NOT_NEEDED 移除：{stale}"


def test_标记都指向存在的断言() -> None:
    """孤儿标记：指向已删除/改名的断言 —— 标记一旦指向空处就只是装饰。"""
    orphan = [i.describe() for i in verify.check_markers() if "没有这条断言" in i.detail]
    assert not orphan, "以下标记指向不存在的断言：\n  " + "\n  ".join(orphan)


def test_标记处的数字与断言期望一致() -> None:
    """标记写 205、断言期望 210 —— 这就是「文档过期」在标记体系里的样子。

    ``v3 verify --fix`` 能修；不带 ``--fix`` 时报红。
    """
    bad = [i.describe() for i in verify.check_markers() if "没有这条断言" not in i.detail]
    assert not bad, (
        "以下标记处的数字与断言期望不一致（跑 `v3 verify --fix` 可修）：\n  " + "\n  ".join(bad)
    )


def test_覆盖率不低于下限() -> None:
    """标记数只许涨。"""
    bound = verify.marker_ids_by_doc()
    ids = {cid for doc_ids in bound.values() for cid in doc_ids}
    assert len(ids) >= MARKER_FLOOR, (
        f"带归属标记的断言从 {MARKER_FLOOR} 掉到了 {len(ids)} —— "
        f"是删除断言时把标记一起删了，还是新断言没加标记？"
    )


def test_fix_是幂等的且只改标记处的数字() -> None:
    """``--fix`` 的两条性质：跑完再跑零改动；无标记的数字一个字都不动。

    这是整个机制的安全底线 —— 如果 ``--fix`` 会碰没有标记的数字，
    那它就从「按归属改」退化成了「猜着改文本」，比不做更危险。
    """
    if not config.DOCS.is_dir():  # pragma: no cover - 文档目录缺失时无意义
        pytest.skip("文档目录不可用")
    before = {p.name: p.read_text(encoding="utf-8") for p in config.DOCS.glob("*.md")}
    assert not verify.fix_markers(write=False), "当前状态下不该有需要改的标记"
    assert not verify.fix_markers(write=True), "写盘路径与实际改动不一致"
    after = {p.name: p.read_text(encoding="utf-8") for p in config.DOCS.glob("*.md")}
    assert before == after, "「没有改动」却动了文件 —— --fix 必须幂等"


def test_合成文档里的错标记会被抓出来(tmp_path) -> None:
    """造一份只含一条标记的目录：数字写错 → 报「不一致」；指向空 id → 报「没有这条断言」。

    没有这条，检查器可能退化成「永远返回空列表」而没人发现
    （本仓库在哈希那件事上踩过同类的坑）。
    """
    claim = next(c for c in verify.CLAIMS if isinstance(c.expected, int) and c.expected > 10)
    assert isinstance(claim.expected, int)  # 收窄类型给 mypy 看
    (tmp_path / claim.doc).write_text(
        f"# 合成文档\n\n共 {claim.expected + 1}<!--claim:{claim.id}--> 个、"
        f"以及 7<!--claim:no.such.claim--> 处\n",
        encoding="utf-8",
    )
    issues = verify.check_markers(tmp_path)
    kinds = {i.detail for i in issues}
    assert any("期望" in k for k in kinds), f"数字写错没被抓到：{kinds}"
    assert any("没有这条断言" in k for k in kinds), f"孤儿标记没被抓到：{kinds}"

    fixes = verify.fix_markers(tmp_path, write=True)
    assert [f.id for f in fixes] == [claim.id], f"待修清单不对：{fixes}"
    text = (tmp_path / claim.doc).read_text(encoding="utf-8")
    assert f"{claim.expected}<!--claim:{claim.id}-->" in text, text
    assert "7<!--claim:no.such.claim-->" in text, "孤儿标记不该被 --fix 动掉"
    assert not [i for i in verify.check_markers(tmp_path) if "期望" in i.detail]


def test_标记语法本身没退化() -> None:
    """三种写法都要认：裸数字、``**粗体**``、反引号，以及链式挂多条。"""
    text = (
        "共 205<!--claim:a--> 个、**42**<!--claim:b--> 个、`7`<!--claim:c--> 个、"
        "0<!--claim:d--><!--claim:e--> 个\n"
    )
    got = [(m.id, m.value, m.raw) for m in markers.iter_markers(text, "x.md")]
    assert got == [("a", 205, "205"), ("b", 42, "42"), ("c", 7, "7"), ("d", 0, "0"), ("e", 0, "0")]
    assert markers.format_value(11705, "11,673") == "11,705", "千分位风格没保留"
