"""工程基线契约的回归测试。"""

from __future__ import annotations

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
    assert "# Situated AI 深化扩展计划" in plan
    assert "计划版本：12.3" in plan
    assert all(f"## F{index}：" in plan for index in range(3))
    assert all(f"## F{index}：" in plan for index in range(9, 19))
    assert "当前扩展队列：F9–F18，全部未开始" in plan
    assert "## 阶段状态机、产物和回退" in plan
    assert "F9 固定候选分母" in plan
    assert "## F15：Mod 内容与结构整合、更新、清理" in plan
    assert "## F16：解释、本地化与计算成本综合收口" in plan
    assert "## F17：Mod 开发原则最终符合性审计与整改" in plan
    assert "完整 `full-acceptance` 留到 F18 在最终冻结候选上只运行一次" in plan
    assert "用户负责长期游戏行为、平衡、后期性能、GUI 和工坊验收" in plan
    assert "用户负责长期游戏行为" in plan
    assert "用户可据此进行长期游戏观察的版本出口" in plan
    assert "UTF-8 无 BOM/LF" in plan
    assert "长期行为、平衡、后期性能、语言呈现和工坊发布" in checklist
    assert "situated-ai" in checklist
    assert "标准包" in checklist
    assert "1.1.0 候选已生成" in checklist
