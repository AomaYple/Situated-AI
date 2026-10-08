"""标准压力剧本（阶段 4 ④）的生成器 —— `pdx.stress_probe`。

为什么值得一组用例
------------------
这份剧本是 G-EXIT-3 能不能**分辨 0.5 ms** 的前提（`阶段4-结果.md` §六·补：非受控对照里
噪声比信号大 4 倍）。它一旦写错，**症状是沉默的**：

* tag 写错一个字母 ⇒ `c:XQZ ?= this` 永远不成立 ⇒ 那条压力**一次都不发生**，
  而脚本侧一个字都不报（B80 同族的失败长相）；
* 效果名写错 ⇒ 引擎只往 `error.log` 里写一句 `Unknown effect`，游戏照样跑；
* `dp_` 类型写错 ⇒ 博弈创建失败，同样静默。

所以这一组用例的核心不是"生成器能跑"，而是**生成的每一样东西在原版里都真的存在**：
tags / 效果名 / 博弈类型，逐条拿原版文件核。

自报与跑者（2026-09-25 起）另有两条：**自报行的形状**（本文件 `Test自报`）与
**跑者那条"两臂序列逐行相等"的断言 + B27 的第三臂**（`Test受控性断言与第三臂`，
按 `test_probe_stage3.py` 的先例用 importlib 加载 `tools/probe/perf_compare.py`）。
两条都**不碰真游戏**：喂合成序列/合成日志，判据在纯逻辑那一层。

覆盖边界（`t73` 写死，别再靠猜）
--------------------------------
本文件 **50 条不碰游戏树**（合成输入 ⇒ CI 全覆盖；其中 8 条是 `t36` 的隔离日志用例、
4 条是 `t12` 把三条静默路径逐条钉住的回归用例），
另有 **3 条集成用例**（共 **53** 条）
（`TestVanillaVocabulary`：逐条读 `config.GAME/common/**`，标了 `@pytest.mark.integration`）。
**CI 无游戏树 ⇒ 这 3 条跳过、不在覆盖内**；而跳过是**可见**的 ——
`pytest tests/test_stress_probe.py -q -rs` 的 summary 里逐条打出
`SKIPPED … 需要游戏树（config.GAME=… 不存在）…`（`t73` 改前只写「游戏目录不可用」：
既没路径、也没说后果 ⇒ 读的人容易以为覆盖是全的）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from typing import TYPE_CHECKING

import pytest

from pdx import config, mods, stress_probe

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

pytestmark = pytest.mark.unit

_NEEDS_GAME_REASON = (
    f"需要游戏树（config.GAME={config.GAME} 不存在）⇒ 无游戏的 CI 上这 3 条不跑、"
    "**不在覆盖内**；有游戏的机器上用 `-m integration` 跑它们"
)
_needs_game = pytest.mark.skipif(not config.GAME.is_dir(), reason=_NEEDS_GAME_REASON)


def _blocks(text: str, key: str) -> list[str]:
    """取出文本里**所有** `key = { … }` 块的原文（按花括号配对切，不靠缩进猜）。"""
    found: list[str] = []
    index = 0
    while True:
        index = text.find(f"{key} = {{", index)
        if index < 0:
            return found
        depth = 0
        for position in range(index, len(text)):
            if text[position] == "{":
                depth += 1
            elif text[position] == "}":
                depth -= 1
                if depth == 0:
                    found.append(text[index : position + 1])
                    index = position + 1
                    break
        else:
            raise AssertionError(f"{key} 的块没有闭合")


def _block(text: str, key: str) -> str:
    """第一个 `key = { … }` 块（多个时只取最靠前那个）。"""
    blocks = _blocks(text, key)
    assert blocks, f"文本里没有 {key} = {{ }} 块"
    return blocks[0]


_PERF = config.REPO / "tools" / "probe" / "perf_compare.py"


def _perf() -> ModuleType:
    """按路径加载 `tools/probe/perf_compare.py`（`tools/probe/` 不是包，没有 `__init__.py`）。

    ⚠️ **必须先注册进 `sys.modules`**：那份脚本里有 `@dataclass(frozen=True, slots=True)`，
    而 dataclasses 建类时要回查 `sys.modules[cls.__module__]` —— 不注册就得到
    `AttributeError: 'NoneType' object has no attribute '__dict__'`（实测踩过）。
    """
    name = "probe_perf_compare"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, _PERF)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _expected_report_lines() -> list[str]:
    """用例**自己**拼出应有的 45 行自报 —— **格式字面量写在这里**，不调生成器内部函数。

    拼错的表现是"用例红了"，而不是"生成器和用例一起错"（P8 那种"两处同一个错"）。
    45 = 大战 5 对 + 破产 8 国 + 革命潮 8 国 × 4 波。
    """
    wars = [
        f"ZZPROBE STRESS;WAR;{stress_probe.WAR_DATE};{initiator}>{target}"
        for initiator, target, _kind in stress_probe.WAR_PAIRS
    ]
    breaks = [
        f"ZZPROBE STRESS;BREAK;{stress_probe.BREAK_DATE};{tag}" for tag in stress_probe.BREAK_TAGS
    ]
    radicals = [
        f"ZZPROBE STRESS;RADICAL;{date};{tag}"
        for date in stress_probe.RADICAL_DATES
        for tag in stress_probe.RADICAL_TAGS
    ]
    return [*wars, *breaks, *radicals]


class Test自报:
    """自报行：形状（前缀/分类/波次/目标国）+ "每一行只由一个写死的国家说"。"""

    def test_格式写在模块docstring里(self) -> None:
        """口径页 §2.1③ 要的是"可机的自报" —— 格式必须**写死在代码里**，不是记在人脑里。"""
        doc = stress_probe.__doc__ or ""
        assert stress_probe.REPORT_PREFIX in doc
        assert "ZZPROBE AB" in doc  # 说明"与 ab_probe 同型、前缀不同"
        for kind in stress_probe.REPORT_KINDS:
            assert kind in doc, kind
        # 完整的一行示例（复制即用）必须在 docstring 里
        assert (
            stress_probe.report_line(stress_probe.KIND_BREAK, stress_probe.BREAK_DATE, "MEX") in doc
        )

    def test_三条压力各自逐波自报(self) -> None:
        text = stress_probe.effects_text()
        scanned = stress_probe.scan_report_lines(text)
        assert scanned.malformed == (), "生成物里出现了形状不对的自报行"
        expected = _expected_report_lines()
        assert len(expected) == 45
        assert sorted(scanned.lines) == sorted(expected)
        # 每一条**只出现一次**：多写一遍就是"这一波重复释放"的证据，先挡在生成侧
        for line in expected:
            assert text.count(line) == 1, line

    def test_每条自报都由一个写死的国家说(self) -> None:
        """发射点必须套在 `if = { limit = { c:<tag> ?= this } … }` 里，且 tag 与行一对一。

        为什么这条是**承重**的：效果**逐国**跑（`on_monthly_pulse_country`），没有守卫就会
        一个国家写一行 —— 国家数在两臂之间会随世界演化分叉 ⇒ 比对报**假**不等。
        """
        text = stress_probe.effects_text()
        expected: list[tuple[str, str]] = [
            (initiator, f"ZZPROBE STRESS;WAR;{stress_probe.WAR_DATE};{initiator}>{target}")
            for initiator, target, _kind in stress_probe.WAR_PAIRS
        ]
        expected += [
            (tag, f"ZZPROBE STRESS;BREAK;{stress_probe.BREAK_DATE};{tag}")
            for tag in stress_probe.BREAK_TAGS
        ]
        expected += [
            (tag, f"ZZPROBE STRESS;RADICAL;{date};{tag}")
            for date in stress_probe.RADICAL_DATES
            for tag in stress_probe.RADICAL_TAGS
        ]
        # 每一条自报的守卫 tag = 那一行自己说的那个国家（大战用发起国）
        for tag, line in expected:
            guarded = re.compile(
                rf"limit = \{{ c:{tag} \?= this \}}\n(?P<body>.*?)"
                rf'debug_log = "{re.escape(line)}"',
                re.DOTALL,
            )
            assert len(guarded.findall(text)) == 1, f"{line} 的守卫不唯一/缺失"
        # 守卫块的**总数**就是自报行数（45）⇒ 没有一行落在守卫外
        assert text.count('debug_log = "ZZPROBE STRESS;') == len(expected) == 45

    def test_大战与破产的施加与自报在同一个守卫里(self) -> None:
        """**行数 = 施加次数**：守卫 → 施加 → 自报，同一块、且施加在前（`t63`）。

        只有"施加与自报同块"才让"两臂序列相等"等于"施加次数相同"；分开写就只能证明
        "这一波落到了谁身上"，证明不了次数（那正是 `t50` 里断言偏弱的原因）。
        """
        text = stress_probe.effects_text()
        for initiator, target, _kind in stress_probe.WAR_PAIRS:
            line = f"ZZPROBE STRESS;WAR;{stress_probe.WAR_DATE};{initiator}>{target}"
            block = re.compile(
                rf"limit = \{{ c:{initiator} \?= this \}}\n"
                rf"\s*create_diplomatic_play = \{{.*?\n\s*\}}\n"
                rf'\s*debug_log = "{re.escape(line)}"',
                re.DOTALL,
            )
            assert len(block.findall(text)) == 1, line
        for tag in stress_probe.BREAK_TAGS:
            line = f"ZZPROBE STRESS;BREAK;{stress_probe.BREAK_DATE};{tag}"
            block = re.compile(
                rf"limit = \{{ c:{tag} \?= this \}}\n"
                rf"\s*add_treasury = {stress_probe.TREASURY_DRAIN}\n"
                rf'\s*debug_log = "{re.escape(line)}"'
            )
            assert len(block.findall(text)) == 1, line

    def test_破产波没有裸的施加语句(self) -> None:
        """回归钉：`t50` 点出的缺陷长相是 `c:MEX ?= { add_treasury = … }`（**缺守卫**）。

        `c:<tag> ?= { … }` 只换作用域、**不限制调用者** ⇒ 效果逐国跑时每个目标国被每一国
        各抽一次（每月约 N 次）。这条用例钉的就是"那种写法不许再出现"。
        """
        text = stress_probe.effects_text()
        assert "?= { add_treasury" not in text, "又出现了没有守卫的施加语句"
        statements = re.findall(r"^\s*add_treasury = ", text, re.MULTILINE)
        assert len(statements) == len(stress_probe.BREAK_TAGS), (
            "施加语句数应等于目标国数（每国恰好一条）"
        )
        # 每条施加都由**它自己那个 tag** 的守卫闸住（守卫写在施加之前、同一个块里）
        for tag in stress_probe.BREAK_TAGS:
            assert (
                f"limit = {{ c:{tag} ?= this }}\n"
                f"{stress_probe.TAB * 3}add_treasury = {stress_probe.TREASURY_DRAIN}\n"
            ) in text, tag

    def test_次数不同必须判不等(self) -> None:
        """同一波落到**同一国**、但次数不同 ⇒ 必须判不等，且差异信息里出现次数（`t63`）。"""
        once = [
            "ZZPROBE STRESS;BREAK;1837.7.1;MEX",
            "ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA",
        ]
        twice = [*once, "ZZPROBE STRESS;BREAK;1837.7.1;MEX"]
        diff = stress_probe.compare_report_sequences(once, twice)
        assert diff is not None, "次数不同必须判不等（旧版只比'落到哪国'，这条会漏）"
        assert "MEX" in diff.describe()
        assert "2 次" in diff.describe(), "差异信息里必须出现次数"
        assert stress_probe.describe_count_differences(once, twice) == [
            "'ZZPROBE STRESS;BREAK;1837.7.1;MEX'：vanilla 1 次 / ours 2 次"
        ]
        assert stress_probe.count_report_lines(twice)["ZZPROBE STRESS;BREAK;1837.7.1;MEX"] == 2

    def test_序列相等时通过_顺序无关(self) -> None:
        """同一月里各 tag 谁先写，取决于引擎遍历国家的顺序 —— 那不是"受的压"，不该判不等。"""
        lines = _expected_report_lines()
        # `t73`：`compare_report_sequences` 的声明是 `Sequence[str]`（`stress_probe.py:303`），
        # 原来传的是 `reversed(...)` 这个**迭代器** ⇒ mypy 报 inSignatures 不符（且它只是一次性可迭代）。
        assert stress_probe.compare_report_sequences(lines, list(reversed(lines))) is None

    def test_序列不等时报出第一处波次与两行(self) -> None:
        """两路：**少一行**（那一波没落地）与**多一行**，都要指出波次 + 给出那一行。"""
        # 规范序（排序后）里 `WAR` 那行排在 `BREAK` 之后 ⇒ 去掉它就是"短一截"的形态
        lines = [
            "ZZPROBE STRESS;BREAK;1837.7.1;MEX",
            "ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA",
        ]
        less = stress_probe.compare_report_sequences(lines, lines[:1])
        assert less is not None
        assert less.wave == "1837.1.1", "差异信息必须指出是哪一波"
        assert "少" in less.describe()
        assert lines[1] in less.describe(), "差异信息必须给出那一行本身"

        more = stress_probe.compare_report_sequences(lines[:1], lines)
        assert more is not None
        assert more.wave == "1837.1.1"
        assert "多出" in more.describe()
        assert lines[1] in more.describe()

    def test_多出来的那一波也被判出来(self) -> None:
        """整条 45 行的序列里少掉**革命潮**那一波 ⇒ 判不等且指出 1838.7.1。"""
        lines = _expected_report_lines()
        missing = "ZZPROBE STRESS;RADICAL;1838.7.1;RUS"
        diff = stress_probe.compare_report_sequences(
            lines, [line for line in lines if line != missing]
        )
        assert diff is not None
        assert diff.wave == "1838.7.1"
        assert "1838.7.1" in diff.describe()

    def test_形状不对的自报行不静默(self) -> None:
        """分类不认识 ⇒ 进 malformed；字段少一个 ⇒ 也进 malformed（都不许被丢掉）。"""
        text = (
            "ZZPROBE STRESS;BOGUS;1837.1.1;GBR\n"
            "ZZPROBE STRESS;WAR;not-a-date;GBR\n"
            "ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA\n"
        )
        scanned = stress_probe.scan_report_lines(text)
        assert scanned.lines == ("ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA",)
        assert len(scanned.malformed) == 2


class Test受控性断言与第三臂:
    """`perf_compare.py` 那条断言（受控 / 非受控）与 B27 的第三臂 —— **一条都不跑游戏**。"""

    def test_日志按轮转顺序读(self, tmp_path: Path) -> None:
        """轮转顺序 = `debug.2.log` → `debug.1.log` → `debug.log`（B85：字典序是错的）。"""
        perf = _perf()

        def logged(line: str) -> str:
            return f"[10:00:00][jomini_effect_impl.cpp:454]: file:12: {line}\n"

        (tmp_path / "debug.2.log").write_text(
            logged("ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA"), encoding="utf-8"
        )
        (tmp_path / "debug.1.log").write_text(
            logged("ZZPROBE STRESS;BREAK;1837.7.1;MEX"), encoding="utf-8"
        )
        (tmp_path / "debug.log").write_text(
            logged("ZZPROBE STRESS;RADICAL;1838.1.1;RUS"), encoding="utf-8"
        )
        scanned = perf.scan_stress_lines(tmp_path)
        assert list(scanned.lines) == [
            "ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA",
            "ZZPROBE STRESS;BREAK;1837.7.1;MEX",
            "ZZPROBE STRESS;RADICAL;1838.1.1;RUS",
        ]

    def test_两臂序列相等时判受控(self) -> None:
        perf = _perf()
        lines = _expected_report_lines()
        control = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": list(reversed(lines))},
            ]
        )
        assert control.ok is True
        assert control.pairs == 1
        assert "逐行相等" in control.describe()

    def test_两臂序列不等时失败且指出哪一波(self) -> None:
        perf = _perf()
        lines = _expected_report_lines()
        missing = "ZZPROBE STRESS;BREAK;1837.7.1;MEX"
        control = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {
                    "label": perf.OURS_LABEL,
                    "index": 1,
                    "stress_lines": [line for line in lines if line != missing],
                },
            ]
        )
        assert control.ok is False
        message = control.describe()
        assert "1837.7.1" in message
        assert missing in message
        assert perf.VANILLA_LABEL in message
        assert perf.OURS_LABEL in message

    def test_一条自报都没有时不算受控(self) -> None:
        """**空的受控不算受控**：两边都空时"相等"没有任何信息量（P13）。"""
        perf = _perf()
        control = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": []},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": []},
            ]
        )
        assert control.ok is False
        assert "没有压力落地" in control.describe()

    def test_形状不对的自报行让判决失败(self) -> None:
        perf = _perf()
        lines = _expected_report_lines()
        control = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {
                    "label": perf.OURS_LABEL,
                    "index": 1,
                    "stress_lines": lines,
                    "stress_malformed": ["ZZPROBE STRESS;BOGUS;1837.1.1;GBR"],
                },
            ]
        )
        assert control.ok is False
        assert "形状不对" in control.describe()

    def test_单臂空的话术指向真实原因(self) -> None:
        """t89 ①：只有**一臂**空时报错必须点名那一臂（不许说成"两臂都没有/剧本没挂上"）。"""
        perf = _perf()
        lines = _expected_report_lines()
        # ① vanilla 空、ours 有 ⇒ 不许退化成一笼统的"两臂一条都没有"
        vanilla_empty = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": []},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": lines},
            ]
        )
        assert vanilla_empty.ok is False
        message = vanilla_empty.describe()
        assert perf.VANILLA_LABEL in message
        assert "一条压力自报都没有" in message
        assert f"{perf.OURS_LABEL} 有 {len(lines)} 行" in message, "要写出另一臂落了多少行"
        assert "两臂一条压力自报都没有" not in message, "单臂空不许套两臂都空的话术"
        assert "不是剧本没挂上" in message
        # ② 反照：ours 空、vanilla 有 ⇒ 点名的换成 ours，且不是笼统的"序列不等"
        ours_empty = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": []},
            ]
        )
        assert ours_empty.ok is False
        message = ours_empty.describe()
        assert perf.OURS_LABEL in message
        assert "这一臂没跑出来" in message
        assert "没有可比的序列" in message
        # ③ 反照：两臂都空 ⇒ 仍是"没有压力落地"那条老话术（新分支不许把它吃掉）
        both_empty = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": []},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": []},
            ]
        )
        assert both_empty.ok is False
        assert "没有压力落地" in both_empty.describe()

    def test_形状漂移自带判定不靠调用方传键(self) -> None:
        """t89 ②：把调用方的 `stress_malformed` 键**去掉**，形状漂移照样判得出来。"""
        perf = _perf()
        lines = _expected_report_lines()
        drift = "ZZPROBE STRESS;BOGUS;1837.1.1;GBR"
        scan_key = perf.STRESS_SCAN_KEY
        # ① 报告自带块（跑者现在写的那个键）带漂移行 ⇒ 不需要任何额外键
        self_contained = perf.stress_control_verdict(
            [
                {
                    "label": perf.VANILLA_LABEL,
                    "index": 1,
                    scan_key: {"lines": lines, "malformed": []},
                },
                {
                    "label": perf.OURS_LABEL,
                    "index": 1,
                    scan_key: {"lines": lines, "malformed": [drift]},
                },
            ]
        )
        assert self_contained.ok is False
        assert "形状不对" in self_contained.describe()
        # ② 漂移行被混进 `stress_lines`（无自带块、也无 malformed 键）⇒ 逐行自核也要抓到
        smuggled = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": [*lines, drift]},
            ]
        )
        assert smuggled.ok is False
        assert "形状不对" in smuggled.describe()
        # ③ 反照：全合法、**没有任何** malformed 来源 ⇒ 不许因为"缺键"误红
        clean = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": lines},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": lines},
            ]
        )
        assert clean.ok is True
        assert "逐行相等" in clean.describe()

    def test_跑者把次数纳入比较(self) -> None:
        """`t63` 的要求：次数不同 ⇒ 判不等，且**失败信息里出现次数**（P13 不许静默降级）。"""
        perf = _perf()
        once = ["ZZPROBE STRESS;BREAK;1837.7.1;MEX"]
        twice = [*once, "ZZPROBE STRESS;BREAK;1837.7.1;MEX"]
        control = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": once},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": twice},
            ]
        )
        assert control.ok is False
        message = control.describe()
        assert "次数" in message
        assert "1 次" in message
        assert "2 次" in message
        # 反向：次数一样就判受控（不能把所有不等都推给"次数"）
        same = perf.stress_control_verdict(
            [
                {"label": perf.VANILLA_LABEL, "index": 1, "stress_lines": twice},
                {"label": perf.OURS_LABEL, "index": 1, "stress_lines": list(reversed(twice))},
            ]
        )
        assert same.ok is True

    def test_默认两臂与从前一致(self) -> None:
        perf = _perf()
        assert perf.arm_labels() == ("vanilla", "ours")
        assert perf.arm_labels(False) == (perf.VANILLA_LABEL, perf.OURS_LABEL)
        assert perf.arm_labels(True) == ("vanilla", "ours", "tempo")

    def test_第三臂flag与帮助文本(self) -> None:
        perf = _perf()
        parser = perf.build_parser()
        assert parser.parse_args([]).tempo_arm is False, "第三臂必须**默认关闭**"
        assert parser.parse_args(["--tempo-arm"]).tempo_arm is True
        help_text = parser.format_help()
        assert "--tempo-arm" in help_text
        assert "B27" in help_text, "帮助文本要写明用途（B27：把节奏杠杆的开销从混杂项里分离）"

    def test_三臂的臂名与产物路径互不冲突(self) -> None:
        perf = _perf()
        labels = perf.arm_labels(True)
        assert len(set(labels)) == 3
        assert len({str(perf.arm_csv_path(label, 1)) for label in labels}) == 3
        # 两臂的产物名与从前**一字不差**（改了就是改了既有产物）
        assert perf.arm_csv_path("vanilla", 2).name == "vanilla-2.csv"
        assert perf.arm_csv_path("ours", 3).name == "ours-3.csv"
        assert perf.arm_csv_path("tempo", 3).name == "tempo-3.csv"
        # 三条臂挂的 mod 目录也互不冲突，且各自挂对了东西
        assert len({perf.OURS_DST, perf.STRESS_DST, perf.TEMPO_DST}) == 3
        assert perf.arm_mods(perf.VANILLA_LABEL, [perf.STRESS_DST]) == [perf.STRESS_DST]
        assert perf.arm_mods(perf.OURS_LABEL, [perf.STRESS_DST])[-1] == perf.OURS_DST
        assert perf.arm_mods(perf.TEMPO_LABEL, [perf.STRESS_DST])[-1] == perf.TEMPO_DST

    def test_产物路径只有一处来源(self) -> None:
        """落盘必须走 `arm_csv_path()`（且**只在这里**拼名字）—— 换回就地拼字符串，
        第三臂就会与两臂**撞名覆盖**（后一局把前一局的 CSV 盖掉，报告里两臂读同一份）。"""
        source = _PERF.read_text(encoding="utf-8")
        assert "arm_csv_path(label, index)" in source
        assert source.count('f"{label}-{index}.csv"') == 1

    def test_壳mod只挂那一份defines且在部署边界加BOM(self, tmp_path: Path) -> None:
        perf = _perf()
        products = tmp_path / "产物"
        (products / "common" / "defines").mkdir(parents=True)
        (products / ".metadata").mkdir()
        (products / ".metadata" / "metadata.json").write_text(
            '{"supported_game_version": "1.14.4"}', encoding="utf-8"
        )
        tempo = products / "common" / "defines" / "sitai_x_tempo.txt"
        tempo.write_bytes(b"NAI = {\r\n\trandom_ai_accept = 1\r\n}\r\n")
        written = perf.write_tempo_shell(tmp_path / "shell", mod_root=products)
        rels = sorted(path.relative_to(tmp_path / "shell").as_posix() for path in written)
        assert rels == [".metadata/metadata.json", "common/defines/sitai_x_tempo.txt"]
        copied = tmp_path / "shell" / "common" / "defines" / "sitai_x_tempo.txt"
        assert copied.read_bytes() == b"\xef\xbb\xbfNAI = {\n\trandom_ai_accept = 1\n}\n"
        assert tempo.read_bytes() == b"NAI = {\r\n\trandom_ai_accept = 1\r\n}\r\n"
        assert (
            not (tmp_path / "shell" / ".metadata" / "metadata.json")
            .read_bytes()
            .startswith(b"\xef\xbb\xbf")
        )
        meta = json.loads(
            (tmp_path / "shell" / ".metadata" / "metadata.json").read_text(encoding="utf-8")
        )
        assert meta["supported_game_version"] == "1.14.4", "版本号要现读产物，不手抄"
        # 两条"别被当成本机 mod"的判据都要占上（`mods.py:185` 目录前缀 + `:203` id 前缀）
        assert perf.TEMPO_MOD_NAME.startswith(mods.PROBE_PREFIX)
        assert meta["id"].startswith(mods.OWN_MOD_ID_PREFIX)

    def test_压力剧本源码无BOM部署副本有BOM且临时目录清理(self, tmp_path: Path) -> None:
        perf = _perf()
        destination = tmp_path / "stress"
        written = perf.deploy_stress_probe(destination)
        assert written
        assert all(path.is_file() for path in written)
        game_files = [path for path in written if path.suffix.lower() in {".txt", ".yml"}]
        assert game_files
        assert all(path.read_bytes().startswith(b"\xef\xbb\xbf") for path in game_files)
        assert all(b"\r" not in path.read_bytes() for path in game_files)
        assert all(
            not path.read_bytes().startswith(b"\xef\xbb\xbf")
            for path in destination.rglob("*")
            if path.is_file() and path.suffix.lower() == ".json"
        )
        assert not list(tmp_path.glob("sitai-stress-source-*"))

    def test_没有tempo产物时报错不静默(self, tmp_path: Path) -> None:
        """仓库没生成 `[tempo]` 产物时装空壳 ⇒ 第三臂变成"原版 + 空气"，读数却看着正常。"""
        perf = _perf()
        empty = tmp_path / "空产物"
        (empty / "common" / "defines").mkdir(parents=True)
        (empty / ".metadata").mkdir()
        (empty / ".metadata" / "metadata.json").write_text(
            '{"supported_game_version": "1.14.4"}', encoding="utf-8"
        )
        with pytest.raises(RuntimeError, match="tempo defines"):
            perf.write_tempo_shell(tmp_path / "shell", mod_root=empty)

    def test_仓库产物里真有那一份tempo(self) -> None:
        perf = _perf()
        sources = perf.tempo_defines_sources()
        assert sources, "仓库产物里没有 *_tempo.txt —— 先跑 `v3 modgen`"
        assert all(path.name.endswith("_tempo.txt") for path in sources)


class TestGeneration:
    def test_三件产物齐全(self) -> None:
        assert set(stress_probe.files()) == {
            ".metadata/metadata.json",
            "common/scripted_effects/zz_stress_effects.txt",
            "common/on_actions/zz_stress_on_actions.txt",
        }

    def test_三条压力都在效果里(self) -> None:
        text = stress_probe.effects_text()
        assert text.count("create_diplomatic_play = {") == len(stress_probe.WAR_PAIRS)
        assert "add_radicals_in_state" in text
        assert re.search(rf"add_treasury = {stress_probe.TREASURY_DRAIN}", text)

    def test_每个压力点都有日期与只做一次的标记(self) -> None:
        text = stress_probe.effects_text()
        for date in (stress_probe.WAR_DATE, stress_probe.BREAK_DATE, *stress_probe.RADICAL_DATES):
            assert f'game_date > "{date}"' in text
        # 每个 fired 标记必须**既写又读**（只写不读 = 每次脉冲都做一遍）
        for var in ("zz_stress_war_fired", "zz_stress_break_fired", "zz_stress_radicals_1"):
            assert f"set_variable = {{ name = {var} value = 1 }}" in text
            assert f"NOT = {{ has_variable = {var} }}" in text

    def test_每月脉冲走官方追加配方_块内不写效果调用(self) -> None:
        """`t73`：这条原来把**坏形状**钉成了"对的"（`t64` 侦察局把它撞出来了）。

        引擎原话：`Unexpected token: zz_stress_tick, near line: 6` —— 那一局钩子**一次都没挂上**
        （0 行 `ZZPROBE STRESS;`）。官方配方 = **转调**：
        `on_monthly_pulse_country = { on_actions = { <我们的 on_action> } }`，
        并在**同一份文件里**定义 `<我们的 on_action> = { effect = { … } }`。
        """
        text = stress_probe.on_actions_text()
        # ① 只碰 `on_monthly_pulse_country` 这一个**原版键**；不覆盖原版文件（F2：R3 禁用）
        assert re.findall(r"^on_[a-z_]+ = \{", text, re.MULTILINE) == [
            "on_monthly_pulse_country = {"
        ]
        original = _block(text, "on_monthly_pulse_country")
        # ② 原版块里**不许**出现脚本效果调用（就是那次实机红的形状）
        assert stress_probe.TICK_EFFECT not in original, (
            "on_action 块里直接写脚本效果调用 ⇒ 引擎报 Unexpected token，整份文件被拒"
        )
        # ③ 原版块里只许放官方那五种顶层键（我们走的是 `on_actions` 转调）
        assert re.findall(r"^\t(\w+) = ", original, re.MULTILINE) == ["on_actions"]
        # ④ 转调目标**在同一份文件里**定义，且它内部用 `effect` 块调脚本效果
        target = _block(text, stress_probe.TICK_ON_ACTION)
        assert re.findall(r"^\t(\w+) = ", target, re.MULTILINE) == ["effect"]
        assert f"{stress_probe.TICK_EFFECT} = yes" in target
        # ⑤ 整份文件只允许**一个** effect 键：第二个会盖掉原版 effect（more than one 'effect'）
        assert len(re.findall(r"^\teffect = \{", text, re.MULTILINE)) == 1

    def test_全部仓库文本无BOM(self, tmp_path: Path) -> None:
        stress_probe.write(tmp_path)
        assert not (
            (tmp_path / "common/scripted_effects/zz_stress_effects.txt")
            .read_bytes()
            .startswith(b"\xef\xbb\xbf")
        )
        raw = (tmp_path / ".metadata/metadata.json").read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        json.loads(raw.decode("utf-8"))

    def test_探针metadata的版本现读产物(self) -> None:
        """`t50` 报的风险、`t63` 修：写死 `1.14.3` 而产物是 `1.14.4`。

        症状是"启动器可能干脆不挂这份探针" ⇒ **0 行自报** ⇒ 白烧一局实机窗口。
        判据：探针元数据里那一格 == 仓库产物的那一格（同一个来源），且不再是写死的旧值。
        """
        product_version = stress_probe.mod_game_version()
        text = stress_probe.metadata_text()
        assert json.loads(text)["supported_game_version"] == product_version
        if product_version != "1.14.3":
            assert "1.14.3" not in text, "又写死了旧版本号"

    def test_探针metadata可指向合成产物(self, tmp_path: Path) -> None:
        root = tmp_path / "产物"
        (root / ".metadata").mkdir(parents=True)
        (root / ".metadata" / "metadata.json").write_text(
            '{"supported_game_version": "9.9.9"}', encoding="utf-8"
        )
        assert stress_probe.mod_game_version(root) == "9.9.9"
        assert json.loads(stress_probe.metadata_text(root))["supported_game_version"] == "9.9.9"

    def test_探针metadata读不到产物时报错不静默(self, tmp_path: Path) -> None:
        """读不到就报错（P13）：猜一个版本号写进去，症状只会在启动器那边出现。"""
        with pytest.raises(RuntimeError, match=r"metadata\.json"):
            stress_probe.mod_game_version(tmp_path / "空产物")

    def test_两次生成逐字节一致(self, tmp_path: Path) -> None:
        """P8：同样的输入 → 同样的产出（压力剧本要能重放，产出就不能抖）。"""
        a, b = tmp_path / "a", tmp_path / "b"
        stress_probe.write(a)
        stress_probe.write(b)
        for rel in stress_probe.files():
            assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel

    def test_落点在用户mod目录且带探针前缀(self) -> None:
        """`zz_` 前缀 ⇒ `pdx.mods.discover_mods()` 会排除它（它不算"本机装了哪些 mod"）。"""
        assert stress_probe.MOD_NAME.startswith("zz_")
        assert stress_probe.dest().parent == config.LOCAL_MODS

    def test_每个if块第一句都是limit_没有裸条件(self) -> None:
        """`t73` 修的缺陷②：③ 革命潮块少了 `limit = {` ⇒ 8 行 `Unknown effect c:GBR`（引擎原话）。

        定位一律按**内容**锚：引擎对 `scripted_effects` 报的行号偏移不恒定（本文件实测 Δ=5，B84 未查）。
        """
        lines = stress_probe.effects_text().splitlines()
        bare: list[tuple[int, str]] = []
        for index, line in enumerate(lines):
            if line.strip() != "if = {":
                continue
            first = next((item.strip() for item in lines[index + 1 :] if item.strip()), "")
            if not first.startswith("limit = {"):
                bare.append((index + 1, first))
        assert not bare, f"这些 if 块第一句不是 limit = {{（裸条件会被当效果读）：{bare}"

    def test_革命潮的8个tag必须收进OR_平铺进limit会恒假(self) -> None:
        """`t73` 的 F2（第 4 次修订）：判据必须落在**语义**上，不是"有 8 条比较"。

        `limit` 是**与** ⇒ 八条平铺 =「当前国同时是这 8 个 tag」⇒ **恒假** ⇒ 自报 0 行、
        `add_radicals_in_state` 一次都不执行 —— 引擎**不报错**的那种安静失败
        （实机实测：首波只到 WAR×5、RADICAL = 0 vs 预期 8；`error.log` 里我们文件 0 行也掩盖不了它）。
        正确写法是 `limit = { OR = { …8 条… } }`：每国脉冲各命中一次 ⇒ 每波正好 8 行。
        """
        text = stress_probe.effects_text()
        hits = [
            block
            for block in _blocks(text, "limit")
            if all(f"c:{tag} ?= this" in block for tag in stress_probe.RADICAL_TAGS)
        ]
        assert hits, "找不到一个同时收下 8 个 RADICAL_TAGS 的 limit 块"
        guard = hits[0]
        assert "OR = {" in guard, "8 个 tag 必须收进 OR（平铺进 limit = 与 ⇒ 恒假）"
        or_block = _block(guard, "OR")
        for tag in stress_probe.RADICAL_TAGS:
            assert f"c:{tag} ?= this" in or_block, f"{tag} 不在 OR 里"
        outside = guard.replace(or_block, "")
        assert "?= this" not in outside, "OR 外面还有裸的 tag 比较 ⇒ 又变回 AND（恒假）"

    def test_抽干的额度比原版最重的那一处还重(self) -> None:
        """剧本要的是**一定**进违约：比原版 `paris_commune_events.txt:243` 的 −100000 再重。

        （`t73` 从 `TestVanillaVocabulary` 移到这里：它**不读游戏树**，留在集成类里会让
        "CI 跳过"白白多一条 —— 移出来之后 CI 真的覆盖它。）
        """
        assert stress_probe.TREASURY_DRAIN <= -100000


@pytest.mark.integration
@_needs_game
class TestVanillaVocabulary:
    """**逐条拿原版文件核**（3 条，都读 `config.GAME/common/**`）：写错一个字母的症状是"静默不做"，不是报错。

    ⚠️ **CI 覆盖边界**（`t65` 的 F1、`t73` 收口）：这 3 条要**真实游戏树** ⇒ 无游戏时**跳过**，
    不在 CI 覆盖内；跳过是**可见**的（`_needs_game` 的 reason 里带 `config.GAME` 路径与后果，
    `-q -rs` 逐条打出）。它们**在 `t73` 之前就在**（不是 `t50`/`t63` 引入的），本文件新增用例一律合成。
    标 `integration` 是为了让选择器（`-m "not integration"`）能**显式**把它们分出去 ——
    不再靠 `skipif` 悄悄吃掉。
    """

    def _definitions(self) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "country_definitions").glob("*.txt")
        )

    def test_用到的国家tag原版都有(self) -> None:
        text = self._definitions()
        tags = {initiator for initiator, _t, _k in stress_probe.WAR_PAIRS}
        tags |= {target for _i, target, _k in stress_probe.WAR_PAIRS}
        tags |= set(stress_probe.BREAK_TAGS) | set(stress_probe.RADICAL_TAGS)
        missing = sorted(tag for tag in tags if not re.search(rf"^{tag} = \{{", text, re.MULTILINE))
        assert not missing, f"这些 tag 原版国家定义里没有：{missing}"

    def test_用到的博弈类型原版都有(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "diplomatic_plays").glob("*.txt")
        )
        kinds = {kind for _i, _t, kind in stress_probe.WAR_PAIRS}
        missing = sorted(
            kind for kind in kinds if not re.search(rf"^{kind} = \{{", text, re.MULTILINE)
        )
        assert not missing, f"这些博弈类型原版没有：{missing}"

    def test_用到的效果名原版都有人用(self) -> None:
        """`create_diplomatic_play` / `add_radicals_in_state` / `add_treasury` 都要有原版先例。"""
        text = "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "scripted_effects").glob("*.txt")
        )
        for name in ("create_diplomatic_play", "add_radicals_in_state", "add_treasury"):
            assert f"{name} = " in text, f"{name} 在原版 scripted_effects 里查无先例"


class Test隔离日志:
    """`t36`：隔离日志那条路的**证据蒸发路径**（B114 同族）；`t12` 逐条复现出**三条**。

    跑者自己那个隔离目录是 `%TEMP%\\v3_quarantine_perflogs`（`perf_compare.py:172` 的
    `_quarantine_logs()`，隔离目录字面量在 `:215`），
    **不是** `game_auto.quarantine_logs()` 的 `%TEMP%\\v3_quarantine_logs`（`game_auto.py:1743`）：
    两个目录名字很像，查日志时找错一个，就会把「在另一边」误判成「丢了」。

    同名冲突实测是**三条**路径（`t12` 逐条复现，读数见 `docs/reports/t12-静默路径文案与回归.md`）：

    * ① 目标里已有同名**文件** ⇒ `os.rename` 抛 `FileExistsError`，`shutil.move` 退回
      `copy2` + `unlink` ⇒ **静默覆盖上一代**（本文件 `test_旧写法在目标被同名文件占位时静默覆盖`）；
    * ② 目标同名的那个**目录里已有同名文件** ⇒ 走"目标是目录"支，`shutil.move` 抛
      **`shutil.Error`**（`Destination path … already exists`）—— 它是 `OSError` 子类，
      被旧 body 的 `except (PermissionError, OSError): continue` **吞掉** ⇒ 文件**留在原地**、
      **零行输出**（本文件 `test_目标目录四种形态都不覆盖不静默` 的第三个变体）；
    * ③ 目标同名的是**空目录** ⇒ 不抛错，按"目标目录"语义把文件挪进
      `target\\<名字>\\<名字>` ⇒ **证据被埋深一层、零行输出**（同上用例的第二个变体，
      旧 body 的现场由 `test_旧写法在目标被目录占名时把证据埋深一层` 重放）。

    这一组用例全部合成（不碰真游戏、不碰真 `%TEMP%`）：`LOGS` 与 `tempfile.gettempdir()`
    都换成 `tmp_path`，时间戳与出声都从注入点给 —— 判据在纯逻辑那一层。
    """

    def _setup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, names: tuple[str, ...]
    ) -> tuple[ModuleType, Path, Path]:
        """造一份 `logs\\`（新日志）与一个空隔离目录，返回（module, logs, target）。"""
        perf = _perf()
        logs = tmp_path / "logs"
        logs.mkdir()
        for name in names:
            (logs / name).write_text(f"这一局：{name}\n", encoding="utf-8")
        temp = tmp_path / "temp"
        target = temp / "v3_quarantine_perflogs"
        target.mkdir(parents=True)
        monkeypatch.setattr(perf, "LOGS", logs)
        monkeypatch.setattr(perf.tempfile, "gettempdir", lambda: str(temp))
        return perf, logs, target

    def test_无冲突时用原名且不出声(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        perf, logs, target = self._setup(tmp_path, monkeypatch, names=("ai.log", "debug.log"))
        said: list[str] = []
        moved = perf._quarantine_logs(stamp="20260101-000000", announce=said.append)
        assert moved == ["ai.log", "debug.log"], "没有冲突就该沿用原名（不改既有落点）"
        assert said == [], "没冲突就不该出声（出声留给真问题，否则读的人会麻木）"
        assert not (logs / "debug.log").exists()
        assert (target / "debug.log").read_text(encoding="utf-8") == "这一局：debug.log\n"

    def test_同名冲突改名落地且两代都留(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**主判据**：目标里已有同名 ⇒ 改名落地、旧的一字不动、新的也在、并出声一行。"""
        perf, logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").write_text("上一局：debug.log\n", encoding="utf-8")
        said: list[str] = []
        moved = perf._quarantine_logs(stamp="20260101-000000", announce=said.append)
        assert moved == ["debug.20260101-000000.log"], "被占就要改名（不是覆盖、也不是丢）"
        assert (target / "debug.log").read_text(encoding="utf-8") == "上一局：debug.log\n"
        assert (target / "debug.20260101-000000.log").read_text(
            encoding="utf-8"
        ) == "这一局：debug.log\n"
        assert len(said) == 1
        assert "两代都留住" in said[0]
        assert "debug.20260101-000000.log" in said[0]
        assert not (logs / "debug.log").exists()

    def test_目标被目录占名时也不丢(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """目录语义下 `shutil.move` 抛的是 `shutil.Error`（`OSError` 子类）——
        旧写法被 `except OSError: continue` 吞掉（既没挪走、也不报错），新写法改名落地。"""
        perf, _logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").mkdir()
        said: list[str] = []
        moved = perf._quarantine_logs(stamp="20260101-000000", announce=said.append)
        assert moved == ["debug.20260101-000000.log"]
        assert (target / "debug.log").is_dir(), "占名的那一项不许被动"
        assert (target / "debug.20260101-000000.log").read_text(
            encoding="utf-8"
        ) == "这一局：debug.log\n"
        assert said
        assert "两代都留住" in said[0]

    def test_挪不动要出声且文件仍在原地(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`PermissionError`（上一次跑批留下的进程握着句柄，2026-09-23 实测）：
        **跳过仍然安全**，但必须带路径与原因出声 —— 不许 `continue` 了事。"""

        def boom(src: str, dst: str) -> None:
            raise PermissionError(f"[WinError 32] 另一个程序正在使用此文件：{src}")

        perf, logs, _target = self._setup(tmp_path, monkeypatch, names=("ai.log",))
        monkeypatch.setattr(perf.shutil, "move", boom)
        said: list[str] = []
        moved = perf._quarantine_logs(stamp="20260101-000000", announce=said.append)
        assert moved == []
        assert (logs / "ai.log").exists(), "挪不动就留在原地（不许删了再算挪走）"
        assert len(said) == 1
        assert "挪不动" in said[0]
        assert str(logs / "ai.log") in said[0], "出声必须带**路径**"
        assert "PermissionError" in said[0], "出声必须带**原因**"

    def test_默认出声出口是stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """不注入 `announce` 时走 `_announce()` ⇒ 一行到 **stderr**（不是静默、也不是混进 stdout 的读数）。"""
        perf, _logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").write_text("上一局\n", encoding="utf-8")
        perf._quarantine_logs(stamp="20260101-000000")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[隔离日志]" in captured.err
        assert "debug.20260101-000000.log" in captured.err

    def test_时间戳复用game_auto那一套(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**不许另写一套**：不传 `stamp` 时用 `game_auto.archive_stamp()`，
        落点名用 `game_auto.unused_path()` 的约定（时间戳插在**扩展名前**）。"""
        perf, _logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").write_text("上一局\n", encoding="utf-8")
        monkeypatch.setattr(perf.ga, "archive_stamp", lambda **_kw: "20260202-030405")
        said: list[str] = []
        moved = perf._quarantine_logs(announce=said.append)
        assert moved == ["debug.20260202-030405.log"], "时间戳要来自 game_auto.archive_stamp()"
        assert (target / "debug.20260202-030405.log").exists()

    def test_旧写法在目标被同名文件占位时静默覆盖(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**阴性对照的判据版本**①（也是 `t31` 实测到的真机制）：目标里已有**同名文件**时，
        `shutil.move` 的 `os.rename` 在 Windows 上抛 `FileExistsError`，于是回退
        `copy2` + `unlink` ⇒ **上一局那一代被覆盖**，而 `moved` 照样自报成功、零行输出。

        重放 `t36` 之前那段 body（**故意不打印**任何东西，旧 body 就是这样）。
        """
        perf, logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").write_text("上一局：先到的那一代\n", encoding="utf-8")
        moved: list[str] = []
        for path in sorted(logs.glob("*.log")):
            try:
                perf.shutil.move(str(path), str(target / path.name))
            except (PermissionError, OSError):
                continue  # ← 旧 body 的全部处置
            moved.append(path.name)
        assert moved == ["debug.log"], "旧写法**自报成功**（调用方看不出任何异常）"
        assert (target / "debug.log").read_text(encoding="utf-8") == "这一局：debug.log\n"
        assert not (logs / "debug.log").exists()

    def test_旧写法在目标被目录占名时把证据埋深一层(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """阴性对照的判据版本③：`target\\debug.log` 是**空目录**时 `shutil.move` 不抛错 ——
        它按"目标目录"语义把文件挪进 `target\\debug.log\\debug.log`，同样零行输出。

        （`t12` 修正：这条只对**空目录**成立。同一个目录里**已有**同名文件时，
        `shutil.move` 会先算出 `target\\debug.log\\debug.log`、发现它存在 ⇒ 抛
        `shutil.Error`（`OSError` 子类）—— 被旧 body 的
        `except (PermissionError, OSError): continue` 吞掉：文件**留在原地**、**零行输出**。
        那是第三条路径，由 `test_目标目录四种形态都不覆盖不静默` 用新写法正面钉住；
        旧 docstring 写的「两种占名方式都不抛」**是错的**。）
        """
        perf, logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        (target / "debug.log").mkdir()
        moved: list[str] = []
        for path in sorted(logs.glob("*.log")):
            try:
                perf.shutil.move(str(path), str(target / path.name))
            except (PermissionError, OSError):
                continue
            moved.append(path.name)
        assert moved == ["debug.log"]
        assert (target / "debug.log" / "debug.log").read_text(
            encoding="utf-8"
        ) == "这一局：debug.log\n", "证据被挪进一层没人会去看的子目录"

    # ── `t12`：三条静默路径逐条钉住（上面两条阴性对照的**正面**版本）────────────
    @pytest.mark.parametrize(
        ("占名形态", "落点名", "出声数"),
        [
            ("空着", "debug.log", 0),
            ("同名文件", "debug.20260101-000000.log", 1),
            ("同名空目录", "debug.20260101-000000.log", 1),
            ("同名目录里已有同名文件", "debug.20260101-000000.log", 1),
        ],
    )
    def test_目标目录四种形态都不覆盖不静默(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        占名形态: str,
        落点名: str,
        出声数: int,
    ) -> None:
        """**`t12` 的永久回归线**：目标目录四种形态各钉一次 —— 空着、被同名**文件**占、
        被同名**空目录**占、被「**里面有同名文件的目录**」占（最后这条就是旧写法会抛
        `shutil.Error` 被 `except OSError` 吞掉、文件留原地、零行输出的那一条）。

        每条都同样要求三件事：**源文件真的挪走**（`moved` 自报 == 落地点）、
        **占位物一字未动**（既不覆盖、也不埋深 —— 用快照前后比对，比逐个断言更不容易写漏）、
        **该出声就出声**（占名 ⇒ 恰一行「两代都留住」，空着 ⇒ 零行）。
        """

        def 快照(root: Path) -> list[str]:
            rows: list[str] = []
            for one in sorted(root.rglob("*")):
                body = "dir" if one.is_dir() else one.read_text(encoding="utf-8").strip()
                rows.append(f"{one.relative_to(root).as_posix()}|{body}")
            return rows

        perf, logs, target = self._setup(tmp_path, monkeypatch, names=("debug.log",))
        if 占名形态 == "同名文件":
            (target / "debug.log").write_text("上一局：先到的那一代\n", encoding="utf-8")
        elif 占名形态 in ("同名空目录", "同名目录里已有同名文件"):
            (target / "debug.log").mkdir()
            if 占名形态 == "同名目录里已有同名文件":
                (target / "debug.log" / "debug.log").write_text("上上局\n", encoding="utf-8")
        before = 快照(target)
        said: list[str] = []
        moved = perf._quarantine_logs(stamp="20260101-000000", announce=said.append)
        assert moved == [落点名], "自报的落地点必须就是真落地的那一个"
        assert not (logs / "debug.log").exists(), "源文件必须真的挪走（不许留原地还自报成功）"
        after = 快照(target)
        for item in before:
            assert item in after, f"占位物被动过：{item}"
        fresh = [one for one in after if one not in before]
        assert fresh == [f"{落点名}|这一局：debug.log"], "新落地的**只有一个**，且就在落点名上"
        assert len(said) == 出声数, "占名恰一行；空着零行（出声多了读的人会麻木）"
        if 出声数:
            assert "两代都留住" in said[0]
            assert 落点名 in said[0]
