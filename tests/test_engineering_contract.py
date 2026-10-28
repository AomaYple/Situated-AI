"""工程基线和终极计划契约的回归测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdx.engineering import (
    ENGINEERING_BASELINE,
    SKIP_CATEGORIES,
    TEST_TIERS,
    classify_skip_reason,
    require_skip_category,
)


def test_engineering_baseline_has_stable_tiers() -> None:
    assert ENGINEERING_BASELINE == "1.0"
    assert set(TEST_TIERS) == {"quick", "offline", "full"}
    assert set(SKIP_CATEGORIES) == {"game", "artifact", "platform", "tool", "environment"}


@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("游戏目录不可用", "game"),
        ("需要锁定原版", "game"),
        ("需要锁定版本的游戏原件", "game"),
        ("没有精简快照", "artifact"),
        ("系统未授予符号链接权限", "platform"),
        ("ruff 不可用：命令不存在", "tool"),
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


def test_current_mod_plan_and_quality_gate_are_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    plan = (root / "docs/design/exec/mod重设计-实施计划.md").read_text(encoding="utf-8")
    checklist = (root / "docs/design/当前工作清单.md").read_text(encoding="utf-8")
    assert "# Situated AI 终极方案 3.0 实施计划" in plan
    version = re.search(r"计划版本：(\d+)\.(\d+)", plan)
    assert version is not None
    assert (int(version.group(1)), int(version.group(2))) >= (20, 0)
    stage_positions = [plan.index(f"| E{index} |") for index in range(16)]
    assert stage_positions == sorted(stage_positions)
    assert "T0–T13" in plan
    assert "每个阶段有静态出口" in plan
    assert "正确性第一、速度第二、内存第三" in plan
    assert "用户在固定包上验收" in plan
    assert "Mod 结构和内容全量整合" in plan
    assert "改动后的全仓全 Mod 复核" in plan
    assert "正式交付和维护" in plan
    assert "E0–E15：已完成" in checklist
    assert "1.3.0" in checklist
    assert "situated-ai" in checklist
    assert "标准包" in checklist
    assert "运行期" in checklist
    assert "日志解析、存档摘要、快照和根 hook" in plan
    assert "11 种本体语言" in plan


def test_current_document_indexes_are_complete() -> None:
    """当前入口指向同一终极队列，历史收据仍可追溯。"""
    root = Path(__file__).resolve().parents[1]
    tools = (root / "tools/README.md").read_text(encoding="utf-8")
    execution = (root / "docs/design/exec/README.md").read_text(encoding="utf-8")

    assert "dist/situated-ai-1.3.0.zip" in tools
    assert "Situated AI 1.3.0" in tools
    assert "dist/situated-ai-1.0.1.zip" not in tools
    assert "当前工程交付为 `Situated AI 1.3.0`" in execution
    assert "E0–E15" in execution
    assert "[Situated AI 终极方案 3.0 实施计划](mod重设计-实施计划.md)" in execution
    assert "[终极方案 3.0 执行结果](终极方案3.0-执行结果.md)" in execution
    assert "历史收据" in execution


def test_ultimate_plan_receipt_is_current() -> None:
    root = Path(__file__).resolve().parents[1]
    receipt = (root / "docs/design/exec/终极方案3.0-执行结果.md").read_text(encoding="utf-8")
    assert "E0–E15" in receipt
    assert "长期游戏行为" in receipt
    assert "static_check" in receipt
    assert "package" in receipt
    for index in range(16):
        assert f"| E{index} |" in receipt
