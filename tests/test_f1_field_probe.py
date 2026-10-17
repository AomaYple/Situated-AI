"""F1 四字段隔离探针的离线契约。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import f1_field_probe
from tools.probe import f1_field_observation

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from pathlib import Path


def test_四个字段和两个臂都有单一规格() -> None:
    assert set(f1_field_probe.FIELD_SPECS) == set(f1_field_probe.FIELDS)
    for field in f1_field_probe.FIELDS:
        for arm in f1_field_probe.ARMS:
            text = f1_field_probe.strategy_text(field, arm)
            assert f"type = {f1_field_probe.FIELD_SPECS[field].slot}" in text
            assert f1_field_probe.strategy_name(field, arm) in text
            assert f"{field} = {{ value = " in text


@pytest.mark.parametrize("field", f1_field_probe.FIELDS)
def test_字段探针只在国家作用域直置策略(field: str) -> None:
    text = f1_field_probe.on_actions_text(field, "candidate")
    assert "c:RUS ?= this" in text
    assert "on_game_started" not in text
    assert "on_game_started_after_lobby" not in text
    assert "has_variable = sitai_f1_field_sample" in text
    assert "set_variable = { name = sitai_f1_field_sample value = 0 }" in text
    assert "set_strategy" in text
    assert "SITAI F1 FIELD;FIELD;" in text
    assert "SITAI F1 FIELD;ARM;candidate" in text


def test_冒险度探针有受控博弈但其它字段不创建博弈() -> None:
    assert "create_diplomatic_play" in f1_field_probe.on_actions_text("recklessness", "candidate")
    for field in (
        "economic_vs_government_spending_balance",
        "subject_value",
        "become_subject_value",
    ):
        assert "create_diplomatic_play" not in f1_field_probe.on_actions_text(field, "candidate")


def test_生成物为无bom_lf且元数据明确不可直接读取() -> None:
    files = f1_field_probe.build("subject_value", "control")
    for path, text in files.items():
        assert "\ufeff" not in text, path
        assert "\r" not in text, path
        assert text.endswith("\n"), path
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["f1_observation"]["runtime_field_value"] == "unavailable"
    assert metadata["f1_observation"]["behavior_quality"] == "not_evaluated"


def test_日志解析和摘要区分策略持有与字段不可读() -> None:
    strategy = f1_field_probe.strategy_name("recklessness", "candidate")
    rows = f1_field_probe.parse_rows(
        "\n".join(
            (
                f"SITAI F1 FIELD;STRATEGY;{strategy};sample-1",
                "SITAI F1 FIELD;LOANS;no;sample-1",
                "SITAI F1 FIELD;FIELD;recklessness;sample-1",
            )
        )
    )
    summary = f1_field_probe.summarize(rows, field="recklessness", arm="candidate")
    assert summary["rows"] == 3
    assert summary["strategy_observed"] is True
    assert summary["runtime_field_value"] == "unavailable"
    assert summary["behavior_quality"] == "not_evaluated"


def test_控制候选配对比较保留上下文和未评估边界() -> None:
    control_rows = f1_field_probe.parse_rows(
        "SITAI F1 FIELD;STRATEGY;"
        f"{f1_field_probe.strategy_name('recklessness', 'control')};sample-1\n"
        "SITAI F1 FIELD;PLAY_INIT;yes;sample-1\n"
    )
    candidate_rows = f1_field_probe.parse_rows(
        "SITAI F1 FIELD;STRATEGY;"
        f"{f1_field_probe.strategy_name('recklessness', 'candidate')};sample-1\n"
        "SITAI F1 FIELD;PLAY_INIT;yes;sample-1\n"
    )
    pair = f1_field_probe.compare_summaries(
        f1_field_probe.summarize(control_rows, field="recklessness", arm="control"),
        f1_field_probe.summarize(candidate_rows, field="recklessness", arm="candidate"),
    )
    assert pair["context_equal"] is True
    assert pair["control"]["strategy_observed"] is True
    assert pair["candidate"]["strategy_observed"] is True
    assert pair["runtime_field_value"] == "unavailable"
    assert pair["behavior_quality"] == "not_evaluated"


def test_控制候选配对禁止跨字段比较() -> None:
    summary = f1_field_probe.summarize((), field="recklessness", arm="control")
    other = f1_field_probe.summarize((), field="subject_value", arm="candidate")
    with pytest.raises(ValueError, match="同一字段"):
        f1_field_probe.compare_summaries(summary, other)


def test_未知字段和臂拒绝() -> None:
    with pytest.raises(ValueError, match="未知 F1 字段"):
        f1_field_probe.validate("unknown", "control")
    with pytest.raises(ValueError, match="未知 F1 臂"):
        f1_field_probe.validate("recklessness", "unknown")


def test_诊断基线显式加入源集合(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f1_field_observation.config, "GAME", tmp_path / "game")
    captured: dict[str, Path] = {}

    def write_resource(root: Path, _game: Path) -> dict[str, str]:
        captured["resource"] = root
        return {"purpose": "diagnostic"}

    def write_decisions(root: Path, _files: dict[str, str] | None = None) -> list[Path]:
        root.mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr(
        f1_field_observation.resource_baseline,
        "write",
        write_resource,
    )
    monkeypatch.setattr(
        f1_field_observation.decision_probe,
        "build_localization_baseline",
        lambda _game: {"baseline.txt": "diagnostic\n"},
    )
    monkeypatch.setattr(
        f1_field_observation.decisions,
        "write",
        write_decisions,
    )
    sources = f1_field_observation._write_sources(
        tmp_path / "sources",
        "recklessness",
        "control",
        resource=True,
        localization=True,
    )
    assert set(sources) == {
        "zz_sitai_f1_field_observation_recklessness_control",
        "zz_sitai_resource_baseline",
        "zz_sitai_vanilla_localization_baseline",
    }
    assert captured["resource"].name == "zz_sitai_resource_baseline"


def test_报告配对入口保留字段边界(tmp_path: Path) -> None:
    control = f1_field_probe.summarize(
        f1_field_probe.parse_rows(
            "SITAI F1 FIELD;STRATEGY;"
            f"{f1_field_probe.strategy_name('recklessness', 'control')};sample-1"
        ),
        field="recklessness",
        arm="control",
    )
    candidate = f1_field_probe.summarize(
        f1_field_probe.parse_rows(
            "SITAI F1 FIELD;STRATEGY;"
            f"{f1_field_probe.strategy_name('recklessness', 'candidate')};sample-1"
        ),
        field="recklessness",
        arm="candidate",
    )
    c = tmp_path / "control.json"
    t = tmp_path / "candidate.json"
    c.write_text(json.dumps({"analysis": control}), encoding="utf-8")
    t.write_text(json.dumps({"analysis": candidate}), encoding="utf-8")
    pair = f1_field_observation.compare_reports(c, t)
    assert pair["field"] == "recklessness"
    assert pair["behavior_quality"] == "not_evaluated"


def test_配对命令不要求虚构字段参数(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    control = f1_field_probe.summarize((), field="recklessness", arm="control")
    candidate = f1_field_probe.summarize((), field="recklessness", arm="candidate")
    c = tmp_path / "control.json"
    t = tmp_path / "candidate.json"
    c.write_text(json.dumps({"analysis": control}), encoding="utf-8")
    t.write_text(json.dumps({"analysis": candidate}), encoding="utf-8")
    assert (
        f1_field_observation.main(
            ["--compare-control-report", str(c), "--compare-candidate-report", str(t)]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["field"] == "recklessness"
