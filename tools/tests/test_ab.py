"""``pdx.ab`` 的用例：阶段 3 A/B 实验的解析、差分与开局自检。

用合成日志钉住六件事：**按月配对**（含脉冲跨秒与轮转副本）、**`RUN` 分段 + 同角色合并**、
**行为层差分**（改革窗口 / 法律首次转换）、**策略层差分**（三槽落点）、
**判定三档**（G2 初步成立 / H2 薄壳 / 无差分），以及**开局自检的通过与否决路径**。

为什么每条自检用例都显式传 `text=` / `error_text=`：不传就会去读本机用户目录里的
真日志（那台机器上真的跑过 A 组），用例会随"今天有没有玩游戏"而飘。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import ab
from pdx.cli import app

pytestmark = pytest.mark.unit

runner = CliRunner()

#: 日志行的前缀：与真实日志逐字一致（`--watch` 快照/轮转副本的行都长这样）。
#: 带上文件路径是**故意的** —— 正常自报行的前缀里就有 `zz_probe_ab_...`，
#: 这正是"命名空间扫描不能套到 debug 日志上"的原因（见 ``test_..._不触发命名空间扫描``）。
_HEAD = "[12:00:{sec:02d}][jomini_effect_impl.cpp:454]: "
_PATH = "common/on_actions/zz_probe_ab_on_actions.txt:30: "
_TAG = "俄罗斯"

#: 一个月的默认自报：没冲击、没改革侧输入、窗口关着、还是农奴制、三槽落点固定、
#: 合法性在最高档（b80）。**与当前探针逐行对应**（含 INPUT / LEG 两行后加的诊断）。
_DEFAULTS = {
    "SHOCK": "no",
    "INPUT": "no",
    "LEG": "b80",
    "JE": "inactive",
    "LAW": "law_serfdom",
    "POLI": "reactionary_agenda",
    "ADMI": "agricultural_expansion",
    "DIPL": "colonial_expansion",
    "STRATEGY": "ai_strategy_reactionary_agenda",
}

#: 加 `INPUT` / `LEG` 之前的探针写了哪些行（老归档的形状）——
#: 用 `skip=` 造这种块，钉住"老归档照样能分析"（阶段 3 的结论就来自那些局）。
LEGACY_SKIP = ("INPUT", "LEG")

#: 加 `STRATEGY` 之前的探针（= 阶段 3 那四局）。
LEGACY_SKIP_STRATEGY = ("INPUT", "LEG", "STRATEGY")


def _line(sec: int, kind: str, value: str, tag: str = _TAG) -> str:
    return f"{_HEAD.format(sec=sec)}{_PATH}ZZPROBE AB;{kind};{value};{tag}"


def _run_line(role: str) -> str:
    """开局标记：`RUN` 行没有国名（它由点哪个决议决定）。"""
    return f"{_HEAD.format(sec=0)}{_PATH}ZZPROBE AB;RUN;{role}"


def _month(
    sec: int,
    *,
    player: str | None = _TAG,
    split: int | None = None,
    skip: tuple[str, ...] = (),
    cells: dict[str, str] | None = None,
) -> str:
    """一个月的自报块。

    ``split`` 给行号时，那一行之后的行走下一秒（月度脉冲跨秒的实况）；
    ``skip`` 用来造"被轮转切断的半块"；``cells`` 用小写行名覆盖 :data:`_DEFAULTS`
    （例如 ``{"shock": "yes"}``）。
    """
    values = {**_DEFAULTS, **{kind.upper(): value for kind, value in (cells or {}).items()}}
    rows: list[tuple[str, str, str]] = []
    if player is not None:
        rows.append(("PLAYER", "yes", player))
    rows.append(("ROLE", "RUS", _TAG))
    rows += [(kind, values[kind], _TAG) for kind in _DEFAULTS if kind not in skip]
    return "\n".join(
        _line(sec + 1 if split is not None and index >= split else sec, kind, value, tag)
        for index, (kind, value, tag) in enumerate(rows)
    )


def _segment(
    role: str,
    months: int = 1,
    *,
    first_sec: int = 1,
    player: str | None = _TAG,
    cells: dict[str, str] | None = None,
    skip: tuple[str, ...] = (),
) -> str:
    """一段：`RUN` 行 + 连续若干个月（每月取值相同）。"""
    return "\n".join(
        [
            _run_line(role),
            *[
                _month(first_sec + index, player=player, cells=cells, skip=skip)
                for index in range(months)
            ],
        ]
    )


def _timeline(role: str, specs: list[dict[str, str]], *, skip: tuple[str, ...] = ()) -> str:
    """一段：`RUN` 行 + 逐月自定义（每个月一个覆盖 dict）。"""
    return "\n".join(
        [
            _run_line(role),
            *[_month(index + 1, cells=spec, skip=skip) for index, spec in enumerate(specs)],
        ]
    )


def _ladder(
    *,
    a_months: int = 12,
    b_months: int = 24,
    b2_months: int = 12,
    a_cells: dict[str, str] | None = None,
    b_cells: dict[str, str] | None = None,
    b2_cells: dict[str, str] | None = None,
    player: str = "塔希提",
) -> str:
    """一局之内按阶梯换臂的日志（当前探针的形状：A → B → B2）。

    玩家默认是**旁观者**（塔希提）—— 实验就是这么跑的：玩家扮演小国，
    冲击远程施加到保持 AI 控制的俄罗斯。
    """
    base = {"shock": "yes"}
    return "\n".join(
        [
            _segment("A", a_months, first_sec=1, player=player, cells=a_cells or {}),
            _segment("B", b_months, first_sec=40, player=player, cells={**base, **(b_cells or {})}),
            _segment(
                "B2",
                b2_months,
                first_sec=80,
                player=player,
                cells={**base, "input": "yes", **(b2_cells or {})},
            ),
        ]
    )


def _healthy_text(*, player: str = _TAG, b_shock: str = "yes") -> str:
    """一局"数据一切正常"的 A+B：自检应当全绿。"""
    return "\n".join(
        [
            _segment("A", 4, player=player),
            _segment("B", 4, first_sec=20, player=player, cells={"shock": b_shock}),
        ]
    )


def _diff(diffs: tuple[ab.Diff, ...], name: str) -> ab.Diff:
    hit = next((diff for diff in diffs if diff.name == name), None)
    assert hit is not None, f"差分表里没有 {name}：{[d.name for d in diffs]}"
    return hit


# ── 解析：按月配对 / 分段 / 合并 ──────────────────────────────


def test_按月配对成一个块() -> None:
    result = ab.analyze_text(_segment("A", 2))
    assert result.months == 2
    assert result.unpaired == 0
    assert list(result.roles) == ["A"]
    first = result.samples[0]
    assert (first.role, first.month, first.shock, first.je, first.law) == (
        "A",
        1,
        "no",
        "inactive",
        "law_serfdom",
    )
    assert first.cards == {
        "political": "reactionary_agenda",
        "administrative": "agricultural_expansion",
        "diplomatic": "colonial_expansion",
    }
    assert first.shock_yes is False
    assert first.je_active is False


def test_RUN行切分两局() -> None:
    result = ab.analyze_text(
        "\n".join([_segment("A", 2), _segment("B", 2, first_sec=20, cells={"shock": "yes"})])
    )
    assert result.runs == ("A", "B")
    assert [sample.role for sample in result.samples] == ["A", "A", "B", "B"]
    assert len(result.segments) == 2
    assert result.roles["B"].shock_rate == 1.0
    assert result.roles["A"].shock_rate == 0.0


def test_缺RUN行时用ROLE行的字母兜底() -> None:
    """老探针的实况（`ab-A-partial` 归档）：没有 RUN 行，`ROLE` 行带的是角色字母。"""
    text = "\n".join(_month(sec) for sec in (1, 2, 3)).replace("AB;ROLE;RUS;", "AB;ROLE;A;")
    result = ab.analyze_text(text)
    assert result.roles["A"].observations == 3
    assert result.segments[0].declared == ""
    assert result.segments[0].role == "A"


def test_同一角色的多段合并且月份连续() -> None:
    """A 跑了两遍 + B 一遍：A 的两段要合并，月份编号首尾相接。"""
    text = "\n".join(
        [
            _segment("A", 2),
            _segment("B", 2, first_sec=20, cells={"shock": "yes"}),
            _segment("A", 2, first_sec=40, cells={"je": "active"}),
        ]
    )
    result = ab.analyze_text(text)
    assert result.roles["A"].segments == 2
    assert result.roles["A"].observations == 4
    assert result.roles["B"].segments == 1
    # 第二段的第一块是 A 的第 3 个月（合并后连续编号）
    assert result.roles["A"].je_first == 3


def test_同一段内重复的自报行只算一次() -> None:
    """轮转边界上同一个月的行可能出现两次：同一段里完全相同的行只算一次。"""
    blocks = "\n".join([_month(1), _month(2)])
    result = ab.analyze_text("\n".join([_run_line("A"), blocks, blocks]))
    assert result.months == 2
    assert result.unpaired == 0


def test_逐字节相同的快照副本只算一次(tmp_path: Path) -> None:
    """`--watch` 每一轮都会把同一个 `debug.log` 复制进归档目录（连 `RUN` 行一起）。"""
    text = _segment("A", 2)
    for name in ("debug.log", "s0001-debug.log", "s0002-debug.log"):
        (tmp_path / name).write_text(text, encoding="utf-8")
    result = ab.analyze(tmp_path)
    assert result.months == 2
    assert result.runs == ("A",)
    assert result.roles["A"].segments == 1


def test_月度块跨秒也能配成一个块() -> None:
    """脉冲偶尔跨秒：块边界靠"同类型的行又出现了"，不靠时间戳。"""
    result = ab.analyze_text("\n".join([_run_line("A"), _month(3, split=4)]))
    assert result.months == 1
    assert result.unpaired == 0


def test_缺行的半块算残缺且不进统计() -> None:
    text = "\n".join([_run_line("A"), _month(1), _month(2, skip=("SHOCK",))])
    result = ab.analyze_text(text)
    assert result.months == 1
    assert result.unpaired == 1
    assert result.roles["A"].observations == 1


def test_角色未知的段不进差分() -> None:
    """两边都判不出角色时，差分表是空的（而不是把未知组当成 A 组）。"""
    text = "\n".join(_month(sec) for sec in (1, 2, 3)).replace("AB;ROLE;RUS;", "AB;ROLE;X;")
    result = ab.analyze_text(text)
    assert list(result.roles) == [ab.ROLE_UNKNOWN]
    assert result.behaviour_diffs == ()
    assert result.verdict == "insufficient"
    assert ab.ROLE_LABELS[ab.ROLE_UNKNOWN] in ab.format_report(result)


# ── 行为层差分 ────────────────────────────────────────────────


def test_行为层差分_改革窗口开启() -> None:
    text = "\n".join(
        [
            _timeline("A", [{}] * 12),
            _timeline("B", [{"shock": "yes", "je": "active"}] * 12),
        ]
    )
    result = ab.analyze_text(text)
    assert result.roles["B"].je_first == 1
    assert result.roles["A"].je_first is None
    assert _diff(result.behaviour_diffs, "改革窗口 JE").changed
    assert result.behaviour_changed
    assert not result.strategy_changed
    assert result.verdict == "g2_preliminary"


def test_行为层差分_法律首次转换月份() -> None:
    """占位差只有 3 个百分点（低于阈值），靠"第几个月转的"才判得出来。"""
    specs = [{"shock": "yes"}] * 29 + [{"shock": "yes", "law": "law_autocracy"}]
    result = ab.analyze_text("\n".join([_timeline("A", [{}] * 30), _timeline("B", specs)]))
    b = result.roles["B"]
    assert (b.first_law, b.law_change, b.law_change_to) == ("law_serfdom", 30, "law_autocracy")
    assert result.roles["A"].law_change is None
    change = _diff(result.behaviour_diffs, "法律首次转换")
    assert change.changed
    assert "第 30 月 → law_autocracy" in change.b
    assert not _diff(result.behaviour_diffs, "法律 law_serfdom").changed
    assert result.behaviour_changed


def test_行为层读数里法律占比可查() -> None:
    specs = [{"shock": "yes"}] * 3 + [{"shock": "yes", "law": "law_censorship"}]
    behaviour = ab.analyze_text(_timeline("B", specs)).roles["B"]
    serfdom = behaviour.law_stat("law_serfdom")
    assert serfdom is not None
    assert serfdom.months == 3
    assert behaviour.law_share("law_serfdom") == pytest.approx(0.75)
    assert behaviour.law_stat("law_autocracy") is None
    assert behaviour.law_share("law_autocracy") == 0.0
    assert behaviour.first_law == "law_serfdom"


# ── 政治牌（2026-09-22 起的直接读数）──────────────────────────


def test_政治牌被折成短名并统计占比() -> None:
    """B53：`change_law_chance` 写在牌上 ⇒ 牌是**行为层**读数，必须能直接统计。

    日志里是全名（`ai_strategy_progressive_agenda`），报告里用短名 —— 与三槽那套同口味。
    """
    specs = [{"shock": "yes"}] * 2 + [
        {"shock": "yes", "strategy": "ai_strategy_progressive_agenda"}
    ]
    behaviour = ab.analyze_text(_timeline("B", specs)).roles["B"]
    assert [stat.name for stat in behaviour.strategies] == [
        "reactionary_agenda",
        "progressive_agenda",
    ]
    assert behaviour.strategy_share("progressive_agenda") == pytest.approx(1 / 3)
    assert behaviour.strategy_stat("progressive_agenda").first_month == 3
    assert behaviour.strategy_share("没有这张牌") == 0.0


def test_认不出来的牌名原样保留() -> None:
    """探针换过牌名 / 原版加了新牌时不许把读数吞掉 —— 短名表只做**折叠**，不做过滤。"""
    behaviour = ab.analyze_text(_timeline("B", [{"strategy": "ai_strategy_brand_new"}])).roles["B"]
    assert [stat.name for stat in behaviour.strategies] == ["ai_strategy_brand_new"]


def test_老归档缺_STRATEGY_行时照样能分析() -> None:
    """口径：**新增的读数只能是可选行** —— 否则阶段 3 那四局会被新判据反向作废。

    这里连**判定**一起钉住：缺 `STRATEGY` 的那一版日志照样出得了 `A`/`B` 两组读数
    与差分（`behaviour_changed` 是个布尔）。缺 `STRATEGY` 只让牌表变空，不影响别的。
    """
    legacy = "\n".join(
        [
            _timeline("A", [{}] * 12, skip=LEGACY_SKIP_STRATEGY),
            _timeline("B", [{"shock": "yes"}] * 12, skip=LEGACY_SKIP_STRATEGY),
        ]
    )
    result = ab.analyze_text(legacy)
    assert result.roles["A"].strategies == (), "老归档没有牌读数 ⇒ 空元组，不是假的 0%"
    assert result.roles["A"].strategy_share("progressive_agenda") == 0.0
    assert result.roles["A"].observations == 12, "牌缺席不影响块是否完整"
    assert set(result.roles) == {"A", "B"}, "两组照样分得出来"
    # 对照：**带** STRATEGY 行的那一版必须真的记到牌（否则上一条是空转）
    modern = ab.analyze_text(
        "\n".join([_timeline("A", [{}] * 12), _timeline("B", [{"shock": "yes"}] * 12)])
    )
    assert modern.roles["A"].strategies, "带 STRATEGY 行时必须有读数"


def test_报告里有一张政治牌表() -> None:
    text = ab.format_report(
        ab.analyze_text(
            "\n".join(
                [
                    _timeline("A", [{}] * 12),
                    _timeline("B", [{"shock": "yes"}] * 12),
                ]
            )
        )
    )
    assert "政治牌" in text
    assert "reactionary_agenda" in text


def test_老归档的报告里明说没有政治牌行() -> None:
    text = ab.format_report(
        ab.analyze_text(
            "\n".join(
                [
                    _timeline("A", [{}] * 12, skip=LEGACY_SKIP_STRATEGY),
                    _timeline("B", [{"shock": "yes"}] * 12, skip=LEGACY_SKIP_STRATEGY),
                ]
            )
        )
    )
    assert "没有 `STRATEGY` 行" in text


# ── 策略层差分与判定 ──────────────────────────────────────────


def test_策略层最常见落点口径() -> None:
    specs = [{"shock": "yes", "poli": "alpha"}] * 3 + [{"shock": "yes", "poli": "beta"}] * 2
    result = ab.analyze_text(_timeline("B", specs))
    dist = result.slots["B"]["political"]
    assert dist.most_common == ("alpha", 3)
    assert dist.share("alpha") == pytest.approx(0.6)
    assert dist.share("没有这张牌") == 0.0
    assert dist.observations == 5


def test_只有策略层动判为H2不成立() -> None:
    text = "\n".join(
        [
            _timeline("A", [{}] * 12),
            _timeline("B", [{"shock": "yes", "poli": "progressive_agenda"}] * 12),
        ]
    )
    result = ab.analyze_text(text)
    assert not result.behaviour_changed
    assert result.strategy_changed
    assert result.verdict == "h2_shell"
    report = ab.format_report(result)
    assert "H2 不成立：意图层是薄壳" in report
    assert "停下重估目标" in report


def test_两层都有差分判为G2初步成立() -> None:
    text = "\n".join(
        [
            _timeline("A", [{}] * 12),
            _timeline("B", [{"shock": "yes", "je": "active", "poli": "progressive_agenda"}] * 12),
        ]
    )
    result = ab.analyze_text(text)
    assert result.verdict == "g2_preliminary"
    report = ab.format_report(result)
    assert "G2 初步成立" in report
    assert "两次同向" in report


def test_无差分() -> None:
    """SHOCK 两边不同**不算差分** —— 它是被操纵的输入，不是观察到的结果。"""
    text = "\n".join([_timeline("A", [{}] * 12), _timeline("B", [{"shock": "yes"}] * 12)])
    result = ab.analyze_text(text)
    assert result.roles["B"].shock_rate == 1.0
    assert result.verdict == "no_diff"
    assert "无差分" in ab.format_report(result)


def test_缺一组时判为无法判定() -> None:
    result = ab.analyze_text(_segment("A", 5))
    assert result.verdict == "insufficient"
    report = ab.format_report(result)
    assert "无法判定" in report
    assert "缺 B 组" in report


def test_报告先行为层再策略层() -> None:
    text = "\n".join(
        [
            _timeline("A", [{}] * 6),
            _timeline("B", [{"shock": "yes", "je": "active", "poli": "x"}] * 6),
        ]
    )
    report = ab.format_report(ab.analyze_text(text))
    assert report.index("① 行为层差分") < report.index("② 策略层差分") < report.index("### 判定")


def test_冲击比例按角色统计() -> None:
    text = "\n".join([_segment("A", 3), _segment("B", 3, first_sec=20, cells={"shock": "yes"})])
    result = ab.analyze_text(text)
    assert result.roles["A"].shock_rate == 0.0
    assert result.roles["B"].shock_rate == 1.0
    assert "A 对照组 0%" in ab.format_report(result)


# ── 开局自检（P13：失败要出声）────────────────────────────────


def test_开局自检_健康双角色全绿() -> None:
    # 玩家必须是**旁观者**（不是主角国家）—— 主角国家要保持 AI 控制，否则问不出「AI 自己改革」
    text = _healthy_text(player="法国")
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    assert all(item.ok for item in items), [item.detail for item in items if not item.ok]
    assert "可以继续跑" in ab.format_health(items)


def test_开局自检_没有RUN行会红但角色仍可判() -> None:
    text = "\n".join(_month(sec) for sec in (1, 2, 3)).replace("AB;ROLE;RUS;", "AB;ROLE;A;")
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    assert not next(item for item in items if item.name.startswith("RUN")).ok
    assert next(item for item in items if item.name.startswith("角色可判")).ok
    assert "现在就停下" in ab.format_health(items)


def test_开局自检_玩家就是主角会红() -> None:
    # 口径在阶段 3 中途反过来：玩家扮演主角国家时那个国家不是 AI，测不出「AI 自己改革」
    text = _healthy_text()
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    player = next(item for item in items if item.name.startswith("PLAYER"))
    assert not player.ok
    assert "它不是 AI" in player.detail


def test_开局自检_B组没有冲击会红() -> None:
    text = _healthy_text(b_shock="no")
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    shock = next(item for item in items if item.name.startswith("SHOCK"))
    assert not shock.ok
    assert "B" in shock.detail


def test_开局自检_A组不该有冲击() -> None:
    text = "\n".join(
        [
            _segment("A", 4, cells={"shock": "yes"}),
            _segment("B", 4, first_sec=20, cells={"shock": "yes"}),
        ]
    )
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    shock = next(item for item in items if item.name.startswith("SHOCK"))
    assert not shock.ok
    assert "A 段不该有冲击" in shock.detail


def test_开局自检_零月度块会红() -> None:
    # 点了决议但一个月都还没跨过 → 只有 RUN 行，没有月度块
    text = "ZZPROBE AB;RUN;A"
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    assert not next(item for item in items if item.name == "观测在流动").ok


def test_开局自检_error日志里我们的命名空间会红() -> None:
    text = _healthy_text()
    error = (
        "[10:00:01][jomini_effect.cpp:542]: Unknown effect sitai_ru_defeat_shock at "
        "common/scripted_effects/zz_probe_ab_effects.txt:12"
    )
    items = ab.health(ab.analyze_text(text), text=text, error_text=error)
    bad = next(item for item in items if "报错" in item.name)
    assert not bad.ok
    assert "sitai_" in bad.detail


def test_开局自检_正常自报行不触发命名空间扫描() -> None:
    """我们每条正常自报行的前缀里就有 `zz_probe_ab_...`：命名空间这一类只能扫 error 日志。"""
    text = _healthy_text()
    assert "zz_probe" in text
    items = ab.health(ab.analyze_text(text), text=text, error_text="")
    assert next(item for item in items if "报错" in item.name).ok


def test_空日志不炸() -> None:
    result = ab.analyze_text("")
    assert result.samples == ()
    assert result.runs == ()
    assert result.verdict == "insufficient"
    assert "无法判定" in ab.format_report(result)
    items = ab.health(result, text="", error_text="")
    assert not next(item for item in items if item.name == "观测在流动").ok


def test_日志目录不存在时返回空() -> None:
    missing = Path("Z:/不存在的目录")
    assert ab.log_files(missing) == []
    assert ab.error_files(missing) == []


def test_分析整个目录含轮转副本(tmp_path: Path) -> None:
    (tmp_path / "debug.log").write_text(_segment("A", 3), encoding="utf-8")
    (tmp_path / "debug.1.log").write_text(
        _segment("B", 3, first_sec=20, cells={"shock": "yes"}), encoding="utf-8"
    )
    (tmp_path / "error.log").write_text("", encoding="utf-8")
    result = ab.analyze(tmp_path)
    assert sorted(result.roles) == ["A", "B"]
    assert result.months == 6
    assert ab.error_files(tmp_path) == [tmp_path / "error.log"]


# ── CLI（`--json` / `--health` 的退出码）──────────────────────


def test_CLI的json输出(tmp_path: Path) -> None:
    text = "\n".join([_segment("A", 12), _segment("B", 12, first_sec=20, cells={"shock": "yes"})])
    (tmp_path / "debug.log").write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["ab", "--json", "--logs", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == "no_diff"
    assert payload["roles"]["B"]["shock_rate"] == 1.0
    assert [segment["role"] for segment in payload["segments"]] == ["A", "B"]


def test_CLI的健康检查不过时退出码1(tmp_path: Path) -> None:
    # A 组出现了冲击 = SHOCK 自检不过（P13：这类失败在脚本侧毫无报错）
    (tmp_path / "debug.log").write_text(_segment("A", 4, cells={"shock": "yes"}), encoding="utf-8")
    result = runner.invoke(app, ["ab", "--health", "--logs", str(tmp_path)])
    assert result.exit_code == 1, result.output
    assert "开局自检" in result.output


def test_样本不足不许宣判() -> None:
    """实测踩过的 bug：B 组刚点完决议才 1 个月，分析器就给出「H2 不成立：意图层是薄壳」。

    那是**假结论** —— 冲击的合法性 -20 要等月度脉冲落到读数上，改革窗口与法律转换是数月尺度。
    两组的观测窗口都够长之前，一律「无法判定」。
    """
    text = "\n".join([_timeline("A", [{}] * 20), _timeline("B", [{"shock": "yes"}] * 2)])
    result = ab.analyze_text(text)
    assert result.verdict == "insufficient"
    assert "无法判定" in ab.format_report(result)


# ── 臂阶梯：一局里的 A → B → B2（RUN;B2 与两处处理的对照）──────


def test_一局之内三臂被切开且各算各的() -> None:
    """`RUN` 行在一局里出现三次：三段必须各自成段、各自的读数分开算。"""
    result = ab.analyze_text(_ladder())
    assert result.runs == ("A", "B", "B2")
    assert [len([s for s in result.samples if s.role == role]) for role in ab.ROLES] == [12, 24, 12]
    assert result.roles["B"].shock_rate == 1.0
    assert result.roles["A"].shock_rate == 0.0
    assert result.roles["B2"].shock_rate == 1.0  # B2 段继承冲击
    assert result.roles["B"].input_rate == 0.0
    assert result.roles["B2"].input_rate == 1.0
    assert len(result.segments) == 3
    assert [segment.role for segment in result.segments] == ["A", "B", "B2"]


def test_判定只看冲击步缺B2不影响宣判() -> None:
    """B2 是追加处理段：还没跑到第 37 个月的局，A/B 的差分照样要判得出来。"""
    text = "\n".join(
        [
            _timeline("A", [{}] * 12),
            _timeline("B", [{"shock": "yes", "je": "active"}] * 12),
        ]
    )
    result = ab.analyze_text(text)
    assert "B2" not in result.roles
    assert result.verdict == "g2_preliminary"
    assert result.input_behaviour_diffs == ()
    assert result.input_strategy_diffs == ()
    assert "B2 臂还没有观测" in ab.format_report(result)


def test_改革侧输入段单独报且与冲击步分开() -> None:
    """B2 段追加改革侧输入之后读数变了 —— 这一段必须**单独**出现在第③节。"""
    text = _ladder(
        b_cells={"je": "inactive", "poli": "reactionary_agenda"},
        b2_cells={"je": "active", "poli": "progressive_agenda"},
    )
    result = ab.analyze_text(text)
    # ① 冲击步：A 与 B 的 JE 都没开 → 行为层无差分（判定不成立）
    assert not result.behaviour_changed
    assert result.roles["B2"].je_share == 1.0
    # ③ 输入步：B → B2 两层都动了
    assert _diff(result.input_behaviour_diffs, "改革窗口 JE").changed
    assert _diff(result.input_strategy_diffs, "POLI").changed
    assert result.input_changed
    report = ab.format_report(result)
    assert "③ 改革侧输入段差分（B → B2）" in report
    assert report.index("① 行为层差分") < report.index("③ 改革侧输入段差分")
    assert "改革侧输入让读数**动了**" in report


def test_改革侧输入段样本不足不宣判() -> None:
    """同一条纪律对每一步处理都成立：B2 只有 3 个月时不解释它的读数。"""
    result = ab.analyze_text(_ladder(b2_months=3))
    assert result.months_of("B2") == 3
    assert f"只有 3 个月（< {ab.VERDICT_MIN_MONTHS}）" in ab.format_report(result)


def test_改革侧输入没落上时不解释无差分() -> None:
    """B2 段没有 INPUT = 那一处输入根本没施加 → 报告要**先**说这件事。"""
    text = _ladder(b2_cells={"input": "no"})
    result = ab.analyze_text(text)
    assert result.roles["B2"].input_rate == 0.0
    report = ab.format_report(result)
    assert "INPUT" in report
    assert "读数**没有动**" in report


def test_老归档没有INPUT与LEG行照样能分析() -> None:
    """阶段 3 的结论来自加诊断行之前跑的局 —— 那批归档不许因为新行而作废。"""
    text = "\n".join(
        [
            _timeline("A", [{}] * 12, skip=LEGACY_SKIP),
            _timeline("B", [{"shock": "yes", "je": "active"}] * 12, skip=LEGACY_SKIP),
        ]
    )
    result = ab.analyze_text(text)
    assert result.unpaired == 0, "缺 INPUT/LEG 不算残缺块（它们是可选诊断行）"
    assert result.months == 24
    assert result.roles["A"].input_rate == 0.0
    assert result.roles["A"].bands == ()
    assert result.verdict == "g2_preliminary"
    assert "没有 `LEG` 诊断行" in ab.format_report(result)


# ── 合法性档位（世界层诊断）──────────────────────────────────


def test_合法性档位按月统计且取最久的一档() -> None:
    specs = [{"leg": "b80"}] * 3 + [{"leg": "b70"}] * 5 + [{"leg": "b55"}]
    behaviour = ab.analyze_text(_timeline("B", specs)).roles["B"]
    assert [(band.band, band.months) for band in behaviour.bands] == [
        ("b55", 1),
        ("b70", 5),
        ("b80", 3),
    ]
    assert behaviour.band_share("b70") == pytest.approx(5 / 9)
    assert behaviour.band_share("b60") == 0.0
    # 最久的一档是 b70（不是按档位顺序排在最前的 b55）
    assert behaviour.leg_top is not None
    assert behaviour.leg_top.band == "b70"


def test_合法性档位进报告() -> None:
    text = "\n".join(
        [
            _timeline("A", [{}] * 12),
            _timeline("B", [{"shock": "yes", "leg": "b75"}] * 12),
        ]
    )
    report = ab.format_report(ab.analyze_text(text))
    assert "合法性档位" in report
    assert "b75 12（100%）" in report


def test_未知档位不会被吞掉() -> None:
    """探针将来加档位（或手写一个错值）时，读数照样出现在分布里。"""
    behaviour = ab.analyze_text(_timeline("B", [{"leg": "b99"}])).roles["B"]
    assert [band.band for band in behaviour.bands] == ["b99"]


# ── INPUT 自检（B2 段该有、A/B 段该没有）─────────────────────


def test_INPUT自检_阶梯局全绿() -> None:
    result = ab.analyze_text(_ladder())
    items = ab.health(result, text="", error_text="")
    assert all(item.ok for item in items), [item.detail for item in items if not item.ok]


def test_INPUT自检_B2段缺输入会红() -> None:
    result = ab.analyze_text(_ladder(b2_cells={"input": "no"}))
    items = ab.health(result, text="", error_text="")
    item = next(item for item in items if item.name.startswith("INPUT"))
    assert not item.ok
    assert "B2" in item.detail
    assert "sitai_ru_reform_input" in item.detail


def test_INPUT自检_A段不该有输入() -> None:
    result = ab.analyze_text(_ladder(a_cells={"input": "yes"}))
    items = ab.health(result, text="", error_text="")
    item = next(item for item in items if item.name.startswith("INPUT"))
    assert not item.ok
    assert "合并成一次施加" in item.detail


def test_冲击自检按阶梯的起始月说期望() -> None:
    """期望值不再写死"点完决议后" —— B 说第 13 月、B2 说第 37 月。"""
    result = ab.analyze_text(_ladder())
    text = ab.format_report(result)
    assert "第 13 月起 ≈100%" in text
    assert "第 37 月起 ≈100%" in text


def test_臂窗口按阶梯算() -> None:
    assert ab._arm_window("A") == "第 1–12 月"
    assert ab._arm_window("B") == "第 13–36 月"
    assert ab._arm_window("B2") == "第 37 月起"
    assert ab._arm_window(ab.ROLE_UNKNOWN) == "—"


def test_CLI的json输出带第二对照与档位(tmp_path: Path) -> None:
    (tmp_path / "debug.log").write_text(_ladder(), encoding="utf-8")
    result = runner.invoke(app, ["ab", "--json", "--logs", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["roles"]["B2"]["input_rate"] == 1.0
    assert payload["roles"]["B2"]["bands"][0]["band"] == "b80"
    assert payload["input_behaviour_diffs"], payload
    assert [segment["role"] for segment in payload["segments"]] == ["A", "B", "B2"]
