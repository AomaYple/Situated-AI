"""D11--D13 静态工程收口辅助合同。"""

from __future__ import annotations

import json

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
        lambda: {
            "status": "blocked",
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


def test_计划门在原版范围有pending时阻止最终交付(monkeypatch) -> None:
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

    result = situated_closeout.plan_gate()

    assert result["status"] == "blocked"
    assert result["stage"] == "D0"
    assert result["pending"] == 2
    assert result["unknown_scopes"] == 2
