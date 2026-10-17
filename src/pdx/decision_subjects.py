"""宗主国与属国关系模块。"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "mod" / "decisions" / "subjects.toml"


@dataclass(frozen=True, slots=True)
class SubjectsPolicy:
    enabled: bool = False
    protected_bonus: float = 10.0
    autonomy_bonus: float = 5.0
    source_sha256: str = ""


def load(source: Path = SOURCE) -> SubjectsPolicy:
    raw = source.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"宗属模块数据源无效：{source}") from exc
    if set(data) != {"schema_version", "subjects"} or data.get("schema_version") != 1:
        raise ValueError("宗属模块 schema 无效")
    values = data["subjects"]
    expected = {"enabled", "protected_bonus", "autonomy_bonus", "why"}
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError("宗属模块含缺失或未知字段")
    if (
        type(values["enabled"]) is not bool
        or not isinstance(values["why"], str)
        or not values["why"].strip()
    ):
        raise ValueError("宗属模块开关和依据无效")
    numbers = (values["protected_bonus"], values["autonomy_bonus"])
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in numbers
    ):
        raise ValueError("宗属模块参数必须是有限数值")
    if not 0 <= values["protected_bonus"] <= 25 or not 0 <= values["autonomy_bonus"] <= 25:
        raise ValueError("宗属模块参数超出保守范围")
    return SubjectsPolicy(
        values["enabled"],
        float(values["protected_bonus"]),
        float(values["autonomy_bonus"]),
        hashlib.sha256(raw).hexdigest(),
    )


def subject_value_delta(
    *, already_subject: bool | None, protected: bool | None, policy: SubjectsPolicy
) -> float:
    if not policy.enabled or already_subject is None or protected is None:
        return 0.0
    if not isinstance(already_subject, bool) or not isinstance(protected, bool):
        raise TypeError("宗属输入必须是布尔值")
    return (policy.protected_bonus if protected else 0.0) + (
        policy.autonomy_bonus if already_subject else 0.0
    )


def triggers(policy: SubjectsPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return """# 由 pdx.decision_subjects 生成；不创造宗属资格或强制独立。
sitai_subject_protected = {
    is_ai = yes
    is_subject_of = scope:target_country
    scope:target_country = { is_at_war = no }
}
sitai_subject_overlord_protected = {
    is_ai = yes
    scope:overlord = { is_at_war = no }
    is_subject_of = scope:overlord
}
"""


def subject_addition(policy: SubjectsPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return f"""\t\t# SITAI SUBJECTS BEGIN
\t\tif = {{ limit = {{ ROOT ?= {{ is_ai = yes }} sitai_subject_protected = yes }} add = {policy.protected_bonus:g} }}
\t\tif = {{ limit = {{ ROOT ?= {{ is_ai = yes }} scope:target_country = {{ is_subject_of = root }} }} add = {policy.autonomy_bonus:g} }}
\t\t# SITAI SUBJECTS END
"""


def become_subject_addition(policy: SubjectsPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return f"""\t\t# SITAI SUBJECTS BEGIN
\t\tif = {{ limit = {{ ROOT ?= {{ is_ai = yes }} sitai_subject_overlord_protected = yes }} add = {policy.protected_bonus:g} }}
\t\t# SITAI SUBJECTS END
"""
