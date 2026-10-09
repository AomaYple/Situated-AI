"""有限实机实验的单写入者账本；不续接游戏片段、不替代文件恢复。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .deployment_state import digest, plain_path

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _failure_types(report: Mapping[str, Any]) -> list[str]:
    findings = report.get("log_findings", {})
    raw_errors = findings.get("errors", {}) if isinstance(findings, dict) else {}
    errors = {key for key, count in raw_errors.items() if isinstance(count, int) and count > 0}
    if isinstance(findings, dict) and findings.get("mod_errors"):
        # 未枚举的模组错误统一保守计次，不被时间戳/对象 ID 的变化绕过。
        errors.add("unclassified-mod-error")
    return sorted(errors)


@dataclass(frozen=True)
class RunRequest:
    plan_id: str
    scene_id: str
    arm: str
    pair: int = 1
    purpose: str = "reconnaissance"
    max_scenes: int = 2
    max_pairs: int = 3
    max_months: float = 6
    min_available_mib: float = 4096

    def limits(self) -> dict[str, object]:
        if (
            not all((self.plan_id, self.scene_id, self.arm))
            or not 1 <= self.max_scenes <= 2
            or not 1 <= self.max_pairs <= 3
            or not 1 <= self.pair <= self.max_pairs
            or not math.isfinite(self.max_months)
            or self.max_months <= 0
            or not math.isfinite(self.min_available_mib)
            or self.min_available_mib < 0
        ):
            raise ValueError("实验身份或预算无效")
        return {
            "max_scenes": self.max_scenes,
            "max_pairs": self.max_pairs,
            "max_months": self.max_months,
            "min_available_mib": self.min_available_mib,
            "purpose": self.purpose,
        }


class ExperimentLedger:
    def __init__(self, path: Path) -> None:
        plain_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        database = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        try:
            database.execute("PRAGMA synchronous=FULL")
            database.execute(
                "CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, limits_json TEXT NOT NULL)"
            )
            database.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, plan TEXT NOT NULL, "
                "scene TEXT NOT NULL, arm TEXT NOT NULL, pair INTEGER NOT NULL, "
                "manifest TEXT NOT NULL, evidence TEXT NOT NULL UNIQUE, status TEXT NOT NULL, "
                "report_sha TEXT, errors TEXT NOT NULL DEFAULT '[]')"
            )
            database.execute(
                "CREATE TABLE IF NOT EXISTS prior_failures (plan TEXT NOT NULL, scene TEXT NOT NULL, "
                "evidence TEXT NOT NULL, report_sha TEXT NOT NULL, errors TEXT NOT NULL, "
                "PRIMARY KEY(plan,scene,evidence))"
            )
            database.execute("BEGIN IMMEDIATE")
            yield database
            database.commit()
        except BaseException:
            database.rollback()
            raise
        finally:
            database.close()

    def reserve(self, request: RunRequest, *, manifest: Mapping[str, Any], evidence: Path) -> str:
        """锁/资源/资格通过后预留身份，失败也占用有限探索预算。"""
        limits = _json(request.limits())
        frozen = _json(manifest)
        plain_path(evidence)
        with self._transaction() as database:
            plan = database.execute(
                "SELECT limits_json FROM plans WHERE id=?", (request.plan_id,)
            ).fetchone()
            if plan is not None and plan[0] != limits:
                raise ValueError("实验预算已冻结，拒绝事后改写")
            database.execute("INSERT OR IGNORE INTO plans VALUES (?,?)", (request.plan_id, limits))
            rows = database.execute(
                "SELECT * FROM runs WHERE plan=?", (request.plan_id,)
            ).fetchall()
            prior = database.execute(
                "SELECT * FROM prior_failures WHERE plan=?", (request.plan_id,)
            ).fetchall()
            scenes = {row["scene"] for row in [*rows, *prior]}
            if request.scene_id not in scenes and len(scenes) >= request.max_scenes:
                raise ValueError("已达到场景预算")
            scene = [row for row in rows if row["scene"] == request.scene_id]
            prior_scene = [row for row in prior if row["scene"] == request.scene_id]
            if len(scene) + len(prior_scene) >= request.max_pairs * 2:
                raise ValueError("已达到三组配对的运行预算（含失败）")
            errors: dict[str, int] = {}
            for row in [*scene, *prior_scene]:
                for error in json.loads(row["errors"]):
                    errors[error] = errors.get(error, 0) + 1
            if any(count >= 2 for count in errors.values()):
                raise ValueError("同场景同类引擎错误重复两次，停止派发")
            for row in scene:
                old_manifest = json.loads(row["manifest"])
                for key in (set(old_manifest) | set(manifest)) - {"sources"}:
                    if old_manifest.get(key) != manifest.get(key):
                        raise ValueError(f"场景冻结输入改变：{key}")
                if row["arm"] == request.arm and old_manifest.get("sources") != manifest.get(
                    "sources"
                ):
                    raise ValueError("同一实验臂的冻结输入改变")
                if row["arm"] == request.arm and row["pair"] == request.pair:
                    if row["manifest"] != frozen:
                        raise ValueError("任务冻结输入改变")
                    if row["status"] == "reserved":
                        raise ValueError("已有未完成任务，先核对中断恢复")
                    if row["status"] == "complete":
                        raise ValueError("该任务已完成，保留原件而不重复派发")
            if database.execute(
                "SELECT id FROM runs WHERE evidence=?", (str(evidence.resolve()),)
            ).fetchone():
                raise ValueError("证据目录已被使用，重跑必须新身份")
            run_id = uuid.uuid4().hex
            database.execute(
                "INSERT INTO runs (id,plan,scene,arm,pair,manifest,evidence,status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    request.plan_id,
                    request.scene_id,
                    request.arm,
                    request.pair,
                    frozen,
                    str(evidence.resolve()),
                    "reserved",
                ),
            )
            return run_id

    def finish(self, run_id: str, report: Mapping[str, Any], *, report_sha256: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", report_sha256):
            raise ValueError("报告指纹无效")
        errors = _failure_types(report)
        with self._transaction() as database:
            changed = database.execute(
                "UPDATE runs SET status=?,report_sha=?,errors=? WHERE id=? AND status='reserved'",
                (
                    "complete" if report.get("ok") is True else "rejected",
                    report_sha256,
                    _json(errors),
                    run_id,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("任务不存在或已封存，拒绝覆盖")

    def interrupt_pending(self) -> None:
        """仅由已持有 RunLock、证明游戏退出并完成部署恢复的入口调用。"""
        from .game_run import read_reviewed_report  # noqa: PLC0415

        with self._transaction() as database:
            rows = database.execute("SELECT * FROM runs WHERE status='reserved'").fetchall()
            for row in rows:
                path = Path(row["evidence"]) / "report.json"
                plain_path(path)
                report_sha = None
                errors: list[str] = []
                if path.exists():
                    report_sha = digest(path)
                    report = json.loads(path.read_text(encoding="utf-8"))
                    expected = {
                        "run_id": row["id"],
                        "plan_id": row["plan"],
                        "scene_id": row["scene"],
                        "arm": row["arm"],
                        "pair": row["pair"],
                        "manifest_sha256": hashlib.sha256(row["manifest"].encode()).hexdigest(),
                    }
                    actual = report.get("experiment", {})
                    if (
                        report.get("evidence") != row["evidence"]
                        or not isinstance(actual, dict)
                        or any(actual.get(key) != value for key, value in expected.items())
                    ):
                        raise ValueError("中断报告身份与冻结账本不符，拒绝消除停止事实")
                    findings = report.get("log_findings", {})
                    counts = findings.get("errors", {}) if isinstance(findings, dict) else None
                    if not (
                        report.get("session_requested") is False
                        and report.get("logs_isolated") is False
                        and not report.get("log_hashes")
                        and isinstance(findings, dict)
                        and isinstance(counts, dict)
                        and all(type(count) is int and count == 0 for count in counts.values())
                        and not findings.get("mod_errors")
                        and not findings.get("mounted")
                        and not findings.get("unexpected_mounts")
                    ):
                        report = read_reviewed_report(path)
                    if digest(path) != report_sha:
                        raise ValueError("中断报告在复核中发生变化")
                    errors = _failure_types(report)
                database.execute(
                    "UPDATE runs SET status='interrupted',report_sha=?,errors=? WHERE id=?",
                    (report_sha, _json(errors), row["id"]),
                )

    def import_prior_failure(
        self,
        request: RunRequest,
        path: Path,
        *,
        checkpoint_sha256: str,
        game_version: Mapping[str, Any],
    ) -> None:
        """显式导入同检查点/游戏版本的保守停止事实，不复用为行为样本。"""
        from .game_run import read_reviewed_report  # noqa: PLC0415

        plain_path(path)
        report_sha = digest(path)
        report = read_reviewed_report(path)
        errors = _failure_types(report)
        if (
            report.get("loaded_save", {}).get("sha256") != checkpoint_sha256
            or report.get("game_version") != game_version
            or not errors
            or digest(path) != report_sha
        ):
            raise ValueError("历史失败的检查点、版本、错误或指纹不符")
        limits = _json(request.limits())
        evidence = str(path.resolve())
        with self._transaction() as database:
            plan = database.execute(
                "SELECT limits_json FROM plans WHERE id=?", (request.plan_id,)
            ).fetchone()
            if plan is not None and plan[0] != limits:
                raise ValueError("实验预算已冻结，拒绝事后改写")
            database.execute("INSERT OR IGNORE INTO plans VALUES (?,?)", (request.plan_id, limits))
            scenes = {
                row[0]
                for row in database.execute(
                    "SELECT scene FROM runs WHERE plan=? UNION SELECT scene FROM prior_failures WHERE plan=?",
                    (request.plan_id, request.plan_id),
                )
            }
            if request.scene_id not in scenes and len(scenes) >= request.max_scenes:
                raise ValueError("已达到场景预算，拒绝导入第三个场景")
            duplicate = database.execute(
                "SELECT report_sha FROM prior_failures WHERE plan=? AND scene=? AND evidence=?",
                (request.plan_id, request.scene_id, evidence),
            ).fetchone()
            if duplicate is not None and duplicate[0] != report_sha:
                raise ValueError("已导入的历史报告发生改变")
            existing = database.execute(
                "SELECT id FROM runs WHERE plan=? AND scene=? AND evidence=?",
                (request.plan_id, request.scene_id, str(path.parent.resolve())),
            ).fetchone()
            if existing is not None:
                raise ValueError("历史运行已在账本中，拒绝重复计次")
            database.execute(
                "INSERT OR IGNORE INTO prior_failures VALUES (?,?,?,?,?)",
                (request.plan_id, request.scene_id, evidence, report_sha, _json(errors)),
            )

    def used_arms(self, plan_id: str, scene_id: str) -> int:
        with self._transaction() as database:
            return sum(
                database.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE plan=? AND scene=?",
                    (plan_id, scene_id),
                ).fetchone()[0]
                for table in ("runs", "prior_failures")
            )

    def runs(self, plan_id: str) -> list[dict[str, Any]]:
        with self._transaction() as database:
            return [
                dict(row)
                for row in database.execute(
                    "SELECT * FROM runs WHERE plan=? ORDER BY rowid", (plan_id,)
                )
            ]

    def manifest_sha256(self, run_id: str) -> str:
        with self._transaction() as database:
            row = database.execute("SELECT manifest FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("任务不存在")
            return hashlib.sha256(row[0].encode("utf-8")).hexdigest()
