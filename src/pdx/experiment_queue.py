"""有限实机实验的单写入者账本；不续接游戏片段、不替代文件恢复。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, TypeGuard

from .deployment_state import digest, plain_path, tree_digest

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator, Mapping

SCHEMA_VERSION = 1
PURPOSES = frozenset({"reconnaissance", "instrument", "safety", "M3-A", "M3-B", "M4", "M4-noise"})
ARMS = frozenset(
    {
        "control",
        "candidate",
        "neutrality",
        "aggression",
        "market-control",
        "market",
        "vanilla",
        "fiscal",
        "reform",
        "combined",
        "reform-positive-control",
        "reform-global-positive-control",
    }
)


def _text(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and all(character.isprintable() for character in value)
    )


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _sha(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _hash_tree(value: object) -> str | None:
    """运行器的来源结构是 mod 名称 -> 文件名 -> SHA；不接受布尔宣告。"""
    if _sha(value):
        return str(value)
    if (
        isinstance(value, dict)
        and value
        and all(_text(key) and _hash_tree(child) is not None for key, child in value.items())
    ):
        return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
    return None


def _game_hashes(value: object) -> TypeGuard[dict[str, str]]:
    """完整原版文件指纹表；拒绝无效路径、缺摘要与空表。"""
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            _text(name)
            and "\\" not in name
            and ":" not in name
            and not PurePosixPath(name).is_absolute()
            and all(part not in {"", ".", ".."} for part in name.split("/"))
            and _sha(fingerprint)
            for name, fingerprint in value.items()
        )
    )


def _archived_input_state(path: Path) -> tuple[tuple[int, ...], str] | None:
    """归档输入允许缺失；存在时必须为稳定普通原件，链接不能冒充缺失。"""
    plain_path(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("归档输入不是普通文件")
    fingerprint = digest(path)
    plain_path(path)
    after = path.lstat()

    def signature(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    if signature(before) != signature(after):
        raise ValueError("归档输入读取期间发生变化")
    return signature(after), fingerprint


def new_game_identity(
    *,
    game: Mapping[str, str],
    sources: Mapping[str, Any],
    language: str | None,
    disabled_dlc: list[str],
) -> str:
    """冻结新局来源；这是运行配置摘要，不是真实存档字节的身份。"""
    payload = {
        "kind": "new-game",
        "game": game,
        "sources": sources,
        "language": language,
        "disabled_dlc": disabled_dlc,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _synthetic_checkpoint(manifest: Mapping[str, Any]) -> bool:
    """按原配方识别已有新局记录，无需修改历史账本或信任新增布尔标签。"""
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        return False
    game = environment.get("game")
    sources = manifest.get("sources")
    if (
        not isinstance(game, dict)
        or not isinstance(sources, dict)
        or "language" not in environment
        or "disabled_dlc" not in environment
    ):
        return False
    return manifest.get("checkpoint") == new_game_identity(
        game={key: value for key, value in game.items() if key != "content_sha256"},
        sources=sources,
        language=environment["language"],
        disabled_dlc=environment["disabled_dlc"],
    )


def _stop_context(manifest: Mapping[str, Any]) -> dict[str, str]:
    """仅已知运行输入能证明新前提；标签、预算、工具/文档指纹不能重开。"""
    context: dict[str, str] = {}
    if _sha(manifest.get("checkpoint")):
        # 新局摘要包含探针源码，不能把代码改动当作真实检查点变化。
        # 保留固定身份以区分新局与实际存档；完整摘要仍在 manifest 冻结。
        context["checkpoint"] = (
            "new-game" if _synthetic_checkpoint(manifest) else manifest["checkpoint"]
        )
    environment = manifest.get("environment")
    if isinstance(environment, dict):
        language = environment.get("language")
        if _text(language):
            context["language"] = language
        game = environment.get("game")
        if isinstance(game, dict):
            for key in (
                "caligula_branch",
                "caligula_rev",
                "clausewitz_branch",
                "clausewitz_rev",
                "version",
                "sha256",
            ):
                value = game.get(key)
                if _text(value) and (not key.endswith("sha256") or _sha(value)):
                    context[f"game:{key}"] = value
    game_hashes = manifest.get("game_hashes")
    if _game_hashes(game_hashes):
        for name, value in game_hashes.items():
            context[f"game-file:{name}"] = value
    # 尚无具体错误到探针/诊断依赖的因果映射，来源或 simulation 变化不能
    # 自动证明原版错误前提已解除。它们仍受完整 manifest 冻结和兼容性审查。
    return context


def _recover_prior_failure_context(evidence: object, report_sha: object) -> dict[str, str]:
    """只读恢复旧导入记录的停止上下文，不改写账本或原报告。

    旧记录早于上下文附表；只有报告仍匹配账本 SHA 且原始日志通过现有
    复核时，才能派生历史输入。缺证或原件变化返回空上下文，维持保守停止。
    """
    if not _text(evidence) or not _sha(report_sha):
        return {}
    from . import game_run  # noqa: PLC0415

    path = Path(evidence)
    try:
        plain_path(path)
        if digest(path) != report_sha:
            return {}
        report = game_run.read_reviewed_report(path)
        review = report.get("review")
        if (
            not isinstance(review, dict)
            or review.get("report_sha256") != report_sha
            or review.get("logs_verified") is not True
            or digest(path) != report_sha
            or game_run.hashes(path.parent / "logs") != report.get("log_hashes")
        ):
            return {}
        loaded = report.get("loaded_save")
        game = report.get("game_version")
        sources = report.get("source_hashes")
        if "game_hashes" in report and not _game_hashes(report["game_hashes"]):
            return {}
        if (
            not isinstance(loaded, dict)
            or not _sha(loaded.get("sha256"))
            or not isinstance(game, dict)
            or not game
            or not all(_text(key) and _text(value) for key, value in game.items())
            or not isinstance(sources, dict)
            or not sources
        ):
            return {}
        flattened: dict[str, str] = {}
        for name, files in sources.items():
            if (
                not _text(name)
                or any(character in name for character in "/\\:")
                or name in {".", ".."}
                or not isinstance(files, dict)
                or not files
            ):
                return {}
            for relative, fingerprint in files.items():
                if (
                    not _text(relative)
                    or "\\" in relative
                    or ":" in relative
                    or PurePosixPath(relative).is_absolute()
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                    or not _sha(fingerprint)
                ):
                    return {}
                flattened[f"{name}/{relative}"] = fingerprint
        source_root = path.parent / "sources"
        source_signature = tree_digest(source_root)
        if game_run.hashes(source_root) != flattened:
            return {}
        input_path = path.parent / "input.v3"
        input_state = _archived_input_state(input_path)
        if input_state is not None and input_state[1] != loaded["sha256"]:
            return {}
        manifest: dict[str, Any] = {
            "checkpoint": loaded["sha256"],
            "environment": {"game": game, "language": report.get("language")},
            "game_hashes": report.get("game_hashes"),
        }
        context = _stop_context(manifest)
        if (
            digest(path) != report_sha
            or game_run.hashes(path.parent / "logs") != report.get("log_hashes")
            or tree_digest(source_root) != source_signature
            or game_run.hashes(source_root) != flattened
            or _archived_input_state(input_path) != input_state
        ):
            return {}
        return context if any(key.startswith("game:") for key in context) else {}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def _same_stop_context(left: dict[str, str], right: dict[str, str]) -> bool:
    # 缺失字段不能被补一个新标签/布尔值解释为前提不同。只有双方都有的真实
    # 指纹或已知环境字段不同才允许重开；未知动态依赖不充当重开依据。
    # 旧附表可能保存集合范围未声明的聚合内容指纹；观测包增删会改变集合，
    # 即使原版文件一字未改也会改变摘要。只比较双方共有的实际文件内容。
    return all(
        left[key] == right[key]
        for key in left.keys() & right.keys()
        if key != "game:content_sha256"
    )


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _compatibility_facts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    environment = manifest.get("environment")
    environment = environment if isinstance(environment, dict) else {}
    qualification = manifest.get("qualification")
    qualification = qualification if isinstance(qualification, dict) else {}
    context = qualification.get("context")
    context = context if isinstance(context, dict) else {}
    return {
        "checkpoint": manifest.get("checkpoint"),
        "sources": manifest.get("sources"),
        "probe_sources": manifest.get("probe_sources"),
        "environment.game": environment.get("game"),
        "environment.language": environment.get("language"),
        "environment.tools": environment.get("tools"),
        "environment.disabled_dlc": environment.get("disabled_dlc"),
        "environment.mount_allowlist": environment.get("mount_allowlist"),
        "provenance": manifest.get("provenance"),
        "months": manifest.get("months"),
        "timeout": manifest.get("timeout"),
        "profile": manifest.get("profile"),
        "allow_save_upgrade": manifest.get("allow_save_upgrade"),
        "keep_save": manifest.get("keep_save"),
        "observation": manifest.get("observation", context.get("observation")),
    }


def _invalid_compatibility_fields(facts: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if not _sha(facts["checkpoint"]):
        invalid.append("checkpoint")
    for field in ("sources", "probe_sources"):
        value = facts[field]
        if not isinstance(value, dict) or not all(
            _text(key) and _hash_tree(child) is not None for key, child in value.items()
        ):
            invalid.append(field)
    game = facts["environment.game"]
    if (
        not isinstance(game, dict)
        or not _sha(game.get("content_sha256"))
        or not (_text(game.get("caligula_branch")) or _text(game.get("version")))
    ):
        invalid.append("environment.game")
    if not _text(facts["environment.language"]):
        invalid.append("environment.language")
    tools = facts["environment.tools"]
    if (
        not isinstance(tools, dict)
        or not tools
        or not all(_text(key) and _sha(value) for key, value in tools.items())
    ):
        invalid.append("environment.tools")
    for field in ("environment.disabled_dlc", "environment.mount_allowlist"):
        value = facts[field]
        if (
            not isinstance(value, list)
            or not all(_text(item) for item in value)
            or len(value) != len(set(value))
            or (field.endswith("mount_allowlist") and not value)
        ):
            invalid.append(field)
    invalid.extend(
        field
        for field in ("months", "timeout")
        if not _finite_number(facts[field]) or facts[field] <= 0
    )
    invalid.extend(
        field
        for field in ("profile", "allow_save_upgrade", "keep_save")
        if type(facts[field]) is not bool
    )
    observation = facts["observation"]
    if (
        not isinstance(observation, dict)
        or not _text(observation.get("version"))
        or not _text(observation.get("package"))
    ):
        invalid.append("observation")
    return invalid


def _known_provenance(value: object) -> bool:
    """无来源回调和未知动态依赖不能因全模块指纹相同冒称已知。"""
    if not isinstance(value, dict):
        return False
    files = value.get("files")
    callback = value.get("callback")
    runtime = value.get("runtime")
    if (
        type(value.get("schema")) is not int
        or value["schema"] != 1
        or value.get("dependency_scope") != "conservative-full"
        or set(value) != {"schema", "files", "callback", "runtime", "dependency_scope"}
        or not isinstance(files, dict)
        or not files
        or not all(_text(name) and _sha(digest) for name, digest in files.items())
        or not isinstance(callback, dict)
        or set(callback) != {"path", "sha256"}
        or not _text(callback.get("path"))
        or not _sha(callback.get("sha256"))
        or files.get(callback["path"]) != callback["sha256"]
        or not isinstance(runtime, dict)
        or set(runtime) != {"python", "platform", "libraries"}
        or not _text(runtime.get("python"))
        or not _text(runtime.get("platform"))
    ):
        return False
    libraries = runtime.get("libraries")
    return (
        isinstance(libraries, dict)
        and bool(libraries)
        and all(
            _text(name) and (version is None or _text(version))
            for name, version in libraries.items()
        )
    )


def _changed_fields(previous: object, current: object, prefix: str = "") -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        fields: list[str] = []
        for key in sorted(previous.keys() | current.keys()):
            field = f"{prefix}.{key}" if prefix else key
            if key not in previous or key not in current:
                fields.append(field)
            else:
                fields.extend(_changed_fields(previous[key], current[key], field))
        return fields
    return [] if _json(previous) == _json(current) else [prefix]


def assess_compatibility(
    previous_manifest: Mapping[str, Any] | None, current_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """只读比较已冻结事实；兼容不替代资格、原件复核或原样本身份。

    旧记录缺少内容/观测字段以及未解释的工具或动态依赖变化均保持未知。
    本轮没有已审核的纯解析职责 profile，因此不自动给出 must-reparse。
    返回结果不修改账本、不刷新停止事实，也不允许复制独立样本。
    """
    result: dict[str, Any] = {
        "schema": 1,
        "state": "unknown",
        "compatible": False,
        "sample_reuse_authorized": False,
        "requires_qualification_review": True,
        "reasons": [],
        "changed_fields": [],
        "missing_fields": [],
        "invalid_fields": [],
    }
    if previous_manifest is None:
        result["reasons"] = ["manifest.previous_missing"]
        result["missing_fields"] = ["previous_manifest"]
        return result
    if not isinstance(previous_manifest, dict) or not isinstance(current_manifest, dict):
        result["reasons"] = ["manifest.shape_unknown"]
        return result
    try:
        _json(previous_manifest)
        _json(current_manifest)
        result["changed_fields"] = _changed_fields(previous_manifest, current_manifest)
        before = _compatibility_facts(previous_manifest)
        after = _compatibility_facts(current_manifest)
        result["missing_fields"] = sorted(
            {field for facts in (before, after) for field, value in facts.items() if value is None}
        )
        result["invalid_fields"] = sorted(
            set(_invalid_compatibility_fields(before)) | set(_invalid_compatibility_fields(after))
        )
        if result["missing_fields"] or result["invalid_fields"]:
            result["reasons"] = ["manifest.facts_incomplete_or_invalid"]
            return result
        if any(
            "dynamic_dependencies" in manifest for manifest in (previous_manifest, current_manifest)
        ):
            result["reasons"] = ["manifest.dynamic_dependencies_unreviewed"]
            return result
        if not all(_known_provenance(facts["provenance"]) for facts in (before, after)):
            result["reasons"] = ["manifest.provenance_unreviewed"]
            return result
        actual_inputs = set(before) - {"environment.tools", "provenance"}
        if any(_json(before[field]) != _json(after[field]) for field in actual_inputs):
            result["state"] = "must-rerun"
            result["reasons"] = ["manifest.run_inputs_changed"]
        elif result["changed_fields"]:
            result["reasons"] = ["manifest.change_scope_unreviewed"]
        else:
            result["state"] = "reusable"
            result["compatible"] = True
            result["reasons"] = ["manifest.frozen_facts_identical"]
    except (TypeError, ValueError, OverflowError):
        result["reasons"] = ["manifest.unserializable_or_invalid"]
    return result


def _failure_types(report: Mapping[str, Any]) -> list[str]:
    from .game_run import ERROR_MARKERS, UNCLASSIFIED_ERROR_MARKERS  # noqa: PLC0415

    findings = report.get("log_findings", {})
    raw_errors = findings.get("errors", {}) if isinstance(findings, dict) else {}
    errors: set[str] = set()
    if isinstance(raw_errors, dict):
        for key, count in raw_errors.items():
            if _text(key) and type(count) is int and count >= 0:
                if count > 0:
                    errors.add(key)
            else:
                errors.add("unclassified-error")
    else:
        errors.add("unclassified-error")
    if isinstance(findings, dict) and findings.get("mod_errors"):
        # 未枚举的模组错误统一保守计次，不被时间戳/对象 ID 的变化绕过。
        errors.add("unclassified-mod-error")
    if isinstance(findings, dict) and findings.get("unclassified_errors"):
        # 资源/VFS 等尚未逐类建模的错误同样必须进入停止计数，不能由旧字段缺失绕过。
        errors.add("unclassified-error")
    if "early_stop" in report:
        # 实时守卫已看到的首错独立于最终归档；汇总损坏不能清除该停止事实。
        guard = report["early_stop"]
        kind = guard.get("kind") if isinstance(guard, dict) else None
        if isinstance(kind, str) and kind in ERROR_MARKERS:
            errors.add(kind)
        elif kind == "Mod error":
            errors.add("unclassified-mod-error")
        elif isinstance(kind, str) and kind in UNCLASSIFIED_ERROR_MARKERS:
            errors.add("unclassified-error")
        else:
            errors.add("unclassified-error")
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
        maximum_months = 120 if self.purpose in ("M4", "M4-noise", "safety") else 6
        minimum_months = 24 if self.purpose == "M4" else 0
        if (
            not all(_text(value) for value in (self.plan_id, self.scene_id, self.arm, self.purpose))
            or self.arm not in ARMS
            or self.purpose not in PURPOSES
            or type(self.max_scenes) is not int
            or not 1 <= self.max_scenes <= 2
            or type(self.max_pairs) is not int
            or not 1 <= self.max_pairs <= 3
            or type(self.pair) is not int
            or not 1 <= self.pair <= self.max_pairs
            or not _finite_number(self.max_months)
            or not minimum_months <= self.max_months <= maximum_months
            or self.max_months <= 0
            or not _finite_number(self.min_available_mib)
            or self.min_available_mib < 0
            or (self.purpose == "M4" and self.max_pairs != 3)
            or (self.purpose == "M4-noise" and self.arm not in {"control", "vanilla"})
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
            database.execute("BEGIN IMMEDIATE")
            version = database.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("实验账本 schema 版本较新，拒绝降级写入")
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
            # 附表保存新导入记录的上下文；旧 plans/runs/prior_failures 原行不重写。
            database.execute(
                "CREATE TABLE IF NOT EXISTS prior_failure_contexts "
                "(evidence TEXT PRIMARY KEY, context_json TEXT NOT NULL)"
            )
            if version < SCHEMA_VERSION:
                database.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
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
        if "months" in manifest and (
            not _finite_number(manifest["months"])
            or not 0 < manifest["months"] <= request.max_months
            or (request.purpose == "M4" and manifest["months"] < 24)
        ):
            raise ValueError("运行输入窗口超出用途预算")
        if request.purpose == "M4" and "months" not in manifest:
            raise ValueError("正式 M4 必须冻结运行窗口")
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
            arms_per_pair = 1 if request.purpose == "M4-noise" else 2
            if len(scene) + len(prior_scene) >= request.max_pairs * arms_per_pair:
                raise ValueError("已达到三组配对的运行预算（含失败）")
            self._require_not_stopped(database, manifest)
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
            if request.purpose in {"M3-A", "M3-B", "M4"} and request.arm not in {
                "control",
                "vanilla",
            }:
                self._require_control(database, request, manifest)
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

    @staticmethod
    def _require_control(
        database: sqlite3.Connection, request: RunRequest, manifest: Mapping[str, Any]
    ) -> None:
        """正式候选只能接在同配对已完成且当前原件复核合格的控制局之后。"""
        from . import experiment_evidence, game_run, m3a_screen  # noqa: PLC0415

        control_arm = "vanilla" if request.purpose == "M4" else "control"
        rows = database.execute(
            "SELECT * FROM runs WHERE plan=? AND scene=? AND pair=? AND arm=? AND status='complete'",
            (request.plan_id, request.scene_id, request.pair, control_arm),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("控制先行门禁：同配对须有唯一已完成控制臂")
        row = rows[0]
        if not _sha(row["report_sha"]):
            raise ValueError("控制先行门禁：控制报告缺少冻结指纹")
        previous = json.loads(row["manifest"])
        if any(
            previous.get(key) != manifest.get(key)
            for key in (previous.keys() | manifest.keys()) - {"sources"}
        ):
            raise ValueError("控制先行门禁：同配对冻结输入不同")
        root = Path(row["evidence"])
        path = root / "report.json"
        try:
            plain_path(path)
            if digest(path) != row["report_sha"]:
                raise ValueError("控制报告原件指纹改变")
            sources = tree_digest(root / "sources")
            logs = tree_digest(root / "logs")
            report = game_run.read_reviewed_report(path)
            game_run.require_clean_report(report)
            facts = m3a_screen.load_report(path)
            if not facts.clean:
                raise ValueError("控制原件当前门禁未通过：" + ";".join(facts.gate_reasons))
            expected = {
                "run_id": row["id"],
                "plan_id": request.plan_id,
                "scene_id": request.scene_id,
                "arm": control_arm,
                "pair": request.pair,
                "purpose": request.purpose,
                "limits": request.limits(),
                "manifest_sha256": hashlib.sha256(row["manifest"].encode("utf-8")).hexdigest(),
            }
            identity = report.get("experiment")
            if (
                not isinstance(identity, dict)
                or any(_json(identity.get(key)) != _json(value) for key, value in expected.items())
                or report.get("evidence") != row["evidence"]
            ):
                raise ValueError("控制报告实验身份与账本不同")
            declared = previous.get("sources")
            if (
                not isinstance(declared, dict)
                or not declared
                or report.get("source_hashes") != declared
            ):
                raise ValueError("控制报告源码与冻结输入不同或缺失")
            flattened = {
                f"{name}/{relative}": fingerprint
                for name, files in declared.items()
                for relative, fingerprint in files.items()
            }
            if game_run.hashes(root / "sources") != flattened:
                raise ValueError("控制源码原件集合或指纹不同")
            probes = {
                name: files
                for name, files in declared.items()
                if name != "sitai_decision_candidate"
            }
            if probes != previous.get("probe_sources"):
                raise ValueError("控制探针与冻结输入不同")
            environment = previous.get("environment")
            if not isinstance(environment, dict) or not isinstance(environment.get("game"), dict):
                raise ValueError("控制冻结环境缺失")
            versions = {
                key: value for key, value in environment["game"].items() if key != "content_sha256"
            }
            content_sha256 = environment["game"].get("content_sha256")
            game_hashes = report.get("game_hashes")
            if (
                not _sha(content_sha256)
                or not isinstance(game_hashes, dict)
                or not game_hashes
                or not all(_text(key) and _sha(value) for key, value in game_hashes.items())
                or hashlib.sha256(
                    json.dumps(game_hashes, sort_keys=True).encode("utf-8")
                ).hexdigest()
                != content_sha256
            ):
                raise ValueError("控制游戏内容指纹与冻结环境不同或缺失")
            qualification = previous.get("qualification")
            preflight = report.get("checkpoint_preflight")
            qualification_path = previous.get("qualification_report")
            if (
                not isinstance(qualification, dict)
                or not isinstance(preflight, dict)
                or _json(preflight.get("qualification")) != _json(qualification)
                or not _sha(qualification.get("report_sha256"))
                or not _text(qualification_path)
                or digest(Path(qualification_path)) != qualification["report_sha256"]
            ):
                raise ValueError("控制资格原件与冻结指纹不同或缺失")
            qualification_context = qualification.get("context")
            if not isinstance(qualification_context, dict):
                raise ValueError("控制资格冻结上下文缺失")
            if (
                report.get("loaded_save", {}).get("sha256") != previous.get("checkpoint")
                or report.get("game_version") != versions
                or report.get("language") != environment.get("language")
                or report.get("mount_allowlist") != qualification_context.get("mount_allowlist")
                or report.get("disabled_dlc") != environment.get("disabled_dlc")
                or report.get("qualification_registration_sha256")
                != previous.get("qualification_registration_sha256")
                or not _sha(previous.get("qualification_registration_sha256"))
                or _json(report.get("months")) != _json(previous.get("months"))
                or report.get("session_requested") is not True
                or report.get("logs_isolated") is not True
            ):
                raise ValueError("控制检查点、窗口或运行环境与冻结输入不同")
            context = dict(qualification_context)
            context.update(
                game_version=versions,
                source_hashes=declared,
                arm=control_arm,
                months=previous["months"],
                pair=request.pair,
            )
            reviewed = experiment_evidence.review_control(
                path,
                qualification_report=Path(qualification_path),
                checkpoint_sha256=previous["checkpoint"],
                expected_version=versions.get("caligula_branch", "").split("/")[-1],
                purpose=request.purpose,
                context=context,
            )
            if reviewed.get("allowed") is not True:
                raise ValueError(
                    "控制实际窗口/机会未通过：" + ";".join(reviewed.get("reasons", []))
                )
            if reviewed.get("report_sha256") != row["report_sha"]:
                raise ValueError("控制独立复核指纹与账本不同")
            if (
                digest(path) != row["report_sha"]
                or tree_digest(root / "sources") != sources
                or tree_digest(root / "logs") != logs
            ):
                raise ValueError("控制报告、源码或日志在复核中变化")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(f"控制先行门禁：{exc}") from exc

    @staticmethod
    def _require_not_stopped(database: sqlite3.Connection, manifest: Mapping[str, Any]) -> None:
        context = _stop_context(manifest)
        failures: dict[str, set[str]] = {}
        for row in database.execute("SELECT manifest,evidence,errors FROM runs"):
            if _same_stop_context(context, _stop_context(json.loads(row["manifest"]))):
                for error in json.loads(row["errors"]):
                    failures.setdefault(error, set()).add(row["evidence"])
        for row in database.execute(
            "SELECT p.evidence,p.report_sha,p.errors,c.context_json FROM prior_failures p "
            "LEFT JOIN prior_failure_contexts c ON p.evidence=c.evidence"
        ):
            previous = json.loads(row["context_json"]) if row["context_json"] else {}
            if not previous:
                previous = _recover_prior_failure_context(row["evidence"], row["report_sha"])
            if _same_stop_context(context, previous):
                for error in json.loads(row["errors"]):
                    # 同一原报告跨计划导入仍只是一局；也与 runs 原目录去重。
                    failures.setdefault(error, set()).add(str(Path(row["evidence"]).parent))
        if any(len(identities) >= 2 for identities in failures.values()):
            raise ValueError("同输入/环境同类引擎错误重复两次，停止派发")

    def finish(self, run_id: str, report: Mapping[str, Any], *, report_sha256: str) -> None:
        if not _sha(report_sha256):
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
                        and not findings.get("unclassified_errors")
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
            not _sha(checkpoint_sha256)
            or report.get("loaded_save", {}).get("sha256") != checkpoint_sha256
            or report.get("game_version") != game_version
            or not errors
            or digest(path) != report_sha
        ):
            raise ValueError("历史失败的检查点、版本、错误或指纹不符")
        limits = _json(request.limits())
        evidence = str(path.resolve())
        context = _stop_context(
            {
                "checkpoint": checkpoint_sha256,
                "environment": {"game": game_version, "language": report.get("language")},
                "game_hashes": report.get("game_hashes"),
                "sources": report.get("source_hashes"),
                "probe_sources": report.get("probe_sources", report.get("source_hashes")),
                "simulation": report.get("simulation"),
            }
        )
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
                "SELECT report_sha FROM prior_failures WHERE evidence=?",
                (evidence,),
            ).fetchone()
            if duplicate is not None and duplicate[0] != report_sha:
                raise ValueError("已导入的历史报告发生改变")
            existing = database.execute(
                "SELECT id FROM runs WHERE evidence=?",
                (str(path.parent.resolve()),),
            ).fetchone()
            if existing is not None:
                raise ValueError("历史运行已在账本中，拒绝重复计次")
            database.execute(
                "INSERT OR IGNORE INTO prior_failures VALUES (?,?,?,?,?)",
                (request.plan_id, request.scene_id, evidence, report_sha, _json(errors)),
            )
            database.execute(
                "INSERT OR IGNORE INTO prior_failure_contexts VALUES (?,?)",
                (evidence, _json(context)),
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
