"""资格必须由可达的真实解析原件证明；不 mock 成功资格。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pdx import behavior_probe, decision_probe, decisions, extension_probe, game_run
from pdx import experiment_evidence as evidence
from pdx.textio import GAME_SUFFIXES, text_bytes

pytestmark = pytest.mark.unit


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": game_run.file_sha(path)}


def _hashes(files: dict[str, str]) -> dict[str, str]:
    return {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}


def _bundle(root: Path) -> dict[str, Any]:
    """源码由生产生成器实际生成，日志由生产分析器实际解析。"""
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "input.v3"
    checkpoint.write_bytes(
        b'SAV0100\nmeta_data={version="1.14.5" game_date=1836.2.1}\nplayer_manager={database={}}\n'
    )
    versions = {
        key: ("release/1.14.5" if key == "caligula_branch" else key + "-revision")
        for key in evidence.VERSION_FILES
    }
    game_files = {}
    for name, raw in {
        **{key + ".txt": value.encode() for key, value in versions.items()},
        "common/diplomatic_plays/plays.txt": b"dp_humiliation = {}\n",
    }.items():
        path = root / "game" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        game_files[name] = _ref(root, path)
    policy = replace(decisions.load(), neutrality=0, aggression=0)
    extensions = replace(decisions.load_extensions(), market_enabled=False, reform_enabled=False)
    sources = {
        "sitai_decision_candidate": decisions.build(policy, extensions=extensions),
        "zz_probe_decision_lifecycle": decision_probe.build_observer(
            lifecycle=True, tags=("RUS", "PRU")
        ),
        "zz_probe_decision_opportunity": behavior_probe.build(
            natural=True, play_types=("dp_humiliation",)
        ),
    }
    run_path = root / "run" / "report.json"
    for name, files in sources.items():
        decisions.write(run_path.parent / "sources" / name, files)
    source_hashes = {name: _hashes(files) for name, files in sources.items()}
    candidate = dict(source_hashes)
    candidate["sitai_decision_candidate"] = _hashes(
        decisions.build(replace(decisions.load(), aggression=0), extensions=extensions)
    )
    registration: dict[str, Any] = {
        "schema": 1,
        "purpose": "M3-A",
        "plan_id": "r1-synthetic",
        "scene_id": "natural-AUS-SAR",
        "criteria_version": "criterion-1",
        "checkpoint_sha256": game_run.file_sha(checkpoint),
        "language": "l_english",
        "mount_allowlist": ["base", "candidate", "fiscal", "opportunity"],
        "disabled_dlc": [],
        "game_hashes": {name: ref["sha256"] for name, ref in game_files.items()},
        "source_hashes": source_hashes,
        "arm_source_hashes": {"control": source_hashes, "neutrality": candidate},
        "observation": {
            "version": evidence.OBSERVATION_VERSION,
            "package": "natural-response",
            "observers": ["RUS", "PRU"],
            "initiator": "AUS",
            "target": "SAR",
        },
        "sampling": {
            "sample_count": 2,
            "window_days": 30,
            "max_overshoot_days": 0,
            "before_treatment": True,
        },
        "declared_differences": {"fiscal_injection": "none", "treatment": "neutrality"},
    }
    registration_path = root / "registration.json"
    _write(registration_path, registration)
    logdir = run_path.parent / "logs"
    logdir.mkdir()
    lines = ["Mounted Data: " + name for name in registration["mount_allowlist"]]
    lines += ["SITAI OPPORTUNITY;CONTROL;BIND;AUS_SAR;sample-0"]
    for sample in (1, 2):
        lines.extend(
            [
                f"SITAI OPPORTUNITY;CONTROL;TYPE;dp_humiliation;sample-{sample}",
                f"SITAI OPPORTUNITY;CONTROL;ESCALATION;10;sample-{sample}",
            ]
        )
        for tag in ("RUS", "PRU"):
            for kind in sorted(behavior_probe.BOOLEAN_KINDS):
                value = (
                    "yes"
                    if kind in {"UNDECIDED", "CAN_INIT", "ACTIVE", "PRESENT", "ENTRY", "HOLD"}
                    else "no"
                )
                lines.append(f"SITAI OPPORTUNITY;{tag};{kind};{value};sample-{sample}")
            for kind in ("INIT_SCORE", "TARGET_SCORE"):
                lines.append(f"SITAI OPPORTUNITY;{tag};{kind};10;sample-{sample}")
            for kind in ("RISK", "ACTIVE"):
                lines.append(f"SITAI DECISION;{tag};{kind};yes;sample-{sample}")
    timed = []
    for line in lines:
        output_line = line
        if "SITAI " in line:
            match = re.search(r"sample-(\d+)", line)
            assert match is not None
            sample = int(match[1])
            second = 2 if sample == 0 else 10 * sample + 1
            output_line = f"[12:00:{second:02d}][jomini_effect_impl.cpp:454]: {line}"
        timed.append(output_line)
    (logdir / "debug.log").write_bytes(("\n".join(timed) + "\n").encode())
    ticks = [
        (0, "1836.2.1"),
        (1, "1836.2.1.6"),
        (10, "1836.2.2"),
        (12, "1836.2.2.6"),
        (20, "1836.2.3"),
        (22, "1836.2.3.6"),
        (30, "1836.3.1"),
    ]
    (logdir / "dedicated_server.log").write_bytes(
        "".join(
            f"[12:00:{second:02d}][jominiapplication.cpp:539]: Processing Tick: {tick}\n"
            for second, tick in ticks
        ).encode()
    )
    (logdir / "error.log").write_bytes(b"")
    deployed = {
        name: {
            relative: hashlib.sha256(
                text_bytes(text, game=Path(relative).suffix in GAME_SUFFIXES)
            ).hexdigest()
            for relative, text in files.items()
        }
        for name, files in sources.items()
    }
    run = {
        "ok": True,
        "cleanup_errors": [],
        "game_version": versions,
        "language": "l_english",
        "months": 1,
        "session_requested": True,
        "logs_isolated": True,
        "session": {"running": "[tick] 1836.2.1 -> 1836.2.1.6 (1.0s) 推进", "speed_ok": True},
        "progress": {
            "start": "1836.2.1.6",
            "end": "1836.3.1",
            "days": 30.44,
            "reached": True,
            "activation_tick": "1836.2.1.6",
            "activation_source": "session.advance.after",
        },
        "mount_allowlist": registration["mount_allowlist"],
        "disabled_dlc": [],
        "source_hashes": source_hashes,
        "deployed_hashes": deployed,
        "game_hashes": registration["game_hashes"],
        "qualification_registration_sha256": game_run.file_sha(registration_path),
        "loaded_save": {
            "sha256": game_run.file_sha(checkpoint),
            "header": game_run.save_header(checkpoint),
        },
        "log_hashes": game_run.hashes(logdir),
        "log_findings": game_run.log_findings(
            logdir, [], expected_mounts=registration["mount_allowlist"]
        ),
    }
    _write(run_path, run)
    qualification = {
        "schema": 1,
        "purpose": "M3-A",
        "checkpoint": _ref(root, checkpoint),
        "run_report": _ref(root, run_path),
        "registration": _ref(root, registration_path),
        "game_files": game_files,
    }
    path = root / "qualification.json"
    _write(path, qualification)
    context = {field: registration[field] for field in evidence.CONTEXT_FIELDS}
    context.update(game_version=versions, months=1, arm="control")
    return {
        "path": path,
        "checkpoint": checkpoint,
        "run_path": run_path,
        "registration_path": registration_path,
        "context": context,
        "root": root,
    }


@pytest.fixture
def bundle(tmp_path):
    return _bundle(tmp_path / "bundle")


def _validate(bundle, **kwargs):
    return evidence.validate(
        bundle["path"],
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M3-A",
        context=bundle["context"],
        **kwargs,
    )


def _preparation(bundle, *, raw=None, context=None):
    qualification = json.loads(bundle["path"].read_bytes())
    game_files = {
        name: bundle["root"] / ref["path"] for name, ref in qualification["game_files"].items()
    }
    actual_context = dict(bundle["context"] if context is None else context)
    actual_context.setdefault("checkpoint_sha256", game_run.file_sha(bundle["checkpoint"]))
    return evidence.validate_preparation(
        bundle["registration_path"].read_bytes() if raw is None else raw,
        game_files=game_files,
        context=actual_context,
    )


def _edit(path, update):
    data = json.loads(path.read_bytes())
    update(data)
    _write(path, data)


def _refresh(bundle):
    root = bundle["root"]
    _edit(
        bundle["run_path"],
        lambda run: run.update(
            log_hashes=game_run.hashes(bundle["run_path"].parent / "logs"),
            qualification_registration_sha256=game_run.file_sha(bundle["registration_path"]),
        ),
    )
    _edit(
        bundle["path"],
        lambda q: q.update(
            run_report=_ref(root, bundle["run_path"]),
            registration=_ref(root, bundle["registration_path"]),
        ),
    )


def _bind_current_mounts(bundle, user):
    mounts = game_run.mount_allowlist(
        [user / "mod" / name for name in bundle["context"]["source_hashes"]]
    )
    bundle["context"]["mount_allowlist"] = mounts
    _edit(bundle["registration_path"], lambda r: r.update(mount_allowlist=mounts))
    logs = bundle["run_path"].parent / "logs"
    debug = logs / "debug.log"
    lines = [
        line
        for line in debug.read_text(encoding="utf-8").splitlines()
        if "Mounted Data:" not in line
    ]
    debug.write_bytes(
        ("\n".join([*("Mounted Data: " + name for name in mounts), *lines]) + "\n").encode()
    )
    _edit(
        bundle["run_path"],
        lambda r: r.update(
            mount_allowlist=mounts,
            log_findings=game_run.log_findings(logs, [], expected_mounts=mounts),
        ),
    )
    _refresh(bundle)


def test_合法原件可达且许可不等于质量(bundle):
    original = {path: path.read_bytes() for path in bundle["root"].rglob("*") if path.is_file()}
    result = _validate(bundle)
    assert result["allowed"], result
    assert result["opportunity_count"] == 1
    assert result["sample_count"] == 2
    assert not result["quality_improvement_proven"]
    assert result["verified_origins"]
    assert all(path.read_bytes() == raw for path, raw in original.items())
    json.dumps(result)


def test_准备许可复用真实源码和当前游戏原件且不升格正式资格(bundle):
    result = _preparation(bundle)
    assert result["allowed"], result
    assert result["preparation_only"]
    assert result["state"] == "preparation-suitable"
    assert not result["quality_improvement_proven"]


def test_准备许可支持现有额外只读包和中文诊断(bundle):
    _add_auxiliary(bundle)
    result = _preparation(bundle)
    assert result["allowed"], result


@pytest.mark.parametrize("purpose", ["M3-B", "M4", "instrument", "unknown"])
def test_准备不以登记声明解锁未支持产品出口(bundle, purpose):
    _edit(bundle["registration_path"], lambda r: r.update(purpose=purpose))
    assert not _preparation(bundle)["allowed"]


@pytest.mark.parametrize("damage", ["injection", "treated", "extra", "declared"])
def test_准备注入源码即使所有指纹和无注入声明同步也拒绝(bundle, damage):
    registration = json.loads(bundle["registration_path"].read_bytes())
    if damage == "injection":
        registration["source_hashes"]["zz_probe_decision_risk"] = _hashes(
            decision_probe.build(inject=True, tags=("RUS", "PRU"))
        )
    elif damage == "treated":
        registration["source_hashes"]["sitai_decision_candidate"] = registration[
            "arm_source_hashes"
        ]["neutrality"]["sitai_decision_candidate"]
    elif damage == "extra":
        registration["source_hashes"]["surprise"] = {"fake.txt": "a" * 64}
    else:
        registration["declared_differences"]["fiscal_injection"] = "stress"
    registration["arm_source_hashes"]["control"] = registration["source_hashes"]
    _write(bundle["registration_path"], registration)
    bundle["context"]["source_hashes"] = registration["source_hashes"]
    assert not _preparation(bundle)["allowed"]


@pytest.mark.parametrize(
    "field",
    [
        "checkpoint_sha256",
        "plan_id",
        "scene_id",
        "language",
        "mount_allowlist",
        "disabled_dlc",
        "game_hashes",
        "game_version",
        "source_hashes",
        "months",
        "arm",
    ],
)
def test_准备现场任一绑定漂移拒绝(bundle, field):
    context = dict(bundle["context"])
    context["checkpoint_sha256"] = game_run.file_sha(bundle["checkpoint"])
    context[field] = "drift"
    assert not _preparation(bundle, context=context)["allowed"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_count", True),
        ("sample_count", 0),
        ("sample_count", 1.5),
        ("before_treatment", False),
        ("before_treatment", "true"),
        ("window_days", True),
        ("max_overshoot_days", True),
        ("max_overshoot_days", -1),
        ("max_overshoot_days", None),
    ],
)
def test_准备采样须严格事前登记(bundle, field, value):
    _edit(bundle["registration_path"], lambda r: r["sampling"].update({field: value}))
    assert not _preparation(bundle)["allowed"]


@pytest.mark.parametrize(
    "damage",
    [
        "unknown-field",
        "unknown-package",
        "duplicate",
        "nonfinite",
        "deep",
        "version",
        "game-content",
    ],
)
def test_准备未知结构或当前原件不符拒绝不崩溃(bundle, damage):
    raw = bundle["registration_path"].read_bytes()
    if damage == "unknown-field":
        _edit(bundle["registration_path"], lambda r: r.update(eligible=True))
    elif damage == "unknown-package":
        _edit(bundle["registration_path"], lambda r: r["observation"].update(surprise=True))
    elif damage == "duplicate":
        raw = raw.replace(b'"schema": 1', b'"schema": 1, "schema": 1')
    elif damage == "nonfinite":
        raw = raw.replace(b'"max_overshoot_days": 0', b'"max_overshoot_days": NaN')
    elif damage == "deep":
        raw = b"[" * 10000 + b"0" + b"]" * 10000
    elif damage == "version":
        (bundle["root"] / "game/caligula_branch.txt").write_bytes(b"release/other")
    else:
        (bundle["root"] / "game/common/diplomatic_plays/plays.txt").write_bytes(
            b"dp_changed = {}\n"
        )
    if damage in {"unknown-field", "unknown-package"}:
        raw = bundle["registration_path"].read_bytes()
    assert not _preparation(bundle, raw=raw)["allowed"]


def test_准备复核期间游戏原件改变拒绝(bundle, monkeypatch):
    sources = evidence._sources

    def changed(*args, **kwargs):
        result = sources(*args, **kwargs)
        (bundle["root"] / "game/clausewitz_rev.txt").write_bytes(b"changed")
        return result

    monkeypatch.setattr(evidence, "_sources", changed)
    assert _preparation(bundle)["reasons"] == ["artifact.changed"]


def _control_report(bundle):
    control_root = bundle["root"] / "control"
    shutil.copytree(bundle["run_path"].parent, control_root)
    path = control_root / "report.json"
    qualified = _validate(bundle)
    assert qualified["allowed"], qualified
    _edit(
        path,
        lambda r: r.update(
            experiment={
                "plan_id": "r1-synthetic",
                "scene_id": "natural-AUS-SAR",
                "arm": "control",
                "purpose": "M3-A",
                "pair": 0,
            },
            qualification_report=str(bundle["path"].resolve()),
            checkpoint_preflight={
                "sha256": game_run.file_sha(bundle["checkpoint"]),
                "qualification": qualified,
            },
        ),
    )
    return path


def _review_control(bundle, path, *, context=None):
    return evidence.review_control(
        path,
        qualification_report=bundle["path"],
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M3-A",
        context=bundle["context"] if context is None else context,
    )


def test_控制原件重新验收才允许已登记处理臂而不证明质量(bundle):
    path = _control_report(bundle)
    result = _review_control(bundle, path)
    assert result["allowed"], result
    assert result["control_only"]
    assert result["state"] == "control-reviewed"
    assert not result["quality_improvement_proven"]
    assert result["report_sha256"] == game_run.file_sha(path)


@pytest.mark.parametrize("damage", ["no-opportunity", "risk", "window", "missing-time"])
def test_干净控制报告不能代替真实机会风险和窗口证据(bundle, damage):
    path = _control_report(bundle)
    logs = path.parent / "logs"
    debug = logs / "debug.log"
    if damage == "no-opportunity":
        debug.write_bytes(debug.read_bytes().replace(b";ACTIVE;yes", b";ACTIVE;no"))
    elif damage == "risk":
        debug.write_bytes(debug.read_bytes().replace(b";RISK;yes", b";RISK;no"))
    elif damage == "window":
        ticks = logs / "dedicated_server.log"
        ticks.write_bytes(ticks.read_bytes().replace(b"1836.3.1", b"1838.2.1"))
        _edit(path, lambda r: r["progress"].update(end="1838.2.1", days=730.5))
    else:
        (logs / "dedicated_server.log").unlink()
    _edit(path, lambda r: r.update(log_hashes=game_run.hashes(logs)))
    assert not _review_control(bundle, path)["allowed"]


@pytest.mark.parametrize(
    "field",
    [
        "qualification_report",
        "qualification_registration_sha256",
        "checkpoint_preflight",
        "experiment",
        "loaded_save",
        "months",
        "source_hashes",
        "language",
        "disabled_dlc",
        "game_version",
    ],
)
def test_控制缺必需身份原资格与现场绑定拒绝(bundle, field):
    path = _control_report(bundle)
    _edit(path, lambda r: r.pop(field))
    assert not _review_control(bundle, path)["allowed"]


@pytest.mark.parametrize("field", ["plan_id", "scene_id", "arm", "purpose", "pair"])
def test_控制报告不能跨计划场景配对或处理臂复用(bundle, field):
    path = _control_report(bundle)
    _edit(path, lambda r: r["experiment"].update({field: "other"}))
    context = {**bundle["context"], "pair": 0}
    assert _review_control(bundle, path, context=context)["reasons"] == ["control.identity"]


def test_控制审查期间原资格目录成员变化拒绝(bundle, monkeypatch):
    path = _control_report(bundle)
    validate = evidence.validate

    def changed(*args, **kwargs):
        result = validate(*args, **kwargs)
        (bundle["run_path"].parent / "sources" / "late.txt").write_bytes(b"late")
        return result

    monkeypatch.setattr(evidence, "validate", changed)
    assert _review_control(bundle, path)["reasons"] == ["artifact.changed"]


def test_控制审查期间纯原版来源缺席事实变化拒绝(bundle, monkeypatch):
    origin = _vanilla_origin(bundle)
    path = _control_report(bundle)
    validate = evidence.validate

    def changed(*args, **kwargs):
        result = validate(*args, **kwargs)
        (origin / "sources").mkdir()
        return result

    monkeypatch.setattr(evidence, "validate", changed)
    assert not _review_control(bundle, path)["allowed"]


def test_控制后原资格损坏不能继续派处理臂(bundle):
    path = _control_report(bundle)
    (bundle["root"] / "game/clausewitz_rev.txt").write_bytes(b"changed")
    assert _review_control(bundle, path)["reasons"] == ["control.qualification_rejected"]


@pytest.mark.parametrize("value", [None, True, 0, -1, 12, "1"])
def test_原始运行月份必须严格绑定登记窗口(bundle, value):
    _edit(bundle["run_path"], lambda r: r.update(months=value))
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["run_report.months"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing-months",
        "handfilled",
        "days",
        "activation",
        "session",
        "tick",
        "timestamp",
        "outside",
        "midnight",
    ],
)
def test_窗口必须由实际会话和时间原日志证明(bundle, damage):
    logs = bundle["run_path"].parent / "logs"
    if damage == "missing-months":
        _edit(bundle["run_path"], lambda r: r.pop("months"))
    elif damage == "handfilled":
        _edit(
            bundle["run_path"],
            lambda r: r.update(
                progress={"simulated_days": 720, "start_tick": "1836.2.1", "end_tick": "1838.2.1"}
            ),
        )
    elif damage == "days":
        _edit(bundle["run_path"], lambda r: r["progress"].update(days=720))
    elif damage == "activation":
        _edit(bundle["run_path"], lambda r: r["progress"].update(activation_tick="1836.2.2"))
    elif damage == "session":
        _edit(bundle["run_path"], lambda r: r["session"].update(running="手填已推进"))
    elif damage == "tick":
        (logs / "dedicated_server.log").unlink()
    elif damage == "timestamp":
        debug = logs / "debug.log"
        debug.write_bytes(
            re.sub(r"\[12:00:\d{2}\]", "", debug.read_text(encoding="utf-8")).encode()
        )
    elif damage == "outside":
        debug = logs / "debug.log"
        debug.write_bytes(debug.read_bytes().replace(b"[12:00:21]", b"[12:00:31]"))
    else:
        ticks = logs / "dedicated_server.log"
        ticks.write_bytes(ticks.read_bytes().replace(b"[12:00:30]", b"[00:00:00]"))
    _refresh(bundle)
    assert not _validate(bundle)["allowed"], damage


def test_月度风险不能以历史yes掩盖同采样矛盾(bundle):
    debug = bundle["run_path"].parent / "logs" / "debug.log"
    raw = debug.read_text(encoding="utf-8")
    for tag in ("RUS", "PRU"):
        raw = raw.replace(
            f"SITAI OPPORTUNITY;{tag};ACTIVE;yes;sample-2",
            f"SITAI OPPORTUNITY;{tag};ACTIVE;no;sample-2",
        )
        raw = raw.replace(
            f"SITAI DECISION;{tag};RISK;yes;sample-1", f"SITAI DECISION;{tag};RISK;no;sample-1"
        )
    debug.write_bytes(raw.encode())
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["opportunity.risk_contradiction"]


def test_机会ACTIVE证明当采样风险不依赖月度样本序号(bundle):
    debug = bundle["run_path"].parent / "logs" / "debug.log"
    raw = debug.read_text(encoding="utf-8")
    raw = re.sub(
        r"(SITAI DECISION;[^\n]+;)sample-(\d+)", lambda m: m[1] + f"sample-{int(m[2]) + 10}", raw
    )
    debug.write_bytes(raw.encode())
    _refresh(bundle)
    result = _validate(bundle)
    assert result["allowed"], result
    assert "has_variable=sitai_fiscal_risk" in result["common_risk_basis"]


@pytest.mark.parametrize("field", ["mount_allowlist", "disabled_dlc"])
def test_现场挂载和DLC必需且不能跨配置复用(bundle, field):
    bundle["context"].pop(field)
    assert _validate(bundle)["reasons"] == [f"context.{field}"]


@pytest.mark.parametrize("value", [None, "dlc", [""], [" dlc"], ["dlc", "dlc"], [True]])
def test_DLC登记必须规范列表(bundle, value):
    _edit(bundle["registration_path"], lambda r: r.update(disabled_dlc=value))
    bundle["context"]["disabled_dlc"] = value
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["registration.disabled_dlc"]


def test_原局必须保留与登记一致的禁用DLC(bundle):
    _edit(bundle["run_path"], lambda r: r.pop("disabled_dlc"))
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["run_report.disabled_dlc"]


def _vanilla_origin(bundle):
    root = bundle["root"] / "vanilla_session"
    checkpoint = root / "saves" / "checkpoint.v3"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(bundle["checkpoint"].read_bytes())
    logs = root / "logs"
    logs.mkdir()
    (logs / "debug.log").write_bytes(b"Mounted Data: base\n")
    (logs / "error.log").write_bytes(b"")
    report = {
        "kind": "vanilla_checkpoint_preparation",
        "ok": True,
        "content_load": "vanilla_only",
        "session_requested": True,
        "logs_isolated": True,
        "cleanup_errors": [],
        "source_hashes": {},
        "deployed_hashes": {},
        "game_version": {"caligula_branch": "release/1.14.5"},
        "mount_allowlist": ["base"],
        "log_hashes": game_run.hashes(logs),
        "checkpoint": {
            "header": game_run.save_header(checkpoint),
            "hashes": {checkpoint.name: game_run.file_sha(checkpoint)},
        },
    }
    _write(root / "report.json", report)
    bundle["checkpoint"] = checkpoint
    _edit(bundle["path"], lambda q: q.update(checkpoint=_ref(bundle["root"], checkpoint)))
    return root


def test_纯原版来源保留saves原件路径与不存在源码契约(bundle):
    root = _vanilla_origin(bundle)
    result = _validate(bundle)
    assert result["allowed"], result
    assert not (root / "sources").exists()
    assert "vanilla_session/report.json" in result["verified_origins"]


def test_纯原版来源缺席目录复核期间出现拒绝(bundle, monkeypatch):
    root = _vanilla_origin(bundle)
    inspect = evidence.checkpoint_catalog.inspect

    def changed(*args, **kwargs):
        result = inspect(*args, **kwargs)
        (root / "sources").mkdir()
        return result

    monkeypatch.setattr(evidence.checkpoint_catalog, "inspect", changed)
    assert _validate(bundle)["reasons"] == ["artifact.changed"]


@pytest.mark.parametrize("value", [None, True, False, -1, "0", [], float("nan"), float("inf")])
def test_越窗预算必须事前有限非负数字(bundle, value):
    _edit(bundle["registration_path"], lambda r: r["sampling"].update(max_overshoot_days=value))
    _refresh(bundle)
    result = _validate(bundle)
    assert not result["allowed"]
    assert result["reasons"] in [["sampling.max_overshoot_days"], ["json.nonfinite"]]


def test_缺越窗预算的旧登记不能解锁(bundle):
    _edit(bundle["registration_path"], lambda r: r["sampling"].pop("max_overshoot_days"))
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["sampling.max_overshoot_days"]


def test_实际原日志也推进720天仍不能扩大30天登记窗口(bundle):
    ticks = bundle["run_path"].parent / "logs" / "dedicated_server.log"
    ticks.write_bytes(ticks.read_bytes().replace(b"1836.3.1", b"1838.2.1"))
    start = game_run.ga.tick_day("1836.2.1.6")
    end = game_run.ga.tick_day("1838.2.1")
    assert start is not None
    assert end is not None
    days = end - start
    _edit(bundle["run_path"], lambda r: r["progress"].update(end="1838.2.1", days=days))
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["run_report.progress"]


def test_明确事前越窗预算可接受正常轮询超出(bundle):
    ticks = bundle["run_path"].parent / "logs" / "dedicated_server.log"
    ticks.write_bytes(ticks.read_bytes().replace(b"1836.3.1", b"1836.3.3"))
    _edit(bundle["registration_path"], lambda r: r["sampling"].update(max_overshoot_days=2))
    _edit(bundle["run_path"], lambda r: r["progress"].update(end="1836.3.3", days=32.44))
    _refresh(bundle)
    result = _validate(bundle)
    assert result["allowed"], result
    assert result["sampling_window"]["allowed_days"] == 33


def test_共享采样行不能拼接不同真实日期的两国(bundle):
    debug = bundle["run_path"].parent / "logs" / "debug.log"
    lines = debug.read_text(encoding="utf-8").splitlines()
    changed = [
        line.replace("[12:00:11]", "[12:00:21]")
        if "SITAI OPPORTUNITY;PRU;" in line and "sample-1" in line
        else line
        for line in lines
    ]
    debug.write_bytes(("\n".join(changed) + "\n").encode())
    _refresh(bundle)
    assert _validate(bundle)["reasons"] == ["sampling.shared_time_inconsistent"]


def test_登记候选单字段源码可达且额外变更拒绝(bundle):
    registration = json.loads(bundle["registration_path"].read_bytes())
    bundle["context"]["arm"] = "neutrality"
    bundle["context"]["source_hashes"] = registration["arm_source_hashes"]["neutrality"]
    assert _validate(bundle)["allowed"]
    bundle["context"]["source_hashes"]["sitai_decision_candidate"] = {"fake.txt": "a" * 64}
    assert not _validate(bundle)["allowed"]


@pytest.mark.parametrize("role", ["run", "log", "source", "registration", "game", "checkpoint"])
def test_任一原件变更拒绝(bundle, role):
    paths = {
        "run": bundle["run_path"],
        "log": bundle["run_path"].parent / "logs/debug.log",
        "source": next((bundle["run_path"].parent / "sources").rglob("*.txt")),
        "registration": bundle["registration_path"],
        "game": bundle["root"] / "game/caligula_rev.txt",
        "checkpoint": bundle["checkpoint"],
    }
    with paths[role].open("ab") as stream:
        stream.write(b"changed")
    assert not _validate(bundle)["allowed"]


@pytest.mark.parametrize(
    "field",
    [
        "language",
        "game_hashes",
        "mount_allowlist",
        "plan_id",
        "scene_id",
        "criteria_version",
        "observation",
        "declared_differences",
        "game_version",
        "months",
    ],
)
def test_现场上下文漂移拒绝(bundle, field):
    bundle["context"][field] = "different"
    result = _validate(bundle)
    assert not result["allowed"]
    assert result["reasons"] == ["context." + field]


@pytest.mark.parametrize("value", [True, False, 0, "1", None, [], {}])
def test_schema不接受布尔或未知结构(bundle, value):
    _edit(bundle["path"], lambda q: q.update(schema=value))
    assert _validate(bundle)["reasons"] == ["qualification.schema"]


@pytest.mark.parametrize("value", [None, True, [], 2, "bad", {"schema": 1}])
def test_未知报告结构返回拒绝不崩溃(bundle, value):
    _write(bundle["path"], value)
    result = _validate(bundle)
    assert not result["allowed"]
    assert result["reasons"]


@pytest.mark.parametrize(
    "path",
    [
        "../input.v3",
        "/input.v3",
        "C:/input.v3",
        "C:input.v3",
        "a/../../input.v3",
        "a\\input.v3",
        "./input.v3",
    ],
)
def test_不安全引用拒绝(bundle, path):
    _edit(bundle["path"], lambda q: q["checkpoint"].update(path=path))
    assert _validate(bundle)["reasons"] == ["artifact.path"]


@pytest.mark.parametrize(
    "damage",
    [
        "single",
        "entry",
        "risk",
        "malformed",
        "duplicate",
        "missing-error",
        "engine-error",
        "unexpected-mount",
    ],
)
def test_重算资格不能用报告eligible或count代替(bundle, damage):
    logs = bundle["run_path"].parent / "logs"
    path = logs / "debug.log"
    raw = path.read_text(encoding="utf-8")
    if damage == "single":
        raw = raw.replace("PRU;CAN_INIT;yes", "PRU;CAN_INIT;no")
    elif damage == "entry":
        raw = raw.replace(";ACTIVE;yes", ";ACTIVE;no")
    elif damage == "risk":
        raw = raw.replace(";RISK;yes", ";RISK;no")
    elif damage == "malformed":
        raw += "SITAI OPPORTUNITY;broken\n"
    elif damage == "duplicate":
        raw += "SITAI OPPORTUNITY;RUS;ACTIVE;yes;sample-2\n"
    elif damage == "missing-error":
        (logs / "error.log").unlink()
    elif damage == "engine-error":
        (logs / "error.log").write_bytes(b"Assertion failed: broken\n")
    else:
        raw += "Mounted Data: third-party\n"
    path.write_bytes(raw.encode())
    _edit(bundle["run_path"], lambda r: r.update(eligible=True, opportunity_count=999))
    _refresh(bundle)
    assert not _validate(bundle)["allowed"]


def test_手填报告分析没有原日志资格仍拒绝(bundle):
    logs = bundle["run_path"].parent / "logs"
    (logs / "debug.log").write_bytes(
        b"Mounted Data: base\nMounted Data: candidate\nMounted Data: fiscal\nMounted Data: opportunity\n"
    )
    _edit(
        bundle["run_path"],
        lambda r: r.update(analysis={"opportunity": {"eligible": True, "count": 99}}),
    )
    _refresh(bundle)
    assert not _validate(bundle)["allowed"]


@pytest.mark.parametrize(
    "damage", ["observer", "treated", "input", "injection", "count", "registration", "arms"]
)
def test_处理后错误版本和准备输出不能作为处理前资格(bundle, damage):
    if damage == "input":
        _edit(bundle["run_path"], lambda r: r["loaded_save"].update(sha256="b" * 64))
    elif damage == "treated":
        _edit(bundle["registration_path"], lambda r: r["sampling"].update(before_treatment=False))
    elif damage == "observer":
        _edit(bundle["registration_path"], lambda r: r["observation"].update(version="older"))
        bundle["context"]["observation"]["version"] = "older"
    elif damage == "injection":
        _edit(
            bundle["registration_path"],
            lambda r: r["declared_differences"].update(fiscal_injection="stress"),
        )
        bundle["context"]["declared_differences"]["fiscal_injection"] = "stress"
    elif damage == "count":
        _edit(bundle["registration_path"], lambda r: r["sampling"].update(sample_count=99))
    elif damage == "arms":
        _edit(
            bundle["registration_path"],
            lambda r: r["arm_source_hashes"]["neutrality"].update(extra={"fake": "a" * 64}),
        )
    else:
        _edit(bundle["registration_path"], lambda r: r.update(checkpoint_sha256="b" * 64))
    _refresh(bundle)
    assert not _validate(bundle)["allowed"]


@pytest.mark.parametrize("instrument", ["candidate", "injection"])
def test_所有手填指纹同步仍不能把处理源码当处理前(bundle, instrument):
    registration = json.loads(bundle["registration_path"].read_bytes())
    if instrument == "candidate":
        name = "sitai_decision_candidate"
        files = decisions.build(
            replace(decisions.load(), aggression=0),
            extensions=replace(
                decisions.load_extensions(), market_enabled=False, reform_enabled=False
            ),
        )
    else:
        name = "zz_probe_decision_lifecycle"
        files = decision_probe.build(inject=True)
    source = bundle["run_path"].parent / "sources" / name
    shutil.rmtree(source)
    decisions.write(source, files)
    registration["source_hashes"][name] = _hashes(files)
    registration["arm_source_hashes"]["control"] = registration["source_hashes"]
    _write(bundle["registration_path"], registration)
    deployed = {
        relative: hashlib.sha256(
            text_bytes(text, game=Path(relative).suffix in GAME_SUFFIXES)
        ).hexdigest()
        for relative, text in files.items()
    }
    _edit(
        bundle["run_path"],
        lambda r: r.update(
            source_hashes=registration["source_hashes"],
            deployed_hashes={**r["deployed_hashes"], name: deployed},
        ),
    )
    bundle["context"]["source_hashes"] = registration["source_hashes"]
    _refresh(bundle)
    result = _validate(bundle)
    assert result["reasons"] == ["sampling.treated_source"], result


def test_资格不得跨purpose使用(bundle):
    result = evidence.validate(
        bundle["path"],
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M3-B",
        context=bundle["context"],
    )
    assert result["reasons"] == ["qualification.purpose"]


def test_M3B完整候选分母缺接口保持拒绝(bundle):
    _edit(bundle["path"], lambda q: q.update(purpose="M3-B"))
    _edit(
        bundle["registration_path"],
        lambda r: r.update(purpose="M3-B", complete_denominator=True, count=99),
    )
    _refresh(bundle)
    result = evidence.validate(
        bundle["path"],
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M3-B",
        context=bundle["context"],
    )
    assert result["reasons"] == ["opportunity.denominator_unsupported"]


def test_读取中报告变化拒绝(bundle, monkeypatch):
    original = game_run.read_reviewed_report

    def change(path):
        reviewed = original(path)
        _edit(path, lambda r: r.update(changed=True))
        return reviewed

    monkeypatch.setattr(game_run, "read_reviewed_report", change)
    result = _validate(bundle)
    assert not result["allowed"]
    assert "artifact.changed" in result["reasons"]


def test_读取中日志内容改变后恢复仍由身份拒绝(bundle, monkeypatch):
    original = behavior_probe.analyze

    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        log = bundle["run_path"].parent / "logs/debug.log"
        raw = log.read_bytes()
        log.write_bytes(raw + b"changed")
        log.write_bytes(raw)
        return result

    monkeypatch.setattr(behavior_probe, "analyze", change)
    assert not _validate(bundle)["allowed"]


def test_目录链接在解析前拒绝(bundle, tmp_path):
    original = bundle["root"] / "run"
    moved = tmp_path / "external"
    shutil.move(str(original), str(moved))
    try:
        original.symlink_to(moved, target_is_directory=True)
    except OSError:
        pytest.skip("本机未提供创建目录符号链接权限")
    assert not _validate(bundle)["allowed"]


def test_模拟父目录链接在resolve前拒绝(bundle, monkeypatch):
    original = Path.is_symlink
    linked = bundle["run_path"].parent
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    assert not _validate(bundle)["allowed"]


def test_读取期间新增源码文件拒绝(bundle, monkeypatch):
    original = behavior_probe.analyze

    def add(*args, **kwargs):
        result = original(*args, **kwargs)
        extra = bundle["run_path"].parent / "sources/extra.txt"
        extra.write_bytes(b"new source")
        return result

    monkeypatch.setattr(behavior_probe, "analyze", add)
    assert "artifact.changed" in _validate(bundle)["reasons"]


def test_未知bool资格与JSON重复键拒绝(bundle):
    _edit(bundle["path"], lambda q: q.update(eligible=True))
    assert _validate(bundle)["reasons"] == ["qualification.shape"]
    bundle["path"].write_bytes(b'{"schema":1,"schema":1}')
    assert _validate(bundle)["reasons"] == ["json.duplicate_key"]


def test_JSON非有限数值和超深未知结构拒绝不崩溃(bundle):
    bundle["path"].write_bytes(b'{"schema":NaN}')
    assert _validate(bundle)["reasons"] == ["json.nonfinite"]
    bundle["path"].write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
    assert not _validate(bundle)["allowed"]


def test_缺现场内容上下文拒绝(bundle):
    del bundle["context"]["game_hashes"]
    assert _validate(bundle)["reasons"] == ["context.game_hashes"]


def test_大型存档和日志散列不物化整文件(bundle, monkeypatch):
    read_bytes = Path.read_bytes
    large = {bundle["checkpoint"], *list((bundle["run_path"].parent / "logs").iterdir())}

    def read(path):
        assert path not in large, "大型原件须流式散列"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    assert _validate(bundle)["allowed"]


def _add_auxiliary(bundle):
    root = bundle["root"]
    game = root / "game"
    originals = {
        "common/laws/laws.txt": b"law_synthetic = {}\n",
        "common/ai_strategies/political.txt": b"ai_strategy_synthetic = { type = political }\n",
        "localization/english/base.yml": (
            "l_english:\n"
            + "".join(f' {key}: "Synthetic"\n' for key in sorted(decision_probe.BASELINE_LOC_KEYS))
        ).encode(),
        "localization/simp_chinese/base.yml": b"l_simp_chinese:\n",
    }
    for name, raw in originals.items():
        path = game / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    registration = json.loads(bundle["registration_path"].read_bytes())
    registration["observation"].update(extra_fiscal=True, reform=True, localization_baseline=True)
    extras = {
        "zz_sitai_fiscal_observer": decision_probe.build_observer(tags=("RUS", "PRU")),
        "zz_sitai_reform_observer": extension_probe.build(
            ("law_synthetic",), strategies=("ai_strategy_synthetic",)
        ),
        "zz_sitai_vanilla_localization_baseline": decision_probe.build_localization_baseline(game),
    }
    deployed = {}
    for name, files in extras.items():
        decisions.write(bundle["run_path"].parent / "sources" / name, files)
        digests = _hashes(files)
        registration["source_hashes"][name] = digests
        for arm in registration["arm_source_hashes"].values():
            arm[name] = digests
        deployed[name] = {
            relative: hashlib.sha256(
                text_bytes(text, game=Path(relative).suffix in GAME_SUFFIXES)
            ).hexdigest()
            for relative, text in files.items()
        }
    registration["game_hashes"].update({name: game_run.file_sha(game / name) for name in originals})
    _write(bundle["registration_path"], registration)
    _edit(
        bundle["path"],
        lambda q: q["game_files"].update({name: _ref(root, game / name) for name in originals}),
    )
    _edit(
        bundle["run_path"],
        lambda r: r.update(
            source_hashes=registration["source_hashes"],
            game_hashes=registration["game_hashes"],
            deployed_hashes={**r["deployed_hashes"], **deployed},
        ),
    )
    bundle["context"].update({field: registration[field] for field in evidence.CONTEXT_FIELDS})
    _refresh(bundle)


def test_完整CLI只读观测和中文诊断由实际原件可达(bundle):
    _add_auxiliary(bundle)
    result = _validate(bundle)
    assert result["allowed"], result
    assert "game/common/laws/laws.txt" in result["verified_origins"]


def test_额外观测包任何源码变更拒绝(bundle):
    _add_auxiliary(bundle)
    path = (
        bundle["run_path"].parent
        / "sources/zz_sitai_reform_observer/common/on_actions/zz_sitai_reform_observer.txt"
    )
    path.write_bytes(path.read_bytes() + b"# different\n")
    assert not _validate(bundle)["allowed"]


def test_完整资格通过真实运行器可到达合成启动边界(bundle, tmp_path, monkeypatch):
    from pdx.experiment_queue import RunRequest

    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "ROOT", bundle["root"] / "game")
    monkeypatch.setattr(game_run.config, "GAME", bundle["root"] / "game")
    _bind_current_mounts(bundle, user)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    seen = {}

    def start(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("SYNTHETIC_START_BOUNDARY")

    monkeypatch.setattr(game_run.ga, "run_session", start)
    sources = {path.name: path for path in (bundle["run_path"].parent / "sources").iterdir()}
    report = game_run.run(
        sources,
        months=1,
        output=tmp_path / "output",
        load_save=bundle["checkpoint"],
        language="l_english",
        qualification_report=bundle["path"],
        qualification_context=bundle["context"],
        experiment=RunRequest(
            "r1-synthetic", "natural-AUS-SAR", "control", purpose="M3-A", min_available_mib=0
        ),
    )
    assert seen, report
    assert "SYNTHETIC_START_BOUNDARY" in str(report["failure"])
    assert report["cleanup_errors"] == []


def test_缺资格在部署和移动日志前拒绝(bundle, tmp_path, monkeypatch):
    from pdx.experiment_queue import RunRequest

    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "ROOT", bundle["root"] / "game")
    monkeypatch.setattr(game_run.config, "GAME", bundle["root"] / "game")
    _bind_current_mounts(bundle, user)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    monkeypatch.setattr(game_run.Deployment, "deploy", lambda *_a: pytest.fail("缺证不得部署"))
    monkeypatch.setattr(game_run.ga, "quarantine_logs", lambda *_a: pytest.fail("缺证不得移动日志"))
    _edit(bundle["path"], lambda q: q.update(eligible=True))
    sources = {path.name: path for path in (bundle["run_path"].parent / "sources").iterdir()}
    report = game_run.run(
        sources,
        months=1,
        output=tmp_path / "output",
        load_save=bundle["checkpoint"],
        language="l_english",
        qualification_report=bundle["path"],
        qualification_context=bundle["context"],
        experiment=RunRequest(
            "r1-synthetic", "natural-AUS-SAR", "control", purpose="M3-A", min_available_mib=0
        ),
    )
    assert "qualification.shape" in str(report["failure"])


def _performance_bundle(bundle):
    """无外交机会的原版性能证据；不能虚构 M3 质量出口。"""
    source_root = bundle["run_path"].parent / "sources"
    shutil.rmtree(source_root)
    files = decision_probe.build_observer(
        tags=("RUS", "PRU"), policy_state=False, native_fiscal_inputs=True
    )
    decisions.write(source_root / "zz_sitai_fiscal_observer", files)
    source_hashes = {"zz_sitai_fiscal_observer": _hashes(files)}
    deployed = {
        "zz_sitai_fiscal_observer": {
            name: hashlib.sha256(
                text_bytes(text, game=Path(name).suffix in GAME_SUFFIXES)
            ).hexdigest()
            for name, text in files.items()
        }
    }
    registration = json.loads(bundle["registration_path"].read_bytes())
    registration.update(
        purpose="M4",
        source_hashes=source_hashes,
        arm_source_hashes={"vanilla": source_hashes, "fiscal": {}},
        observation={
            "version": evidence.OBSERVATION_VERSION,
            "package": "vanilla-performance",
            "observers": ["RUS", "PRU"],
        },
        sampling={
            "sample_count": 1,
            "window_days": 720,
            "max_overshoot_days": 0,
            "before_treatment": True,
        },
        declared_differences={"fiscal_injection": "none", "treatment": "frozen-candidate"},
    )
    (bundle["run_path"].parent / "logs/debug.log").write_bytes(
        "".join("Mounted Data: " + name + "\n" for name in registration["mount_allowlist"]).encode()
    )
    _edit(
        bundle["run_path"],
        lambda r: r.update(source_hashes=source_hashes, deployed_hashes=deployed, months=24),
    )
    _edit(bundle["path"], lambda q: q.update(purpose="M4"))
    _write(bundle["registration_path"], registration)
    _refresh(bundle)
    noise_refs = []
    for index in range(3):
        directory = bundle["root"] / f"noise-{index}"
        shutil.copytree(bundle["run_path"].parent, directory)
        path = directory / "report.json"
        _edit(path, lambda r, index=index: r.update(noise_run=index))
        noise_refs.append(_ref(bundle["root"], path))
    frozen = bundle["root"] / "freeze.json"
    _write(frozen, {"stage": "M3", "quality": True, "frozen": True})
    registration["performance"] = {
        "period": "early",
        "input_date": "1836.2.1",
        "budgets": {"seconds_per_day": 1, "rss_peak": 10, "cpu_seconds": 10, "noise_fraction": 0.1},
        "noise_reports": noise_refs,
        "frozen_candidate": _ref(bundle["root"], frozen),
    }
    _write(bundle["registration_path"], registration)
    _refresh(bundle)
    bundle["context"].update({field: registration[field] for field in evidence.CONTEXT_FIELDS})
    bundle["context"].update(
        months=24, arm="vanilla", m3_frozen_candidate_sha256=game_run.file_sha(frozen)
    )


def _validate_performance(bundle):
    return evidence.validate(
        bundle["path"],
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M4",
        context=bundle["context"],
    )


def test_M4不要求外交机会但仪器及手填审核不得升格(bundle):
    _performance_bundle(bundle)
    result = _validate_performance(bundle)
    assert result["reasons"] == ["frozen_candidate.quality_unsupported"], result
    assert result["opportunity_count"] is None


@pytest.mark.parametrize("damage", ["noise", "duplicate", "period", "budget", "window"])
def test_M4性能登记缺证独立拒绝(bundle, damage):
    _performance_bundle(bundle)

    def change(r):
        if damage == "noise":
            r["performance"]["noise_reports"] = []
        elif damage == "duplicate":
            r["performance"]["noise_reports"] = [r["performance"]["noise_reports"][0]] * 3
        elif damage == "period":
            r["performance"]["input_date"] = "1900.1.1"
        elif damage == "budget":
            r["performance"]["budgets"]["rss_peak"] = True
        else:
            r["sampling"]["window_days"] = 30
            bundle["context"]["months"] = 1

    _edit(bundle["registration_path"], change)
    _refresh(bundle)
    result = _validate_performance(bundle)
    assert not result["allowed"]
    assert result["reasons"] == [
        "performance."
        + {
            "noise": "noise",
            "duplicate": "noise_duplicate",
            "period": "period",
            "budget": "budgets",
            "window": "window",
        }[damage]
    ], result


def _prepare_environment(bundle, tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "ROOT", bundle["root"] / "game")
    monkeypatch.setattr(game_run.config, "GAME", bundle["root"] / "game")
    _bind_current_mounts(bundle, user)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    return {path.name: path for path in (bundle["run_path"].parent / "sources").iterdir()}


def test_实际禁用DLC变化即使挂载路径相同仍在副作用前拒绝(bundle, tmp_path, monkeypatch):
    from pdx.experiment_queue import RunRequest

    sources = _prepare_environment(bundle, tmp_path, monkeypatch)
    _write(game_run.config.USERDIR / "content_load.json", {"disabledDLC": ["changed-dlc"]})
    monkeypatch.setattr(game_run.Deployment, "deploy", lambda *_a: pytest.fail("DLC变化不得部署"))
    monkeypatch.setattr(
        game_run.ga, "quarantine_logs", lambda *_a: pytest.fail("DLC变化不得移动日志")
    )
    report = game_run.run(
        sources,
        months=1,
        output=tmp_path / "output",
        load_save=bundle["checkpoint"],
        language="l_english",
        qualification_report=bundle["path"],
        qualification_context=bundle["context"],
        experiment=RunRequest(
            "r1-synthetic", "natural-AUS-SAR", "control", purpose="M3-A", min_available_mib=0
        ),
    )
    assert not report["ok"]
    assert "context.disabled_dlc" in str(report["failure"]), report


def test_真实准备链归档登记输入和游戏原件但失败不能合格(bundle, tmp_path, monkeypatch):
    from pdx.experiment_queue import RunRequest

    sources = _prepare_environment(bundle, tmp_path, monkeypatch)

    def start(**_kwargs):
        raise RuntimeError("REGISTERED_PREPARATION_STOP")

    monkeypatch.setattr(game_run.ga, "run_session", start)
    report = game_run.run(
        sources,
        months=1,
        output=tmp_path / "output",
        load_save=bundle["checkpoint"],
        language="l_english",
        qualification_registration=bundle["registration_path"],
        qualification_context=bundle["context"],
        experiment=RunRequest(
            "r1-synthetic", "natural-AUS-SAR", "control", purpose="instrument", min_available_mib=0
        ),
    )
    assert "REGISTERED_PREPARATION_STOP" in str(report["failure"]), report
    root = Path(str(report["evidence"]))
    assert (root / "registration.json").read_bytes() == bundle["registration_path"].read_bytes()
    assert (root / "input.v3").read_bytes() == bundle["checkpoint"].read_bytes()
    assert game_run.hashes(root / "game") == bundle["context"]["game_hashes"]
    result = evidence.validate(
        root / "qualification.json",
        checkpoint_sha256=game_run.file_sha(bundle["checkpoint"]),
        expected_version="1.14.5",
        purpose="M3-A",
        context=bundle["context"],
    )
    assert not result["allowed"]


@pytest.mark.parametrize(
    "field",
    ["plan_id", "checkpoint_sha256", "source_hashes", "game_hashes", "language", "observation"],
)
def test_准备登记与现场不符在部署和移动日志前拒绝(bundle, tmp_path, monkeypatch, field):
    from pdx.experiment_queue import RunRequest

    sources = _prepare_environment(bundle, tmp_path, monkeypatch)
    _edit(
        bundle["registration_path"],
        lambda r: r.update(
            {field: "bad" if field not in {"source_hashes", "game_hashes", "observation"} else {}}
        ),
    )
    monkeypatch.setattr(game_run.Deployment, "deploy", lambda *_a: pytest.fail("错误登记不能部署"))
    monkeypatch.setattr(
        game_run.ga, "quarantine_logs", lambda *_a: pytest.fail("错误登记不能移动日志")
    )
    monkeypatch.setattr(
        game_run.ga, "run_session", lambda **_kwargs: pytest.fail("错误登记不能启动")
    )
    report = game_run.run(
        sources,
        months=1,
        output=tmp_path / "output",
        load_save=bundle["checkpoint"],
        language="l_english",
        qualification_registration=bundle["registration_path"],
        qualification_context=bundle["context"],
        experiment=RunRequest(
            "r1-synthetic", "natural-AUS-SAR", "control", purpose="instrument", min_available_mib=0
        ),
    )
    assert not report["ok"]
    assert "资格" in str(report["failure"]), report
