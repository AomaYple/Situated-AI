"""筛选 M3-A 受控外交配对。

该模块只做历史证据的筛选，不把评分差分或强制创建机会升级为行为质量结论。
候选必须满足当前配对契约：同版本、同检查点、同完整挂载允许清单、同非策略源，
且只改变默认策略中的 neutrality；两臂都必须通过严格错误门禁。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import decisions
from .game_run import ERROR_MARKERS, _normalize_mount_path, ga
from .textio import GAME_SUFFIXES, text_bytes

TAG_RE = re.compile(r"^[A-Z]{3}$")
STRATEGY_PATH = "common/ai_strategies/00_default_strategy.txt"
ERROR_KEYS = ERROR_MARKERS
ROLE_KINDS = ("BACKER", "INIT_BACKER", "TARGET_BACKER")
ELIGIBILITY_KINDS = ("CAN_INIT", "CAN_TARGET")


def _sample_key(value: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"sample-(\d+)", value)
    return ("sample", int(match[1]), "") if match else (value, 0, value)


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _number(value: str) -> float | None:
    text = value.strip().replace("−", "-").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _clean_report(report: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if report.get("ok") is not True:
        reasons.append("report.ok_not_true")
    if report.get("failure"):
        reasons.append("report.failure")
    if report.get("cleanup_errors") != []:
        reasons.append("report.cleanup_errors")
    findings = report.get("log_findings")
    if not isinstance(findings, Mapping):
        reasons.append("log_findings.missing")
    else:
        errors = findings.get("errors")
        if not isinstance(errors, Mapping):
            reasons.append("log_findings.errors_missing")
        else:
            reasons.extend(
                f"log_findings.error:{key}" for key in ERROR_KEYS if errors.get(key) != 0
            )
        reasons.extend(
            f"log_findings.{key}"
            for key in ("mod_errors", "missing_mounts", "unexpected_mounts")
            if findings.get(key) != []
        )
        # 历史原报告尚无这个字段；归档复核会补解析值。已有必需字段仍须
        # 显式为空列表，不能为兼容新字段而把缺失的挂载/Mod结果默认为成功。
        if findings.get("unclassified_errors", []) != []:
            reasons.append("log_findings.unclassified_errors")
    review = report.get("review")
    if isinstance(review, Mapping) and review.get("mounts_verified") is False:
        reasons.append("review.mounts_not_verified")
    allowlist = report.get("mount_allowlist")
    if not isinstance(allowlist, list) or not allowlist:
        reasons.append("mount_allowlist.missing")
    elif any(not isinstance(item, str) or not item for item in allowlist):
        reasons.append("mount_allowlist.invalid")
    elif isinstance(findings, Mapping):
        mounted = findings.get("mounted")
        actual = (
            {
                _normalize_mount_path(line.split("Mounted Data:", 1)[-1])
                for line in mounted or ()
                if isinstance(line, str) and "Mounted Data:" in line
            }
            if isinstance(mounted, list)
            else set()
        )
        if actual != {_normalize_mount_path(item) for item in allowlist}:
            reasons.append("mounts.actual_missing_or_differs")
    sources, deployed = report.get("source_hashes"), report.get("deployed_hashes")
    if not isinstance(deployed, Mapping) or not isinstance(sources, Mapping) or not deployed:
        reasons.append("deployed_hashes.missing")
    elif sources.keys() != deployed.keys() or any(
        not isinstance(files, Mapping)
        or not files
        or not isinstance(deployed.get(name), Mapping)
        or files.keys() != deployed[name].keys()
        for name, files in sources.items()
    ):
        reasons.append("deployed_hashes.incomplete")
    loaded = report.get("loaded_save")
    if not isinstance(loaded, Mapping) or not re.fullmatch(
        r"[0-9a-f]{64}", str(loaded.get("sha256", ""))
    ):
        reasons.append("loaded_save.sha256_missing")
    version = report.get("game_version")
    if not isinstance(version, Mapping) or not version:
        reasons.append("game_version.missing")
    if report.get("language") is not None and report["language"] not in ga.SESSION_LANGUAGES:
        reasons.append("language.invalid")
    return not reasons, reasons


@dataclass(frozen=True, slots=True)
class CountryFacts:
    tag: str
    eligible_active_dates: tuple[str, ...]
    backer_dates: tuple[str, ...]
    role_by_date: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    score_values: tuple[tuple[str, tuple[float, ...]], ...]
    samples: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    issues: tuple[str, ...]

    @property
    def score_range(self) -> tuple[float, float] | None:
        values = [value for _, numbers in self.score_values for value in numbers]
        return (min(values), max(values)) if values else None

    def role_at(self, date: str) -> tuple[tuple[str, str], ...]:
        for item_date, roles in self.role_by_date:
            if item_date == date:
                return roles
        return ()


@dataclass(frozen=True, slots=True)
class ReportFacts:
    path: str
    clean: bool
    gate_reasons: tuple[str, ...]
    game_version: Mapping[str, Any]
    checkpoint_sha256: str | None
    mount_allowlist: tuple[str, ...] | None
    source_hashes: Mapping[str, Mapping[str, str]]
    countries: Mapping[str, CountryFacts]
    observer: str | None
    evidence: str | None
    phases: Mapping[str, str]
    deployed_hashes: Mapping[str, Mapping[str, str]]
    window_start: str | None
    activation_tick: str | None
    language: str | None = None

    @property
    def strategy_digest(self) -> str | None:
        source = self.source_hashes.get("sitai_decision_candidate", {})
        value = source.get(STRATEGY_PATH)
        return value if isinstance(value, str) else None

    @property
    def non_strategy_sources(self) -> Mapping[str, Mapping[str, str]]:
        return {
            name: {
                key: value
                for key, value in files.items()
                if name != "sitai_decision_candidate" or key != STRATEGY_PATH
            }
            for name, files in self.source_hashes.items()
        }


@dataclass(frozen=True, slots=True)
class PairCandidate:
    control: ReportFacts
    treatment: ReportFacts
    neutrality_delta: float | None
    common_eligible_active_dates: tuple[str, ...]
    countries: tuple[str, ...]
    role_changes: Mapping[str, Mapping[str, bool | None]]
    score_deltas: Mapping[str, tuple[float, ...]]
    qualified: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "control": self.control.path,
            "treatment": self.treatment.path,
            "evidence": {
                "control": self.control.evidence,
                "treatment": self.treatment.evidence,
            },
            "game_version": dict(self.control.game_version),
            "checkpoint_sha256": self.control.checkpoint_sha256,
            "mount_allowlist": list(self.control.mount_allowlist or ()),
            "countries": list(self.countries),
            "neutrality_delta": self.neutrality_delta,
            "common_eligible_active_dates": list(self.common_eligible_active_dates),
            "score_deltas": {key: list(value) for key, value in self.score_deltas.items()},
            "role_changes": {key: dict(value) for key, value in self.role_changes.items()},
            "qualified": self.qualified,
            "reasons": list(self.reasons),
        }


def _country_facts(tag: str, rows: Iterable[Mapping[str, Any]]) -> CountryFacts:
    eligible: set[str] = set()
    backer: set[str] = set()
    roles: dict[str, dict[str, str]] = defaultdict(dict)
    scores: dict[str, list[float]] = defaultdict(list)
    by_date: dict[str, dict[str, str]] = defaultdict(dict)
    issues: list[str] = []
    for row in rows:
        date = str(row.get("date", ""))
        kind = str(row.get("kind", ""))
        value = str(row.get("value", "")).strip()
        if not date or not kind or not value:
            issues.append(f"opportunity.invalid_row:{tag}")
            continue
        if kind in by_date[date]:
            issues.append(f"opportunity.duplicate_sample:{tag}:{date}:{kind}")
            continue
        by_date[date][kind] = value
        if kind in ROLE_KINDS:
            roles[date][kind] = value
        if kind == "BACKER" and value == "yes":
            backer.add(date)
    for date, state in sorted(by_date.items(), key=lambda item: _sample_key(item[0])):
        if any(
            state.get(kind) not in {"yes", "no"}
            for kind in ("UNDECIDED", "ACTIVE", *ELIGIBILITY_KINDS, *ROLE_KINDS)
        ):
            issues.append(f"opportunity.incomplete_sample:{tag}:{date}")
        if state.get("UNDECIDED") == state.get("ACTIVE") == "yes" and any(
            state.get(kind) == "yes" for kind in ELIGIBILITY_KINDS
        ):
            eligible.add(date)
        for kind in ("INIT_SCORE", "TARGET_SCORE"):
            if kind in state:
                number = _number(state[kind])
                if number is None:
                    issues.append(f"opportunity.invalid_score:{tag}:{date}:{kind}")
                else:
                    scores[kind].append(number)
    return CountryFacts(
        tag=tag,
        eligible_active_dates=tuple(sorted(eligible, key=_sample_key)),
        backer_dates=tuple(sorted(backer, key=_sample_key)),
        role_by_date=tuple(
            (date, tuple(sorted(values.items()))) for date, values in sorted(roles.items())
        ),
        score_values=tuple((kind, tuple(values)) for kind, values in sorted(scores.items())),
        samples=tuple(
            (date, tuple(sorted(state.items())))
            for date, state in sorted(by_date.items(), key=lambda item: _sample_key(item[0]))
        ),
        issues=tuple(dict.fromkeys(issues)),
    )


def load_report(path: Path) -> ReportFacts:
    from .game_run import read_reviewed_report  # noqa: PLC0415

    report = json.loads(path.read_text(encoding="utf-8"))
    # 原报告里的失败/缺证不能被新的日志解析清空；成功还必须经当前归档门禁复核。
    clean, reasons = _clean_report(report)
    try:
        report = read_reviewed_report(path)
        reviewed_clean, reviewed_reasons = _clean_report(report)
        clean = clean and reviewed_clean
        reasons.extend(reviewed_reasons)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        clean = False
        reasons.append("log_archive.unverified")
    analysis = report.get("analysis")
    opportunity = analysis.get("opportunity") if isinstance(analysis, Mapping) else None
    rows = opportunity.get("rows", []) if isinstance(opportunity, Mapping) else []
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and TAG_RE.fullmatch(str(row.get("tag", ""))):
                grouped[str(row["tag"])].append(row)
    phases: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else ():
        if (
            isinstance(row, Mapping)
            and row.get("tag") == "CONTROL"
            and row.get("kind") == "ESCALATION"
        ):
            date, value = str(row.get("date", "")), str(row.get("value", ""))
            if not date or _number(value) is None or date in phases:
                reasons.append("opportunity.phase_invalid_or_duplicate")
            phases[date] = value
    countries = {tag: _country_facts(tag, tag_rows) for tag, tag_rows in sorted(grouped.items())}
    reasons.extend(issue for facts in countries.values() for issue in facts.issues)
    loaded = report.get("loaded_save")
    sha = loaded.get("sha256") if isinstance(loaded, Mapping) else None
    header = loaded.get("header", {}) if isinstance(loaded, Mapping) else {}
    allowlist = report.get("mount_allowlist")
    sources = report.get("source_hashes")
    if not isinstance(sources, Mapping):
        sources = {}
        reasons.append("source_hashes.missing")
        clean = False
    deployed = report.get("deployed_hashes", {})
    if not isinstance(deployed, Mapping):
        deployed = {}
    for name, files in sources.items():
        if not isinstance(files, Mapping):
            continue
        for relative, digest in files.items():
            source = path.parent / "sources" / str(name) / str(relative)
            root = path.parent / "sources"
            if not source.resolve().is_relative_to(root.resolve()) or any(
                p.is_symlink() for p in (source, *source.parents)
            ):
                reasons.append("deployment.source_path_invalid")
                continue
            try:
                raw = source.read_bytes()
                expected = (
                    text_bytes(raw.decode("utf-8-sig"), game=True)
                    if source.suffix.lower() in GAME_SUFFIXES
                    else raw
                )
                actual = deployed.get(name, {})
                if (
                    not isinstance(actual, Mapping)
                    or hashlib.sha256(raw).hexdigest() != digest
                    or hashlib.sha256(expected).hexdigest() != actual.get(relative)
                ):
                    reasons.append("deployment.fingerprint_mismatch")
            except (OSError, UnicodeError):
                reasons.append("deployment.source_unavailable")
    progress = report.get("progress", {})
    if not isinstance(progress, Mapping):
        progress = {}
    return ReportFacts(
        path=str(path),
        clean=clean and not reasons,
        gate_reasons=tuple(dict.fromkeys(reasons)),
        game_version=dict(report.get("game_version", {}))
        if isinstance(report.get("game_version"), Mapping)
        else {},
        checkpoint_sha256=sha if isinstance(sha, str) else None,
        mount_allowlist=tuple(sorted(allowlist)) if isinstance(allowlist, list) else None,
        source_hashes={
            str(name): {str(key): str(value) for key, value in files.items()}
            for name, files in sources.items()
            if isinstance(files, Mapping)
        },
        countries=countries,
        observer=str(header.get("observer")) if header.get("observer") is not None else None,
        evidence=str(report.get("evidence")) if report.get("evidence") else None,
        phases=phases,
        deployed_hashes={
            str(name): dict(files) for name, files in deployed.items() if isinstance(files, Mapping)
        },
        window_start=str(progress["start"]) if progress.get("start") else None,
        activation_tick=str(progress["activation_tick"])
        if progress.get("activation_tick")
        else None,
        language=report.get("language") if isinstance(report.get("language"), str) else None,
    )


def _pair_shape(left: ReportFacts, right: ReportFacts) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if left.game_version != right.game_version:
        reasons.append("game_version.differs")
    if left.language != right.language:
        reasons.append("language.differs_or_unknown")
    if not left.checkpoint_sha256 or left.checkpoint_sha256 != right.checkpoint_sha256:
        reasons.append("checkpoint.sha256_differs_or_missing")
    if left.mount_allowlist is None or right.mount_allowlist is None:
        reasons.append("mount_allowlist.missing")
    elif left.mount_allowlist != right.mount_allowlist:
        reasons.append("mount_allowlist.differs")
    if left.non_strategy_sources != right.non_strategy_sources:
        reasons.append("source_hashes.non_strategy_differs")
    deployed = [
        {
            name: {
                key: value
                for key, value in files.items()
                if name != "sitai_decision_candidate" or key != STRATEGY_PATH
            }
            for name, files in report.deployed_hashes.items()
        }
        for report in (left, right)
    ]
    if deployed[0] != deployed[1]:
        reasons.append("deployed_hashes.non_strategy_differs")
    if not left.window_start or left.window_start != right.window_start:
        reasons.append("opportunity.window_start_missing_or_differs")
    if (
        not left.activation_tick
        or not right.activation_tick
        or left.activation_tick != left.window_start
        or right.activation_tick != right.window_start
    ):
        reasons.append("opportunity.activation_tick_missing_or_differs")
    if left.source_hashes.keys() != right.source_hashes.keys():
        reasons.append("source_hashes.mod_set_differs")
    if left.countries.keys() != right.countries.keys():
        reasons.append("opportunity.tags_differs")
    if left.observer != right.observer or left.observer != "yes":
        reasons.append("checkpoint.observer_not_same_yes")
    return not reasons, reasons


def pair_reports(
    control: ReportFacts,
    treatment: ReportFacts,
    *,
    neutrality_resolver: Callable[[str], tuple[float, float] | None] | None = None,
) -> PairCandidate:
    reasons: list[str] = list(control.gate_reasons) + list(treatment.gate_reasons)
    shape_ok, shape_reasons = _pair_shape(control, treatment)
    reasons.extend(shape_reasons)
    delta: float | None = None
    if control.strategy_digest == treatment.strategy_digest:
        reasons.append("strategy.no_difference")
    elif not control.strategy_digest or not treatment.strategy_digest:
        reasons.append("strategy.digest_missing")
    elif neutrality_resolver is None:
        reasons.append("strategy.neutrality_unresolved")
    else:
        left = neutrality_resolver(control.strategy_digest)
        right = neutrality_resolver(treatment.strategy_digest)
        if left is None or right is None:
            reasons.append("strategy.unrecognized_experiment_arm")
        elif left[1] != right[1] or left[0] == right[0]:
            reasons.append("strategy.not_neutrality_only")
        else:
            delta = right[0] - left[0]
            if not (math.isfinite(delta) and 0 < delta <= 100):
                reasons.append("strategy.invalid_neutrality_delta")
    tags = tuple(sorted(set(control.countries) & set(treatment.countries)))
    common_dates = tuple(
        sorted(
            set.intersection(
                *(
                    set(control.countries[tag].eligible_active_dates)
                    & set(treatment.countries[tag].eligible_active_dates)
                    for tag in tags
                )
            ),
            key=_sample_key,
        )
        if tags
        else ()
    )
    if len(tags) < 2:
        reasons.append("opportunity.fewer_than_two_countries")
    if len(tags) > 2:
        reasons.append("opportunity.more_than_two_countries")
    if any(
        not (
            set(control.countries[tag].eligible_active_dates)
            & set(treatment.countries[tag].eligible_active_dates)
        )
        for tag in tags
    ):
        reasons.append("opportunity.no_common_eligible_active_date_for_country")
    if not common_dates:
        reasons.append("opportunity.no_common_eligible_active_date")
    role_changes: dict[str, dict[str, bool | None]] = {}
    score_deltas: dict[str, tuple[float, ...]] = {}
    for tag in tags:
        left_facts: CountryFacts = control.countries[tag]
        right_facts: CountryFacts = treatment.countries[tag]
        left_samples = {date: dict(values) for date, values in left_facts.samples}
        right_samples = {date: dict(values) for date, values in right_facts.samples}
        dates = sorted(left_samples.keys() & right_samples.keys(), key=_sample_key)
        if left_samples.keys() != right_samples.keys():
            reasons.append(f"opportunity.sample_keys_differ:{tag}")
        if not dates or any(
            date not in control.phases or date not in treatment.phases for date in dates
        ):
            reasons.append("opportunity.phase_missing")
        elif any(
            _number(control.phases[date]) != _number(treatment.phases[date]) for date in dates
        ):
            reasons.append("opportunity.phase_differs")
        role_changes[tag] = {
            kind: None
            if any(
                kind not in left_samples[date] or kind not in right_samples[date] for date in dates
            )
            else any(
                dict(left_facts.role_at(date)).get(kind)
                != dict(right_facts.role_at(date)).get(kind)
                for date in dates
            )
            for kind in ROLE_KINDS
        }
        deltas: list[float] = []
        for date in sorted(
            set(left_facts.eligible_active_dates) & set(right_facts.eligible_active_dates),
            key=_sample_key,
        ):
            if any(
                left_samples[date].get(kind) != right_samples[date].get(kind)
                for kind in ELIGIBILITY_KINDS
            ):
                reasons.append(f"opportunity.eligibility_side_differs:{tag}:{date}")
            for eligible_kind, score_kind in (
                ("CAN_INIT", "INIT_SCORE"),
                ("CAN_TARGET", "TARGET_SCORE"),
            ):
                if (
                    left_samples[date].get(eligible_kind)
                    == right_samples[date].get(eligible_kind)
                    == "yes"
                ):
                    a = _number(left_samples[date].get(score_kind, ""))
                    b = _number(right_samples[date].get(score_kind, ""))
                    if a is None or b is None:
                        reasons.append(f"opportunity.score_missing:{tag}:{date}:{score_kind}")
                    else:
                        deltas.append(round(b - a, 10))
        if not deltas:
            reasons.append(f"opportunity.no_common_readable_score:{tag}")
        score_deltas[tag] = tuple(deltas)
    if not shape_ok:
        reasons.extend(shape_reasons)
    qualified = not reasons and len(tags) == 2 and len(common_dates) > 0
    return PairCandidate(
        control=control,
        treatment=treatment,
        neutrality_delta=delta,
        common_eligible_active_dates=common_dates,
        countries=tags,
        role_changes=role_changes,
        score_deltas=score_deltas,
        qualified=qualified,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _default_neutrality_resolver() -> Callable[[str], tuple[float, float] | None] | None:
    try:
        policy = decisions.load()
        baseline = decisions.BASELINE.read_text(encoding="utf-8")
        values: dict[str, tuple[float, float]] = {}
        for neutrality, aggression in (
            (0, 0),
            (policy.neutrality, 0),
            (0, policy.aggression),
            (policy.neutrality, policy.aggression),
        ):
            text = decisions.patch_default(
                baseline,
                policy.__class__(
                    game_version=policy.game_version,
                    baseline_sha256=policy.baseline_sha256,
                    entry_weeks=policy.entry_weeks,
                    exit_weeks=policy.exit_weeks,
                    ttl_days=policy.ttl_days,
                    neutrality=neutrality,
                    aggression=aggression,
                ),
            )
            values[hashlib.sha256(text.encode("utf-8")).hexdigest()] = neutrality, aggression
        return values.get
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def discover(root: Path) -> list[ReportFacts]:
    return [load_report(path) for path in sorted(root.rglob("report.json"))]


def screen(
    root: Path, *, resolver: Callable[[str], tuple[float, float] | None] | None = None
) -> dict[str, Any]:
    reports = discover(root)
    resolver = _default_neutrality_resolver() if resolver is None else resolver
    groups: dict[tuple[str, str, tuple[str, ...], str, str], list[ReportFacts]] = defaultdict(list)
    for report in reports:
        groups[
            (
                _json_key(report.game_version),
                report.checkpoint_sha256 or "",
                report.mount_allowlist or (),
                _json_key(report.non_strategy_sources),
                report.language or "",
            )
        ].append(report)
    candidates: list[PairCandidate] = []
    for group in groups.values():
        for index, control in enumerate(group):
            for treatment in group[index + 1 :]:
                pair = pair_reports(control, treatment, neutrality_resolver=resolver)
                if resolver is not None and control.strategy_digest and treatment.strategy_digest:
                    left, right = (
                        resolver(control.strategy_digest),
                        resolver(treatment.strategy_digest),
                    )
                    if left is not None and right is not None and left[0] > right[0]:
                        pair = pair_reports(treatment, control, neutrality_resolver=resolver)
                candidates.append(pair)
    candidates.sort(
        key=lambda item: (
            not item.qualified,
            -len(item.common_eligible_active_dates),
            item.control.path,
        )
    )
    return {
        "report_count": len(reports),
        "strict_clean_count": sum(report.clean for report in reports),
        "qualified_count": sum(pair.qualified for pair in candidates),
        "candidates": [pair.as_dict() for pair in candidates],
        "limits": [
            "筛选不会把评分差分、BACKER变化或强制创建机会当作质量通过",
            "没有完整挂载允许清单、检查点SHA或严格错误复核的历史报告不能进入候选",
            "aggression必须保持不变；自然started实验不属于M3-A",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path("tools/out/decisions"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = screen(args.root)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
