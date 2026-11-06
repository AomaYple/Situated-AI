"""Independent counterexamples for historical/current classification separation."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tools.ci import a4_classify as classify
from tools.ci.a4_scope import Sources


def _writers():
    return {
        "migration_writers": {
            "writer:construction": {
                "source": "mod/decisions/information.toml",
                "definition": "remaining_industrial_construction_need",
                "actor": "root",
                "target": "none",
                "operation": "multiply",
                "semantics": {
                    "predicates": [{"fact": "tools_balance"}],
                    "legacy_action": {
                        "predicates": ["old"],
                        "contribution_group": "construction_need",
                    },
                },
                "semantic_ir_sha256": "a" * 64,
                "cause_ids": ["construction_need"],
            },
            "writer:school": {
                "source": "mod/decisions/information.toml",
                "definition": "school_need",
                "actor": "root",
                "target": "none",
                "operation": "multiply",
                "semantics": {"predicates": [{"fact": "literacy"}]},
                "semantic_ir_sha256": "c" * 64,
                "cause_ids": ["education_need"],
            },
        },
        "migration_files": {"common/ai_strategies/00_default_strategy.txt": {}},
    }


def _changed():
    before = _writers()
    after = deepcopy(before)
    writer = after["migration_writers"]["writer:construction"]
    writer["semantic_ir_sha256"] = "b" * 64
    writer["semantics"]["predicates"] = [{"fact": "tools_balance", "op": "<", "value": 0}]
    writer["semantics"]["legacy_action"].update(
        predicates=["tools_short"], contribution_group="construction_supply_need"
    )
    writer["cause_ids"] = ["construction_supply_need"]
    declarations = [
        {
            "writer_id": "writer:construction",
            "before": "a" * 64,
            "after": "b" * 64,
            "reason": "Keep independent tools and recovery causes",
            "witness_nodes": [
                "tests/test_a4_construction_ports.py::test_recovery_exit_removes_only_independent_recovery"
            ],
        }
    ]
    return before, after, declarations


def test_current_refresh_requires_exact_new_semantics_and_independent_witnesses():
    before, after, declarations = _changed()
    assert classify.current_differences(before, after, declarations) == ["writer:construction"]
    assert classify.current_differences(before, before, []) == []
    for field, value in (
        ("before", "d" * 64),
        ("after", "a" * 64),
        ("reason", ""),
        ("witness_nodes", []),
    ):
        broken = deepcopy(declarations)
        broken[0][field] = value
        with pytest.raises(ValueError, match="independent witnesses"):
            classify.current_differences(before, after, broken)
    with pytest.raises(ValueError, match="independent witnesses"):
        classify.current_differences(before, after, [])
    with pytest.raises(ValueError, match="coverage"):
        classify.current_differences(before, before, declarations)


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "target",
        "operation",
        "evaluation_context",
        "reader_context_bindings",
        "native_parent_ids",
        "fact_key_bindings",
    ],
)
def test_current_refresh_rejects_role_scope_and_native_permission_drift(field):
    before, after, declarations = _changed()
    after["migration_writers"]["writer:construction"][field] = "unreviewed"
    with pytest.raises(
        ValueError, match=r"authority drift|fact/object binding drift|reader scope/role"
    ):
        classify.current_differences(before, after, declarations)


def test_current_refresh_rejects_dropped_ids_and_unrelated_semantic_changes():
    before, after, declarations = _changed()
    after["migration_writers"].pop("writer:school")
    with pytest.raises(ValueError, match="writer IDs"):
        classify.current_differences(before, after, declarations)
    before, after, declarations = _changed()
    after["migration_writers"]["writer:school"]["semantics"]["predicates"] = []
    with pytest.raises(ValueError, match="unrelated semantic drift"):
        classify.current_differences(before, after, declarations)


class _TextSources:
    root = Path()

    def __init__(self, texts):
        self.texts = texts

    def read(self, path):
        return self.texts[path].encode()


def test_current_native_protection_preserves_complete_tail_parent_and_sibling():
    path = "mod/common/ai_strategies/00_default_strategy.txt"
    original = (
        "ai_strategy_default = {\nwanted_construction_output = {\n"
        "add = 10\nmultiply = { value = 1 subtract = diplomatic_pact_expense_ratio }\n"
        "if = { limit = { total_population <= 250000 } multiply = 0 }\n"
        "# SITAI BEGIN information:wanted_construction_output\n"
        "multiply = 1.1\n# SITAI END information:wanted_construction_output\n"
        "}\nother_field = { value = 2 }\n}\n"
    )
    changed = original.replace("multiply = 1.1", "multiply = 1.22")
    values: dict[str, Any] = {"migration_files": {path.removeprefix("mod/"): {}}}
    classify.protect_current_native(
        _TextSources({path: changed}), _TextSources({path: original}), values
    )
    for needle, replacement in (
        ("multiply = 0", "multiply = 1"),
        ("subtract = diplomatic_pact_expense_ratio", "subtract = 0"),
        ("other_field = { value = 2 }", "other_field = { value = 3 }"),
        ("ai_strategy_default", "ai_strategy_other"),
    ):
        broken = changed.replace(needle, replacement)
        with pytest.raises(ValueError, match="tail/parent/sibling"):
            classify.protect_current_native(
                _TextSources({path: broken}), _TextSources({path: original}), values
            )


def test_pending_current_migration_does_not_inherit_historical_passes():
    class Sources:
        def json(self, path):
            assert path == classify.MIGRATION_PATH
            return {
                "objectives": {
                    "old:construction": {"witness_nodes": ["tests/test_old.py::test_old"]}
                }
            }

    values = {"predecessors": {"old:construction": {"current_writer_ids": ["writer:construction"]}}}
    actual = classify.migration_acceptance(
        Sources(),
        values,
        replay=False,
        receipt_path=None,
        extra_nodes=("tests/test_current.py::test_current",),
    )
    assert actual["old:construction"]["migration_status"] == "pending_current_witnesses"
    assert actual["old:construction"]["receipt"] is None
    assert actual["old:construction"]["witness_nodes"] == [
        "tests/test_current.py::test_current",
        "tests/test_old.py::test_old",
    ]
    with pytest.raises(ValueError, match="pending migration"):
        classify.migration_acceptance(Sources(), values, replay=True, receipt_path=None)


@pytest.mark.parametrize("first", ["pdx.decision_rules", "pdx.situated", "pdx.decision_interfaces"])
def test_public_situated_imports_have_no_first_import_cycle(first):
    code = (
        "import importlib; "
        f"importlib.import_module({first!r}); "
        "import pdx.situated as package; "
        "from pdx.situated import audit, compiler, programs, ActionCard, SituatedModel; "
        "assert audit is importlib.import_module('pdx.situated.audit'); "
        "assert compiler is importlib.import_module('pdx.situated.compiler'); "
        "assert programs is importlib.import_module('pdx.situated.programs'); "
        "assert SituatedModel is compiler.SituatedModel; "
        "assert package.load_model is compiler.load_model; "
        "assert ActionCard.__name__ == 'ActionCard'"
    )
    process = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr


def _intake_sources(root):
    test = root / "tests/test_current.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_current_B_contract():\n    return True\n", encoding="utf8")
    (root / "current.zip").write_bytes(b"current package identity")
    sources = Sources(root)
    node = "tests/test_current.py::test_current_B_contract"
    intake = {
        "schema": 1,
        "historical_commit": "a" * 40,
        "package": sources.reference("current.zip"),
        "status": "pending",
        "receipt_path": "pending",
        "witness_nodes": [node],
        "crosscheck_nodes": [node],
        "changes": [],
    }
    path = root / classify.CURRENT_INTAKE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(intake), encoding="utf8")
    return intake


def test_current_intake_refuses_old_passes_missing_witness_and_stale_package(tmp_path):
    intake = _intake_sources(tmp_path)
    assert classify.current_intake(Sources(tmp_path))["status"] == "pending"
    for changes, message in (
        ({"receipt_path": classify.MIGRATION_RECEIPT}, "pending current"),
        ({"status": "verified", "receipt_path": classify.MIGRATION_RECEIPT}, "distinct current"),
        ({"witness_nodes": []}, "independent current witness"),
        ({"witness_nodes": ["tests/test_current.py::test_missing"]}, "missing python"),
    ):
        broken = {**intake, **changes}
        (tmp_path / classify.CURRENT_INTAKE).write_text(json.dumps(broken), encoding="utf8")
        with pytest.raises(ValueError, match=message):
            classify.current_intake(Sources(tmp_path))
    (tmp_path / classify.CURRENT_INTAKE).write_text(json.dumps(intake), encoding="utf8")
    (tmp_path / "current.zip").write_bytes(b"old or altered package")
    with pytest.raises(ValueError, match="stale hash"):
        classify.current_intake(Sources(tmp_path))
