"""把「正文逐字引用官方原文」的实测数变成可复算的检查。

README 的授权节里有一张表，写着正文 991,185 字符、逐字命中 44,709 个窗口
（4.51%）、其中代码块内 40,829（4.12%）、代码块外 3,880（0.39%）。
那组数是**一次性脚本**算出来的 —— 而「文档里的数字必须可复现」正是这个
仓库一直在坚持的事，所以这里补上重算与比对。

为什么用**容差**而不是精确相等：分母是知识库总字符数，任何一次正文编辑都会
让它变化（本轮就编辑了十几处）。精确相等意味着「改一个字就得同步 README」，
那样的看守很快会被关掉 —— 而它的真正目的是**防止有人大段搬进官方原文**。
所以判据是「比例不许明显变大」，同时在失败信息里打印实测值供刷新 README。
"""

from __future__ import annotations

import re

import pytest

from pdx import config

#: 滑窗长度。80 字符足够长到不可能是巧合，又短到能发现「整段搬运」。
N = 80

#: 比例允许的绝对偏差（百分点）。正文增删几百字不会触发，搬进一整节会。
PCT_TOLERANCE = 0.6

#: 散文占比的硬上限 —— 这一项才是「逐字搬运说明文字」的直接指标。
PROSE_PCT_CEILING = 1.0


def _norm(s: str) -> str:
    """折叠空白后比对 —— 排版差异不该算成不同文本。"""
    return " ".join(s.split())


def _official_corpus() -> list[str]:
    """官方 92 篇 ``.md`` 的正文（优先读游戏本体，退而读本机镜像）。"""
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


def _readme_numbers() -> dict[str, float]:
    """从 README 的授权节里读出它自己声明的数。"""
    text = (config.REPO / "README.md").read_text(encoding="utf-8")
    want = {
        "总字符": r"知识库正文总量 \| ([\d,]+) 字符",
        "逐字窗口": r"逐字命中官方原文 \| ([\d,]+) 个窗口",
        "代码块内": r"代码块内 \| ([\d,]+) 个",
        "散文": r"代码块外 \| ([\d,]+) 个",
    }
    out: dict[str, float] = {}
    for key, pat in want.items():
        m = re.search(pat, text)
        assert m, f"README 里读不到「{key}」—— 授权节的表被改过？"
        out[key] = float(m.group(1).replace(",", ""))
    return out


@pytest.mark.integration
def test_正文逐字引用的实测数与README一致() -> None:
    """README 授权节那组数必须能重算出来。

    需要官方语料（游戏或本机镜像），所以是 ``integration`` —— 装机器的机器上跑。

    **它第一次运行就抓到了真错**：README 初版的「正文总量 991,185」只统计了
    含逐字命中的那 10 篇，分母漏掉 10 篇无命中的文档，于是占比被抬高
    （4.51% → 实际 3.93%、0.39% → 实际 0.34%）。一次性脚本算出来的数字
    留在文档里就是这个下场。
    """
    actual = _audit()
    claimed = _readme_numbers()

    report = "  " + "\n  ".join(
        f"{k}: README {claimed[k]:,.0f} → 实测 {actual[k]:,.0f}" for k in actual
    )

    # 1) 代码块外的逐字占比是核心指标：不许明显变大
    prose_pct = actual["散文"] / actual["总字符"] * 100
    assert prose_pct <= PROSE_PCT_CEILING, (
        f"正文里逐字引用的**散文**占了 {prose_pct:.2f}%，超过 {PROSE_PCT_CEILING}% 的上限。\n{report}"
    )

    # 2) README 声明的比例与实际的比例不能差太多
    for key, denom_key in (("逐字窗口", "总字符"), ("散文", "总字符")):
        got = actual[key] / actual[denom_key] * 100
        said = claimed[key] / claimed[denom_key] * 100
        assert abs(got - said) <= PCT_TOLERANCE, (
            f"README 说「{key}」占 {said:.2f}%，实测 {got:.2f}%，"
            f"差 {abs(got - said):.2f} 个百分点（容差 {PCT_TOLERANCE}）。\n"
            f"正文改动后请按实测值刷新 README 授权节的表：\n{report}"
        )

    # 3) 总量本身也要对得上：差得太多说明 README 的表已经不是这份正文的了
    drift = abs(actual["总字符"] - claimed["总字符"]) / max(claimed["总字符"], 1)
    assert drift <= 0.05, f"README 的正文总量与实测差了 {drift:.1%} —— 那张表过期了。\n{report}"

    print(f"\n逐字引用实测：{report}")
