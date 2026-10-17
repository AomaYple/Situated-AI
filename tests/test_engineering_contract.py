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
    plan = (root / "docs/design/exec/mod重设计-实施计划.md").read_text(encoding="utf-8")
    methods = (root / "docs/design/exec/速度优化计划-正确性优先.md").read_text(encoding="utf-8")
    checklist = (root / "docs/design/当前工作清单.md").read_text(encoding="utf-8")
    quality = (root / "docs/design/exec/M3-可测性清单.md").read_text(encoding="utf-8")
    # 保护全目标先实现、再集中验证的依赖及质量门，而非旧附件排期。
    assert "全目标实现优先与集中验证计划 · 4.0" in plan
    phases = [
        "## 3. F0：最终目标完整实现",
        "## 4. F1：集中验证与修正",
        "## 5. F2：稳定性、性能与正式交付",
    ]
    positions = [plan.index(phase) for phase in phases]
    assert positions == sorted(positions)
    assert "M3-A" in plan
    assert "M3-B" in plan
    assert "同输入/环境同类错误两次停止" in plan
    assert "先三次 vanilla 测噪声" in plan
    assert "安全诊断" in plan
    assert "尚未派发，属于执行遗漏" in plan
    assert "最终目标与实现对照" in plan
    assert "fallback_languages" in plan
    assert "全部语言翻译初稿" in plan
    assert "不创建另一套排期" in methods
    assert "原账本停止条件保持" in methods
    assert "质量观测边界" in quality
    assert "unsupported" in quality
    assert "全目标实现优先与集中验证计划 4.0" in checklist
    assert "整个 Mod 尚未完成" in checklist

    scan = root / "tools/out/evidence/v0.1-g1-20261013/g1-reopen-scan-20261013.json"
    data = json.loads(scan.read_text(encoding="utf-8"))
    assert data["status"] == "NO_NEW_REOPENING_INPUT"
    assert data["findings"]["new_complete_pre_treatment_input"] is False
    assert data["findings"]["complete_opportunity_denominator"] is None
