"""工程基线、当前分层计划入口和历史证据边界的回归测试。"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
                r"(?:已|当时|该轮|曾).*(?:验收|通过|完成|签署)|共同(?:通过|完成|签署)", state
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


def test_historical_r2_acceptance_and_navigation() -> None:
    root = Path(__file__).resolve().parents[1]
    design = root / "docs/design"
    execution = design / "exec"
    implementation = (execution / "1.15架构-实施计划.md").read_text(encoding="utf-8")
    architecture = (design / "1.15架构设计.md").read_text(encoding="utf-8")
    checklist = (design / "当前工作清单.md").read_text(encoding="utf-8")
    historical = _document_section(checklist, "历史交付与治理")
    index = (execution / "README.md").read_text(encoding="utf-8")
    receipt_name = "1.15-R2-最终验收结果.md"
    matrix_name = "1.15-R2-需求验收矩阵.md"
    receipt = (execution / receipt_name).read_text(encoding="utf-8")
    matrix = (execution / matrix_name).read_text(encoding="utf-8")
    assert f"(exec/{receipt_name})" in architecture
    assert f"({receipt_name})" in implementation
    assert "(../1.15架构设计.md)" in implementation
    for target in (receipt_name, matrix_name):
        assert f"({target})" in index
        assert f"(exec/{target})" in historical
    checklist_status = [
        line for line in historical.splitlines() if f"(exec/{receipt_name})" in line
    ]
    assert len(checklist_status) == 1
    _assert_r2_acceptance_consistent(
        receipt, (implementation.split("\n\n")[1], checklist_status[0]), matrix
    )
    assert "工程门和 Mod 生产静态语义门均必需" in implementation
    assert "E 和 M 全部通过才可签署架构静态完成" in architecture


def test_plan_archive_preserves_historical_records() -> None:
    root = Path(__file__).resolve().parents[1]
    plan = (root / "docs/design/archive/X1/架构主计划.md").read_text(encoding="utf-8")
    subplans = (root / "docs/design/archive/X1/架构子计划.md").read_text(encoding="utf-8")
    previous = (root / "docs/design/exec/mod重设计-实施计划.md").read_text(encoding="utf-8")
    assert plan.startswith("# Situated AI 架构主计划\n")
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
    assert "11 种语言" in previous


_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_ASPECT_ID = re.compile(r"`(D\d{2})\.[a-z][a-z0-9_]*`")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _assert_plan_links(path: Path, text: str) -> None:
    for target in _MARKDOWN_LINK.findall(text):
        link = urlsplit(target)
        if link.scheme or link.netloc:
            continue
        destination = path.parent / unquote(link.path) if link.path else path
        assert destination.exists(), (path.name, target)
        if link.fragment and destination.suffix.lower() == ".md":
            headings = re.findall(
                r"^#{1,6}\s+(.+)$", destination.read_text(encoding="utf-8"), re.MULTILINE
            )
            anchors = {
                re.sub(r"[^\w\s-]", "", heading.strip().lower()).replace(" ", "-")
                for heading in headings
            }
            assert unquote(link.fragment) in anchors, (path.name, target)


def test_current_plan_routes_stage_exits_and_delivery_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    design = root / "docs/design"
    plan_path = design / "架构主计划.md"
    checklist_path = design / "当前工作清单.md"
    plan = plan_path.read_text(encoding="utf-8")
    checklist = checklist_path.read_text(encoding="utf-8")
    route = _document_section(checklist, "当前设计与下一动作")
    production = _document_section(checklist, "主线生产与交付")
    historical = _document_section(checklist, "历史交付与治理")
    assert {"架构子计划.md", "当前工作清单.md", "exec/工程基线-1.0.md"} <= set(
        _MARKDOWN_LINK.findall(plan)
    )
    assert {"架构主计划.md", "架构子计划.md"} <= set(_MARKDOWN_LINK.findall(route))
    assert any(link.startswith("架构主计划.md#") for link in _MARKDOWN_LINK.findall(route))
    assert "exec/版本交付-结果.md" in _MARKDOWN_LINK.findall(production)
    assert "archive/README.md" in _MARKDOWN_LINK.findall(historical)
    assert distribution.RELEASE_VERSION in production

    # 现行阶段出口由主计划维护，清单只导航到相应入口。
    stages = re.search(r"^### 阶段出口\n(.*?)(?=^#{1,3} |\Z)", plan, re.MULTILINE | re.DOTALL)
    assert stages is not None
    rows = [_table_cells(line) for line in stages[1].splitlines() if line.startswith("|")]
    assert rows[0] == ["阶段", "交付物", "出口与失败路线"]
    assert rows[2:]
    assert all(len(cells) == 3 and all(cells) for cells in rows[2:])
    assert "### 阶段出口\n" not in checklist

    workflow = _document_section((root / "CONTRIBUTING.md").read_text(encoding="utf-8"), "验证")
    assert "docs/design/架构主计划.md" in _MARKDOWN_LINK.findall(workflow)
    assert "docs/design/exec/广度深度拓展-结果.md" in _MARKDOWN_LINK.findall(workflow)
    for path, contents in ((plan_path, plan), (checklist_path, checklist)):
        _assert_plan_links(path, contents)


def test_aspect_interfaces_have_unique_ids_owners_and_evidence_entries() -> None:
    path = Path(__file__).resolve().parents[1] / "docs/design/架构子计划.md"
    plan = path.read_text(encoding="utf-8")
    domains = re.findall(r"^## ((D\d{2}) .+)$", plan, re.MULTILINE)
    assert [owner for _, owner in domains] == [f"D{number:02}" for number in range(1, 26)]
    ids = set()
    for heading, owner in domains:
        section = _document_section(plan, heading)
        rows = [_table_cells(line) for line in section.splitlines() if line.startswith("|")]
        assert rows[0] == [
            "方面接口",
            "合法观察候选",
            "国家机会与原版接入",
            "实际后果与反馈",
            "证据入口",
        ], owner
        assert rows[2:], owner
        for cells in rows[2:]:
            assert len(cells) == 5, (owner, cells)
            assert all(cells), (owner, cells)
            aspect, _, _, _, evidence = cells
            parsed = _ASPECT_ID.fullmatch(aspect)
            assert parsed is not None, (owner, aspect)
            assert parsed[1] == owner, (owner, aspect)
            assert aspect not in ids, aspect
            ids.add(aspect)
            # 待证入口也可用原版字段或文件定位，实际读权由对应证据独立验收。
            assert _MARKDOWN_LINK.search(evidence) or re.search(r"`[^`]+`", evidence), aspect
    assert "架构主计划.md" in _MARKDOWN_LINK.findall(plan)
    _assert_plan_links(path, plan)


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
