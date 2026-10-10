"""冻结工程工具链的公开接口，防止收尾后的结构重整产生隐性破坏。"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pdx import cli
from pdx.snapshot import FORMAT, Snapshot, SnapshotFormatError, compare
from tools.ci.run_check import BASELINE_COMMANDS, COMMANDS


def test_snapshot_format_and_shape_are_stable() -> None:
    snapshot = Snapshot(version={"caligula_branch": "test"}, sections={}, compact=True)
    payload = snapshot.to_dict()
    assert FORMAT == 1
    assert set(payload) >= {"格式版本", "版本", "精简", "域"}
    assert payload["格式版本"] == FORMAT
    assert payload["精简"] is True


def test_snapshot_diff_rejects_mixed_compactness() -> None:
    compact = Snapshot(compact=True)
    full = Snapshot(compact=False)
    with pytest.raises(SnapshotFormatError, match="精简快照"):
        compare(compact, full)


def test_public_cli_commands_have_help() -> None:
    runner = CliRunner()
    commands = {
        "analyze",
        "verify",
        "snapshot",
        "modgen",
        "modguard",
        "package",
        "citations",
        "preflight",
        "tables",
        "ai-surface",
    }
    for command in sorted(commands):
        result = runner.invoke(cli.app, [command, "--help"])
        assert result.exit_code == 0, f"{command}: {result.output}"
        assert command in result.output or "Usage" in result.output


def test_baseline_command_manifest_is_stable() -> None:
    assert [label for label, _ in BASELINE_COMMANDS] == [
        "依赖一致性",
        "离线断言",
        "离线生成表格",
        "Mod 生成一致性",
        "离线 Mod 门禁",
        "离线 AI 可执行面",
        "离线引用",
        "死代码审计",
    ]
    assert [command for _, command in BASELINE_COMMANDS] == [
        ["pip", "check"],
        ["pdx.cli", "verify", "--from-snapshot"],
        ["pdx.cli", "tables", "--offline"],
        ["pdx.cli", "modgen", "--check"],
        ["pdx.cli", "modguard", "--offline"],
        ["pdx.cli", "ai-surface", "--check", "--offline"],
        ["pdx.cli", "citations", "--offline"],
        ["tools.ci.deadcode_audit", "--check"],
    ]


def test_offline_test_runner_keeps_marker_as_one_argument() -> None:
    assert COMMANDS["test-offline"] == ["pytest", "-m", "not integration and not benchmark"]
