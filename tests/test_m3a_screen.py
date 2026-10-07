from __future__ import annotations

import json
from pathlib import Path

from pdx import m3a_screen


def _report(path: Path, *, neutrality: str = "control", clean: bool = True) -> Path:
    strategy = {"control": "aa", "treatment": "bb"}[neutrality]
    rows = []
    for tag in ("RUS", "PRU"):
        for date in ("sample-1", "sample-2"):
            rows.extend(
                [
                    {"tag": tag, "kind": "UNDECIDED", "value": "yes", "date": date},
                    {"tag": tag, "kind": "ACTIVE", "value": "yes", "date": date},
                    {"tag": tag, "kind": "CAN_INIT", "value": "yes", "date": date},
                    {"tag": tag, "kind": "CAN_TARGET", "value": "no", "date": date},
                    {"tag": tag, "kind": "BACKER", "value": "no", "date": date},
                    {"tag": tag, "kind": "INIT_BACKER", "value": "no", "date": date},
                    {"tag": tag, "kind": "TARGET_BACKER", "value": "no", "date": date},
                    {
                        "tag": tag,
                        "kind": "INIT_SCORE",
                        "value": "10" if neutrality == "control" else "-15",
                        "date": date,
                    },
                ]
            )
    data = {
        "ok": clean,
        "game_version": {"caligula_branch": "release/1.14.5"},
        "loaded_save": {
            "sha256": "a" * 64,
            "header": {"observer": "yes", "version": "1.14.5"},
        },
        "mount_allowlist": ["base", "candidate"],
        "source_hashes": {
            "sitai_decision_candidate": {
                "common/ai_strategies/00_default_strategy.txt": strategy,
                "common/on_actions/a.txt": "same",
            },
            "zz_probe_decision_opportunity": {"probe.txt": "same-probe"},
        },
        "evidence": str(path.parent),
        "log_findings": {
            "errors": dict.fromkeys(m3a_screen.ERROR_KEYS, 0),
            "mod_errors": [],
            "missing_mounts": [],
            "unexpected_mounts": [],
        },
        "analysis": {"opportunity": {"rows": rows}},
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return path


def test_load_report_extracts_two_eligible_countries(tmp_path: Path) -> None:
    facts = m3a_screen.load_report(_report(tmp_path / "report.json"))
    assert facts.clean
    assert facts.checkpoint_sha256 == "a" * 64
    assert facts.countries["RUS"].eligible_active_dates == ("sample-1", "sample-2")
    assert facts.countries["PRU"].score_range == (10.0, 10.0)


def test_pair_requires_resolved_neutrality_and_reports_roles(tmp_path: Path) -> None:
    control = m3a_screen.load_report(_report(tmp_path / "control.json"))
    treatment = m3a_screen.load_report(_report(tmp_path / "treatment.json", neutrality="treatment"))
    pair = m3a_screen.pair_reports(
        control, treatment, neutrality_resolver={"aa": (0.0, -0.2), "bb": (25.0, -0.2)}.get
    )
    assert pair.qualified
    assert pair.neutrality_delta == 25.0
    assert pair.countries == ("PRU", "RUS")
    assert pair.common_eligible_active_dates == ("sample-1", "sample-2")
    assert pair.role_changes["RUS"]["BACKER"] is False
    assert pair.score_deltas["RUS"] == (-25.0, -25.0)


def test_missing_mounts_cannot_be_candidate(tmp_path: Path) -> None:
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")
    for path in (left, right):
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["mount_allowlist"]
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    pair = m3a_screen.pair_reports(
        m3a_screen.load_report(left),
        m3a_screen.load_report(right),
        neutrality_resolver={"aa": (0.0, -0.2), "bb": (25.0, -0.2)}.get,
    )
    assert not pair.qualified
    assert "mount_allowlist.missing" in pair.reasons


def test_screen_current_archive_does_not_promote_unreviewed_history() -> None:
    result = m3a_screen.screen(Path("tools/out/decisions"))
    assert result["report_count"] >= 1
    assert result["qualified_count"] == 0
    assert any(
        "mount_allowlist.missing" in reason
        for item in result["candidates"]
        for reason in item["reasons"]
    )
