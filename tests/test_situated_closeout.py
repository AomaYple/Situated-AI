"""D11--D13 静态工程收口辅助合同。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from tools.ci import situated_closeout

pytestmark = pytest.mark.unit


def test_生产文件编码合同拒绝BOM_CR和非法UTF8(tmp_path) -> None:
    root = tmp_path / "mod"
    (root / "common").mkdir(parents=True)
    (root / "common" / "good.txt").write_bytes(b"good = {}\n")
    (root / "common" / "bom.txt").write_bytes(b"\xef\xbb\xbfbad\n")
    (root / "common" / "crlf.txt").write_bytes(b"bad\r\n")
    (root / "common" / "invalid.txt").write_bytes(b"\xff\n")

    violations = situated_closeout.production_encoding_violations(root)

    assert {(item["path"], item["reason"]) for item in violations} == {
        ("common/bom.txt", "UTF-8 BOM"),
        ("common/crlf.txt", "CR/CRLF"),
        ("common/invalid.txt", "不是 UTF-8"),
    }


def test_候选包拒绝探针缓存日志和Python运行态() -> None:
    names = (
        ".metadata/metadata.json",
        "common/ai_strategies/00_default_strategy.txt",
        "common/probes/temporary.txt",
        "common/scripted_effects/cache_values.txt",
        "debug.log",
        "tools/out/report.json",
        "scripts/build.py",
    )

    assert situated_closeout.package_exclusion_violations(names) == [
        "common/probes/temporary.txt",
        "common/scripted_effects/cache_values.txt",
        "debug.log",
        "scripts/build.py",
        "tools/out/report.json",
    ]


def test_当前生产metadata登记ConsumerIR唯一owner() -> None:
    result = situated_closeout.consumer_ir_owner_report()

    assert result["issues"] == []
    assert result["writer_count"] > 0
    owners = result["field_owners"]
    assert owners["diplomatic_play_neutrality"] == "situated_kernel"
    assert owners["change_law_chance"] == "situated_kernel"
    assert owners["recklessness"] == "situated_kernel"
    assert "consumer_adapters" in set(owners.values())


def test_收口报告保持静态范围且可写出稳定JSON(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(situated_closeout, "PRODUCTION", tmp_path / "mod")
    monkeypatch.setattr(situated_closeout.distribution, "check_generation_lock", lambda: None)
    monkeypatch.setattr(
        situated_closeout.distribution,
        "read_production_files",
        lambda: {"common/a.txt": "a = {}\n"},
    )
    monkeypatch.setattr(
        situated_closeout,
        "consumer_ir_owner_report",
        lambda: {"issues": [], "field_owners": {"field": "owner"}, "writer_count": 1},
    )
    monkeypatch.setattr(
        situated_closeout.repo_hygiene,
        "report",
        lambda root: {
            "schema": 1,
            "root": str(root),
            "excluded_roots": [],
            "violation_count": 0,
            "violations": [],
        },
    )
    monkeypatch.setattr(
        situated_closeout,
        "plan_gate",
        lambda _root: {
            "status": "blocked",
            "ready": False,
            "engineering_ready": False,
            "stage": "D0",
            "reason": "测试中的未闭合范围",
            "discovered": 1,
            "pending": 1,
            "parse_failures": [],
            "scope_hash": "a" * 64,
            "evidence": "static_check",
        },
    )
    (tmp_path / "mod" / "common").mkdir(parents=True)
    (tmp_path / "mod" / "common" / "a.txt").write_bytes(b"a = {}\n")

    result = situated_closeout.report(root=tmp_path, production=tmp_path / "mod")

    assert result["status"] == "complete"
    assert result["delivery_ready"] is False
    assert all(result["checks"].values())
    assert result["scope"].startswith("静态工程收口")
    assert json.dumps(result, ensure_ascii=False, sort_keys=True)


def test_计划门保留原版pending但仍由unknown范围阻止最终交付(tmp_path, monkeypatch) -> None:
    class Inventory:
        pending_count = 2
        parse_failures = ()
        discovered_count = 3
        legal_count = 1
        unexposed_count = 0
        unknown_scopes = ("surface-a", "surface-b")
        scope_hash = "b" * 64
        capability_counts = {"observation": 1}

    def discover() -> Inventory:
        return Inventory()

    monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", discover)

    result = situated_closeout.plan_gate(tmp_path)

    assert result["status"] == "blocked"
    assert result["stage"] == "D0"
    assert result["pending"] == 2
    assert result["unknown_scopes"] == 2


@pytest.fixture
def closed_plan(tmp_path, monkeypatch):
    """独立临时计划及逐阶段 JSON 收据；不会修改真实计划或生产文件。"""

    plan_path = tmp_path / situated_closeout.PLAN_PATH
    plan_path.parent.mkdir(parents=True)
    sections = []
    for stage, dependencies in situated_closeout.STAGE_DEPENDENCIES.items():
        step = f"{stage}.04" if stage == "D13" else f"{stage}.01"
        sections.append(
            f"## {stage}：测试阶段\n\n- **状态：** `verified`。\n"
            f"- **依赖：** {'、'.join(dependencies) or '无'}。\n\n"
            f"| {step} | 独立见证 | 合同 | 反例 |\n"
        )
        data: dict[str, Any] = {
            "stage_id": stage,
            "step_id": stage,
            "status": "verified",
            "input_hashes": {
                "scope": "b" * 64,
                **{
                    dependency: hashlib.sha256(
                        (plan_path.parent / f"{dependency}-结果.md").read_bytes()
                    ).hexdigest()
                    for dependency in dependencies
                },
            },
            "output_paths": ["mod/common/a.txt"],
            "evidence_ids": ["tests/test_situated_closeout.py::independent_witness"],
            "dependencies": list(dependencies),
            "failures": [],
            "scope_hash": "b" * 64,
            "scope_status": "verified",
            "pending": [],
            "blocked": [],
            "unclassified": [],
            "rows": [],
        }
        data["receipts"] = [
            {
                **{
                    key: data[key]
                    for key in (
                        "step_id",
                        "status",
                        "input_hashes",
                        "output_paths",
                        "evidence_ids",
                        "dependencies",
                        "failures",
                    )
                },
                "step_id": step,
            }
        ]
        _write_receipt(tmp_path, stage, data)
    plan_path.write_text("\n".join(sections), encoding="utf-8")

    @dataclass(frozen=True, slots=True)
    class CandidateInventory:
        pending_count: int = 0
        unknown_scopes: tuple[str, ...] = ()
        parse_failures: tuple[str, ...] = ()
        discovered_count: int = 2
        legal_count: int = 1
        unexposed_count: int = 1
        capability_counts: dict[str, int] = field(default_factory=lambda: {"observation": 0})
        scope_hash: str = "b" * 64

    monkeypatch.setattr(
        situated_closeout.vanilla_inventory,
        "discover",
        CandidateInventory,
    )
    monkeypatch.setattr(situated_closeout.distribution, "check_generation_lock", lambda: None)
    monkeypatch.setattr(
        situated_closeout.distribution,
        "read_production_files",
        lambda: {"common/a.txt": "a = {}\n"},
    )
    monkeypatch.setattr(
        situated_closeout,
        "consumer_ir_owner_report",
        lambda: {"issues": [], "field_owners": {"field": "owner"}, "writer_count": 1},
    )
    monkeypatch.setattr(
        situated_closeout.repo_hygiene, "report", lambda _root: {"violation_count": 0}
    )
    (tmp_path / "mod/common").mkdir(parents=True)
    (tmp_path / "mod/common/a.txt").write_bytes(b"a = {}\n")
    return tmp_path


def _write_receipt(root, stage, data) -> None:
    (root / f"docs/design/exec/{stage}-结果.md").write_text(
        f"# {stage}\n\n状态：`{data['status']}`。\n\n```json\n"
        + json.dumps(data, ensure_ascii=False)
        + "\n```\n",
        encoding="utf-8",
    )


def _read_receipt(root, stage):
    text = (root / f"docs/design/exec/{stage}-结果.md").read_text(encoding="utf-8")
    return json.loads(text.split("```json\n")[1].split("\n```")[0])


@pytest.fixture
def engineering_candidate(closed_plan):
    """D0--D13 全部闭合，但 D14 尚未发布且没有交付收据。"""

    (closed_plan / "docs/design/exec/D14-结果.md").unlink()
    path = closed_plan / situated_closeout.PLAN_PATH
    plan = path.read_text(encoding="utf-8")
    prefix, delivery = plan.split("## D14：", 1)
    path.write_text(
        prefix + "## D14：" + delivery.replace("`verified`", "`not_started`"),
        encoding="utf-8",
    )
    return closed_plan


def test_工程候选可进入交付但未发布不算最终完成(engineering_candidate, capsys) -> None:
    arguments = [
        "--root",
        str(engineering_candidate),
        "--production",
        str(engineering_candidate / "mod"),
    ]

    assert situated_closeout.main([*arguments, "--require-engineering"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["engineering_complete"] is True
    assert result["delivery_complete"] is False
    assert result["delivery_ready"] is False
    assert result["plan_gate"]["engineering_status"] == "ready"
    assert result["plan_gate"]["status"] == "blocked"
    receipts = result["plan_gate"]["stage_receipts"]
    assert receipts["missing_receipts"] == ["D14"]
    assert receipts["engineering_unfinished_stages"] == []

    assert situated_closeout.main([*arguments, "--require-plan"]) == 1
    assert json.loads(capsys.readouterr().out)["delivery_complete"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "unknown",
        "parse_failure",
        "inventory_failure",
        "inventory_scope",
        "missing_engineering_receipt",
        "unfinished_engineering_receipt",
        "dependency",
        "stale_hash",
        "receipt_scope",
        "unclassified",
        "blocked",
        "failed_static_check",
    ],
)
def test_工程入口保留范围依赖功能和静态硬门(
    engineering_candidate, monkeypatch, capsys, kind
) -> None:
    root = engineering_candidate
    if kind in {"unknown", "parse_failure", "inventory_scope"}:
        base = situated_closeout.vanilla_inventory.discover()
        inventory = SimpleNamespace(
            pending_count=base.pending_count,
            unknown_scopes=base.unknown_scopes,
            parse_failures=base.parse_failures,
            discovered_count=base.discovered_count,
            legal_count=base.legal_count,
            unexposed_count=base.unexposed_count,
            capability_counts=base.capability_counts,
            scope_hash=base.scope_hash,
        )
        if kind == "unknown":
            inventory.unknown_scopes = ("unverified-actor",)
        elif kind == "parse_failure":
            inventory.parse_failures = ("unparsed.txt",)
        else:
            inventory.scope_hash = "c" * 64
        monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", lambda: inventory)
    elif kind == "inventory_failure":

        def fail_inventory():
            raise ValueError("独立盘点失败")

        monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", fail_inventory)
    elif kind == "missing_engineering_receipt":
        (root / "docs/design/exec/D13-结果.md").unlink()
    elif kind == "failed_static_check":
        (root / "mod/common/a.txt").write_bytes(b"bad\r\n")
    else:
        data = _read_receipt(root, "D13")
        if kind == "unfinished_engineering_receipt":
            data["status"] = "in_progress"
        elif kind == "dependency":
            data["dependencies"] = []
        elif kind == "stale_hash":
            data["input_hashes"]["D12"] = "0" * 64
        elif kind == "receipt_scope":
            data["scope_hash"] = "c" * 64
        else:
            data[kind] = ["unresolved-facet"]
        _write_receipt(root, "D13", data)

    assert (
        situated_closeout.main(
            ["--root", str(root), "--production", str(root / "mod"), "--require-engineering"]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["engineering_complete"] is False
    assert result["delivery_complete"] is False
    if kind == "failed_static_check":
        assert result["plan_gate"]["engineering_ready"] is True
        assert result["checks"]["production_encoding"] is False
    else:
        assert result["plan_gate"]["engineering_ready"] is False


def test_阶段摘要使用stage_id时仍按StageReceipt校验() -> None:
    data = {
        "stage_id": "D0",
        "status": "in_progress",
        "input_hashes": {"scope": "a" * 64},
        "output_paths": ["docs/design/exec/D0-结果.md"],
        "evidence_ids": ["static-check"],
        "dependencies": [],
        "failures": [],
    }

    assert situated_closeout._receipt_issues(data, "D0") == ["status=in_progress"]


def test_缺任何阶段收据均不得因D0未知清零而交付(closed_plan) -> None:
    for stage in situated_closeout.STAGE_DEPENDENCIES:
        (closed_plan / f"docs/design/exec/{stage}-结果.md").unlink()

    result = situated_closeout.report(root=closed_plan, production=closed_plan / "mod")

    assert all(result["checks"].values())
    assert result["plan_gate"]["unknown_scopes"] == 0
    assert result["plan_gate"]["status"] == "blocked"
    assert result["delivery_ready"] is False
    assert result["plan_gate"]["stage_receipts"]["missing_receipts"] == [f"D{i}" for i in range(15)]


def test_完整真实收据依赖和功能门闭合才允许交付(closed_plan) -> None:
    result = situated_closeout.report(root=closed_plan, production=closed_plan / "mod")

    assert result["plan_gate"]["status"] == "ready"
    assert result["engineering_complete"] is True
    assert result["delivery_complete"] is True
    assert result["delivery_ready"] is True
    assert result["plan_gate"]["stage_receipts"]["stages"]["D9"]["dependencies"] == [
        "D6",
        "D7",
        "D8",
    ]


@pytest.mark.parametrize("status", ["unknown", "not_started", "in_progress", "blocked", "rejected"])
@pytest.mark.parametrize("stage", ["D0", "D11", "D14"])
def test_阶段未完成即使其他门全绿仍阻止交付(closed_plan, stage, status) -> None:
    data = _read_receipt(closed_plan, stage)
    data["status"] = status
    _write_receipt(closed_plan, stage, data)

    result = situated_closeout.report(root=closed_plan, production=closed_plan / "mod")

    gate = result["plan_gate"]
    assert all(result["checks"].values())
    assert gate["status"] == "blocked"
    assert stage in gate["stage_receipts"]["unfinished_stages"]
    assert result["engineering_complete"] is (stage == "D14")
    assert result["delivery_ready"] is False
    if stage == "D11":
        assert gate["stage_receipts"]["stages"]["D14"]["dependency_failures"]


def test_只有Markdown_verified不能代替可核验收据(closed_plan) -> None:
    path = closed_plan / "docs/design/exec/D0-结果.md"
    path.write_text("# D0\nstatus: verified\n", encoding="utf-8")

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["status"] == "blocked"
    assert gate["stage_receipts"]["stages"]["D0"]["status"] == "verified"
    assert gate["stage_receipts"]["stages"]["D0"]["ready"] is False


@pytest.mark.parametrize(
    "kind", ["pending", "missing_step", "failed_gate", "dependency", "stale_hash", "scope"]
)
def test_功能与依赖反例阻止静态全绿候选交付(closed_plan, kind) -> None:
    data = _read_receipt(closed_plan, "D12")
    if kind == "pending":
        data["pending_count"] = 0
        data["rows"] = [{"surface_id": "still-unfinished", "status": "pending"}]
    elif kind == "missing_step":
        data["receipts"] = []
    elif kind == "failed_gate":
        data["receipts"][0]["status"] = "blocked"
    elif kind == "dependency":
        data["dependencies"] = []
    elif kind == "stale_hash":
        data["input_hashes"]["D11"] = "0" * 64
    else:
        data["scope_hash"] = "c" * 64
    _write_receipt(closed_plan, "D12", data)

    result = situated_closeout.report(root=closed_plan, production=closed_plan / "mod")

    assert all(result["checks"].values())
    assert result["plan_gate"]["status"] == "blocked"
    assert result["delivery_ready"] is False


def test_D0未知状态且其余收据缺失时公开未知而不归零(closed_plan) -> None:
    for index in range(1, 15):
        (closed_plan / f"docs/design/exec/D{index}-结果.md").unlink()
    (closed_plan / "docs/design/exec/D0-结果.md").write_text(
        "# D0\nstatus: unknown\n", encoding="utf-8"
    )

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["status"] == "blocked"
    assert gate["stage_receipts"]["stages"]["D0"]["status"] == "unknown"
    assert gate["stage_receipts"]["missing_receipts"] == [f"D{i}" for i in range(1, 15)]


@pytest.mark.parametrize("stage", ["D0", "D11", "D14"])
def test_仅缺单个阶段收据也阻止最终交付(closed_plan, stage) -> None:
    (closed_plan / f"docs/design/exec/{stage}-结果.md").unlink()

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["status"] == "blocked"
    assert gate["stage_receipts"]["missing_receipts"] == [stage]
    assert gate["engineering_ready"] is (stage == "D14")


def test_盘点实现pending不阻止范围门但解析失败仍阻止(closed_plan, monkeypatch) -> None:
    inventory = situated_closeout.vanilla_inventory.discover()
    object.__setattr__(inventory, "pending_count", 1)
    monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", lambda: inventory)

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["stage_receipts"]["ready"] is True
    assert gate["unknown_scopes"] == 0
    assert gate["status"] == "ready"


def test_盘点解析失败仍阻止范围门(closed_plan, monkeypatch) -> None:
    inventory = situated_closeout.vanilla_inventory.discover()
    object.__setattr__(inventory, "parse_failures", ("unparsed.txt",))
    monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", lambda: inventory)

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["stage_receipts"]["ready"] is True
    assert gate["unknown_scopes"] == 0
    assert gate["status"] == "blocked"


def test_require_plan退出码不能被静态complete覆盖(closed_plan, capsys) -> None:
    (closed_plan / "docs/design/exec/D14-结果.md").unlink()
    arguments = ["--root", str(closed_plan), "--production", str(closed_plan / "mod")]

    assert situated_closeout.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["delivery_ready"] is False
    assert situated_closeout.main([*arguments, "--require-plan"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "complete"
    assert result["delivery_ready"] is False


def test_计划状态未完成不能被伪造verified收据覆盖(closed_plan) -> None:
    path = closed_plan / situated_closeout.PLAN_PATH
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("`verified`", "`not_started`"), encoding="utf-8")

    gate = situated_closeout.plan_gate(closed_plan)

    assert gate["status"] == "blocked"
    assert gate["stage_receipts"]["stages"]["D11"]["plan_status"] == "not_started"
