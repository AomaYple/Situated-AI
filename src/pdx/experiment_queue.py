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
from typing import TYPE_CHECKING, Any

from .deployment_state import plain_path

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


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
            scenes = {row["scene"] for row in rows}
            if request.scene_id not in scenes and len(scenes) >= request.max_scenes:
                raise ValueError("已达到场景预算")
            scene = [row for row in rows if row["scene"] == request.scene_id]
            if len(scene) >= request.max_pairs * 2:
                raise ValueError("已达到三组配对的运行预算（含失败）")
            errors: dict[str, int] = {}
            for row in scene:
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
        findings = report.get("log_findings", {})
        raw_errors = findings.get("errors", {}) if isinstance(findings, dict) else {}
        errors = sorted(
            key for key, count in raw_errors.items() if isinstance(count, int) and count > 0
        )
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
        with self._transaction() as database:
            database.execute("UPDATE runs SET status='interrupted' WHERE status='reserved'")

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
