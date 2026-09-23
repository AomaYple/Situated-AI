"""探针脚本 `tools/probe/stage3_rerun.py` 的看守（B78 点名过的那类缺口）。

为什么单独一条
--------------
`tools/probe/*` 下的脚本**一直没有人守**：静态检查不读它们、门禁不跑它们，
所以"改一处、别处 `NameError`"这种事只会在**实跑到那一步**才炸（B78 实测踩过：
一次整段替换把夹在中间的 `wait_months` 一起切掉了，ruff/mypy/pytest 全绿）。
这里至少把**新增的那一小块**（引擎判定读数）钉住 —— 它是实机流程里唯一
"读引擎写的文件"的地方，读错了不会有人发现。

怎么加载
--------
`tools/probe/` 不是包（没有 `__init__.py`），所以按路径 import。
它导入时只做 `sys.path.insert` 与 `import pdx`，没有副作用。
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from typing import TYPE_CHECKING

import pytest

from pdx import config, modgen
from pdx import game_auto as ga

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

pytestmark = pytest.mark.unit

_PROBE = config.REPO / "tools" / "probe" / "stage3_rerun.py"

_OK_XML = """<?xml version="1.0" ?>
<testsuites tests="2" failures="0" errors="0">
\t<testsuite name="tools/scripted_tests/sitai_ab.txt" tests="2" failures="0" errors="0">
\t\t<testcase classname="reform_window_opens" name="" />
\t\t<testcase classname="law_changed" name="" />
\t</testsuite>
</testsuites>
"""


def _probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("probe_stage3_rerun", _PROBE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def 探针(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """加载探针模块，并把它的成绩单/日志路径指到临时目录。"""
    probe = _probe()
    xml = tmp_path / "abc_GameTests_testoutput.xml"
    log = tmp_path / "error.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(ga, "error_log_path", lambda: log)
    monkeypatch.setattr(ga, "TESTS_TXT", tmp_path / "tests.txt")
    monkeypatch.setattr(ga, "testoutput_files", lambda: [xml] if xml.is_file() else [])
    return probe, xml, log


def test_没有成绩单时如实说没判定(探针) -> None:
    """**没判定 ≠ 判了通过**：这一局可能在套件判完之前就被杀了。"""
    probe, _xml, _log = 探针
    out = probe.engine_verdict()
    assert out["套件跑没跑"] is False
    assert "没有成绩单" in str(out["引擎判定"])


def test_有成绩单时给引擎的判定(探针) -> None:
    probe, xml, _log = 探针
    xml.write_text(_OK_XML, encoding="utf-8")
    out = probe.engine_verdict()
    assert out["套件跑没跑"] is True
    assert out["引擎判定"] == "通过"
    assert out["suite_count"] == 1
    assert out["suite_ok"] is True


def test_我们命名空间里有报错时判不通过(探针) -> None:
    probe, xml, log = 探针
    xml.write_text(_OK_XML, encoding="utf-8")
    log.write_text("common/scripted_effects/sitai_bv_alignment_effects.txt:3: unknown\n", "utf-8")
    out = probe.engine_verdict()
    assert out["引擎判定"] == "不通过"
    assert out["suite_our_errors"] == 1


def test_读成绩单要在挪走它之前(探针) -> None:
    """收尾会把成绩单移去临时目录 —— 所以读数必须发生在 `quarantine_*` **之前**。

    这条钉的是顺序，不是函数：`main()` 里 `report["verdict"]` 必须排在 `finally` 之前。
    """
    source = _PROBE.read_text(encoding="utf-8")
    assert source.index('report["verdict"] = engine_verdict()') < source.index(
        "moved = quarantine_test_artifacts()"
    ), "读数被排到收尾之后了 —— 那样永远读不到成绩单"


# ── 认主语：`TARGET` 行不可靠，`ROLE;<TAG>` 才是每月都有的那条 ──────────


def test_有TARGET行时按它认主语(探针) -> None:
    probe, _xml, _log = 探针
    ours = ['…: ZZPROBE AB;TARGET;pe_great_game"', "…: ZZPROBE AB;ROLE;PER;波斯"]
    assert probe._subject_archive(ours) == "pe_great_game"


def test_没有TARGET行时按ROLE的tag反查(探针) -> None:
    """`TARGET` 只在武装那一刻写一次，且**可能落在轮转文件里**（实测 `debug.1.log` 有、
    `debug.log` 里 0 条）—— 只看当前那份就会误判成"这一行没落"。

    所以还要有一条不依赖它的路：`ROLE;<TAG>` → `[archive].country`（数据源里的事实）。
    """
    probe, _xml, _log = 探针
    ours = ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"]
    assert probe._subject_tag(ours) == "BAV"
    assert probe._subject_archive(ours) == "bv_alignment"


def test_两条路都没有时不猜(探针) -> None:
    probe, _xml, _log = 探针
    assert probe._subject_archive(["…: ZZPROBE AB;SHOCK;yes;巴伐利亚"]) == ""


def test_一个国家对上多份档案时不认(探针, monkeypatch: pytest.MonkeyPatch) -> None:
    """抽象没保证「一国一档案」—— 真撞上就返回空串，**不挑第一个**。"""
    probe, _xml, _log = 探针
    real = list(probe.modgen.load_all())
    bav = next(a for a in real if a.country == "BAV")
    monkeypatch.setattr(probe.modgen, "load_all", lambda: [*real, bav])
    assert probe._subject_archive(["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"]) == ""
    assert probe._subject_archive(["…: ZZPROBE AB;TARGET;bv_alignment"]) == "bv_alignment"


def test_反查得到的档案真的带reform_law(探针) -> None:
    """兜底那条路必须能给出**可判**的结果，否则加它没意义。"""
    probe, _xml, _log = 探针
    out = probe._law_reading(["law_tenant_farmers"], ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"])
    assert out.get("本档案盯的法（bv_alignment.[probe].reform_law）") == "law_tenant_farmers"
    assert out.get("✅ 那条法已不是现行法律（law_tenant_farmers）") is False


# ── 意图层：按档案声明的牌判（B86）────────────────────────────────────


def test_声明的牌出现过就算动过(探针) -> None:
    probe, _xml, _log = 探针
    out = probe._card_reading(
        ["ai_strategy_conservative_agenda", "ai_strategy_progressive_agenda"],
        ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"],
    )
    assert out.get("本档案盯的牌（bv_alignment.[probe].reform_card）") == (
        "ai_strategy_progressive_agenda"
    )
    assert out.get("✅ 那张牌挂上过（ai_strategy_progressive_agenda）") is True


def test_没声明牌就不判并说明理由(探针, monkeypatch: pytest.MonkeyPatch) -> None:
    """留空是正当结论（那张牌对该档案没有判别力）⇒ 不判，而不是报 False。"""
    probe, _xml, _log = 探针
    real = list(probe.modgen.load_all())
    # ⚠️ 不能写成 `[replace(bv, probe=None), *real[1:]]` —— 那会按 bv 的位置**复制/丢掉**别的档案，
    # 而"一个国家对上多份档案"会让 `_subject_archive` 按设计返回空串（不猜），测试就测错了东西。
    monkeypatch.setattr(
        probe.modgen,
        "load_all",
        lambda: [dataclasses.replace(a, probe=None) if a.id == "bv_alignment" else a for a in real],
    )
    out = probe._card_reading(
        ["ai_strategy_progressive_agenda"], ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"]
    )
    key = next(iter(out))
    assert "不判" in key, out
    assert "bv_alignment" in str(out[key])


def test_一行牌读数都没有时报读不到而不是报没挂上(探针) -> None:
    """B87 的另一半：`STRATEGY` 行**一条都没有**时，不许报成"那张牌没挂上过"。

    探针那条链是 `if / else_if … / else`，链尾必落一行 ⇒ 空列表只可能是
    "根本没读到这类行"（老归档、探针没盯这个国家、日志被剪过）。
    报成 False 就是**假否定**：读数是"缺"，报出来却像"否"。
    """
    probe, _xml, _log = 探针
    out = probe._card_reading([], ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"])
    key = next(iter(out))
    assert "读不到" in key, out
    assert "这不是「牌没挂上」" in str(out[key]), out
    assert not any("挂上过" in k for k in out), "空读数不该走「挂上过」那条判据"


def test_牌读数是none时按不出现处理(探针) -> None:
    """链尾的 `none` / `ai_strategy_default` 是**真读数**：它们出现时就是"没挂着那张牌"。"""
    probe, _xml, _log = 探针
    out = probe._card_reading(["none"], ["…: ZZPROBE AB;ROLE;BAV;巴伐利亚"])
    assert out.get("✅ 那张牌挂上过（ai_strategy_progressive_agenda）") is False


def test_分析器不再写死进步牌(探针) -> None:
    """B86 的根：写死的那一版对**开局就挂着它**的国家必然假真。

    这条钉的是「分析器里不许再出现写死的牌名」—— 判据只在数据源的 `[probe].reform_card` 里。
    ⚠️ 只查**代码**，不查 docstring（那段解释里当然要提这张牌，它是反例本身）。
    """
    source = _PROBE.read_text(encoding="utf-8")
    body = source.split("def _card_reading", 1)[1].split("\ndef ", 1)[0]
    code = body.split('"""', 2)[-1]
    assert "ai_strategy_progressive_agenda" not in code, (
        "`_card_reading` 的代码里又出现了写死的牌名 —— 那样巴西（开局就挂着它）会报假的「动过」"
    )


def _initial_agenda_cards(path: Path) -> dict[str, set[str]]:
    """`common/history/ai/00_strategy.txt` 里每个国家块内的 `set_strategy = ai_strategy_*_agenda`。

    ⚠️ 读的是**整份文件**、按缩进配对块（`c:XXX ?= {` → 条目 → `}`）——
    拿 `Select-String` 扫前几行的教训在 B85 那条纪律里（"只看一份得到的没有从来不是证据"）。
    """
    out: dict[str, set[str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        opened = _COUNTRY_BLOCK.match(line)
        if opened:
            current = opened.group(1)
            out.setdefault(current, set())
            continue
        if current is not None and line.strip() == "}":
            current = None
            continue
        if current is not None:
            found = _AGENDA_LINE.match(line)
            if found:
                out[current].add(found.group(1))
    return out


_COUNTRY_BLOCK = re.compile(r"^\s*c:([A-Z0-9]+)\s*\?=\s*\{")
_AGENDA_LINE = re.compile(r"^\s*set_strategy\s*=\s*(ai_strategy_\w*agenda)\b")


def test_开局牌的解析器本身可信(探针) -> None:
    """反向自检：解析器读出来的东西必须与原版文件对得上（否则下面那条等于没查）。"""
    strategy = config.GAME / "common" / "history" / "ai" / "00_strategy.txt"
    if not strategy.is_file():
        pytest.skip("没有游戏本体")
    cards = _initial_agenda_cards(strategy)
    assert "ai_strategy_reactionary_agenda" in cards["RUS"]
    assert "ai_strategy_conservative_agenda" in cards["AUS"]
    assert "ai_strategy_progressive_agenda" in cards["BRZ"]
    assert "SPA" not in cards
    assert "BAV" not in cards
    assert "BRZ" in cards, "巴西有 c: 块，这正是 B86 那个陷阱的来源"


def test_声明的牌不能是该国开局就有的(探针) -> None:
    """**B86 的机器化**：判据是「那张牌出现过」，所以声明一张**开局就挂着**的牌 = 假真。

    这正是收口清单那句「任何跨档案通用的判据都要问：它对别的档案是不是立刻为真」。
    巴西就是那个反例：`c:BRZ` 的初始政治牌里本来就有 `ai_strategy_progressive_agenda`
    ⇒ 那份档案必须**留空并在 why 里写明**。
    """
    strategy = config.GAME / "common" / "history" / "ai" / "00_strategy.txt"
    if not strategy.is_file():
        pytest.skip("没有游戏本体")
    initial = _initial_agenda_cards(strategy)
    bad = [
        f"{a.id}（{a.country}）声明了 {a.probe.reform_card}，而它开局就挂着这张牌"
        for a in modgen.load_all()
        if a.probe is not None
        and a.probe.reform_card
        and a.probe.reform_card in initial.get(a.country, set())
    ]
    assert not bad, (
        "声明的牌对该档案没有判别力（判据是「出现过」，开局就有 ⇒ 必然假真）：\n  "
        + "\n  ".join(bad)
    )


# ── 轮转日志的顺序（**一次真被读错过的 bug**）──────────────────────────


def test_轮转日志按时间从旧到新(探针, tmp_path: Path) -> None:
    """`debug.4 → debug.3 → debug.2 → debug.1 → debug.log`，**不是字典序**。

    实测踩过（2026-09-23 跑 `sp_empire_remnant`）：字典序是
    `[debug.1, debug.2, debug.3, debug.4, debug.log]` —— 当前那份排最后、次新的排最前，
    于是拼出来的文本时间顺序是错的。叠加下面那条 `RUN` 剪切之后，`debug.3/2/1` 整份被丢掉：
    **盘上 1,401 行自报，分析器只报了 402 行**，还报出一个假的「窗口 `inactive → active`」。
    """
    probe, _xml, _log = 探针
    for name in ("debug.4.log", "debug.3.log", "debug.2.log", "debug.1.log", "debug.log"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    (tmp_path / "debug.log.bak").write_text("不是日志", encoding="utf-8")
    got = [p.name for p in probe.debug_logs(tmp_path)]
    assert got == ["debug.4.log", "debug.3.log", "debug.2.log", "debug.1.log", "debug.log"]


def test_只有当前那份日志时也给得出来(探针, tmp_path: Path) -> None:
    probe, _xml, _log = 探针
    (tmp_path / "debug.log").write_text("x", encoding="utf-8")
    assert [p.name for p in probe.debug_logs(tmp_path)] == ["debug.log"]


def test_没有日志目录时给空表(探针, tmp_path: Path) -> None:
    probe, _xml, _log = 探针
    assert probe.debug_logs(tmp_path / "不存在") == []


def test_读数要报出被剪掉多少行(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只报「算进去多少」会让人以为那就是盘上的全部 —— 两个数都要报。"""
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        "\n".join(
            [
                '…: ZZPROBE AB;SHOCK;no;西班牙"',
                '…: ZZPROBE AB;RUN;B"',
                '…: ZZPROBE AB;SHOCK;yes;西班牙"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    cut = probe.analyze(only_after_arm=True)
    assert cut["盘上自报行数"] == 3
    assert cut["算进读数的行数"] == 1  # 只留 RUN;B 之后那一条
    whole = probe.analyze(only_after_arm=False)
    assert whole["算进读数的行数"] == 3
    assert whole["冲击读数（去重）"] == ["no", "yes"]


# ── 数值读数（2026-09-24，B88）────────────────────────────────────────
#
# 旧读数是**五档夹逼**（b55/b60/…），而夹逼量不出档内的变化 —— B88 问的正是
# 「我们的压力有没有把合法性抬起来一点」。探针改成记原版的 data function 数值，
# 这一组钉住解析与摘要。


def test_合法性数值逐月摘要(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        "\n".join(
            [
                '…: ZZPROBE AB;LEGV;61.4;土耳其"',
                '…: ZZPROBE AB;LEGV;55.0;土耳其"',
                '…: ZZPROBE AB;LEGV;52.5;土耳其"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    text = str(out["合法性数值（逐月）"])
    assert "61.4" in text, text
    assert "52.5" in text, text
    assert "最低 52.5" in text, text
    assert "最高 61.4" in text, text
    assert "3 个月" in text


def test_IG政治力量数值按IG分开报(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        "\n".join(
            [
                '…: ZZPROBE AB;CLOUTV;landowners;24.8%;土耳其"',
                '…: ZZPROBE AB;CLOUTV;landowners;21.3%;土耳其"',
                '…: ZZPROBE AB;CLOUTV;intelligentsia;18.0%;土耳其"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    # 数值格式：`%g` 会把 18.0 打成 18（读数里够用，且不假装有小数点精度）
    assert "24.8%" in str(out["IG 政治力量数值（landowners）"])
    assert "18%" in str(out["IG 政治力量数值（intelligentsia）"])


def test_读不出数值时不编一个0(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """data function 拼错时引擎会把 `[...]` 原样留在日志里 —— 那不算数值。

    报 0 是最坏的失败形态（"合法性跌到 0"看起来像个发现）；正确做法是**没有这一栏**。
    """
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        '…: ZZPROBE AB;LEGV;[THIS.GetCountry.GetGovernmentLegitimacy|v];土耳其"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    assert "合法性数值（逐月）" not in out
    assert out["分类计数"]["LEGV"] == 1, "行还是要数出来 —— 读不到与没记是两件事"


def test_数值摘要函数本身() -> None:
    probe = _probe()
    assert probe._series_summary([]) == "（没有数值读数）"
    assert probe._series_summary([1.0]) == "1 → 1（共 1 个月；最低 1、最高 1）"
    assert "→ 3%" in probe._series_summary([1.0, 2.0, 3.0], unit="%")


def test_两条同义读数里取能解析的那条(
    探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`LEGV`（不带格式指令）优先；它读不出来时退回 `LEGF`（带 `|v`）。

    带不带 `|v` 是**没验过的细节**，所以探针两条都记，这里由数据决定用哪条 ——
    一次实机是分钟级代价，不该为了省两行日志去赌。
    """
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        '…: ZZPROBE AB;LEGV;[THIS.GetCountry.GetGovernmentLegitimacy];土耳其"\n'
        '…: ZZPROBE AB;LEGF;47.2;土耳其"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    assert "47.2" in str(out["合法性数值（逐月）"]), out.get("合法性数值（逐月）")


def test_IG数值的两条同义读数同理(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        '…: ZZPROBE AB;CLOUTV;landowners;[…];土耳其"\n'
        '…: ZZPROBE AB;CLOUTP;landowners;23.5%;土耳其"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    assert "23.5%" in str(out["IG 政治力量数值（landowners）"])


def test_立法进度数值(探针, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe, _xml, _log = 探针
    log = tmp_path / "debug.log"
    log.write_text(
        "\n".join(['…: ZZPROBE AB;PROG;0.35;土耳其"', '…: ZZPROBE AB;PROG;0.10;土耳其"']),
        encoding="utf-8",
    )
    monkeypatch.setattr(probe, "DEBUG_LOG", log)
    out = probe.analyze(only_after_arm=False)
    assert "0.35" in str(out["立法进度数值"])
