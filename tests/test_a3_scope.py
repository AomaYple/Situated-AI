"""A3-0 冻结台账不得漏方向、引用死文件或把调查状态冒充完成。"""

from __future__ import annotations

import copy
import hashlib
import runpy
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/design/A3实施台账.toml"


def _validate(data: dict[str, Any], *, complete: bool = False) -> dict[str, int]:
    script = ROOT / "tools/ci/a3_scope.py"
    assert script.is_file(), "缺少 A3 台账校验器"
    validate = runpy.run_path(str(script))["validate_scope"]
    return validate(data, root=ROOT, require_complete=complete)


def _ledger() -> dict[str, Any]:
    assert LEDGER.is_file(), "缺少 A3 冻结台账"
    return tomllib.loads(LEDGER.read_text(encoding="utf-8"))


def test_frozen_scope_is_valid_but_not_product_complete() -> None:
    data = _ledger()
    result = _validate(data)
    assert result == {"directions": 52, "relations": 12, "contracts": 9, "pending": 73}
    with pytest.raises(ValueError, match="未完成"):
        _validate(data, complete=True)


@pytest.mark.parametrize("index", [0, 51, 52, 63, 64, 72])
def test_scope_rejects_missing_domain_relation_or_contract(index: int) -> None:
    data = _ledger()
    del data["obligations"][index]
    with pytest.raises(ValueError, match="缺失"):
        _validate(data)


def test_scope_rejects_duplicate_stable_id() -> None:
    data = _ledger()
    data["obligations"].append(copy.deepcopy(data["obligations"][0]))
    with pytest.raises(ValueError, match="重复"):
        _validate(data)


@pytest.mark.parametrize("status", ["done", "retained", "passed", "unsupported", "implemented"])
def test_scope_rejects_completion_without_production_acceptance(status: str) -> None:
    data = _ledger()
    data["obligations"][0]["status"] = status
    with pytest.raises(ValueError, match="状态"):
        _validate(data)


def test_scope_rejects_dead_production_route() -> None:
    data = _ledger()
    data["obligations"][0]["source_paths"] = ["mod/decisions/not_present.toml"]
    with pytest.raises(ValueError, match="不存在"):
        _validate(data)


def test_scope_rejects_escaped_route() -> None:
    data = _ledger()
    data["obligations"][0]["source_paths"] = ["../AGENTS.md"]
    with pytest.raises(ValueError, match="相对路径"):
        _validate(data)


@pytest.mark.parametrize(
    "field", ["question", "acceptance", "consumer_investigation", "existing_state", "gap"]
)
def test_scope_rejects_empty_investigation_contract(field: str) -> None:
    data = _ledger()
    data["obligations"][0][field] = ""
    with pytest.raises(ValueError, match="为空"):
        _validate(data)


def test_scope_rejects_unchecked_completion_evidence() -> None:
    data = _ledger()
    data["obligations"][0]["implementation_evidence"] = ["passed"]
    with pytest.raises(ValueError, match="不允许"):
        _validate(data)


def _implementation_refs() -> list[dict[str, str]]:
    refs = []
    for role, path, kind, identity in [
        ("source", "mod/decisions/actions.toml", "toml_key", "actions.fiscal_recovery"),
        ("consumer", "mod/decisions/actions.toml", "toml_key", "consumers.fiscal_neutrality"),
        (
            "witness",
            "tests/test_a3_scope.py",
            "python_symbol",
            "test_scope_rejects_dead_rule_identity",
        ),
    ]:
        refs.append(
            {
                "role": role,
                "path": path,
                "kind": kind,
                "identity": identity,
                "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
            }
        )
    return refs


def test_scope_accepts_traceable_implementation_but_keeps_other_items_pending() -> None:
    data = _ledger()
    row = data["obligations"][0]
    row.update(status="implemented", rationale="此测试仅证明引用身份校验，不签发行为结论。")
    row["evidence"] = _implementation_refs()
    assert _validate(data)["pending"] == 72
    with pytest.raises(ValueError, match="未完成"):
        _validate(data, complete=True)


def test_scope_rejects_dead_rule_identity() -> None:
    data = _ledger()
    row = data["obligations"][0]
    row.update(
        status="implemented", rationale="测试失效规则身份。", evidence=_implementation_refs()
    )
    row["evidence"][0]["identity"] = "actions.not_a_rule"
    with pytest.raises(ValueError, match="身份不存在"):
        _validate(data)


def test_scope_rejects_metadata_as_rule_identity() -> None:
    data = _ledger()
    row = data["obligations"][0]
    row.update(
        status="implemented", rationale="schema 不是实际规则。", evidence=_implementation_refs()
    )
    row["evidence"][0]["identity"] = "schema"
    with pytest.raises(ValueError, match="规则表"):
        _validate(data)


@pytest.mark.parametrize("status", ["unknown", "in_progress"])
def test_scope_keeps_unknown_and_in_progress_noncomplete(status: str) -> None:
    data = _ledger()
    data["obligations"][0]["status"] = status
    assert _validate(data)["pending"] == 73
    with pytest.raises(ValueError, match="未完成"):
        _validate(data, complete=True)


def test_scope_rejects_stale_source_identity() -> None:
    data = _ledger()
    row = data["obligations"][0]
    row.update(status="implemented", rationale="测试过期源身份。", evidence=_implementation_refs())
    row["evidence"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="哈希"):
        _validate(data)


def test_scope_rejects_missing_independent_witness() -> None:
    data = _ledger()
    row = data["obligations"][0]
    row.update(
        status="implemented", rationale="测试缺少独立见证。", evidence=_implementation_refs()[:2]
    )
    with pytest.raises(ValueError, match="witness"):
        _validate(data)
