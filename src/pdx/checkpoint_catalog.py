"""内容绑定的检查点目录与资格预检；不从处理后结果挑选正式机会。"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .deployment_state import digest, plain_path

STATES = ("instrument-suitable", "formal-pair-suitable", "rejected", "opportunity-unknown")


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
        del raw
        reviewed = read_reviewed_report(path)
        facts = load_report(path)
        if digest(path) != before:
            raise ValueError("报告在复核中变化")
        row.update(
            checkpoint_sha256=facts.checkpoint_sha256,
            clean=reviewed.get("ok") is True and facts.clean,
            reasons=list(facts.gate_reasons),
        )
        if reviewed.get("ok") is not True:
            row["reasons"].append(str(reviewed.get("failure", "report.rejected")))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
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
) -> dict[str, Any]:
    """只证明输入内容、载入资格；当前二进制头不提供外交机会分母。"""
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
    if purpose not in {"instrument", "reconnaissance", "safety", "M3-A", "M3-B", "M4"}:
        reasons.append("purpose.invalid")
    if not math.isfinite(months) or months <= 0:
        reasons.append("months.invalid")
    if checkpoint.get("instrument_suitable") is not True:
        reasons.extend(checkpoint.get("reasons", ("checkpoint.rejected",)))
    if purpose in {"M3-A", "M3-B", "M4"} and checkpoint.get("formal_pair_suitable") is not True:
        reasons.append("opportunity.unverified")
    if purpose in {"instrument", "reconnaissance", "M3-A", "M3-B"}:
        if months > 6:
            reasons.append("budget.six_months")
        if used_arms >= 6:
            reasons.append("budget.three_pairs")
    if used_arms < 0:
        reasons.append("budget.invalid_count")
    return {
        "allowed": not reasons,
        "purpose": purpose,
        "months": months,
        "used_arms": used_arms,
        "remaining_arms": max(0, 6 - used_arms),
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
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = catalog(args.root, expected_version=current_game_version())
    write_json(args.output, result)
    print(json.dumps({"state_counts": result["state_counts"], "reports": len(result["reports"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
