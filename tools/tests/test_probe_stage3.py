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

import importlib.util
from typing import TYPE_CHECKING

import pytest

from pdx import config
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
