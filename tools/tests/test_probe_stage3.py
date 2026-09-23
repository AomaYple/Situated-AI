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
    """**2026-09-23 `bv_alignment` 那一局的现场**：日志里没有 `TARGET`，只有 56 条 `ROLE`。

    照旧口径这一栏会报「不判」，白白丢掉一条本可以判的读数；现在按
    `ROLE;<TAG>` → `[archive].country` 反查（档案↔国家是数据源里的事实）。
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
