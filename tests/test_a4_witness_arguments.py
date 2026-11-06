"""Real long pytest selections retain exact identities and reject argv injection."""

from __future__ import annotations

import copy

import pytest

from tools.ci import a4_discovery, a4_scope


@pytest.fixture(scope="module")
def long_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("long-witness")
    (root / "tests").mkdir()
    identifiers = [f"case_{index}_" + "x" * 120 for index in range(300)]
    source = root / "tests/test_long.py"
    source.write_text(
        "import pytest\n@pytest.mark.parametrize('index', range(300), ids="
        + repr(identifiers)
        + ")\ndef test_real(index):\n    assert 0 <= index < 300\n",
        encoding="utf8",
    )
    nodes = [f"tests/test_long.py::test_real[{identity}]" for identity in identifiers]
    sources = a4_scope.Sources(root)
    bindings = [
        sources.reference("tests/test_long.py"),
        sources.reference("tests/test_long.py", "test_real", "python"),
    ]
    receipt = a4_scope.run_tests(root, nodes, bindings, root / "evidence")
    return root, receipt, bindings


def test_real_long_selection_executes_all_cases_and_replays_exactly(long_run):
    root, receipt, bindings = long_run
    assert receipt["exit_code"] == 0
    assert not receipt["failed"]
    assert len(receipt["passed"]) == 300
    assert set(receipt["selection"]) == set(receipt["passed"])
    assert receipt["command"][-2].startswith("@")
    assert a4_scope.witness_command_refs(a4_scope.Sources(root), receipt)
    path = root / "receipt.json"
    a4_discovery.write_json(path, receipt)
    sources = a4_scope.Sources(root)
    a4_scope.verify_receipt(
        sources,
        {"id": receipt["id"], "path": "receipt.json", "sha256": sources.hash("receipt.json")},
        bindings,
        receipt["selection"],
    )


@pytest.mark.parametrize(
    "fault", ["tampered", "missing", "newline", "extra_cli", "unbound", "outside"]
)
def test_long_selection_cannot_hide_changed_arguments(long_run, fault):
    root, original, _ = long_run
    receipt = copy.deepcopy(original)
    overrides = {}
    if fault == "tampered":
        overrides["evidence/selection.args"] = b"tests/test_long.py::test_real\n--maxfail=1\n"
    elif fault == "missing":
        receipt["command"][-2] = "@" + str(root / "missing.args")
    elif fault == "newline":
        receipt["selection"][0] += "\n--override-ini=addopts=-x"
    elif fault == "extra_cli":
        receipt["command"].insert(-1, "--maxfail=1")
    elif fault == "unbound":
        receipt["bindings"] = [
            ref for ref in receipt["bindings"] if not ref["path"].endswith(".args")
        ]
    else:
        receipt["command"][-2] = "@" + str(root.parent / "outside.args")
    with pytest.raises((ValueError, OSError), match=r"argument|command|selection|missing"):
        a4_scope.witness_command_refs(a4_scope.Sources(root, overrides), receipt)


def test_argument_file_rejects_newline_before_process_start(long_run):
    root, original, bindings = long_run
    nodes = list(original["selection"])
    nodes[0] += "\n--maxfail=1"
    with pytest.raises(ValueError, match="newline"):
        a4_scope.run_tests(root, nodes, bindings, root / "injection")


def test_short_selection_keeps_original_direct_command(long_run):
    root, original, bindings = long_run
    receipt = a4_scope.run_tests(root, original["selection"][:1], bindings, root / "short")
    assert receipt["exit_code"] == 0
    assert receipt["passed"] == original["selection"][:1]
    assert receipt["command"][-2] == original["selection"][0]
    assert not a4_scope.witness_command_refs(a4_scope.Sources(root), receipt)
