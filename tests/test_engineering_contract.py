"""工程基线契约的回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx.automation_contract import AutomationPhase, AutomationTrace
from pdx.engineering import (
    ENGINEERING_BASELINE,
    SKIP_CATEGORIES,
    TEST_TIERS,
    classify_skip_reason,
    require_skip_category,
)


def test_engineering_baseline_has_stable_tiers() -> None:
    assert ENGINEERING_BASELINE == "1.0"
    assert set(TEST_TIERS) == {"quick", "offline", "full", "live"}
    assert set(SKIP_CATEGORIES) == {"game", "artifact", "platform", "tool", "live", "environment"}


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("游戏目录不可用", "game"),
        ("没有精简快照", "artifact"),
        ("系统未授予符号链接权限", "platform"),
        ("ruff 不可用：命令不存在", "tool"),
        ("真实游戏 GUI 尚未连接", "live"),
        ("本机没有可发现的 mod", "environment"),
    ],
)
def test_skip_reason_is_classified(reason: str, category: str) -> None:
    assert classify_skip_reason(reason) == category
    assert require_skip_category(reason) == category


def test_unknown_or_empty_skip_reason_is_rejected() -> None:
    assert classify_skip_reason("") is None
    assert classify_skip_reason("some unexplained condition") is None
    with pytest.raises(ValueError, match="无法分类"):
        require_skip_category("some unexplained condition")


def test_automation_trace_requires_the_standard_order() -> None:
    trace = AutomationTrace()
    for phase in (
        AutomationPhase.FOREGROUND_READY,
        AutomationPhase.BOOT_SETTLED,
        AutomationPhase.OBSERVE_SELECTED,
        AutomationPhase.SPEED_SET,
        AutomationPhase.RUNNING,
        AutomationPhase.BACKGROUND,
        AutomationPhase.VERIFIED,
        AutomationPhase.COMPLETE,
    ):
        trace = trace.advance(phase)
    assert trace.complete is True
    assert trace.as_dict()["phases"] == [phase.value for phase in trace.phases]


def test_automation_trace_rejects_reordered_or_repeated_steps() -> None:
    trace = AutomationTrace().advance(AutomationPhase.FOREGROUND_READY)
    with pytest.raises(ValueError, match="非法自动化状态转移"):
        trace.advance(AutomationPhase.SPEED_SET)


def test_current_mod_plan_and_quality_gate_are_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    plan = (root / "docs/design/exec/速度优化计划-正确性优先.md").read_text(encoding="utf-8")
    checklist = (root / "docs/design/当前工作清单.md").read_text(encoding="utf-8")
    quality = (root / "docs/design/exec/M3-可测性清单.md").read_text(encoding="utf-8")
    assert "版本**：2.4" in plan
    assert "P0 规则层" in plan
    assert "R 运行层" in plan
    assert "质量观测边界" in quality
    assert "unsupported" in quality
    assert "G1 重开扫描" in checklist

    scan = root / "tools/out/evidence/v0.1-g1-20261013/g1-reopen-scan-20261013.json"
    data = json.loads(scan.read_text(encoding="utf-8"))
    assert data["status"] == "NO_NEW_REOPENING_INPUT"
    assert data["findings"]["new_complete_pre_treatment_input"] is False
    assert data["findings"]["complete_opportunity_denominator"] is None
