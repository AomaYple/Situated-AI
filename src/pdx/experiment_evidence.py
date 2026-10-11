"""正式启动资格；只复核原件，不运行游戏，也不证明行为质量。

schema 1 的资格文件引用 ``checkpoint``、``run_report``、``registration``
三个 ``{path, sha256}`` 原件，以及 ``game_files``（原版相对名到同类引用）。
引用只允许报告目录内的普通文件。登记 schema 1 冻结 purpose、plan_id、
scene_id、criteria_version、language、mount_allowlist、game_hashes、
disabled_dlc、source_hashes、observation、sampling 和 declared_differences；运行报告必须
保存 registration_sha256，且 loaded_save 必须是同一输入，而不是保存输出。

observation version 为 OBSERVATION_VERSION，M3-A 包为 natural-response，
包含 observers、initiator、target；采样为 sample_count/window_days、有限非负的
max_overshoot_days 和 before_treatment=true，该声明还须由未处理源码与原日志证明。
M3-A 原会话/激活点、月份和实际进度须与归档 dedicated_server 逐 tick 原件绑定；
带引擎壁钟秒的每条正采样须由前后 tick 包围，且所有可能 tick 位于登记窗口。
跨午夜或缺少包围证据时拒绝，不能将手填 progress 当作时间真值。
M4 包为 vanilla-performance，performance 登记时期、输入日期、三份
noise_reports、正数 budgets 和 frozen_candidate 原件。现有接口不能复核
M3 行为质量出口，因此正式 M4 始终拒绝，手填质量或审查 SHA 也不能放行。

context 为现场冻结上下文；必需 plan_id、scene_id、language、mount_allowlist、disabled_dlc、game_hashes、
game_version、months、arm 和 source_hashes，其余登记字段若提供也逐字段
绑定。arm_source_hashes 冻结 control/neutrality 两臂；原件必须来自 control。
game_version 绑定原件解析的版本，months 绑定 window_days / 30。正式
默认无财政注入；未知结构、未支持观测、目录链接和读取期间变化均拒绝。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from itertools import pairwise
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from . import (
    behavior_probe,
    checkpoint_catalog,
    decision_probe,
    decisions,
    extension_probe,
    game_auto,
    game_run,
    m3a_screen,
)
from .deployment_state import plain_path
from .model import Block
from .parser import parse_text

SCHEMA = 1
OBSERVATION_VERSION = "r1-readonly-1"
FORMAL_PURPOSES = frozenset({"M3-A", "M3-B", "M4"})
VERSION_FILES = ("caligula_branch", "caligula_rev", "clausewitz_branch", "clausewitz_rev")
CONTEXT_FIELDS = (
    "plan_id",
    "scene_id",
    "criteria_version",
    "language",
    "mount_allowlist",
    "disabled_dlc",
    "game_hashes",
    "source_hashes",
    "observation",
    "declared_differences",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(ValueError):
    """稳定机器原因和中文解释随同返回。"""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _require(condition: object, reason: str, message: str) -> None:
    if not condition:
        raise EvidenceError(reason, message)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, role: str) -> Mapping[str, Any]:
    _require(isinstance(value, dict), f"{role}.shape", f"{role} 必须是对象")
    return value  # type: ignore[return-value]


def _json(raw: bytes, role: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _require(key not in result, "json.duplicate_key", "JSON 原件包含重复键")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise EvidenceError("json.nonfinite", f"JSON 原件包含非有限数值：{value}")

    return _mapping(
        json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant), role
    )


def _number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value > 0  # type: ignore[arg-type,operator]


def _nonnegative(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0  # type: ignore[arg-type,operator]


def _relative(root: Path, value: object) -> Path:
    _require(isinstance(value, str) and bool(value), "artifact.path", "原件路径缺失")
    assert isinstance(value, str)
    parts = PurePosixPath(value).parts
    _require(
        "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and not PurePosixPath(value).is_absolute()
        and not PureWindowsPath(value).drive
        and bool(parts)
        and all(part not in {"..", "."} for part in value.split("/")),
        "artifact.path",
        "原件只允许目录内的相对路径，禁止绝对路径和路径穿越",
    )
    path = root.joinpath(*parts)
    plain_path(path)
    _require(path.resolve().is_relative_to(root.resolve()), "artifact.path", "原件逃出证据目录")
    return path


def _identity(path: Path) -> tuple[int, ...]:
    plain_path(path)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode), "artifact.not_file", "原件必须是普通文件")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class _Snapshot:
    """每个原件在解析前后和整个判定结束时重读；包括目录成员集合。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[Path, tuple[tuple[int, ...], str]] = {}
        self.trees: dict[Path, tuple[str, ...]] = {}
        self.absent: set[Path] = set()

    def read(self, path: Path) -> bytes:
        before = _identity(path)
        raw = path.read_bytes()
        _require(before == _identity(path), "artifact.changed", "原件在读取期间变化")
        entry = before, _hash(raw)
        _require(
            path not in self.files or self.files[path] == entry,
            "artifact.changed",
            "同一原件在复核期间变化",
        )
        self.files[path] = entry
        return raw

    def digest(self, path: Path) -> str:
        before = _identity(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(before == _identity(path), "artifact.changed", "原件在散列期间变化")
        entry = before, digest
        _require(
            path not in self.files or self.files[path] == entry,
            "artifact.changed",
            "原件在复核期间变化",
        )
        self.files[path] = entry
        return digest

    def reference(self, ref: object, role: str, *, load: bool = True) -> tuple[Path, bytes]:
        ref = _mapping(ref, role)
        _require(set(ref) == {"path", "sha256"}, f"{role}.shape", "原件引用字段不完整或未知")
        path = _relative(self.root, ref["path"])
        raw = self.read(path) if load else b""
        actual = _hash(raw) if load else self.digest(path)
        _require(
            isinstance(ref["sha256"], str)
            and _SHA256.fullmatch(ref["sha256"])
            and actual == ref["sha256"],
            f"{role}.hash",
            f"{role} 原件指纹不匹配",
        )
        return path, raw

    def tree(self, root: Path) -> dict[str, str]:
        plain_path(root)
        _require(root.is_dir(), "artifact.directory_missing", "原件目录缺失")
        entries: dict[str, str] = {}
        names: list[str] = []
        for path in sorted(root.rglob("*")):
            plain_path(path)
            name = path.relative_to(root).as_posix()
            names.append(name)
            if path.is_file():
                entries[name] = self.digest(path)
            else:
                _require(path.is_dir(), "artifact.not_file", "证据树包含特殊文件")
        _require(
            root not in self.trees or self.trees[root] == tuple(names),
            "artifact.changed",
            "证据目录成员在复核期间变化",
        )
        self.trees[root] = tuple(names)
        return entries

    def missing(self, path: Path) -> None:
        plain_path(path)
        _require(not path.exists(), "artifact.expected_absent", "纯原版来源不得包含源码目录")
        self.absent.add(path)

    def verify(self) -> None:
        for path in self.absent:
            plain_path(path)
            _require(not path.exists(), "artifact.changed", "缺席的来源目录在复核期间出现")
        for root, names in self.trees.items():
            plain_path(root)
            members = sorted(root.rglob("*"))
            for path in members:
                plain_path(path)
            current = tuple(path.relative_to(root).as_posix() for path in members)
            _require(current == names, "artifact.changed", "证据目录成员在复核期间变化")
        for path, (identity, digest) in list(self.files.items()):
            _require(
                _identity(path) == identity and self.digest(path) == digest,
                "artifact.changed",
                "原件在复核期间变化",
            )


def _review(snapshot: _Snapshot, path: Path, raw: bytes) -> dict[str, Any]:
    report = _json(raw, "run_report")
    logs = snapshot.tree(path.parent / "logs")
    _require(
        any(name.startswith("error") and name.endswith(".log") for name in logs)
        and any(name.startswith("debug") and name.endswith(".log") for name in logs),
        "run_report.logs_missing",
        "必须保留原始 error 与 debug 日志，空日志也须归档",
    )
    _require(logs == report.get("log_hashes"), "run_report.logs_hash", "原始日志集合或指纹不同")
    for field in (
        "game_version",
        "source_hashes",
        "deployed_hashes",
        "log_findings",
        "loaded_save",
    ):
        _mapping(report.get(field), f"run_report.{field}")
    _mapping(report["loaded_save"].get("header"), "run_report.loaded_save.header")
    _require(
        report.get("ok") is True
        and report.get("cleanup_errors") == []
        and not report.get("failure"),
        "run_report.not_clean",
        "原报告失败或缺少清理证据",
    )
    source_root = path.parent / "sources"
    actual_sources = snapshot.tree(source_root)
    declared: dict[str, str] = {}
    for name, files in report["source_hashes"].items():
        _relative(source_root, name)
        for relative, digest in _mapping(files, "run_report.sources").items():
            _relative(source_root / name, relative)
            declared[f"{name}/{relative}"] = digest
    _require(actual_sources == declared, "run_report.source_hash", "实际源码集合或指纹不同")
    reviewed = game_run.read_reviewed_report(path)
    game_run.require_clean_report(reviewed)
    facts = m3a_screen.load_report(path)
    _require(
        facts.clean,
        "run_report.current_gate",
        "当前源码、挂载或错误门禁未通过：" + ";".join(facts.gate_reasons),
    )
    snapshot.verify()
    return reviewed


def _generated_hashes(files: Mapping[str, str]) -> dict[str, str]:
    return {name: _hash(text.encode("utf-8")) for name, text in files.items()}


def _sources(
    observation: Mapping[str, Any],
    purpose: str,
    play_types: tuple[str, ...],
    auxiliary: Mapping[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    tags = observation.get("observers")
    _require(
        isinstance(tags, list)
        and len(tags) == 2
        and all(isinstance(tag, str) and re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
        and tags[0] != tags[1],
        "observation.observers",
        "须声明两个不同的规范观察国",
    )
    assert isinstance(tags, list)
    tags = tuple(tags)
    _require(
        observation.get("version") == OBSERVATION_VERSION,
        "observation.version",
        "观察器版本不受支持或已过期",
    )
    if purpose == "M4":
        _require(
            observation.get("package") == "vanilla-performance",
            "observation.package",
            "M4 须使用声明的原版性能观测包",
        )
        return {
            "zz_sitai_fiscal_observer": _generated_hashes(
                decision_probe.build_observer(
                    tags=tags, policy_state=False, native_fiscal_inputs=True
                )
            )
        }
    _require(
        observation.get("package") == "natural-response",
        "observation.package",
        "正式响应资格只支持自然对象的只读观测包",
    )
    initiator, target = observation.get("initiator"), observation.get("target")
    _require(
        all(isinstance(tag, str) and re.fullmatch(r"[A-Z]{3}", tag) for tag in (initiator, target))
        and len({*tags, initiator, target}) == 4,
        "observation.participants",
        "指定响应发起、目标与两观察国必须不同",
    )
    assert isinstance(initiator, str)
    assert isinstance(target, str)
    extensions = replace(decisions.load_extensions(), market_enabled=False, reform_enabled=False)
    policy = replace(decisions.load(), neutrality=0, aggression=0)
    return {
        "sitai_decision_candidate": _generated_hashes(
            decisions.build(policy, extensions=extensions)
        ),
        "zz_probe_decision_lifecycle": _generated_hashes(
            decision_probe.build_observer(lifecycle=True, tags=tags)
        ),
        "zz_probe_decision_opportunity": _generated_hashes(
            behavior_probe.build(
                initiator=initiator, target=target, tags=tags, natural=True, play_types=play_types
            )
        ),
        **(auxiliary or {}),
    }


def _auxiliary(
    snapshot: _Snapshot, files: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    """额外包只能由冻结原版原件和已支持生成器产生。"""
    result: dict[str, dict[str, str]] = {}
    for key in ("extra_fiscal", "reform", "localization_baseline"):
        _require(
            key not in observation or type(observation[key]) is bool,
            "observation.package",
            "额外观测包须显式声明布尔配置",
        )
    if observation.get("extra_fiscal"):
        result["zz_sitai_fiscal_observer"] = _generated_hashes(
            decision_probe.build_observer(tags=tuple(observation["observers"]))
        )
    if observation.get("reform"):
        laws: set[str] = set()
        strategies: set[str] = set()
        for name, ref in files.items():
            if not (
                name.startswith(("common/laws/", "common/ai_strategies/")) and name.endswith(".txt")
            ):
                continue
            _path, raw = snapshot.reference(ref, "game_file")
            tree = parse_text(raw.decode("utf-8-sig"))
            _require(not tree.errors, "game_file.parse", "原版法律或政治策略无法解析")
            if name.startswith("common/laws/"):
                laws.update(key for key in tree.top_keys if key.startswith("law_"))
            else:
                for assignment in tree.root.assignments():
                    if isinstance(assignment.value, Block):
                        kind = assignment.value.first("type")
                        if kind is not None and str(kind.value) == "political":
                            _require(
                                assignment.key not in strategies,
                                "game_file.duplicate_key",
                                "原版政治策略键重复，不能冻结歧义输入",
                            )
                            strategies.add(assignment.key)
        _require(
            bool(laws) and bool(strategies),
            "game_file.reform_missing",
            "政治观察包缺少实际原版法律或政治策略原件",
        )
        result["zz_sitai_reform_observer"] = _generated_hashes(
            extension_probe.build(laws, strategies=sorted(strategies))
        )
    if observation.get("localization_baseline"):
        localization = {
            name: ref for name, ref in files.items() if name.startswith("localization/")
        }
        _require(
            bool(localization), "game_file.localization_missing", "中文诊断包缺少原版本地化原件"
        )
        roots: set[Path] = set()
        for name, ref in localization.items():
            path, _raw = snapshot.reference(ref, "game_file", load=False)
            root = path
            for _part in PurePosixPath(name).parts:
                root = root.parent
            _require(
                path == root / name, "game_file.localization_layout", "本地化原件须保持原版相对布局"
            )
            roots.add(root)
        _require(len(roots) == 1, "game_file.localization_layout", "本地化原件必须来自同一冻结镜像")
        root = roots.pop()
        expected = {
            name.removeprefix("localization/"): ref["sha256"] for name, ref in localization.items()
        }
        _require(
            snapshot.tree(root / "localization") == expected,
            "game_file.localization_files",
            "本地化镜像存在未登记原件或指纹不同",
        )
        result["zz_sitai_vanilla_localization_baseline"] = _generated_hashes(
            decision_probe.build_localization_baseline(root)
        )
        snapshot.verify()
    return result


def _game(
    snapshot: _Snapshot, files: object, expected_version: str
) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    originals = _mapping(files, "game_files")
    hashes: dict[str, str] = {}
    versions: dict[str, str] = {}
    play_types: set[str] = set()
    for name, ref in originals.items():
        _relative(snapshot.root, name)
        needs_text = name in {key + ".txt" for key in VERSION_FILES} or name.startswith(
            "common/diplomatic_plays/"
        )
        path, raw = snapshot.reference(ref, "game_file", load=needs_text)
        hashes[name] = snapshot.files[path][1]
        if name in {key + ".txt" for key in VERSION_FILES}:
            versions[name.removesuffix(".txt")] = raw.decode("utf-8-sig").strip()
        elif name.startswith("common/diplomatic_plays/") and name.endswith(".txt"):
            tree = parse_text(raw.decode("utf-8-sig"))
            _require(not tree.errors, "game_file.parse", "原版博弈类型无法解析")
            keys = [key for key in tree.top_keys if key.startswith("dp_")]
            _require(
                len(keys) == len(set(keys)) and not play_types.intersection(keys),
                "game_file.duplicate_key",
                "原版博弈类型键重复，不能冻结歧义输入",
            )
            play_types.update(keys)
    _require(
        set(versions) == set(VERSION_FILES)
        and all(versions.values())
        and versions["caligula_branch"].split("/")[-1] == expected_version,
        "game.version",
        "实际游戏版本/修订原件缺失或版本不同",
    )
    return hashes, versions, tuple(sorted(play_types))


def _context(
    registration: Mapping[str, Any], versions: Mapping[str, str], context: Mapping[str, Any] | None
) -> None:
    _require(
        isinstance(context, Mapping),
        "context.missing",
        "缺少现场冻结上下文，不能验证游戏内容与登记是否仍适用",
    )
    assert context is not None
    required = {"plan_id", "scene_id", "language", "game_hashes", "mount_allowlist", "disabled_dlc"}
    for field in CONTEXT_FIELDS:
        if field == "source_hashes":
            continue
        if field in required or field in context:
            _require(
                field in context and context[field] == registration.get(field),
                f"context.{field}",
                f"现场 {field} 与冻结登记不同或缺失",
            )
    disabled_dlc = registration.get("disabled_dlc")
    _require(
        isinstance(disabled_dlc, list)
        and all(
            isinstance(value, str)
            and bool(value)
            and value == value.strip()
            and value.isprintable()
            for value in disabled_dlc
        )
        and len(disabled_dlc) == len(set(disabled_dlc)),
        "registration.disabled_dlc",
        "disabled_dlc 须为规范且不重复的字符串列表，空列表合法",
    )
    mounts = registration.get("mount_allowlist")
    _require(
        isinstance(mounts, list)
        and bool(mounts)
        and all(
            isinstance(value, str)
            and bool(value)
            and value == value.strip()
            and value.isprintable()
            for value in mounts
        )
        and len(mounts) == len(set(mounts)),
        "registration.mount_allowlist",
        "挂载允许清单须为完整且不重复的规范字符串列表",
    )
    arms = _mapping(registration.get("arm_source_hashes"), "registration.arm_source_hashes")
    arm = context.get("arm")
    _require(
        isinstance(arm, str) and arm in arms and context.get("source_hashes") == arms[arm],
        "context.source_hashes",
        "现场实验臂源码与登记不同或缺失",
    )
    observation = _mapping(registration.get("observation"), "observation")
    for field in ("observers", "initiator", "target"):
        if field in context:
            value = context[field]
            if field == "observers" and isinstance(value, tuple):
                value = list(value)
            _require(value == observation.get(field), f"context.{field}", "现场对象与登记不同")
    _require(
        context.get("game_version") == versions,
        "context.game_version",
        "现场游戏版本/修订与原件不同",
    )
    sampling = _mapping(registration.get("sampling"), "sampling")
    _require(
        _number(context.get("months")) and context["months"] * 30 == sampling.get("window_days"),
        "context.months",
        "现场运行窗口与事前登记不同",
    )


_WALL_TIME = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]")


def _wall_time(line: str) -> int:
    match = _WALL_TIME.match(line)
    _require(match is not None, "sampling.timestamp_missing", "采样与逐 tick 原日志须有引擎时间戳")
    assert match is not None
    hour, minute, second = map(int, match.groups())
    _require(hour < 24 and minute < 60 and second < 60, "sampling.timestamp", "引擎时间戳无效")
    return hour * 3600 + minute * 60 + second


def _tick(value: object) -> tuple[int, ...]:
    _require(isinstance(value, str), "run_report.tick", "运行窗口缺少真实 tick")
    assert isinstance(value, str)
    parts = game_auto.parse_tick_date(value)
    _require(len(parts) in {3, 4}, "run_report.tick", "运行窗口 tick 结构无效")
    date(*parts[:3])
    _require(len(parts) == 3 or parts[3] < 24, "run_report.tick", "运行窗口 tick 小时无效")
    return (*parts[:3], parts[3] if len(parts) == 4 else 0)


def _window(
    snapshot: _Snapshot, path: Path, registration: Mapping[str, Any], run: Mapping[str, Any]
) -> dict[str, Any]:
    """运行报告的数值声明须与逐 tick 原件一致，秒精度歧义采用包围区间。"""
    months = run.get("months")
    _require(_number(months), "run_report.months", "原始运行月份须为有限正数，布尔无效")
    assert isinstance(months, int | float)
    _require(
        months * 30 == registration["sampling"]["window_days"],
        "run_report.months",
        "原始运行月份缺失或与事前采样窗口不同",
    )
    progress = _mapping(run.get("progress"), "run_report.progress")
    session = _mapping(run.get("session"), "run_report.session")
    start, end = _tick(progress.get("start")), _tick(progress.get("end"))
    activation = progress.get("activation_tick")
    running = session.get("running")
    advance = re.fullmatch(
        r"\[[^\]\r\n]+\] (\d+(?:\.\d+){2,3}) -> (\d+(?:\.\d+){2,3}) "
        r"\(\d+(?:\.\d+)?s\) 推进",
        running if isinstance(running, str) else "",
    )
    _require(
        run.get("session_requested") is True
        and run.get("logs_isolated") is True
        and session.get("speed_ok") is True
        and advance is not None
        and _tick(advance[1]) < start
        and advance[2] == activation == progress.get("start")
        and progress.get("activation_source") == "session.advance.after"
        and progress.get("reached") is True
        and start < end,
        "run_report.activation",
        "窗口起点须绑定真实会话推进与激活点，不能由手填进度解锁",
    )
    start_day = game_auto.tick_day(str(progress["start"]))
    end_day = game_auto.tick_day(str(progress["end"]))
    assert start_day is not None
    assert end_day is not None
    actual_days = end_day - start_day
    target_days = months * 365.25 / 12
    overshoot = registration["sampling"].get("max_overshoot_days")
    _require(
        _nonnegative(overshoot),
        "sampling.max_overshoot_days",
        "必须事前登记有限非负越窗预算，布尔无效",
    )
    allowed_days = math.ceil(target_days) + overshoot
    _require(
        _number(progress.get("days"))
        and math.isclose(progress["days"], actual_days, rel_tol=0, abs_tol=1e-9)
        and target_days <= actual_days <= allowed_days,
        "run_report.progress",
        "原报告进度须从原件起止 tick 重算，并实际达到请求窗口",
    )
    # 同一壁钟秒可包含多个 tick；不假装能确定该秒内日志的跨文件顺序。
    clock: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    seen: set[tuple[int, ...]] = set()
    required_ticks = {start, end, _tick(advance[1]) if advance is not None else ()}
    previous_time = -1
    previous_tick: tuple[int, ...] = ()
    tick_logs = game_auto.rotated_logs(path.parent / "logs", "dedicated_server")
    _require(bool(tick_logs), "sampling.tick_log_missing", "缺少引擎逐 tick 原日志")
    for log in tick_logs:
        snapshot.digest(log)
        with log.open(encoding="utf-8-sig", errors="strict") as stream:
            for line in stream:
                match = game_auto.TICK_RE.search(line)
                if match is None:
                    continue
                stamp, tick = _wall_time(line), _tick(match[1])
                _require(
                    stamp >= previous_time and tick >= previous_tick,
                    "sampling.time_ambiguous",
                    "逐 tick 原日志倒退或跨午夜；当前秒精度关联不能审计该窗口",
                )
                lower, upper = clock.get(stamp, (tick, tick))
                clock[stamp] = min(lower, tick), max(upper, tick)
                if tick in required_ticks:
                    seen.add(tick)
                previous_time, previous_tick = stamp, tick
    _require(
        start in seen and end in seen and advance is not None and _tick(advance[1]) in seen,
        "sampling.tick_unverified",
        "会话激活与窗口起止 tick 未在实际引擎日志出现",
    )
    times = sorted(clock)
    temporal_samples: dict[str, dict[str, Any]] = {}
    for log in game_auto.rotated_logs(path.parent / "logs", "debug"):
        with log.open(encoding="utf-8-sig", errors="strict") as stream:
            for line in stream:
                match = behavior_probe.ROW.search(line.rstrip()) or decision_probe.ROW.search(
                    line.rstrip()
                )
                if match is None or match["date"] == "sample-0":
                    continue
                stamp = _wall_time(line)
                before, after = bisect_left(times, stamp) - 1, bisect_right(times, stamp)
                _require(
                    before >= 0 and after < len(times),
                    "sampling.time_unbounded",
                    "采样没有前后引擎 tick 包围，无法判定是否在登记窗口内",
                )
                lower, upper = clock[times[before]][0], clock[times[after]][1]
                upper_day = game_auto.tick_day(".".join(map(str, upper)))
                _require(
                    start <= lower <= upper <= end
                    and upper_day is not None
                    and upper_day - start_day <= allowed_days,
                    "sampling.outside_window",
                    "采样的全部可能 tick 须位于登记窗口，窗外记录不能提供资格",
                )
                if "SITAI OPPORTUNITY;" in line:
                    key = match["date"]
                    entry = temporal_samples.setdefault(
                        key, {"wall_seconds": [], "tick_bounds": []}
                    )
                    if stamp not in entry["wall_seconds"]:
                        entry["wall_seconds"].append(stamp)
                    bounds = [list(lower), list(upper)]
                    if bounds not in entry["tick_bounds"]:
                        entry["tick_bounds"].append(bounds)
    snapshot.verify()
    for sample, entry in temporal_samples.items():
        bounds = entry["tick_bounds"]
        _require(
            max(tuple(bound[0]) for bound in bounds) <= min(tuple(bound[1]) for bound in bounds),
            "sampling.shared_time_inconsistent",
            f"共享机会采样 {sample} 的观察行不在同一可证明时间区间",
        )
    ordered = sorted(temporal_samples, key=lambda sample: int(sample.removeprefix("sample-")))
    for left, right in pairwise(ordered):
        _require(
            max(temporal_samples[left]["wall_seconds"])
            <= min(temporal_samples[right]["wall_seconds"]),
            "sampling.order",
            "每日共享采样序号与实际日志时间顺序不一致",
        )
    return {
        "start_tick": progress["start"],
        "end_tick": progress["end"],
        "requested_days": target_days,
        "max_overshoot_days": overshoot,
        "allowed_days": allowed_days,
        "actual_days": actual_days,
        "samples": temporal_samples,
        "time_basis": "引擎壁钟秒的前后逐 tick 包围；秒内跨日志顺序保持不确定",
    }


def _behavior(
    snapshot: _Snapshot, path: Path, registration: Mapping[str, Any], run: Mapping[str, Any]
) -> dict[str, Any]:
    observation = registration["observation"]
    tags = tuple(observation["observers"])
    logs = path.parent / "logs"
    opportunity = behavior_probe.analyze(
        logs, tags=tags, natural_pair=(observation["initiator"], observation["target"])
    )
    fiscal = decision_probe.analyze(logs, strict=True, tags=tags)
    common = opportunity["common_eligible_active_dates"]
    _require(
        bool(common),
        "opportunity.no_common_active_undecided",
        "两国须在同一指定响应采样中 ACTIVE 且未决并可支持",
    )
    fiscal_states: dict[tuple[str, str], dict[str, str]] = {}
    for row in fiscal["rows"]:
        if row["kind"] in {"RISK", "ACTIVE"}:
            fiscal_states.setdefault((row["tag"], row["date"]), {})[row["kind"]] = row["value"]
    _require(
        not any(
            state.get("ACTIVE") == "yes" and state.get("RISK") != "yes"
            for state in fiscal_states.values()
        ),
        "opportunity.risk_contradiction",
        "同一财政观察中的 ACTIVE=yes 与 RISK 缺失或否定矛盾",
    )
    window = _window(snapshot, path, registration, run)
    actual_count = opportunity["natural_capture"]["samples"]
    _require(
        type(actual_count) is int and actual_count == registration["sampling"]["sample_count"],
        "sampling.count",
        "登记样本数量与原日志重新计算不同",
    )
    snapshot.verify()
    return {
        "opportunity_count": 1,
        "common_eligible_active_samples": common,
        "sample_count": actual_count,
        "sampling_window": window,
        "common_risk_basis": "精确复核的生产 ACTIVE 触发器包含 has_variable=sitai_fiscal_risk；月度序号不与每日序号连接",
        "quality_improvement_proven": False,
    }


def _performance(
    snapshot: _Snapshot,
    registration: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    performance = _mapping(registration.get("performance"), "performance")
    _require(
        performance.get("period") in {"early", "late", "stress"}
        and performance.get("input_date") == checkpoint["header"].get("game_date"),
        "performance.period",
        "性能时期和输入日期须绑定实际检查点",
    )
    _require(
        registration["sampling"]["window_days"] >= 24 * 30,
        "performance.window",
        "正式长期窗口至少 24 游戏月",
    )
    budgets = _mapping(performance.get("budgets"), "performance.budgets")
    _require(
        set(budgets) == {"seconds_per_day", "rss_peak", "cpu_seconds", "noise_fraction"}
        and all(_number(value) for value in budgets.values()),
        "performance.budgets",
        "资源与噪声预算须完整且为有限正数",
    )
    noise = performance.get("noise_reports")
    _require(
        isinstance(noise, list) and len(noise) == 3,
        "performance.noise",
        "须冻结三次独立原版噪声测量原件",
    )
    assert isinstance(noise, list)
    seen: set[str] = set()
    for ref in noise:
        path, raw = snapshot.reference(ref, "noise_report")
        _require(_hash(raw) not in seen, "performance.noise_duplicate", "重复原件不能增加样本数")
        seen.add(_hash(raw))
        report = _review(snapshot, path, raw)
        _require(
            report.get("loaded_save", {}).get("sha256") == checkpoint["sha256"]
            and report.get("source_hashes") == registration["source_hashes"]
            and report.get("language") == registration["language"]
            and report.get("mount_allowlist") == registration["mount_allowlist"]
            and report.get("disabled_dlc") == registration["disabled_dlc"]
            and report.get("game_hashes") == registration["game_hashes"]
            and _number(report.get("months"))
            and report["months"] * 30 == registration["sampling"]["window_days"],
            "performance.noise_context",
            "噪声测量的输入、观测、环境或窗口不同",
        )
    snapshot.reference(performance.get("frozen_candidate"), "frozen_candidate")
    raise EvidenceError(
        "frozen_candidate.quality_unsupported",
        "现有分析器不能复核 M3 行为质量出口；仪器、手填质量或审查 SHA 不能升格为正式 M4",
    )


def _arms(
    registration: Mapping[str, Any], baseline: dict[str, dict[str, str]], purpose: str
) -> None:
    arms = _mapping(registration.get("arm_source_hashes"), "registration.arm_source_hashes")
    if purpose == "M4":
        _require(
            set(arms) == {"vanilla", "fiscal"} and arms["vanilla"] == baseline,
            "registration.arms",
            "M4 须登记原版/冻结候选独立实验臂",
        )
        return
    _require(
        set(arms) == {"control", "neutrality"} and arms["control"] == baseline,
        "registration.arms",
        "M3-A 须登记未处理 control 和 neutrality 单字段实验臂",
    )
    policy = replace(decisions.load(), aggression=0)
    extensions = replace(decisions.load_extensions(), market_enabled=False, reform_enabled=False)
    candidate = dict(baseline)
    candidate["sitai_decision_candidate"] = _generated_hashes(
        decisions.build(policy, extensions=extensions)
    )
    _require(
        arms["neutrality"] == candidate,
        "registration.undeclared_difference",
        "处理臂须由当前冻结政策生成且仅改变 neutrality",
    )


def validate_preparation(
    raw: bytes,
    *,
    game_files: Mapping[str, Path],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """只许可受支持的未处理准备观察；重新核验当前游戏原件，不提供正式资格。"""
    result: dict[str, Any] = {
        "allowed": False,
        "state": "rejected",
        "reasons": [],
        "messages": [],
        "preparation_only": True,
        "quality_improvement_proven": False,
        "registration_sha256": _hash(raw),
    }
    try:
        registration = _json(raw, "registration")
        purpose = registration.get("purpose")
        _require(
            purpose != "M3-B", "opportunity.denominator_unsupported", "准备包不支持完整发起分母"
        )
        _require(
            purpose != "M4", "frozen_candidate.quality_unsupported", "准备包不能复核冻结候选质量"
        )
        _require(
            type(registration.get("schema")) is int
            and registration["schema"] == SCHEMA
            and purpose == "M3-A",
            "registration.schema_or_purpose",
            "准备登记仅支持当前 M3-A 未处理自然响应版本",
        )
        _require(
            set(registration)
            == {
                "schema",
                "purpose",
                "plan_id",
                "scene_id",
                "criteria_version",
                "checkpoint_sha256",
                "language",
                "mount_allowlist",
                "disabled_dlc",
                "game_hashes",
                "source_hashes",
                "arm_source_hashes",
                "observation",
                "sampling",
                "declared_differences",
            },
            "registration.shape",
            "准备登记字段缺失或包含未知声明",
        )
        for field in ("plan_id", "scene_id", "criteria_version"):
            _require(
                isinstance(registration.get(field), str)
                and bool(registration[field])
                and registration[field] == registration[field].strip()
                and registration[field].isprintable(),
                f"registration.{field}",
                "准备登记身份和判据须为完整规范字符串",
            )
        checkpoint_sha = registration.get("checkpoint_sha256")
        _require(
            isinstance(checkpoint_sha, str)
            and bool(_SHA256.fullmatch(checkpoint_sha))
            and context.get("checkpoint_sha256") == checkpoint_sha,
            "registration.checkpoint",
            "准备登记必须绑定当前已复核检查点 SHA",
        )
        _require(
            registration.get("language") in {"l_english", "l_simp_chinese"},
            "registration.language",
            "准备观察仅支持当前已验证的英文或简体中文运行语言",
        )
        sampling = _mapping(registration.get("sampling"), "sampling")
        _require(
            set(sampling)
            == {"sample_count", "window_days", "max_overshoot_days", "before_treatment"}
            and type(sampling.get("sample_count")) is int
            and sampling["sample_count"] > 0
            and _number(sampling.get("window_days"))
            and sampling.get("before_treatment") is True,
            "sampling.invalid",
            "准备采样须事前登记正整数样本数量、有限正窗口和未处理状态",
        )
        _require(
            _nonnegative(sampling.get("max_overshoot_days")),
            "sampling.max_overshoot_days",
            "准备运行须事前登记有限非负越窗预算，布尔无效",
        )
        observation = _mapping(registration.get("observation"), "observation")
        _require(
            set(observation)
            <= {
                "version",
                "package",
                "observers",
                "initiator",
                "target",
                "extra_fiscal",
                "reform",
                "localization_baseline",
            },
            "observation.package",
            "准备观察包包含未知配置",
        )
        differences = _mapping(registration.get("declared_differences"), "declared_differences")
        _require(
            differences == {"fiscal_injection": "none", "treatment": "neutrality"},
            "differences.unsupported",
            "准备运行禁止财政注入和未知处理差异",
        )
        _require(context.get("arm") == "control", "preparation.arm", "准备观察仅支持未处理 control")
        versions_context = _mapping(context.get("game_version"), "context.game_version")
        branch = versions_context.get("caligula_branch")
        _require(isinstance(branch, str) and bool(branch), "context.game_version", "现场版本缺失")
        assert isinstance(branch, str)
        _require(bool(game_files), "game_files.shape", "准备运行缺少当前游戏原件")
        for path in game_files.values():
            _require(isinstance(path, Path), "game_files.shape", "当前游戏原件须为普通文件路径")
            plain_path(path)
        # 当前安装的版本文件可位于 ROOT、其余原件位于 GAME；共同祖先只用于相对引用。
        root = Path(
            os.path.commonpath([str(path.absolute().parent) for path in game_files.values()])
        )
        snapshot = _Snapshot(root)
        refs = {
            name: {
                "path": path.absolute().relative_to(root).as_posix(),
                "sha256": snapshot.digest(path),
            }
            for name, path in game_files.items()
        }
        hashes, versions, play_types = _game(snapshot, refs, branch.split("/")[-1])
        _require(
            registration["game_hashes"] == hashes,
            "game.content",
            "准备登记的游戏内容与重新散列的当前原件不同",
        )
        _context(registration, versions, context)
        _require(bool(play_types), "game.play_types", "自然响应准备须保留实际原版博弈类型")
        expected_sources = _sources(
            observation, "M3-A", play_types, _auxiliary(snapshot, refs, observation)
        )
        _require(
            registration["source_hashes"] == expected_sources,
            "sampling.treated_source",
            "实际源码不是当前原件生成的未处理只读包，无注入声明不能替代源码复核",
        )
        _arms(registration, expected_sources, "M3-A")
        snapshot.verify()
        result.update(
            allowed=True,
            state="preparation-suitable",
            messages=["准备登记与当前原件已复核；仅允许未处理观察，正式资格仍须重新核验运行原件。"],
            game_hashes=hashes,
            source_hashes=expected_sources,
        )
    except EvidenceError as exc:
        result["reasons"].append(exc.reason)
        result["messages"].append(str(exc))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as exc:
        result["reasons"].append("preparation.invalid")
        result["messages"].append(f"准备原件结构或读取失败：{type(exc).__name__}: {exc}")
    return result


def review_control(
    report_path: Path,
    *,
    qualification_report: Path,
    checkpoint_sha256: str,
    expected_version: str,
    purpose: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """原资格仍有效且当前控制再次通过真实观察后，才许可派出处理臂。"""
    result: dict[str, Any] = {
        "allowed": False,
        "state": "rejected",
        "reasons": [],
        "messages": [],
        "control_only": True,
        "quality_improvement_proven": False,
    }
    try:
        _require(
            context.get("arm") == "control", "control.arm", "控制后审查须使用 control 现场上下文"
        )
        qualification = validate(
            qualification_report,
            checkpoint_sha256=checkpoint_sha256,
            expected_version=expected_version,
            purpose=purpose,
            context=context,
        )
        _require(
            qualification["allowed"],
            "control.qualification_rejected",
            "原资格当前复核失败：" + ";".join(qualification["reasons"]),
        )
        snapshot = _Snapshot(qualification_report.parent)
        qualification_raw = snapshot.read(qualification_report)
        _require(
            _hash(qualification_raw) == qualification["report_sha256"],
            "artifact.changed",
            "原资格在控制后审查期间变化",
        )
        # 初次资格判定和控制后判定之间所有间接原件仍须保持同一内容。
        for name, digest in qualification["verified_origins"].items():
            path = _relative(snapshot.root, name)
            _require(
                snapshot.digest(path) == digest, "artifact.changed", "资格原件在控制后审查期间变化"
            )
        for name, members in qualification["verified_trees"].items():
            path = _relative(snapshot.root, name)
            snapshot.tree(path)
            _require(
                snapshot.trees[path] == tuple(members),
                "artifact.changed",
                "资格目录成员在控制后审查期间变化",
            )
        for name in qualification["verified_absent"]:
            snapshot.missing(_relative(snapshot.root, name))
        original = _json(qualification_raw, "qualification")
        _registration_path, registration_raw = snapshot.reference(
            original["registration"], "registration"
        )
        registration = _json(registration_raw, "registration")
        _origin_run_path, origin_run_raw = snapshot.reference(original["run_report"], "run_report")
        origin_run = _json(origin_run_raw, "run_report")
        raw = snapshot.read(report_path)
        run = _review(snapshot, report_path, raw)
        experiment = _mapping(run.get("experiment"), "control.experiment")
        _require(
            experiment.get("plan_id") == registration["plan_id"]
            and experiment.get("scene_id") == registration["scene_id"]
            and experiment.get("purpose") == purpose
            and experiment.get("arm") == "control"
            and ("pair" not in context or experiment.get("pair") == context["pair"]),
            "control.identity",
            "控制报告的实验身份与冻结登记不同",
        )
        pointer = run.get("qualification_report")
        _require(
            isinstance(pointer, str) and bool(pointer),
            "control.qualification_missing",
            "控制报告缺少原资格路径",
        )
        assert isinstance(pointer, str)
        plain_path(Path(pointer))
        _require(
            Path(pointer).resolve() == qualification_report.resolve(),
            "control.qualification_pointer",
            "控制报告指向另一原资格，不能跨来源复用",
        )
        preflight = _mapping(run.get("checkpoint_preflight"), "control.checkpoint_preflight")
        prior = _mapping(preflight.get("qualification"), "control.qualification")
        _require(
            preflight.get("sha256") == checkpoint_sha256
            and prior.get("allowed") is True
            and prior.get("report_sha256") == qualification["report_sha256"]
            and run.get("qualification_registration_sha256") == _hash(registration_raw),
            "control.qualification_binding",
            "控制报告未绑定同一载入输入、原资格指纹与事前登记指纹",
        )
        _require(
            run["loaded_save"].get("sha256") == checkpoint_sha256
            and run["loaded_save"].get("header") == origin_run["loaded_save"]["header"],
            "run_report.loaded_input",
            "控制报告的真实载入输入与原资格不同",
        )
        for field in (
            "language",
            "mount_allowlist",
            "disabled_dlc",
            "game_hashes",
            "source_hashes",
        ):
            _require(
                run.get(field) == registration[field] == context.get(field),
                f"run_report.{field}",
                "控制局实际上下文与冻结登记或现场不同",
            )
        _require(
            run.get("game_version") == context.get("game_version"),
            "run_report.game_version",
            "控制局版本不同",
        )
        _require(
            run.get("months") == context.get("months"), "run_report.months", "控制局窗口与现场不同"
        )
        verified = _behavior(snapshot, report_path, registration, run)
        snapshot.verify()
        result.update(verified)
        result.update(
            allowed=True,
            state="control-reviewed",
            report_sha256=_hash(raw),
            qualification_sha256=qualification["report_sha256"],
            registration_sha256=_hash(registration_raw),
            messages=[
                "当前控制的原资格、输入和观察原件重新通过；只允许进入已登记处理臂，尚未证明质量提升。"
            ],
        )
    except EvidenceError as exc:
        result["reasons"].append(exc.reason)
        result["messages"].append(str(exc))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as exc:
        result["reasons"].append("control.invalid")
        result["messages"].append(f"控制原件结构或读取失败：{type(exc).__name__}: {exc}")
    return result


def validate(
    report_path: Path,
    *,
    checkpoint_sha256: str,
    expected_version: str,
    purpose: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """返回序列化启动许可；任何缺证/变化均拒绝，原件不会被修改。"""
    result: dict[str, Any] = {
        "allowed": False,
        "state": "rejected",
        "schema": None,
        "purpose": purpose,
        "reasons": [],
        "messages": [],
        "report_sha256": None,
        "verified_origins": {},
        "opportunity_count": None,
        "context": {},
    }
    snapshot: _Snapshot | None = None
    try:
        plain_path(report_path)
        snapshot = _Snapshot(report_path.parent)
        raw = snapshot.read(report_path)
        result["report_sha256"] = _hash(raw)
        report = _json(raw, "qualification")
        result["schema"] = report.get("schema")
        _require(
            type(report.get("schema")) is int and report["schema"] == SCHEMA,
            "qualification.schema",
            "资格 schema 不受支持",
        )
        _require(
            purpose in FORMAL_PURPOSES and report.get("purpose") == purpose,
            "qualification.purpose",
            "资格不得跨目的使用",
        )
        _require(
            set(report)
            == {"schema", "purpose", "checkpoint", "run_report", "registration", "game_files"},
            "qualification.shape",
            "资格结构包含缺失或未支持字段；布尔资格不能替代原件",
        )
        checkpoint_path, _raw = snapshot.reference(report["checkpoint"], "checkpoint", load=False)
        _require(
            report["checkpoint"]["sha256"] == checkpoint_sha256,
            "checkpoint.sha256",
            "不是现场冻结输入",
        )
        # inspect 会复核保存原件旁的来源局；间接输入也加入同一读前/读后快照。
        if checkpoint_path.parent.name == "saves":
            origin_root = checkpoint_path.parent.parent
            origin = _json(snapshot.read(origin_root / "report.json"), "checkpoint_origin")
            snapshot.tree(origin_root / "logs")
            if origin.get("kind") == "vanilla_checkpoint_preparation":
                snapshot.missing(origin_root / "sources")
            else:
                snapshot.tree(origin_root / "sources")
        checkpoint = checkpoint_catalog.inspect(checkpoint_path, expected_version=expected_version)
        _require(
            checkpoint["instrument_suitable"] is True,
            "checkpoint.rejected",
            "实际存档头或来源复核失败：" + ";".join(checkpoint["reasons"]),
        )
        run_path, run_raw = snapshot.reference(report["run_report"], "run_report")
        _registration_path, registration_raw = snapshot.reference(
            report["registration"], "registration"
        )
        registration = dict(_json(registration_raw, "registration"))
        _require(
            type(registration.get("schema")) is int
            and registration["schema"] == SCHEMA
            and registration.get("purpose") == purpose,
            "registration.schema_or_purpose",
            "登记版本或目的不同",
        )
        for field in ("plan_id", "scene_id", "criteria_version"):
            _require(
                isinstance(registration.get(field), str) and bool(registration[field].strip()),
                f"registration.{field}",
                "登记身份和判据版本必须完整",
            )
        _require(
            registration.get("checkpoint_sha256") == checkpoint_sha256,
            "registration.checkpoint",
            "事前登记未绑定冻结检查点",
        )
        hashes, versions, play_types = _game(snapshot, report["game_files"], expected_version)
        _require(
            registration.get("game_hashes") == hashes, "game.content", "登记游戏内容不是复核原件"
        )
        _context(registration, versions, context)
        observation = _mapping(registration.get("observation"), "observation")
        expected_sources = _sources(
            observation,
            purpose,
            play_types,
            _auxiliary(snapshot, report["game_files"], observation),
        )
        run = _review(snapshot, run_path, run_raw)
        _require(
            run["loaded_save"].get("sha256") == checkpoint_sha256
            and run["loaded_save"].get("header") == checkpoint["header"],
            "run_report.loaded_input",
            "证据来自另一输入或保存输出，不能冒充同一载入输入",
        )
        _require(
            run.get("qualification_registration_sha256") == _hash(registration_raw),
            "registration.unbound",
            "原运行未绑定事前登记原件",
        )
        for field in (
            "language",
            "mount_allowlist",
            "disabled_dlc",
            "game_hashes",
            "source_hashes",
        ):
            _require(
                run.get(field) == registration.get(field),
                f"run_report.{field}",
                "原局上下文与登记不同",
            )
        _require(
            run.get("game_version") == versions,
            "run_report.game_version",
            "原运行游戏版本/修订不同",
        )
        _require(
            registration["source_hashes"] == expected_sources,
            "sampling.treated_source",
            "原局不是受支持版本的未处理观测包",
        )
        _arms(registration, expected_sources, purpose)
        differences = _mapping(registration.get("declared_differences"), "declared_differences")
        _require(
            set(differences) == {"fiscal_injection", "treatment"}
            and differences["fiscal_injection"] == "none"
            and differences["treatment"]
            == ("frozen-candidate" if purpose == "M4" else "neutrality"),
            "differences.unsupported",
            "禁止财政注入及未登记差异",
        )
        sampling = _mapping(registration.get("sampling"), "sampling")
        _require(
            _nonnegative(sampling.get("max_overshoot_days")),
            "sampling.max_overshoot_days",
            "必须事前登记有限非负越窗预算，布尔无效",
        )
        _require(
            type(sampling.get("sample_count")) is int
            and sampling["sample_count"] > 0
            and _number(sampling.get("window_days"))
            and sampling.get("before_treatment") is True,
            "sampling.invalid",
            "须事前登记处理前采样与有限窗口",
        )
        _require(
            purpose != "M3-B",
            "opportunity.denominator_unsupported",
            "当前仪器没有完整且可审计发起候选分母，M3-B 保持拒绝",
        )
        registration["play_types"] = play_types
        if purpose == "M4":
            assert context is not None
            verified = _performance(snapshot, registration, checkpoint)
        else:
            _require(bool(play_types), "game.play_types", "指定自然响应缺少原版博弈类型原件")
            verified = _behavior(snapshot, run_path, registration, run)
        snapshot.verify()
        result.update(verified)
        result["verified_origins"] = {
            path.relative_to(snapshot.root).as_posix(): digest
            for path, (_identity_value, digest) in snapshot.files.items()
        }
        result["verified_trees"] = {
            path.relative_to(snapshot.root).as_posix(): list(members)
            for path, members in snapshot.trees.items()
        }
        result["verified_absent"] = sorted(
            path.relative_to(snapshot.root).as_posix() for path in snapshot.absent
        )
        result["context"] = {field: registration[field] for field in CONTEXT_FIELDS}
        result["allowed"] = True
        result["state"] = "formal-pair-suitable"
        result["messages"] = ["原件和现场上下文已复核；仅许可启动，运行后仍须重新验收机会与质量。"]
    except EvidenceError as exc:
        result["reasons"].append(exc.reason)
        result["messages"].append(str(exc))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        OverflowError,
        RecursionError,
    ) as exc:
        result["reasons"].append("qualification.invalid")
        result["messages"].append(f"原件不可复核或结构不受支持：{type(exc).__name__}: {exc}")
    if snapshot is not None:
        try:
            snapshot.verify()
        except (OSError, ValueError, TypeError) as exc:
            result["allowed"] = False
            result["state"] = "rejected"
            result["reasons"].append("artifact.changed")
            result["messages"].append(f"复核结束时原件变化或不可读：{exc}")
    result["reasons"] = list(dict.fromkeys(result["reasons"]))
    return result
