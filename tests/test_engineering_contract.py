"""工程基线、当前分层计划入口和历史证据边界的回归测试。"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

from pdx import country_coordination, country_state, decision_report, distribution
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


def test_plan_archival_and_quality_gate_are_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    plan_entry = (root / "docs/design/架构主计划.md").read_text(encoding="utf-8")
    subplan_entry = (root / "docs/design/架构子计划.md").read_text(encoding="utf-8")
    plan = (root / "docs/design/archive/X1/架构主计划.md").read_text(encoding="utf-8")
    subplans = (root / "docs/design/archive/X1/架构子计划.md").read_text(encoding="utf-8")
    previous = (root / "docs/design/exec/mod重设计-实施计划.md").read_text(encoding="utf-8")
    checklist = (root / "docs/design/当前工作清单.md").read_text(encoding="utf-8")
    assert plan.startswith("# Situated AI 架构主计划\n")
    for current in (plan_entry, subplan_entry, checklist):
        assert "A4" in current
        assert "已制定" in current
        assert "(架构深化计划.md)" in current
    assert (root / "docs/design/架构深化计划.md").is_file()
    assert "archive/A3-manifest.json" in plan_entry
    assert "archive/A3-manifest.json" in subplan_entry
    assert "已完成并归档" in plan
    assert "已完成并归档" in subplans
    assert re.findall(r"^\| (A4-\d+) ", plan_entry, re.MULTILINE) == [
        f"A4-{index}" for index in range(9)
    ]
    assert "[架构子计划](架构子计划.md)" in plan
    assert "[架构主计划](架构主计划.md)" in subplans
    assert re.findall(r"^\| (X\d+) ", plan, re.MULTILINE) == [f"X{i}" for i in range(7)]
    assert re.findall(r"^## ([DGE]\d+) ", subplans, re.MULTILINE) == [
        *(f"D{i}" for i in range(1, 5)),
        *(f"G{i}" for i in range(1, 4)),
        *(f"E{i}" for i in range(1, 5)),
    ]
    assert "具体实现随证据调整" in subplans
    assert "不是新架构完成门" in (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
    archive = root / "docs/design/archive"
    assert (archive / "manifest.json").is_file()
    assert "历史" in (archive / "README.md").read_text(encoding="utf-8")
    for plan_id in ("X1", "A3"):
        manifest = json.loads((archive / f"{plan_id}-manifest.json").read_text(encoding="utf-8"))
        assert manifest["status"] == "archived_reference_only"
        expected = {"docs/design/架构主计划.md", "docs/design/架构子计划.md"}
        if plan_id == "A3":
            expected |= {
                "docs/design/架构深化计划.md",
                "docs/design/当前工作清单.md",
                "docs/design/A3实施台账.toml",
                "docs/design/exec/A3分层联动-结果.md",
            }
        assert {row["path"] for row in manifest["originals"]} == expected
        assert len(manifest["originals"]) == len(expected)
        for row in manifest["originals"]:
            raw = gzip.decompress((archive / row["object"]).read_bytes())
            assert len(raw) == row["bytes"]
            assert hashlib.sha256(raw).hexdigest() == row["sha256"]
            readable = archive / row["readable"]
            assert readable.is_file()
            if row.get("readable_kind") == "exact_original":
                assert readable.read_bytes() == raw
            if plan_id == "A3":
                assert row["provenance"] in {
                    "committed_at_base",
                    "uncommitted_checkpoint_at_capture",
                }
        if plan_id == "A3":
            assert re.fullmatch(r"[0-9a-f]{40}", manifest["base_commit"])
            assert not (root / "docs/design/A3实施台账.toml").exists()
    assert "# Situated AI 处境行动决策内核实施计划" in previous
    assert "旧计划已暂停，未完成" in previous
    version = re.search(r"计划版本：(\d+)\.(\d+)", previous)
    assert version is not None
    assert (int(version.group(1)), int(version.group(2))) >= (26, 0)
    assert re.findall(r"^### (K\d+)：", previous, re.MULTILINE) == [
        f"K{index}" for index in range(14)
    ]
    assert "阶段" in plan
    assert "出口" in plan
    assert "正确性第一、速度第二、内存第三" in plan
    assert "长期游戏行为" in plan
    assert "由用户验收" in plan
    assert "全仓库终审和计划闭环" in previous
    assert "标准交付、用户验收包、部署和回滚" in previous
    assert "A4" in checklist
    assert "长期行为" in checklist
    assert distribution.RELEASE_VERSION in checklist
    assert "发布" in checklist
    assert "部署" in checklist
    assert "Release" in checklist
    assert "ZIP/SHA" in checklist
    assert "A2" in checklist
    assert "不签发A4完成" in checklist
    assert "11 种语言" in previous


def test_current_document_indexes_are_complete() -> None:
    """导航统一指向当前计划和收据，旧方案只保留历史上下文。"""
    root = Path(__file__).resolve().parents[1]
    tools = (root / "tools/README.md").read_text(encoding="utf-8")
    execution = (root / "docs/design/exec/README.md").read_text(encoding="utf-8")

    assert "-m pdx.cli package" in tools
    assert "[版本交付索引](../docs/design/exec/版本交付-结果.md)" in tools
    assert "K0–K13" in execution
    assert "[处境行动决策内核实施计划](mod重设计-实施计划.md)" in execution
    assert "分层联动-执行结果.md" in execution
    assert "历史收据" in execution

    indexes = {
        "README.md": "docs/design/exec/",
        "tools/README.md": "../docs/design/exec/",
        "docs/README.md": "design/exec/",
        "docs/design/README.md": "exec/",
        "docs/design/exec/README.md": "",
    }
    for path, prefix in indexes.items():
        content = (root / path).read_text(encoding="utf-8")
        design_prefix = prefix.removesuffix("exec/") if prefix else "../"
        assert f"[架构主计划]({design_prefix}架构主计划.md)" in content, path
        assert f"[架构子计划]({design_prefix}架构子计划.md)" in content, path
        assert (
            f"[处境行动决策内核实施计划]({prefix}mod重设计-实施计划.md)" in content
            or f"[分层联动实施计划]({prefix}mod重设计-实施计划.md)" in content
        ), path
        assert "终极方案 4.0 实施计划" not in content, path
        version_links = re.findall(r"\[[^\]]*版本交付索引[^\]]*\]\(([^)]+)\)", content)
        assert version_links, path
        assert all(
            ((root / path).parent / link).resolve()
            == (root / "docs/design/exec/版本交付-结果.md").resolve()
            for link in version_links
        ), path
        for target in re.findall(r"\[[^\]]+\]\(([^)]+\.md)\)", content):
            if "://" not in target:
                assert ((root / path).parent / target).is_file(), (path, target)


def test_layered_design_tracks_production_contract_and_boundaries() -> None:
    """设计必须覆盖生产分类与未知/原版边界，不能靠粗域开关宣称全深度。"""
    root = Path(__file__).resolve().parents[1]
    design = (root / "docs/design/03-处境决策设计.md").read_text(encoding="utf-8")
    for name in (*country_coordination.LAYERS, *country_coordination.NEEDS):
        assert f"`{name}`" in design or name in design
    for key, label, *_ in decision_report.TAXONOMY:
        assert f"`{key}`" in design
        assert label in design
    for domain in decision_report.DOMAINS:
        assert f"`{domain}`" in design or domain in design
    contract = country_state.contract(country_state.load())
    assert contract["persistent_variables"] == []
    assert "stateless_consumer_observations" in design
    for boundary in (
        "不新增持久变量",
        "按需求值",
        "已证实的低档",
        "第一匹配胜出",
        "只作为合同开关",
        "政治可行性",
        "战败重建优先于扩张",
        "原版实际成本、资格、前置、政治支持、随机",
        "终结零分",
        "玩家决策路径不变",
        "活跃原版策略定义的同名字段可能覆盖默认策略",
        "不能擅自认定",
        "用户在固定标准包上验收",
    ):
        assert boundary in design


def test_ultimate_plan_receipt_retains_historical_context() -> None:
    root = Path(__file__).resolve().parents[1]
    receipt = (root / "docs/design/exec/终极方案4.0-执行结果.md").read_text(encoding="utf-8")
    assert "终极方案 4.0" in receipt
    assert "旧的《终极方案 3.0 执行结果》" in receipt
    assert "本轮实际生产改动" in receipt
    assert "长期游戏行为" in receipt
    assert "static_check" in receipt
    assert "package" in receipt
    assert "投入短缺优先" in receipt
    assert "城市化研究纵切" in receipt
