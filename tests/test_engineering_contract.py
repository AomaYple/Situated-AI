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


def _document_section(text: str, title: str) -> str:
    heading = f"## {title}\n"
    assert text.count(heading) == 1, title
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def _assert_r2_acceptance_consistent(receipt: str, statuses: tuple[str, ...], matrix: str) -> None:
    gates = _document_section(receipt, "分别签署")
    rows = {}
    for line in gates.splitlines():
        if line.startswith("| "):
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if len(cells) == 2:
                assert cells[0] not in rows, cells[0]
                rows[cells[0]] = cells[1]
    assert {"工程 E", "三纵切 Mod 生产静态语义 M", "运行执行 R", "长期体验 U"} <= rows.keys()
    for gate in ("运行执行 R", "长期体验 U"):
        assert re.match(r"(?:runtime-unknown|unknown|未验收)(?:[:：]|$)", rows[gate]), rows[gate]
    passed = []
    for gate in ("工程 E", "三纵切 Mod 生产静态语义 M"):
        state = rows[gate]
        complete = state.startswith(("通过：", "已通过：", "已闭合：", "已签署："))
        assert complete or re.search(r"未闭合|待闭合|等待|尚未|尚待", state), (gate, state)
        passed.append(complete)
    engineering_passed, production_passed = passed
    complete = engineering_passed and production_passed
    for state in (receipt.split("\n\n")[1], *statuses):
        pending = bool(re.search(r"尚未|未闭合|待闭合|待.*验收|等待|尚待|正在.*验收", state))
        if complete:
            assert not pending, state
            assert re.search(
                r"(?:已|当时).*(?:验收|通过|完成|签署)|共同(?:通过|完成|签署)", state
            ), state
        else:
            assert pending, state
    for requirement, signed in (("SAI-19", engineering_passed), ("SAI-20", complete)):
        matches = [line for line in matrix.splitlines() if line.startswith(f"| {requirement} |")]
        assert len(matches) == 1, requirement
        assert matches[0].split("|")[-2].strip() == ("已证明" if signed else "待闭合")
    if engineering_passed:
        # Receipt identities and results are checked here. The original
        # artifacts require independent byte-level verification.
        full = _document_section(receipt, "当前完整验收")
        assert re.search(r"full-acceptance[^\n]*--profile 1\.15\.0", full)
        assert re.search(r"^(?:本轮|最终)[^\n]*(?:exit|退出码)\s*[=:：]?\s*0\b", full, re.MULTILINE)
        identity = _document_section(receipt, "当前 A0 完整盘点、处置与成本")
        package = _document_section(receipt, "本轮六文件 R2 候选包")
        snapshot_pattern = r"snapshot(?:为|[:：])?\s*`([0-9a-f]{64})`"
        workflow_snapshot = re.search(snapshot_pattern, full)
        inventory_snapshot = re.search(snapshot_pattern, identity)
        assert workflow_snapshot is not None
        assert inventory_snapshot is not None
        assert workflow_snapshot.group(1) == inventory_snapshot.group(1)
        assert ".zip" in package
        assert re.search(r"SHA-256\s*[:：]?\s*`[0-9a-f]{64}`", package)


def test_delivery_baseline_defines_distinct_acceptance_responsibilities() -> None:
    root = Path(__file__).resolve().parents[1]
    delivery_baseline = (root / "docs/design/exec/工程基线-1.0.md").read_text(encoding="utf-8")
    acceptance = _document_section(delivery_baseline, "验收职责")
    assert "开发侧补齐 E、M 的实现与验证缺口" in acceptance
    assert "E 和 M 具备充分证据后可签署相应的静态验收" in acceptance
    for gate, responsibility in (
        ("工程验收（E）", "核对工具、生成和标准包交付合同"),
        ("Mod 静态语义验收（M）", "以独立证据核对交付的 Mod 如何接入并影响所声明的原版决策"),
        ("运行验收（R）", "以固定交付包与游戏条件下的引擎证据核对实际行为"),
        ("长期体验验收（U）", "由用户在版本与哈希固定的交付包上实机验收"),
    ):
        assert f"- **{gate}**{responsibility}" in acceptance
    assert "R 和 U 依据各自取得的实机结果签署" in acceptance


def test_plan_archival_and_quality_gate_are_explicit() -> None:
    root = Path(__file__).resolve().parents[1]
    plan_entry = (root / "docs/design/架构主计划.md").read_text(encoding="utf-8")
    subplan_entry = (root / "docs/design/架构子计划.md").read_text(encoding="utf-8")
    plan = (root / "docs/design/archive/X1/架构主计划.md").read_text(encoding="utf-8")
    subplans = (root / "docs/design/archive/X1/架构子计划.md").read_text(encoding="utf-8")
    previous = (root / "docs/design/exec/mod重设计-实施计划.md").read_text(encoding="utf-8")
    checklist = (root / "docs/design/当前工作清单.md").read_text(encoding="utf-8")
    implementation = (root / "docs/design/exec/1.15架构-实施计划.md").read_text(encoding="utf-8")
    architecture = (root / "docs/design/1.15架构设计.md").read_text(encoding="utf-8")
    engineering = (root / "docs/principles/工程原则.md").read_text(encoding="utf-8")
    assert plan.startswith("# Situated AI 架构主计划\n")
    # These paragraphs describe the signed 1.15.0 round. The current migration
    # introduction has its own gates and cannot inherit the historical signature.
    receipt = (root / "docs/design/exec/1.15-R2-最终验收结果.md").read_text(encoding="utf-8")
    matrix = (root / "docs/design/exec/1.15-R2-需求验收矩阵.md").read_text(encoding="utf-8")
    for page, prefix in ((plan_entry, "exec/"), (implementation, ""), (checklist, "exec/")):
        assert f"({prefix}1.15-R2-最终验收结果.md)" in page
    a6 = [line for line in plan_entry.splitlines() if line.startswith("| A6 |")]
    assert len(a6) == 1
    _assert_r2_acceptance_consistent(
        receipt,
        (
            next(
                paragraph
                for paragraph in plan_entry.split("\n\n")
                if paragraph.startswith("架构实施基准为 **1.15 架构主计划 R2**")
            ),
            implementation.split("\n\n")[1],
            _document_section(checklist, "1.15.0 架构阶段承接").strip().split("\n\n")[0],
            a6[0].split("|")[-2],
        ),
        matrix,
    )
    assert "(1.15架构设计.md)" in plan_entry
    assert "(exec/1.15架构-实施计划.md)" in plan_entry
    assert "唯一架构规范" in plan_entry
    assert "规范与稳定需求 ID 的唯一来源为[1.15架构设计](../1.15架构设计.md)" in implementation
    assert "阶段状态只由[架构主计划](../架构主计划.md)维护" in implementation
    assert "阶段状态只由[架构主计划](架构主计划.md)维护" in checklist
    assert "(exec/1.15-R2-需求验收矩阵.md)" in plan_entry
    assert "(exec/1.15-R2-实施结果.md)" in checklist
    assert "不改写成R2证据" in plan_entry
    assert "不证明R2完成" in checklist
    assert any(
        wording in checklist for wording in ("不能把定向通过签为整体完成", "定向通过不签发整体完成")
    )
    assert "工程门和 Mod 生产静态语义门均必需" in implementation
    assert "E 和 M 全部通过才可签署架构静态完成" in architecture
    assert "工程治理与产品开发分别验收" in engineering
    assert "保留未完成能力和有效失败的真实状态" in engineering
    assert "仅目标，未启动" in subplan_entry
    assert "(archive/X1/架构主计划.md)" in plan_entry
    assert "(archive/X1/架构子计划.md)" in subplan_entry
    assert "已完成并归档" in plan
    assert "已完成并归档" in subplans
    assert "已授权实施" in plan
    assert "[架构子计划](架构子计划.md)" in plan
    assert "[架构主计划](架构主计划.md)" in subplans
    assert re.findall(r"^\| (X\d+) ", plan, re.MULTILINE) == [f"X{i}" for i in range(7)]
    assert re.findall(r"^## ([DGE]\d+) ", subplans, re.MULTILINE) == [
        *(f"D{i}" for i in range(1, 5)),
        *(f"G{i}" for i in range(1, 4)),
        *(f"E{i}" for i in range(1, 5)),
    ]
    assert "具体实现随证据调整" in subplans
    workflow = _document_section((root / "CONTRIBUTING.md").read_text(encoding="utf-8"), "验证")
    assert "(docs/design/架构主计划.md)" in workflow
    assert "(docs/design/exec/广度深度拓展-结果.md)" in workflow
    archive = root / "docs/design/archive"
    assert (archive / "manifest.json").is_file()
    assert "历史" in (archive / "README.md").read_text(encoding="utf-8")
    manifest = json.loads((archive / "X1-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "archived_reference_only"
    assert {row["path"] for row in manifest["originals"]} == {
        "docs/design/架构主计划.md",
        "docs/design/架构子计划.md",
    }
    for row in manifest["originals"]:
        raw = gzip.decompress((archive / row["object"]).read_bytes())
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert (archive / row["readable"]).is_file()
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
    assert "不能关闭新架构需求" in checklist
    assert "X1的X0–X6及D1–D4、G1–G3、E1–E4已归档" in checklist
    assert "长期行为" in checklist
    assert distribution.RELEASE_VERSION in checklist
    assert "发布" in checklist
    assert "部署" in checklist
    assert "(exec/版本交付-结果.md)" in checklist
    # A new source version is a release target until its actual delivery exists.
    delivery_index = (root / "docs/design/exec/版本交付-结果.md").read_text(encoding="utf-8")
    delivered = re.findall(r"当前交付为 \*\*(\d+\.\d+\.\d+)\*\*", delivery_index)
    assert len(delivered) == 1
    receipt_link = f"{delivered[0]}-交付结果.md"
    assert f"(exec/{receipt_link})" in checklist
    assert (root / "docs/design/exec" / receipt_link).is_file()
    assert "不得缩小源码哈希集合、刷新旧锁或跳过失败制造通过" in checklist
    assert "11 种语言" in previous


@pytest.mark.parametrize("engineering_passed", [False, True])
@pytest.mark.parametrize("production_passed", [False, True])
def test_acceptance_requires_both_static_gates_to_close(
    engineering_passed: bool, production_passed: bool
) -> None:
    complete = engineering_passed and production_passed
    state = "已共同完成静态验收" if complete else "尚未共同签署"
    passed_gate = "通过：同源码证据已核验"
    pending_gate = "待闭合：等待完整验收"
    engineering_gate = passed_gate if engineering_passed else pending_gate
    production_gate = passed_gate if production_passed else pending_gate
    status = "已证明" if complete else "待闭合"
    engineering_status = "已证明" if engineering_passed else "待闭合"
    receipt = (
        f"# 最终验收\n\n状态：{state}\n\n## 分别签署\n\n"
        f"| 工程 E | {engineering_gate} |\n| 三纵切 Mod 生产静态语义 M | {production_gate} |\n"
        "| 运行执行 R | runtime-unknown |\n| 长期体验 U | 未验收 |\n"
        "\n## 当前完整验收\n\n"
        "命令：full-acceptance --profile 1.15.0 --quiet\n本轮最终完整验收：exit 0\n"
        f"完整 source snapshot：`{'a' * 64}`\n"
        "\n## 当前 A0 完整盘点、处置与成本\n\n"
        f"snapshot：`{'a' * 64}`\n\n## 本轮六文件 R2 候选包\n\n"
        f"candidate.zip SHA-256：`{'b' * 64}`\n"
    )
    matrix = f"| SAI-19 | {engineering_status} |\n| SAI-20 | {status} |"
    _assert_r2_acceptance_consistent(receipt, (state, state, state, state), matrix)
    with pytest.raises(AssertionError):
        _assert_r2_acceptance_consistent(
            receipt, ("尚未共同签署" if complete else "已共同完成静态验收",), matrix
        )
    for requirement, requirement_passed in (("SAI-19", engineering_passed), ("SAI-20", complete)):
        wrong_status = "待闭合" if requirement_passed else "已证明"
        wrong_matrix = re.sub(
            rf"\| {requirement} \|[^|]+\|", f"| {requirement} | {wrong_status} |", matrix
        )
        with pytest.raises(AssertionError):
            _assert_r2_acceptance_consistent(receipt, (state,), wrong_matrix)
    with pytest.raises(AssertionError):
        _assert_r2_acceptance_consistent(
            receipt.replace("runtime-unknown", "已通过：继承静态验收"), (state,), matrix
        )
    if engineering_passed:
        stale_result = receipt.replace(
            "本轮最终完整验收：exit 0", "上一轮：exit 0\n本轮最终完整验收：exit 1"
        )
        missing_snapshot = receipt.replace("snapshot", "历史身份")
        mismatched_snapshot = receipt.replace("a" * 64, "c" * 64, 1)
        missing_zip_hash = receipt.replace("b" * 64, "失去包哈希")
        for unsupported in (stale_result, missing_snapshot, mismatched_snapshot, missing_zip_hash):
            with pytest.raises(AssertionError):
                _assert_r2_acceptance_consistent(unsupported, (state,), matrix)


def test_current_document_indexes_are_complete() -> None:
    """导航统一指向当前计划和收据，旧方案只保留历史上下文。"""
    root = Path(__file__).resolve().parents[1]
    tools = (root / "tools/README.md").read_text(encoding="utf-8")
    execution = (root / "docs/design/exec/README.md").read_text(encoding="utf-8")

    assert "-m pdx.cli package" in tools
    assert "[版本交付索引](../docs/design/exec/版本交付-结果.md)" in tools
    assert "K0–K13" in execution
    archive = (root / "docs/design/archive/README.md").read_text(encoding="utf-8")
    assert "[31.4 旧实施计划](../exec/mod重设计-实施计划.md)" in archive
    assert "分层联动-执行结果.md" in execution
    assert "历史收据" in execution
    assert "tools/ci/architecture_witness_capture.py" in tools

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
        if path != "tools/README.md":
            assert f"]({design_prefix}archive/README.md" in content, path
            assert "mod重设计-实施计划.md" not in content, path
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
