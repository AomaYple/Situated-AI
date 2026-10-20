"""内容绑定的检查点目录与资格预检；不从处理后结果挑选正式机会。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .deployment_state import digest, plain_path

STATES = ("instrument-suitable", "formal-pair-suitable", "rejected", "opportunity-unknown")


def _protected_roots(
    screen_saves: Sequence[Path], origin_reports: Sequence[Path]
) -> tuple[Path, ...]:
    """返回筛选输入及其来源证据根；screen 输入的来源根按 report 父目录保守保护。"""
    roots: list[Path] = []
    for report in origin_reports:
        plain_path(report)
        roots.append(report.parent)
    for save in screen_saves:
        plain_path(save)
        roots.append(save)
        if save.parent.name.casefold() == "saves":
            report = save.parent.parent / "report.json"
            if report.exists():
                plain_path(report)
                roots.append(report.parent)
    return tuple(dict.fromkeys(Path(os.path.normcase(str(root.resolve()))) for root in roots))


def _output_conflicts(output: Path, roots: Sequence[Path]) -> bool:
    """检查输出是否落在受保护证据根内，兼容相对、大小写和重解析点路径。"""
    plain_path(output)
    candidate = Path(os.path.normcase(str(output.resolve())))
    return any(candidate == root or root in candidate.parents for root in roots)


def _review_preparation(path: Path, report: Mapping[str, Any]) -> list[str]:
    """原版新局没有载入存档或探针，按独立准备契约核验，不能借用行为资格。"""
    from .game_run import (  # noqa: PLC0415
        require_clean_report,
        save_header,
        validate_load_save_header,
    )

    require_clean_report(dict(report))
    reasons: list[str] = []
    for field, expected in (
        ("content_load", "vanilla_only"),
        ("source_hashes", {}),
        ("deployed_hashes", {}),
        ("cleanup_errors", []),
        ("session_requested", True),
        ("logs_isolated", True),
    ):
        if (
            field not in report
            or type(report[field]) is not type(expected)
            or report[field] != expected
        ):
            reasons.append(f"preparation.{field}")
    if report.get("loaded_save") or (path.parent / "sources").exists():
        reasons.append("preparation.not_vanilla_new_game")
    checkpoint = report.get("checkpoint")
    if not isinstance(checkpoint, Mapping) or not isinstance(checkpoint.get("header"), Mapping):
        reasons.append("preparation.checkpoint_missing")
        return reasons
    output = path.parent / "saves" / "checkpoint.v3"
    plain_path(output)
    before = digest(output)
    header = save_header(output)
    if checkpoint.get("hashes") != {output.name: before} or digest(output) != before:
        reasons.append("preparation.output_changed_or_incomplete")
    if checkpoint["header"] != header or header.get("observer") != "yes":
        reasons.append("preparation.header_differs_or_not_observer")
    version = report.get("game_version")
    expected_version = version.get("caligula_branch") if isinstance(version, Mapping) else None
    if not isinstance(expected_version, str) or not expected_version:
        reasons.append("preparation.game_version_missing")
    else:
        validate_load_save_header(
            header,
            expected_version=expected_version.split("/")[-1],
            allow_save_upgrade=False,
        )
    return reasons


def _review_mod_preparation(path: Path, report: Mapping[str, Any]) -> list[str]:
    """复用完整日志和部署审计，只为新局输出免除不存在的载入指纹。"""
    from .game_run import (  # noqa: PLC0415
        require_clean_report,
        save_header,
        validate_load_save_header,
    )
    from .m3a_screen import load_report  # noqa: PLC0415

    require_clean_report(dict(report))
    facts = load_report(path)
    reasons = [reason for reason in facts.gate_reasons if reason != "loaded_save.sha256_missing"]
    if "loaded_save" in report or any(
        key in report for key in ("experiment", "qualification_report", "qualification_preparation")
    ):
        reasons.append("mod_preparation.not_new_game")
    reasons.extend(
        f"mod_preparation.{key}"
        for key in ("session_requested", "logs_isolated")
        if report.get(key) is not True
    )
    session, progress = report.get("session"), report.get("progress")
    if (
        not isinstance(session, Mapping)
        or session.get("automation_phase") != "complete"
        or session.get("speed_ok") is not True
        or not isinstance(progress, Mapping)
        or progress.get("reached") is not True
    ):
        reasons.append("mod_preparation.session_incomplete")
    checkpoint = report.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        return [*reasons, "mod_preparation.checkpoint_missing"]
    output = path.parent / "saves/autosave.v3"
    plain_path(output)
    before = digest(output)
    header = save_header(output)
    if checkpoint.get("hashes") != {output.name: before} or digest(output) != before:
        reasons.append("mod_preparation.output_changed_or_incomplete")
    if (
        checkpoint.get("header") != header
        or report.get("checkpoint_ready") != header
        or header.get("observer") != "yes"
    ):
        reasons.append("mod_preparation.header_differs_or_not_observer")
    version = report.get("game_version")
    expected_version = version.get("caligula_branch") if isinstance(version, Mapping) else None
    if not isinstance(expected_version, str) or not expected_version:
        reasons.append("mod_preparation.game_version_missing")
    else:
        validate_load_save_header(
            header, expected_version=expected_version.split("/")[-1], allow_save_upgrade=False
        )
    return list(dict.fromkeys(reasons))


def _review_report(path: Path) -> dict[str, Any]:
    """保留输出指纹后复核原局，避免把失败局产物当作新输入。"""
    from .game_run import read_reviewed_report  # noqa: PLC0415
    from .m3a_screen import load_report  # noqa: PLC0415

    row: dict[str, Any] = {
        "path": str(path.resolve()),
        "clean": False,
        "reasons": [],
        "output_sha256": [],
    }
    try:
        plain_path(path)
        before = digest(path)
        row["sha256"] = before
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("报告根必须是对象")
        checkpoint = raw.get("checkpoint")
        if isinstance(checkpoint, Mapping):
            outputs = checkpoint.get("hashes")
            if isinstance(outputs, Mapping):
                row["output_sha256"] = sorted(
                    {
                        value
                        for name, value in outputs.items()
                        if isinstance(name, str)
                        and name.lower().endswith(".v3")
                        and isinstance(value, str)
                        and re.fullmatch(r"[0-9a-f]{64}", value)
                    }
                )
        for field in (
            "loaded_save",
            "game_version",
            "source_hashes",
            "deployed_hashes",
            "log_findings",
        ):
            if field in raw and not isinstance(raw[field], Mapping):
                raise ValueError(f"报告字段 {field} 必须是对象")
        loaded = raw.get("loaded_save", {})
        if "header" in loaded and not isinstance(loaded["header"], Mapping):
            raise ValueError("报告字段 loaded_save.header 必须是对象")
        is_preparation = raw.get("kind") == "vanilla_checkpoint_preparation"
        row["kind"] = raw.get("kind")
        # 旧运行器未写 kind；只读识别完整的新局保存结构，不改写原报告。
        is_mod_preparation = raw.get("kind") == "mod_checkpoint_preparation" or (
            "kind" not in raw
            and "loaded_save" not in raw
            and isinstance(raw.get("checkpoint_ready"), Mapping)
            and isinstance(checkpoint, Mapping)
        )
        if is_mod_preparation:
            reasons = _review_mod_preparation(path, raw)
            output_sha = row["output_sha256"]
            row.update(
                kind="mod_checkpoint_preparation",
                classification="reported" if "kind" in raw else "structural_legacy",
                checkpoint_sha256=output_sha[0] if len(output_sha) == 1 else None,
                clean=not reasons,
                reasons=reasons,
            )
        del raw
        if is_preparation:
            reviewed = read_reviewed_report(path)
            reasons = _review_preparation(path, reviewed)
            output_sha = row["output_sha256"]
            row.update(
                checkpoint_sha256=output_sha[0] if len(output_sha) == 1 else None,
                clean=not reasons,
                reasons=reasons,
            )
        elif not is_mod_preparation:
            # 行为报告加载器已执行当前日志门禁；避免再次散列/扫描同一大归档。
            facts = load_report(path)
            row.update(
                checkpoint_sha256=facts.checkpoint_sha256,
                clean=facts.clean,
                reasons=list(facts.gate_reasons),
            )
        if digest(path) != before:
            raise ValueError("报告在复核中变化")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        row["clean"] = False
        row["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return row


def _check_origins(
    result: dict[str, Any], path: Path, reports: Sequence[Mapping[str, Any]] | None
) -> None:
    """局部来源在运行前检查；目录盘点还按内容匹配复制、改名后的输出。"""
    local = path.parent.parent / "report.json" if path.parent.name == "saves" else None
    local_name = str(local.resolve()) if local is not None else None
    reports = list(reports or ())
    if local is not None and not any(row["path"] == local_name for row in reports):
        reports.append(_review_report(local))
    origins = [
        row
        for row in reports
        if result["sha256"] in row.get("output_sha256", ()) or row["path"] == local_name
    ]
    result["origin_reports"] = [dict(row) for row in origins]
    for row in origins:
        if result["sha256"] not in row.get("output_sha256", ()):
            result["reasons"].append("origin.output_unverified")
        if row.get("clean") is not True:
            result["reasons"].append("origin.not_clean")
    if any(reason.startswith("origin.") for reason in result["reasons"]):
        result["state"] = "rejected"
        result["instrument_suitable"] = False
    result["reasons"] = list(dict.fromkeys(result["reasons"]))


def inspect(
    path: Path,
    *,
    expected_version: str,
    allow_save_upgrade: bool = False,
    origin_reports: Sequence[Mapping[str, Any]] | None = None,
    qualification_report: Path | None = None,
    purpose: str | None = None,
    qualification_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """载入资格与正式资格分别核验；无独立报告仍保持机会未知。"""
    from .game_run import save_header, validate_load_save_header  # noqa: PLC0415

    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "state": "rejected",
        "sha256": None,
        "header": {},
        "instrument_suitable": False,
        "formal_pair_suitable": False,
        "opportunity_count": None,
        "reasons": [],
        "origin_reports": [],
    }
    try:
        plain_path(path)
        before = path.stat()
        result["sha256"] = digest(path)
        result["header"] = header = save_header(path)
        after = path.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("检查点在资格读取中发生变化")
        validate_load_save_header(
            header, expected_version=expected_version, allow_save_upgrade=allow_save_upgrade
        )
        result["instrument_suitable"] = True
        result["state"] = (
            "instrument-suitable"
            if header["version"] != expected_version
            else "opportunity-unknown"
        )
        result["reasons"] = ["opportunity.unverified"]
        if header["version"] != expected_version:
            result["reasons"].append("upgrade.load_unverified")
    except (OSError, ValueError, UnicodeError) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    if result["sha256"] is not None:
        _check_origins(result, path, origin_reports)
    if qualification_report is not None:
        from .experiment_evidence import validate  # noqa: PLC0415

        qualification = validate(
            qualification_report,
            checkpoint_sha256=result["sha256"],
            expected_version=expected_version,
            purpose=purpose or "",
            context=qualification_context,
        )
        result["qualification"] = qualification
        diagnostic_origin = any(
            row.get("kind") == "mod_checkpoint_preparation" for row in result["origin_reports"]
        )
        if diagnostic_origin:
            result["reasons"].append("origin.diagnostic_only")
        if (
            result["instrument_suitable"]
            and result["header"].get("version") == expected_version
            and qualification["allowed"]
            and not diagnostic_origin
        ):
            result["formal_pair_suitable"] = True
            result["formal_purpose"] = purpose
            result["state"] = "formal-pair-suitable"
            result["opportunity_count"] = qualification.get("opportunity_count")
            result["reasons"] = []
        else:
            result["reasons"].extend(qualification["reasons"])
            result["reasons"] = list(dict.fromkeys(result["reasons"]))
    return result


def preflight(
    checkpoint: dict[str, Any],
    *,
    purpose: str,
    months: float,
    used_arms: int = 0,
    stop_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    """资格与预算分开。持久计数、锁与资源由实验账本/运行器负责。"""
    reasons = list(stop_reasons)
    if purpose not in {"instrument", "reconnaissance", "safety", "M3-A", "M3-B", "M4", "M4-noise"}:
        reasons.append("purpose.invalid")
    if not math.isfinite(months) or months <= 0:
        reasons.append("months.invalid")
    if checkpoint.get("instrument_suitable") is not True:
        reasons.extend(checkpoint.get("reasons", ("checkpoint.rejected",)))
    if purpose in {"M3-A", "M3-B", "M4"}:
        if checkpoint.get("formal_pair_suitable") is not True:
            reasons.append("opportunity.unverified")
            reasons.extend(checkpoint.get("qualification", {}).get("reasons", ()))
        elif checkpoint.get("formal_purpose") != purpose:
            reasons.append("qualification.purpose")
    if purpose in {"instrument", "reconnaissance", "M3-A", "M3-B"}:
        if months > 6:
            reasons.append("budget.six_months")
        if used_arms >= 6:
            reasons.append("budget.three_pairs")
    if purpose == "M4-noise":
        if months > 120:
            reasons.append("budget.noise_window")
        if used_arms >= 3:
            reasons.append("budget.three_runs")
    if purpose == "M4" and not 24 <= months <= 120:
        reasons.append("budget.m4_window")
    if used_arms < 0:
        reasons.append("budget.invalid_count")
    return {
        "allowed": not reasons,
        "purpose": purpose,
        "months": months,
        "used_arms": used_arms,
        "remaining_arms": max(0, (3 if purpose == "M4-noise" else 6) - used_arms),
        "state": checkpoint.get("state"),
        "opportunity_count": checkpoint.get("opportunity_count"),
        "reasons": list(dict.fromkeys(reasons)),
    }


def catalog(root: Path, *, expected_version: str) -> dict[str, Any]:
    """盘点全部输入和历史拒绝项；报告仅证明仪器曾工作，不提名处理后机会。"""
    plain_path(root)
    if not root.is_dir():
        raise ValueError(f"目录不存在：{root}")
    reports = [_review_report(path) for path in sorted(root.rglob("report.json"))]
    entries = [
        inspect(p, expected_version=expected_version, origin_reports=reports)
        for p in sorted(root.rglob("*.v3"))
    ]
    for entry in entries:
        entry["instrument_reports"] = [
            row["path"]
            for row in reports
            if row.get("checkpoint_sha256") == entry["sha256"] and row["clean"]
        ]
    parser_sources = [Path(__file__), Path(__file__).with_name("game_run.py")]
    return {
        "schema": 1,
        "root": str(root.resolve()),
        "expected_version": expected_version,
        "states": STATES,
        "parser_sha256": {p.name: digest(p) for p in parser_sources},
        "state_counts": dict(Counter(row["state"] for row in entries)),
        "entries": entries,
        "reports": reports,
        "limits": [
            "二进制头只证明存档具备加载资格；决策机会仍未知",
            "不使用处理后的评分或角色来筛选检查点",
            "formal-pair-suitable 需要独立核实处理前的决策机会；此处尚无该证据",
            "原局输出按完整 SHA 关联；失败或缺证的来源不得作为干净输入，改名复制不改变此边界",
            "来源关联仅覆盖盘点根；无关联不证明来源干净，也不证明新场景或后期资格",
        ],
    }


def main() -> int:
    from .game_run import write_json  # noqa: PLC0415
    from .save_migration import current_game_version  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screen-save", type=Path, action="append", default=[])
    parser.add_argument("--expected-sha256", action="append", default=[])
    parser.add_argument("--origin-report", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.screen_save:
        from .checkpoint_screen import screen  # noqa: PLC0415

        if args.root is not None:
            parser.error("显式原件筛选不接受递归目录 root")
        if len(args.screen_save) != len(args.expected_sha256):
            parser.error("每份 --screen-save 必须对应一份完整 --expected-sha256")
        try:
            protected_roots = _protected_roots(args.screen_save, args.origin_report)
            if args.output.suffix.lower() == ".v3" or _output_conflicts(
                args.output, protected_roots
            ):
                parser.error("筛选结果不得覆盖原始存档或来源证据根")
        except ValueError as exc:
            parser.error(str(exc))
        try:
            result = screen(
                list(zip(args.screen_save, args.expected_sha256, strict=True)),
                expected_version=current_game_version(),
                origin_report_paths=args.origin_report,
            )
        except ValueError as exc:
            parser.error(str(exc))
    else:
        if args.root is None or args.expected_sha256 or args.origin_report:
            parser.error("普通目录模式必须给 root；筛选附加参数需配合 --screen-save")
        result = catalog(args.root, expected_version=current_game_version())
    write_json(args.output, result)
    print(json.dumps({"state_counts": result["state_counts"], "reports": len(result["reports"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
