"""Snapshot verification preserves exact JSON text and complete failure behavior."""

from __future__ import annotations

import json
from typing import Any

import pytest
from _helpers import run_cli

from pdx import cli, snapshot

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            {"名字": ["真实原版", '引号"和\n换行', "😀"]},
            {"名字": ["真实原版", '引号"和\n换行', "😀"]},
        ),
        ({"b": ["same"], "a": ["value"]}, {"a": ["value"], "b": ["same"]}),
        ({"a": ["prefix"]}, {"a": ["prefix", "tail"]}),
        ({"a": ["prefix", "tail"]}, {"a": ["prefix"]}),
        ({"a": ["first", "second"]}, {"a": ["second", "first"]}),
        ({"a": 1}, {"a": 1.0}),
        ({"a": "a"}, {"a": "aa"}),
        ({"a": "aa"}, {"a": "a"}),
    ],
)
def test_streamed_comparison_matches_complete_json_text(first, second):
    encoded = json.dumps(first, ensure_ascii=False, indent=1, sort_keys=True)
    other = json.dumps(second, ensure_ascii=False, indent=1, sort_keys=True)
    assert cli._matches_json_text(encoded, second) is (encoded == other)


@pytest.mark.parametrize("expected", ["", '{"a": []}\n', '{"a": []}extra'])
def test_streamed_comparison_checks_complete_encoded_length(expected):
    value: dict[str, list[object]] = {"a": []}
    assert cli._matches_json_text(expected, value) is (
        expected == json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True)
    )


@pytest.mark.parametrize("error", ["unsupported", "circular"])
def test_initial_difference_does_not_hide_later_encoding_error(error):
    value: dict[str, Any] = {"a": "different", "z": []}
    if error == "unsupported":
        value["z"].append(object())
    else:
        value["z"].append(value)
    with pytest.raises((TypeError, ValueError)) as complete:
        json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True)
    with pytest.raises(type(complete.value), match=str(complete.value)):
        cli._matches_json_text('{"a": "other"}', value)


@pytest.mark.parametrize("equal", [True, False])
def test_snapshot_verify_keeps_output_exit_and_original_difference_details(monkeypatch, equal):
    first = snapshot.Snapshot(
        version={"v": "真实"},
        sections={"sample": {"names": ["first", "second"]}},
    )
    second = snapshot.Snapshot(
        version={"v": "真实"},
        sections={"sample": {"names": ["first", "second" if equal else "changed"]}},
    )
    pending = iter((first, second))
    monkeypatch.setattr(cli, "_require_game", lambda: None)
    monkeypatch.setattr(snapshot, "build", lambda: next(pending))
    expected_changes = snapshot.compare(first, second)

    result = run_cli("snapshot", "verify")

    assert result.exit_code == (0 if equal else 1), result.output
    assert "构建快照两次并比较" in result.output
    if equal:
        assert "两次构建结果完全一致" in result.output
        assert "域 1 个，条目总计 2" in result.output
    else:
        assert "两次构建结果不同" in result.output
        assert all(change.line() in result.output for change in expected_changes)


def test_snapshot_verify_propagates_encoding_error_before_difference_report(monkeypatch):
    class InvalidSnapshot:
        def to_dict(self):
            return {"a": "different", "z": object()}

    first = snapshot.Snapshot(sections={"a": {"name": ["unchanged"]}})
    pending = iter((first, InvalidSnapshot()))
    monkeypatch.setattr(cli, "_require_game", lambda: None)
    monkeypatch.setattr(snapshot, "build", lambda: next(pending))
    result = run_cli("snapshot", "verify")
    assert isinstance(result.exception, TypeError)
    assert "两次构建结果不同" not in result.output
