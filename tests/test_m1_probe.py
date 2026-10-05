from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdx import m1_probe


def test_strategy_text_contains_two_extreme_diplomatic_strategies() -> None:
    text = m1_probe.strategy_text()
    assert text.count("type = diplomatic") == 2
    assert f"{m1_probe.CAUTIOUS} = {{" in text
    assert f"{m1_probe.ASSERTIVE} = {{" in text
    assert "diplomatic_play_neutrality = { value = 100 }" in text
    assert "diplomatic_play_neutrality = { value = -100 }" in text
    assert "aggression = { value = 100 }" in text
    assert "aggression = { value = -1 }" in text


def test_on_actions_text_has_controlled_play_and_phase_ladder() -> None:
    text = m1_probe.on_actions_text()
    assert "on_diplomatic_play_started" in text
    assert "create_diplomatic_play" in text
    assert "target_country = c:PRU" in text
    assert "type = dp_humiliation" in text
    assert "set_strategy = ai_strategy_sitai_m1_cautious_diplomacy" in text
    assert "set_strategy = ai_strategy_sitai_m1_assertive_diplomacy" in text
    assert "PLAY_ACTIVE_INIT" in text
    assert "PLAY_ACTIVE_TARGET" in text
    assert "has_play_goal = humiliation" in text
    assert "set_variable = { name = sitai_m1_month value = 0 }" in text
    assert "set_variable = { name = sitai_m1_phase value = 0 }" in text
    assert "set_variable = { name = sitai_m1_play_created value = 1 }" in text
    assert "scope:initiator" not in text
    assert "scope:target" not in text


def test_build_outputs_utf8_lf_text() -> None:
    for rel, text in m1_probe.build().items():
        assert "\ufeff" not in text, rel
        assert "\r" not in text, rel
        assert text.endswith("\n"), rel


def test_metadata_uses_game_loader_field() -> None:
    metadata = m1_probe.metadata_text()
    payload = json.loads(metadata)
    assert payload["supported_game_version"] == "1.14.5"
    assert payload["short_description"]
    assert '"supported_game_version": "1.14.5"' in metadata
    assert '"supported_version"' not in metadata


def test_parse_rows_and_summarize_distinguish_strategy_and_behavior() -> None:
    rows = m1_probe.parse_rows(
        """
        [debug] ZZPROBE M1;PHASE;cautious;俄罗斯
        [debug] ZZPROBE M1;STRATEGY;cautious;俄罗斯
        [debug] ZZPROBE M1;PLAY_START_INIT;yes;俄罗斯
        [debug] ZZPROBE M1;PLAY_START_TARGET;yes;普鲁士
        [debug] ZZPROBE M1;CONTROL_PLAY;c:PRU;俄罗斯
        [debug] ZZPROBE M1;PLAY_TYPE;dp_humiliation;play
        [debug] ZZPROBE M1;PLAY_GOAL;humiliation;play
        """
    )
    summary = m1_probe.summarize(rows)
    assert summary["strategies"] == ["cautious"]
    assert summary["strategy_counts"] == {"cautious": 1}
    assert summary["play_start_observed"] is True
    assert summary["play_active_observed"] is False
    assert summary["control_play_observed"] is True
    assert summary["control_play_targets"] == ["c:PRU"]
    assert summary["play_types"] == ["dp_humiliation"]
    assert summary["play_goals"] == ["humiliation"]
    assert summary["behavior_evidence"] is True


@pytest.mark.parametrize("text", ["ZZPROBE AB;STRATEGY;old;RUS", "noise"])
def test_parse_rows_ignores_non_m1_rows(text: str) -> None:
    assert m1_probe.parse_rows(text) == ()
