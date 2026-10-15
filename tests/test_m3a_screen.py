from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from pdx import game_run, m3a_screen
from pdx.textio import text_bytes

if TYPE_CHECKING:
    from pathlib import Path

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
    data: dict[str, Any] = {
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
    deployed: dict[str, dict[str, str]] = {}
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
    logs = path.parent / "logs"
    logs.mkdir()
    (logs / "debug.log").write_bytes(b"Mounted Data: base\nMounted Data: candidate\n")
    (logs / "error.log").write_bytes(b"")
    data["log_hashes"] = game_run.hashes(logs)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return path


@pytest.mark.parametrize("damage", ["vfs", "missing", "tampered"])
def test_历史报告漏判或日志缺证不能进入合格筛选(tmp_path, damage):
    path = _report(tmp_path / "old.json")
    logs = path.parent / "logs"
    if damage == "missing":
        (logs / "error.log").unlink()
    else:
        (logs / "error.log").write_bytes(b"VFSOpen Error: missing texture\n")
    if damage == "vfs":
        data = json.loads(path.read_bytes())
        data["log_hashes"] = game_run.hashes(logs)
        game_run.write_json(path, data)
    original = path.read_bytes()
    facts = m3a_screen.load_report(path)
    assert not facts.clean
    assert (
        "log_findings.unclassified_errors" if damage == "vfs" else "log_archive.unverified"
    ) in facts.gate_reasons
    assert path.read_bytes() == original


def test_load_report_extracts_two_eligible_countries(tmp_path: Path) -> None:
    facts = m3a_screen.load_report(_report(tmp_path / "report.json"))
    assert facts.clean
    assert facts.checkpoint_sha256 == "a" * 64
    assert facts.countries["RUS"].eligible_active_dates == ("sample-1", "sample-2")
    assert facts.countries["PRU"].score_range == (10.0, 10.0)


def test_load_and_pair保留质量边界但不把unsupported当资格(tmp_path: Path) -> None:
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")
    for path, status in ((left, "unsupported"), (right, "complete")):
        data = json.loads(path.read_bytes())
        opportunity = data["analysis"]["opportunity"]
        opportunity["quality_observations"] = {
            "status": status,
            "action_cost": None if status == "unsupported" else 12.5,
            "adverse_outcome": None,
        }
        opportunity["role_timing"] = {
            "quality_improvement_proven": False,
            "countries": {"RUS": {"status": "observed"}},
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    control = m3a_screen.load_report(left)
    treatment = m3a_screen.load_report(right)
    assert control.quality_observations["status"] == "unsupported"
    assert treatment.role_timing["quality_improvement_proven"] is False
    pair = m3a_screen.pair_reports(
        control,
        treatment,
        neutrality_resolver={CONTROL_DIGEST: (0.0, -0.2), TREATMENT_DIGEST: (25.0, -0.2)}.get,
    )
    assert pair.qualified
    assert not pair.quality_ready
    assert pair.as_dict()["structural_qualified"] is True
    assert pair.as_dict()["quality_ready"] is False
    assert pair.as_dict()["quality_observations"]["control"]["action_cost"] is None


@pytest.mark.parametrize(
    ("section", "key", "value", "reason"),
    [
        ("quality_observations", "status", "NaN", "quality_observations.status_invalid"),
        (
            "quality_observations",
            "action_cost",
            "not-a-number",
            "quality_observations.action_cost_invalid",
        ),
        (
            "role_timing",
            "quality_improvement_proven",
            "yes",
            "role_timing.quality_improvement_proven_invalid",
        ),
    ],
)
def test_质量字段非法类型进入门禁而不改变历史文件(tmp_path: Path, section, key, value, reason):
    path = _report(tmp_path / "report.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["analysis"]["opportunity"][section] = {key: value}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    facts = m3a_screen.load_report(path)
    assert not facts.clean
    assert reason in facts.gate_reasons


@pytest.mark.parametrize("other", [None, "l_simp_chinese"])
def test_语言改变或缺证不属于同一冻结场景(tmp_path, other):
    left = _report(tmp_path / "left.json")
    right = _report(tmp_path / "right.json", neutrality="treatment")
    for path, language in ((left, "l_english"), (right, other)):
        data = json.loads(path.read_bytes())
        data["language"] = language
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    pair = m3a_screen.pair_reports(
        m3a_screen.load_report(left),
        m3a_screen.load_report(right),
        neutrality_resolver={CONTROL_DIGEST: (0.0, -0.2), TREATMENT_DIGEST: (25.0, -0.2)}.get,
    )
    assert not pair.qualified
    assert "language.differs_or_unknown" in pair.reasons
    assert m3a_screen.screen(tmp_path)["qualified_count"] == 0


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


@pytest.mark.parametrize("report_count", [1, 2])
def test_screen_current_archive_does_not_promote_unreviewed_history(
    tmp_path: Path, report_count: int
) -> None:
    paths = [_report(tmp_path / "left.json")]
    if report_count == 2:
        paths.append(_report(tmp_path / "right.json", neutrality="treatment"))
    for path in paths:
        data = json.loads(path.read_bytes())
        del data["mount_allowlist"]
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    original = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    result = m3a_screen.screen(tmp_path)
    assert result["report_count"] == report_count
    assert result["qualified_count"] == 0
    assert result["strict_clean_count"] == 0
    if report_count == 1:
        assert result["candidates"] == []
        assert "mount_allowlist.missing" in m3a_screen.load_report(paths[0]).gate_reasons
    else:
        assert len(result["candidates"]) == 1
        assert "mount_allowlist.missing" in result["candidates"][0]["reasons"]
    assert {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == original


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


@pytest.fixture
def complete_quality_reports(tmp_path):
    paths = (
        _report(tmp_path / "left.json"),
        _report(tmp_path / "right.json", neutrality="treatment"),
    )

    def add_quality(data):
        opportunity = data["analysis"]["opportunity"]
        opportunity["quality_observations"] = {
            "status": "complete",
            "action_cost": 12.5,
            "adverse_outcome": -2,
            "join_latency": 3,
            "leave_latency": 4.5,
            "quality_improvement_proven": True,
        }
        opportunity["role_timing"] = {"quality_improvement_proven": True}

    for path in paths:
        _edit(path, add_quality)
    return paths


def test_完整两臂缺失时延不得晋升质量就绪(complete_quality_reports):
    left, right = complete_quality_reports

    def remove_latencies(data):
        quality = data["analysis"]["opportunity"]["quality_observations"]
        del quality["join_latency"]
        del quality["leave_latency"]

    for path in (left, right):
        _edit(path, remove_latencies)
    pair = _pair(left, right)
    assert pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize(
    "field", ["action_cost", "adverse_outcome", "join_latency", "leave_latency"]
)
@pytest.mark.parametrize("mutation", ["missing", "null"])
@pytest.mark.parametrize("arm", [0, 1])
def test_任一臂质量字段缺失或null只阻止质量就绪(complete_quality_reports, field, mutation, arm):
    def remove(data):
        quality = data["analysis"]["opportunity"]["quality_observations"]
        if mutation == "missing":
            del quality[field]
        else:
            quality[field] = None

    _edit(complete_quality_reports[arm], remove)
    facts = m3a_screen.load_report(complete_quality_reports[arm])
    assert facts.clean
    pair = _pair(*complete_quality_reports)
    assert pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize(
    "field", ["action_cost", "adverse_outcome", "join_latency", "leave_latency"]
)
@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), "3"])
def test_质量数值非法有明确理由且不能质量就绪(complete_quality_reports, field, value):
    def invalidate(data):
        data["analysis"]["opportunity"]["quality_observations"][field] = value

    _edit(complete_quality_reports[1], invalidate)
    facts = m3a_screen.load_report(complete_quality_reports[1])
    assert not facts.clean
    assert f"quality_observations.{field}_invalid" in facts.gate_reasons
    pair = _pair(*complete_quality_reports)
    assert not pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize("field", ["join_latency", "leave_latency"])
def test_负时延有明确理由且不能质量就绪(complete_quality_reports, field):
    def invalidate(data):
        data["analysis"]["opportunity"]["quality_observations"][field] = -0.5

    _edit(complete_quality_reports[1], invalidate)
    facts = m3a_screen.load_report(complete_quality_reports[1])
    assert not facts.clean
    assert f"quality_observations.{field}_invalid" in facts.gate_reasons
    pair = _pair(*complete_quality_reports)
    assert not pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize("fault", ["report", "structure"])
def test_完整质量字段仍要求干净报告和结构合格(complete_quality_reports, fault):
    def damage(data):
        if fault == "report":
            data["ok"] = False
        else:
            data["progress"]["start"] = "1836.4.2"

    _edit(complete_quality_reports[1], damage)
    facts = m3a_screen.load_report(complete_quality_reports[1])
    assert facts.clean is (fault == "structure")
    pair = _pair(*complete_quality_reports)
    assert not pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize("status", ["unknown", "unsupported", "observed", None])
def test_质量就绪明确要求complete状态(complete_quality_reports, status):
    def change(data):
        data["analysis"]["opportunity"]["quality_observations"]["status"] = status

    _edit(complete_quality_reports[0], change)
    pair = _pair(*complete_quality_reports)
    assert pair.qualified
    assert not pair.quality_ready


@pytest.mark.parametrize("section", ["quality_observations", "role_timing"])
@pytest.mark.parametrize("proven", [False, None, "missing", 1, "yes"])
def test_质量就绪要求两个proven显式为真(complete_quality_reports, section, proven):
    def change(data):
        quality = data["analysis"]["opportunity"][section]
        if proven == "missing":
            del quality["quality_improvement_proven"]
        else:
            quality["quality_improvement_proven"] = proven

    _edit(complete_quality_reports[1], change)
    pair = _pair(*complete_quality_reports)
    assert pair.qualified is (proven in (False, None, "missing"))
    assert not pair.quality_ready


@pytest.mark.parametrize("values", [(0, 0.0, 0, 0.0), (-5, -2.5, 3.5, 4)])
def test_完整有限质量字段和显式proven只证明机械筛选就绪(complete_quality_reports, values):
    def change(data):
        quality = data["analysis"]["opportunity"]["quality_observations"]
        quality.update(
            zip(
                ("action_cost", "adverse_outcome", "join_latency", "leave_latency"),
                values,
                strict=True,
            )
        )

    for path in complete_quality_reports:
        _edit(path, change)
    assert all(m3a_screen.load_report(path).clean for path in complete_quality_reports)
    pair = _pair(*complete_quality_reports)
    assert pair.qualified
    assert pair.quality_ready
    assert pair.as_dict()["quality_ready"] is True


@pytest.mark.parametrize("fingerprint", ["source_hashes", "deployed_hashes"])
def test_仅候选模组策略允许差异而探针同名路径必须一致(tmp_path, fingerprint):
    from dataclasses import replace

    left = m3a_screen.load_report(_report(tmp_path / "left.json"))
    right = m3a_screen.load_report(_report(tmp_path / "right.json", neutrality="treatment"))
    hashes = {name: dict(files) for name, files in getattr(right, fingerprint).items()}
    hashes["zz_probe_decision_opportunity"][m3a_screen.STRATEGY_PATH] = "f" * 64
    right = (
        replace(right, source_hashes=hashes)
        if fingerprint == "source_hashes"
        else replace(right, deployed_hashes=hashes)
    )
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
