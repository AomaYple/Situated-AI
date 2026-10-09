"""显式国家 × IG × 法律的只读态度仪器；不推断 AI 革命否决。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

PREFIX = "SITAI APPROVAL;"
ROW = re.compile(
    r"SITAI APPROVAL;(?P<tag>[A-Z]{3});(?P<ig>ig_[a-z0-9_]+);"
    r"(?P<law>law_[a-z0-9_]+);(?P<kind>[A-Z_]+);(?P<value>[^;]*);"
    r"(?P<sample>sample-[1-9]\d*)$"
)
KINDS = frozenset({"EXISTS", "NAME", "CURRENT", "DELTA", "PREDICTED", "RADICALIZE"})
NUMERIC = frozenset({"CURRENT", "DELTA", "PREDICTED"})


@dataclass(frozen=True, slots=True)
class ApprovalRow:
    tag: str
    ig: str
    law: str
    kind: str
    value: str | int | bool
    sample: str


def validate(igs: Iterable[str], laws: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """空参数关闭仪器；非空声明必须完整、唯一且无法注入脚本。"""
    groups, targets = tuple(igs), tuple(laws)
    if (
        bool(groups) != bool(targets)
        or len(groups) != len(set(groups))
        or len(targets) != len(set(targets))
        or any(not re.fullmatch(r"ig_[a-z0-9_]+", key) for key in groups)
        or any(not re.fullmatch(r"law_[a-z0-9_]+", key) for key in targets)
    ):
        raise ValueError("态度矩阵必须成对声明唯一且规范的 IG/法律键")
    return tuple(sorted(groups)), tuple(sorted(targets))


def readings(tag: str, igs: Iterable[str], laws: Iterable[str], sample_variable: str) -> str:
    groups, targets = validate(igs, laws)
    if not re.fullmatch(r"[A-Z]{3}", tag) or not re.fullmatch(r"[a-z][a-z0-9_]*", sample_variable):
        raise ValueError("态度观察国或采样变量无效")
    blocks = []
    for ig in groups:
        receiver = f"THIS.GetCountry.GetInterestGroupOfType('{ig}')"
        for law in targets:

            def log(kind: str, value: str, *, ig: str = ig, law: str = law) -> str:
                return (
                    f'debug_log = "{PREFIX}{tag};{ig};{law};{kind};{value};'
                    f"sample-[THIS.Var('{sample_variable}').GetValue|0]\""
                )

            argument = f"GetLawType('{law}').Self"
            present = "\n".join(
                (
                    log("EXISTS", "yes"),
                    log("NAME", f"[{receiver}.GetNameNoFormatting]"),
                    log("CURRENT", f"[{receiver}.GetApprovalValue|0]"),
                    log("DELTA", f"[{receiver}.GetApprovalValueDeltaFromEnactment({argument})|0]"),
                    log("PREDICTED", f"[{receiver}.GetApprovalValueIfEnacted({argument})|0]"),
                    log("RADICALIZE", f"[{receiver}.WillRadicalizeIfEnacted({argument})]"),
                )
            )
            blocks.append(
                f"if = {{ limit = {{ any_interest_group = {{ is_interest_group_type = {ig} }} }}\n"
                f"{present}\n}} else = {{ {log('EXISTS', 'no')} }}"
            )
    return "\n".join(blocks)


def parse_row(line: str) -> ApprovalRow:
    match = ROW.search(line.rstrip())
    if match is None:
        raise ValueError("态度仪器行未完整解析")
    fields = match.groupdict()
    kind, value = fields["kind"], fields["value"]
    value = re.sub(r"\x15[^;\x15]*;", "", value).replace("\x15!", "").strip()
    parsed: str | int | bool = value
    if kind not in KINDS:
        raise ValueError("未知态度字段")
    if kind in {"EXISTS", "RADICALIZE"}:
        if value not in {"yes", "no", "0", "1"}:
            raise ValueError("态度布尔读数未解析")
        parsed = value in {"yes", "1"}
    elif kind in NUMERIC:
        normalized = value.replace("−", "-")
        if not re.fullmatch(r"-?\d+", normalized):
            raise ValueError("态度整数未解析")
        parsed = int(normalized)
        if not -(2**31) <= parsed < 2**31:
            raise ValueError("态度整数超出 int32")
    elif not value or "[" in value or "]" in value:
        raise ValueError("态度名称未解析")
    return ApprovalRow(fields["tag"], fields["ig"], fields["law"], kind, parsed, fields["sample"])


def analyze(
    rows: Iterable[ApprovalRow],
    *,
    expected_tags: tuple[str, ...],
    expected_igs: tuple[str, ...],
    expected_laws: tuple[str, ...],
    country_samples: Iterable[tuple[str, str, str]],
) -> dict:
    groups, laws = validate(expected_igs, expected_laws)
    if len(expected_tags) != len(set(expected_tags)) or any(
        not re.fullmatch(r"[A-Z]{3}", tag) for tag in expected_tags
    ):
        raise ValueError("态度矩阵国家声明无效")
    observed = list(rows)
    country_observations = list(country_samples)
    anchors = Counter((tag, sample) for tag, sample, _name in country_observations)
    samples = set(anchors) | {(r.tag, r.sample) for r in observed}
    cells: dict[tuple[str, str, str, str], list[ApprovalRow]] = defaultdict(list)
    invariant_values: dict[tuple[str, str, str, str], set[str | int | bool]] = defaultdict(set)
    for row in observed:
        cells[row.tag, row.sample, row.ig, row.law].append(row)
        if row.kind in {"EXISTS", "NAME", "CURRENT"}:
            invariant_values[row.tag, row.sample, row.ig, row.kind].add(row.value)
    expected = {
        (tag, sample, ig, law)
        for tag, sample in samples
        if tag in expected_tags
        for ig in groups
        for law in laws
    }
    issues = []
    if not expected_tags or not groups or not laws:
        issues.append("expected_matrix.missing")
    if set(expected_tags) != {tag for tag, _sample in samples}:
        issues.append("matrix.country_missing_or_unexpected")
    if not expected or set(cells) != expected:
        issues.append("matrix.missing_or_unexpected_cells")
    if any(anchors[sample] != 1 for sample in samples):
        issues.append("matrix.country_sample_missing_or_duplicate")
    if any(not name or "[" in name or "]" in name for _tag, _sample, name in country_observations):
        issues.append("matrix.country_name_unresolved")
    if any(len(values_) != 1 for values_ in invariant_values.values()):
        issues.append("matrix.interest_group_state_inconsistent_across_laws")
    present_cells = 0
    for readings_ in cells.values():
        counts = Counter(row.kind for row in readings_)
        existence = [r.value for r in readings_ if r.kind == "EXISTS"]
        if counts["EXISTS"] != 1:
            issues.append("matrix.existence_missing_or_duplicate")
            continue
        present = existence[0] is True
        required = KINDS if present else {"EXISTS"}
        if set(counts) != required or any(count != 1 for count in counts.values()):
            issues.append("matrix.fields_missing_duplicate_or_inconsistent")
        present_cells += int(present)
    complete = not issues
    values = sorted({r.value for r in observed if r.kind == "RADICALIZE"})
    numeric_valid = complete and present_cells > 0
    return {
        "rows": [asdict(row) for row in observed],
        "expected_tags": list(expected_tags),
        "expected_igs": list(groups),
        "expected_laws": list(laws),
        "expected_cells": len(expected),
        "observed_cells": len(cells),
        "present_cells": present_cells,
        "matrix_complete": complete,
        "numeric_interface_validated": numeric_valid,
        "radicalize_interface_validated": numeric_valid and values == [False, True],
        "radicalize_values": values,
        "issues": sorted(set(issues)),
        "country_identity_verified": False,
        "ai_veto_proven": False,
        "quality_improvement_proven": False,
        "scope": "Explicit country × interest-group type × law type, paired by country sample-N; predicted approval and radicalization are native getters, not final AI feasibility or civil-war probability.",
    }
