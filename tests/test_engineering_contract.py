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
    assert "# Situated AI 终极深化计划" in plan
    version = re.search(r"计划版本：(\d+)\.(\d+)", plan)
    assert version is not None
    assert (int(version.group(1)), int(version.group(2))) >= (13, 0)
    stage_positions = [plan.index(f"### U{index}：") for index in range(13)]
    assert stage_positions == sorted(stage_positions)
    assert "F0–F18" in plan
    assert "每个 U 阶段都必须从上一完整包增量生成一个可安装、可运行、可解释的标准 Mod 包" in plan
    assert "正确性第一、速度第二、内存第三" in plan
    assert "静态检查、日志、快照、模拟、实测、推断和玩家验收" in plan
    assert "当前下一步" in plan
    assert "U0" in checklist
    assert "每阶段必须交付可玩包" in checklist
    assert "situated-ai" in checklist
    assert "标准包" in checklist
    assert "1.1.1 候选已生成" in checklist
    assert "运行期观察工具 | U11 工程候选已交付" in checklist
    assert "docs/publishing/创意工坊描述.md" in plan
    assert "src/pdx/observe.py" in plan
    assert "src/pdx/savegame.py" in plan
    assert "日志增量读取有明确的输入目录" in plan
    assert "目标、内容、兼容性、支持的语言" in plan


def test_current_document_indexes_are_complete() -> None:
    """当前入口指向同一终极队列，历史收据仍可追溯。"""
    root = Path(__file__).resolve().parents[1]
    tools = (root / "tools/README.md").read_text(encoding="utf-8")
    execution = (root / "docs/design/exec/README.md").read_text(encoding="utf-8")

    assert "dist/situated-ai-1.1.1.zip" in tools
    assert "Situated AI 1.1.1" in tools
    assert "dist/situated-ai-1.0.1.zip" not in tools
    assert all(f"F{index}-" in execution for index in range(9, 19))
    assert "当前维护候选为 Situated AI 1.1.1" in execution
    assert "U0–U12" in execution
    assert "不另列第二套待办" in execution
    assert "[Situated AI 终极深化计划](mod重设计-实施计划.md)" in execution
    assert "[F18 集成、完整回归和交付](F18-集成交付-结果.md)" in execution
    assert "观察器和 Workshop 文案已经是当前" in execution
