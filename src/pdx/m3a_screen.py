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

TAG_RE = re.compile(r"^[A-Z]{3}$")
STRATEGY_PATH = "common/ai_strategies/00_default_strategy.txt"
ERROR_KEYS = (
    "Unexpected token",
    "Unknown effect",
    "Unknown trigger",
    "Invalid database object",
    "Mod metadata read error",
    "Duplicated key",
    "Undefined event target",
    "Invalid left side",
)
ROLE_KINDS = ("BACKER", "INIT_BACKER", "TARGET_BACKER")
ELIGIBILITY_KINDS = ("CAN_INIT", "CAN_TARGET")


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
    if report.get("cleanup_errors"):
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
            if findings.get(key)
        )
    review = report.get("review")
    if isinstance(review, Mapping) and review.get("mounts_verified") is False:
        reasons.append("review.mounts_not_verified")
    allowlist = report.get("mount_allowlist")
    if not isinstance(allowlist, list) or not allowlist:
        reasons.append("mount_allowlist.missing")
    elif any(not isinstance(item, str) or not item for item in allowlist):
        reasons.append("mount_allowlist.invalid")
    loaded = report.get("loaded_save")
    if not isinstance(loaded, Mapping) or not re.fullmatch(
        r"[0-9a-f]{64}", str(loaded.get("sha256", ""))
    ):
        reasons.append("loaded_save.sha256_missing")
    version = report.get("game_version")
    if not isinstance(version, Mapping) or not version:
        reasons.append("game_version.missing")
    return not reasons, reasons


@dataclass(frozen=True, slots=True)
class CountryFacts:
    tag: str
    eligible_active_dates: tuple[str, ...]
    backer_dates: tuple[str, ...]
    role_by_date: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    score_values: tuple[tuple[str, tuple[float, ...]], ...]

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

    @property
    def strategy_digest(self) -> str | None:
        source = self.source_hashes.get("sitai_decision_candidate", {})
        value = source.get(STRATEGY_PATH)
        return value if isinstance(value, str) else None

    @property
    def non_strategy_sources(self) -> Mapping[str, Mapping[str, str]]:
        return {
            name: {key: value for key, value in files.items() if key != STRATEGY_PATH}
            for name, files in self.source_hashes.items()
        }


@dataclass(frozen=True, slots=True)
class PairCandidate:
    control: ReportFacts
    treatment: ReportFacts
    neutrality_delta: float | None
    common_eligible_active_dates: tuple[str, ...]
    countries: tuple[str, ...]
    role_changes: Mapping[str, Mapping[str, bool]]
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
    for row in rows:
        date = str(row.get("date", ""))
        kind = str(row.get("kind", ""))
        value = str(row.get("value", "")).strip()
        if not date:
            continue
        by_date[date][kind] = value
        if kind in ROLE_KINDS:
            roles[date][kind] = value
        if kind == "BACKER" and value == "yes":
            backer.add(date)
        if kind in ELIGIBILITY_KINDS and value == "yes":
            state = by_date[date]
            if state.get("UNDECIDED") == "yes" and state.get("ACTIVE") == "yes":
                eligible.add(date)
        if kind in {"INIT_SCORE", "TARGET_SCORE"}:
            number = _number(value)
            if number is not None:
                scores[kind].append(number)
    return CountryFacts(
        tag=tag,
        eligible_active_dates=tuple(sorted(eligible)),
        backer_dates=tuple(sorted(backer)),
        role_by_date=tuple(
            (date, tuple(sorted(values.items()))) for date, values in sorted(roles.items())
        ),
        score_values=tuple((kind, tuple(values)) for kind, values in sorted(scores.items())),
    )


def load_report(path: Path) -> ReportFacts:
    report = json.loads(path.read_text(encoding="utf-8"))
    analysis = report.get("analysis")
    opportunity = analysis.get("opportunity") if isinstance(analysis, Mapping) else None
    rows = opportunity.get("rows", []) if isinstance(opportunity, Mapping) else []
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and TAG_RE.fullmatch(str(row.get("tag", ""))):
                grouped[str(row["tag"])].append(row)
    clean, reasons = _clean_report(report)
    loaded = report.get("loaded_save")
    sha = loaded.get("sha256") if isinstance(loaded, Mapping) else None
    header = loaded.get("header", {}) if isinstance(loaded, Mapping) else {}
    allowlist = report.get("mount_allowlist")
    sources = report.get("source_hashes")
    if not isinstance(sources, Mapping):
        sources = {}
        reasons.append("source_hashes.missing")
        clean = False
    return ReportFacts(
        path=str(path),
        clean=clean,
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
        countries={tag: _country_facts(tag, tag_rows) for tag, tag_rows in sorted(grouped.items())},
        observer=str(header.get("observer")) if header.get("observer") is not None else None,
        evidence=str(report.get("evidence")) if report.get("evidence") else None,
    )


def _pair_shape(left: ReportFacts, right: ReportFacts) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if left.game_version != right.game_version:
        reasons.append("game_version.differs")
    if not left.checkpoint_sha256 or left.checkpoint_sha256 != right.checkpoint_sha256:
        reasons.append("checkpoint.sha256_differs_or_missing")
    if left.mount_allowlist is None or right.mount_allowlist is None:
        reasons.append("mount_allowlist.missing")
    elif left.mount_allowlist != right.mount_allowlist:
        reasons.append("mount_allowlist.differs")
    if left.non_strategy_sources != right.non_strategy_sources:
        reasons.append("source_hashes.non_strategy_differs")
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
            )
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
    role_changes: dict[str, dict[str, bool]] = {}
    score_deltas: dict[str, tuple[float, ...]] = {}
    for tag in tags:
        left_facts: CountryFacts = control.countries[tag]
        right_facts: CountryFacts = treatment.countries[tag]
        dates = sorted(
            set(left_facts.eligible_active_dates) & set(right_facts.eligible_active_dates)
        )
        role_changes[tag] = {
            kind: any(
                dict(left_facts.role_at(date)).get(kind)
                != dict(right_facts.role_at(date)).get(kind)
                for date in dates
            )
            for kind in ROLE_KINDS
        }
        deltas: list[float] = []
        left_scores = dict(left_facts.score_values)
        right_scores = dict(right_facts.score_values)
        for kind in set(left_scores) & set(right_scores):
            if len(left_scores[kind]) == len(right_scores[kind]):
                deltas.extend(
                    round(b - a, 10)
                    for a, b in zip(left_scores[kind], right_scores[kind], strict=True)
                )
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
    groups: dict[tuple[str, str, tuple[str, ...], str], list[ReportFacts]] = defaultdict(list)
    for report in reports:
        groups[
            (
                _json_key(report.game_version),
                report.checkpoint_sha256 or "",
                report.mount_allowlist or (),
                _json_key(report.non_strategy_sources),
            )
        ].append(report)
    candidates: list[PairCandidate] = []
    for group in groups.values():
        for index, control in enumerate(group):
            for treatment in group[index + 1 :]:
                pair = pair_reports(control, treatment, neutrality_resolver=resolver)
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
