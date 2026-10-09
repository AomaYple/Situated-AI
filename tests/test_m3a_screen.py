from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pdx import m3a_screen
from pdx.textio import text_bytes

CONTROL_DIGEST = hashlib.sha256(b"control").hexdigest()
TREATMENT_DIGEST = hashlib.sha256(b"treatment").hexdigest()


def _report(path: Path, *, neutrality: str = "control", clean: bool = True) -> Path:
    path = path.parent / path.stem / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    strategy = {"control": "control", "treatment": "treatment"}[neutrality]
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
    rows.extend(
        {"tag": "CONTROL", "kind": "ESCALATION", "value": "10", "date": date}
        for date in ("sample-1", "sample-2")
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
        "cleanup_errors": [],
        "progress": {"start": "1836.4.1", "activation_tick": "1836.4.1"},
        "log_findings": {
            "errors": dict.fromkeys(m3a_screen.ERROR_KEYS, 0),
            "mod_errors": [],
            "missing_mounts": [],
            "unexpected_mounts": [],
            "mounted": ["Mounted Data: base", "Mounted Data: candidate"],
        },
        "analysis": {"opportunity": {"rows": rows}},
    }
    deployed = {}
    for name, files in data["source_hashes"].items():
        deployed[name] = {}
        for relative, value in files.items():
            source = path.parent / "sources" / name / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            raw = value.encode("utf-8")
            source.write_bytes(raw)
            files[relative] = hashlib.sha256(raw).hexdigest()
            deployed[name][relative] = hashlib.sha256(text_bytes(value, game=True)).hexdigest()
    data["deployed_hashes"] = deployed
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
        control,
        treatment,
        neutrality_resolver={CONTROL_DIGEST: (0.0, -0.2), TREATMENT_DIGEST: (25.0, -0.2)}.get,
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
        neutrality_resolver={CONTROL_DIGEST: (0.0, -0.2), TREATMENT_DIGEST: (25.0, -0.2)}.get,
    )
    assert not pair.qualified
    assert "mount_allowlist.missing" in pair.reasons


def test_screen_current_archive_does_not_promote_unreviewed_history() -> None:
    if not any(Path("tools/out/decisions").rglob("report.json")):
        pytest.skip("本机没有历史实机归档；合成证据契约由其它用例验证")
    result = m3a_screen.screen(Path("tools/out/decisions"))
    assert result["report_count"] >= 1
    assert result["qualified_count"] == 0
    assert any(
        "mount_allowlist.missing" in reason
        for item in result["candidates"]
        for reason in item["reasons"]
    )


def _edit(path, edit):
    data = json.loads(path.read_bytes())
    edit(data)
    path.write_bytes(json.dumps(data).encode("utf-8"))


def _pair(left, right):
    return m3a_screen.pair_reports(
        m3a_screen.load_report(left),
        m3a_screen.load_report(right),
        neutrality_resolver={CONTROL_DIGEST: (0.0, 0.0), TREATMENT_DIGEST: (25.0, 0.0)}.get,
    )


@pytest.mark.parametrize("fingerprint", ["source_hashes", "deployed_hashes"])
def test_仅候选模组策略允许差异而探针同名路径必须一致(tmp_path, fingerprint):
    from dataclasses import replace

    left = m3a_screen.load_report(_report(tmp_path / "left.json"))
    right = m3a_screen.load_report(_report(tmp_path / "right.json", neutrality="treatment"))
    hashes = {name: dict(files) for name, files in getattr(right, fingerprint).items()}
    hashes["zz_probe_decision_opportunity"][m3a_screen.STRATEGY_PATH] = "f" * 64
    right = replace(right, **{fingerprint: hashes})
    ok, reasons = m3a_screen._pair_shape(left, right)
    assert not ok
    assert f"{fingerprint}.non_strategy_differs" in reasons


def test_真实行顺序与逆序得到相同资格和评分(tmp_path):
    path = _report(tmp_path / "report.json")
    first = m3a_screen.load_report(path)
    _edit(path, lambda data: data["analysis"]["opportunity"]["rows"].reverse())
    assert m3a_screen.load_report(path).countries == first.countries


def test_按样本键配对评分不会随行顺序变化(tmp_path):
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")

    def vary(data):
        for row in data["analysis"]["opportunity"]["rows"]:
            if row["kind"] == "INIT_SCORE" and row["date"] == "sample-2":
                row["value"] = "-30"
        data["analysis"]["opportunity"]["rows"].reverse()

    _edit(right, vary)
    pair = _pair(left, right)
    assert pair.qualified
    assert pair.score_deltas["RUS"] == (-25.0, -40.0)


@pytest.mark.parametrize(
    "fault",
    [
        "phase_missing",
        "phase_differs",
        "duplicate",
        "score_missing",
        "role_missing",
        "sample_missing",
        "script_error",
        "assertion",
        "mounts_missing",
        "deployed_missing",
        "cleanup_missing",
    ],
)
def test_不完整或冲突证据不能晋升合格配对(tmp_path, fault):
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")

    def damage(data):
        rows = data["analysis"]["opportunity"]["rows"]
        if fault == "phase_missing":
            rows[:] = [r for r in rows if r["tag"] != "CONTROL"]
        elif fault == "phase_differs":
            next(r for r in rows if r["tag"] == "CONTROL")["value"] = "20"
        elif fault == "duplicate":
            rows.append(dict(rows[0]))
        elif fault in {"score_missing", "role_missing"}:
            kind = "INIT_SCORE" if fault == "score_missing" else "BACKER"
            rows[:] = [r for r in rows if not (r["tag"] == "RUS" and r["kind"] == kind)]
        elif fault == "sample_missing":
            rows[:] = [r for r in rows if not (r["tag"] == "RUS" and r["date"] == "sample-1")]
        elif fault in {"script_error", "assertion"}:
            key = "Script system error!" if fault == "script_error" else "Assertion failed"
            data["log_findings"]["errors"][key] = 1
        elif fault == "mounts_missing":
            del data["log_findings"]["mounted"]
        elif fault == "deployed_missing":
            del data["deployed_hashes"]
        else:
            del data["cleanup_errors"]

    _edit(right, damage)
    pair = _pair(left, right)
    assert not pair.qualified
    assert pair.reasons
    if fault == "role_missing":
        assert pair.role_changes["RUS"]["BACKER"] is None


def test_加入后不再未决仍能观测角色差分(tmp_path):
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")

    def joined(data):
        for row in data["analysis"]["opportunity"]["rows"]:
            if row["tag"] == "RUS" and row["date"] == "sample-2":
                if row["kind"] == "UNDECIDED":
                    row["value"] = "no"
                elif row["kind"] in {"BACKER", "INIT_BACKER"}:
                    row["value"] = "yes"

    _edit(right, joined)
    assert _pair(left, right).role_changes["RUS"]["INIT_BACKER"] is True


def test_目录排序不决定控制臂与候选臂(tmp_path):
    _report(tmp_path / "a-treatment.json", neutrality="treatment")
    _report(tmp_path / "z-control.json")
    result = m3a_screen.screen(
        tmp_path, resolver={CONTROL_DIGEST: (0.0, 0.0), TREATMENT_DIGEST: (25.0, 0.0)}.get
    )
    assert result["qualified_count"] == 1
    assert result["candidates"][0]["neutrality_delta"] == 25.0


@pytest.mark.parametrize("fault", ["opposite_side", "start", "activation", "deployed"])
def test_同档同序号不足以证明同机会和同部署(tmp_path, fault):
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")

    def change(data):
        if fault == "opposite_side":
            for row in data["analysis"]["opportunity"]["rows"]:
                if row["kind"] == "CAN_INIT":
                    row["value"] = "no"
                elif row["kind"] == "CAN_TARGET":
                    row["value"] = "yes"
        elif fault == "start":
            data["progress"]["start"] = "1836.4.2"
        elif fault == "activation":
            del data["progress"]["activation_tick"]
        else:
            data["deployed_hashes"]["zz_probe_decision_opportunity"]["probe.txt"] = "f" * 64

    _edit(right, change)
    assert not _pair(left, right).qualified
