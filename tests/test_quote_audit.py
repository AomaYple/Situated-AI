"""检查知识库正文逐字引用官方散文的占比，不依赖已退役的 README 数字表。"""

from __future__ import annotations

import pytest

from pdx import config

#: 滑窗长度。80 字符足够长到不可能是巧合，又短到能发现「整段搬运」。
N = 80

#: 散文占比的硬上限 —— 这一项才是「逐字搬运说明文字」的直接指标。
PROSE_PCT_CEILING = 1.0


def _norm(s: str) -> str:
    """折叠空白后比对 —— 排版差异不该算成不同文本。"""
    return " ".join(s.split())


def _official_corpus() -> list[str]:
    """官方 94 篇 ``.md`` 的正文（优先读游戏本体，退而读本机镜像）。"""
    texts: list[str] = []
    for base in (config.GAME, config.JOMINI, config.CLAUSEWITZ):
        if base.is_dir():
            texts.extend(
                _norm(p.read_text(encoding="utf-8", errors="replace")) for p in base.rglob("*.md")
            )
    if texts:
        return texts
    mirror = config.OFFICIAL_DOCS_MIRROR
    if mirror.is_dir():
        texts.extend(
            _norm(p.read_text(encoding="utf-8", errors="replace")) for p in mirror.rglob("*.md")
        )
    return texts


def _audit() -> dict[str, float]:
    """重算四个数：正文总量、逐字窗口数、代码块内、代码块外。"""
    corpus = _official_corpus()
    assert corpus, "既没有游戏也没有本机镜像，读不到官方语料"
    shingles = {t[i : i + N] for t in corpus for i in range(max(0, len(t) - N + 1))}

    total = verbatim = prose = 0
    for md in sorted(config.DOCS.glob("*.md")):
        t = _norm(md.read_text(encoding="utf-8"))
        total += len(t)
        for i in range(max(0, len(t) - N + 1)):
            if t[i : i + N] in shingles:
                verbatim += 1
                # 落在 ``` 围栏内 = 引的是语法骨架，不是散文
                if t.count("```", 0, i) % 2 == 0:
                    prose += 1
    return {
        "总字符": float(total),
        "逐字窗口": float(verbatim),
        "代码块内": float(verbatim - prose),
        "散文": float(prose),
    }


@pytest.mark.integration
def test_正文逐字引用散文比例不超过上限() -> None:
    """使用实际官方语料重新计算引用比例，工程摘要不另存易漂移数字。"""
    actual = _audit()
    assert actual["总字符"] > 0
    report = "\n".join(f"{key}: {value:,.0f}" for key, value in actual.items())
    prose_pct = actual["散文"] / actual["总字符"] * 100
    assert prose_pct <= PROSE_PCT_CEILING, (
        f"正文逐字引用散文占 {prose_pct:.2f}%，超过 {PROSE_PCT_CEILING}% 上限。\n{report}"
    )
    print(f"\n逐字引用实测：\n{report}")
