"""可再生的规则参数、敏感性和资源审计。

本模块只读取生产 TOML，并复用 :func:`decision_rules.evaluate` 作为参考求值。
它证明静态规则合同和固定输入的边界，不证明游戏内 AI 行为或游戏速度。
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import time
import tomllib
import tracemalloc
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import country_parameters, decision_adapters, decision_rules

DEFAULT_OUTPUT = Path("tools/out/t-plan/parameter-report.md")


def _range(rule: decision_rules.Rule) -> dict[str, float]:
    if rule.operation == "multiply":
        return {"lower": 0.5, "upper": 1.5}
    if rule.operation == "add":
        return {"lower": -50.0, "upper": 50.0}
    raise ValueError(f"未知规则操作：{rule.operation}")


def _parameter_points(rule: decision_rules.Rule) -> tuple[float, float, float]:
    bounds = _range(rule)
    value = float(rule.value)
    if not math.isfinite(value) or not bounds["lower"] <= value <= bounds["upper"]:
        raise ValueError("规则值不在规则范围")
    return (bounds["lower"], value, bounds["upper"])


def _candidate_values(reader: decision_rules.Reader, literals: set[float]) -> list[object]:
    if reader.kind == "boolean":
        return [False, True]
    points = {0.0, -1.0, 1.0}
    for bound in (reader.minimum, reader.maximum):
        if bound is not None:
            points.add(float(bound))
    for value in literals:
        points.update(
            (
                value,
                math.nextafter(value, -math.inf),
                math.nextafter(value, math.inf),
                value - 1,
                value + 1,
            )
        )
    return [value for value in sorted(points) if reader.accepts(value)]


def _satisfies(condition: decision_rules.Predicate, values: dict[str, object]) -> bool:
    left = values[condition.fact]
    right = (
        values[condition.value.key]
        if isinstance(condition.value, decision_rules.FactReference)
        else condition.value
    )
    # Fixtures only contain values already accepted by their typed readers.
    if condition.op == "=":
        return left == right
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[
        condition.op
    ]


def _fixture(
    policy: decision_rules.RuleSet, rule: decision_rules.Rule
) -> tuple[dict[str, object], dict[str, list[object]]]:
    readers = {reader.key: reader for reader in policy.readers if reader.key in rule.input_keys()}
    if set(readers) != rule.input_keys() or not rule.conditions:
        raise ValueError("规则缺少有效输入读取器或条件")
    literals = {
        float(condition.value)
        for condition in rule.conditions
        if isinstance(condition.value, (int, float)) and not isinstance(condition.value, bool)
    }
    candidates = {
        key: _candidate_values(reader, literals) for key, reader in sorted(readers.items())
    }
    unary = [
        condition
        for condition in rule.conditions
        if not isinstance(condition.value, decision_rules.FactReference)
    ]
    domains = {
        key: [
            value
            for value in choices
            if all(
                _satisfies(condition, {key: value}) for condition in unary if condition.fact == key
            )
        ]
        for key, choices in candidates.items()
    }
    order = sorted(domains, key=lambda key: (len(domains[key]), key))
    values: dict[str, object] = {}

    def solve(index: int) -> bool:
        if index == len(order):
            return True
        key = order[index]
        for value in domains[key]:
            values[key] = value
            relevant = [
                condition
                for condition in rule.conditions
                if condition.fact in values
                and (
                    not isinstance(condition.value, decision_rules.FactReference)
                    or condition.value.key in values
                )
            ]
            if all(_satisfies(condition, values) for condition in relevant) and solve(index + 1):
                return True
        values.pop(key, None)
        return False

    if not solve(0):
        raise ValueError(f"无法构造满足规则的固定输入：{rule.id}")
    return dict(sorted(values.items())), candidates


def audit_rule(
    policy: decision_rules.RuleSet, rule: decision_rules.Rule, *, consumer: str
) -> dict[str, Any]:
    """逐规则使用隔离 RuleSet，验证三点参数和所有输入回退。"""
    if not policy.rules:
        raise ValueError("规则集不能为空")
    if rule not in policy.rules:
        raise ValueError("规则不在规则集")
    points = _parameter_points(rule)
    satisfying, candidates = _fixture(policy, rule)
    isolated = replace(policy, rules=(rule,), enabled_domains=frozenset({rule.domain}))
    field = ".".join(rule.field)
    expected = {field: (rule.id, rule.value)}

    def evaluate(
        values: dict[str, object], *, is_ai: bool = True, disabled: bool = False
    ) -> dict[str, tuple[str, float]]:
        return decision_rules.evaluate(
            isolated, values, is_ai=is_ai, enabled_domains=frozenset() if disabled else None
        )

    if evaluate(satisfying) != expected:
        raise ValueError(f"满足输入没有命中唯一规则：{rule.id}")
    violating = None
    for key, choices in candidates.items():
        for value in choices:
            trial = {**satisfying, key: value}
            if not all(_satisfies(condition, trial) for condition in rule.conditions):
                violating = trial
                break
        if violating is not None:
            break
    if violating is None:
        raise ValueError(f"无法构造违反规则的合法输入：{rule.id}")
    cases: dict[str, tuple[dict[str, object], bool, bool]] = {
        "satisfying": (satisfying, True, False),
        "violating": (violating, True, False),
        "unknown": ({**satisfying, next(iter(satisfying)): None}, True, False),
        "invalid": ({**satisfying, next(iter(satisfying)): "invalid"}, True, False),
        "empty": ({}, True, False),
        "player": (satisfying, False, False),
        "disabled": (satisfying, True, True),
    }
    checks = {}
    for name, (values, is_ai, disabled) in cases.items():
        result = evaluate(values, is_ai=is_ai, disabled=disabled)
        if result != (expected if name == "satisfying" else {}):
            raise ValueError(f"规则回退失败：{rule.id}/{name}")
        checks[name] = {"inputs": values, "matched": bool(result), "result": result}
    input_fallbacks = []
    for key in satisfying:
        for label, bad in (("unknown", None), ("invalid", "invalid"), ("nonfinite", float("nan"))):
            result = evaluate({**satisfying, key: bad})
            if result:
                raise ValueError(f"输入回退失败：{rule.id}/{key}/{label}")
            input_fallbacks.append({"fact": key, "case": label, "matched": False})
    # A matching lower priority candidate must never be accumulated with this rule.
    lower = replace(rule, id=rule.id + "_audit_lower", priority=rule.priority - 1)
    arbitration = replace(isolated, rules=(lower, rule))
    if decision_rules.evaluate(arbitration, satisfying, is_ai=True) != expected:
        raise ValueError(f"首个匹配仲裁失败：{rule.id}")
    sensitivity = []
    for label, point in zip(("lower", "base", "upper"), points, strict=True):
        candidate = replace(rule, value=point)
        candidate_policy = replace(isolated, rules=(candidate,))
        result = decision_rules.evaluate(candidate_policy, satisfying, is_ai=True)
        if result != {field: (rule.id, point)}:
            raise ValueError(f"参数敏感性求值失败：{rule.id}/{label}")
        fallback_results = {
            name: decision_rules.evaluate(
                candidate_policy,
                case_values,
                is_ai=is_ai,
                enabled_domains=frozenset() if disabled else None,
            )
            for name, (case_values, is_ai, disabled) in cases.items()
            if name != "satisfying"
        }
        if any(fallback_results.values()):
            raise ValueError(f"参数敏感性回退失败：{rule.id}/{label}")
        sensitivity.append(
            {
                "point": label,
                "value": point,
                "bounded": True,
                "matched": True,
                "adjustment": result[field][1],
                "fallbacks": fallback_results,
            }
        )
    return {
        "consumer": consumer,
        "id": rule.id,
        "field": field,
        "domain": rule.domain,
        "priority": rule.priority,
        "operation": rule.operation,
        "value": rule.value,
        "range": _range(rule),
        "sensitivity": sensitivity,
        "conditions": [
            {
                "fact": condition.fact,
                "op": condition.op,
                "value": {"fact": condition.value.key}
                if isinstance(condition.value, decision_rules.FactReference)
                else condition.value,
            }
            for condition in rule.conditions
        ],
        "why": rule.why,
        "counterexample": rule.counterexample,
        "checks": checks,
        "input_fallbacks": input_fallbacks,
        "arbitration": "one_matching_adjustment_no_accumulation",
        "eligibility_costs_execution": "not modeled; retained_vanilla_by_production_consumer_contract",
    }


def _build_static() -> dict[str, Any]:
    information = decision_rules.load()
    adapters = decision_adapters.load()
    rules: list[dict[str, Any]] = []
    declared: dict[str, int] = {}
    referenced: dict[str, int] = {}
    signature_uses: dict[str, list[dict[str, Any]]] = defaultdict(list)
    consumers: set[str] = set()
    policies: list[tuple[str, decision_rules.RuleSet]] = [
        ("information_rules", information),
        *adapters.policies,
    ]
    for consumer, policy in policies:
        declared[consumer] = len(policy.readers)
        used = {key for rule in policy.rules for key in rule.input_keys()}
        referenced[consumer] = len(used)
        for reader in policy.readers:
            signature = json.dumps(
                {
                    "engine": reader.engine,
                    "scope": reader.scope,
                    "actor_path": list(policy.actor_path),
                    "unit": reader.unit,
                    "kind": reader.kind,
                    "argument": reader.argument,
                    "minimum": reader.minimum,
                    "maximum": reader.maximum,
                    "path": list(reader.path),
                    "value_field": reader.value_field,
                    "parameters": dict(reader.parameters),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            usages = [rule for rule in policy.rules if reader.key in rule.input_keys()]
            signature_uses[signature].append(
                {
                    "consumer": consumer,
                    "key": reader.key,
                    "rules": sorted(rule.id for rule in usages),
                    "fields": sorted({".".join(rule.field) for rule in usages}),
                }
            )
        if consumer != "information_rules":
            consumers.add(consumer)
        rules.extend(audit_rule(policy, rule, consumer=consumer) for rule in policy.rules)
    source_declared = {
        "information_rules": len(
            tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))["readers"]
        ),
        "consumer_adapters": len(
            tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))["readers"]
        ),
    }
    by_module: dict[str, set[str]] = {"information_rules": set(), "consumer_adapters": set()}
    for consumer, policy in policies:
        module = "information_rules" if consumer == "information_rules" else "consumer_adapters"
        by_module[module].update(key for rule in policy.rules for key in rule.input_keys())
    reader_signatures = [
        {
            "signature": json.loads(signature),
            "declarations": uses,
            "declaration_count": len(uses),
            "rule_references": sum(len(item["rules"]) for item in uses),
            "consumer_count": len({str(item["consumer"]) for item in uses}),
        }
        for signature, uses in sorted(signature_uses.items())
    ]
    return {
        "schema": 1,
        "evidence": "static_generated_rule_contract_and_fixed_input_reference_evaluation",
        "rules": rules,
        "country_coordination": country_parameters.audit(),
        "consumers": sorted(consumers),
        "field_count": sum(len(policy.groups()) for _, policy in policies),
        "source_fingerprints": {
            "information_rules": information.source_sha256,
            "consumer_adapters": adapters.source_sha256,
            "vanilla_consumers": dict(adapters.sources),
        },
        "reader_usage": {
            "declared": sum(source_declared.values()),
            "referenced": sum(len(keys) for keys in by_module.values()),
            "by_module": {
                name: {"declared": source_declared[name], "referenced": len(by_module[name])}
                for name in by_module
            },
            "per_consumer_declaration_slots": sum(declared.values()),
            "per_consumer_referenced_slots": sum(referenced.values()),
            "by_consumer": {
                name: {"declared": declared[name], "referenced": referenced[name]}
                for name in sorted(declared)
            },
            "unique_signatures": len(signature_uses),
            "duplicate_signature_count": sum(declared.values()) - len(signature_uses),
            "signatures": reader_signatures,
            "duplicate_reads": [row for row in reader_signatures if row["rule_references"] > 1],
            "cost_limits": "reference counts are static potential evaluations; no runtime cache or engine cost measurement",
            "vanilla_catalog": {
                "size": None,
                "meaning": "not counted; discovery scale is separate from production usage",
            },
        },
        "resource_measurement": {"static_evidence_only": True, "measured": False},
        "verification": {
            "rule_count": len(rules),
            "sensitivity_evaluations": sum(len(row["sensitivity"]) for row in rules),
            "input_fallback_evaluations": sum(len(row["input_fallbacks"]) for row in rules),
            "execution": "serial_fixed_input_reference_evaluate",
            "passed": True,
        },
        "limits": [
            "不证明游戏内 AI 行为",
            "不证明游戏速度或内存",
            "不改变原版资格、成本、随机性和玩家路径",
        ],
    }


def build(*, measure: bool = True) -> dict[str, Any]:
    if not measure:
        return _build_static()
    if tracemalloc.is_tracing():
        raise ValueError("资源审计要求独占 tracemalloc；不能覆盖调用方测量")
    tracemalloc.start()
    started = time.perf_counter()
    try:
        report = _build_static()
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    report["resource_measurement"] = {
        "static_evidence_only": True,
        "measured": True,
        "serial": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "wall_seconds": elapsed,
        "peak_tracemalloc_bytes": peak,
    }
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = report["rules"]
    lines = [
        "# 参数注册与固定输入敏感性报告",
        "",
        "证据：`static_generated_rule_contract_and_fixed_input_reference_evaluation`。本报告不证明游戏内 AI 行为、游戏速度或内存。",
        "静态资源标记：`static_evidence_only = true`；测量值只表示本机、串行、生成期成本。",
        "",
        f"规则数：{len(rows)}；消费者数：{len(report['consumers'])}；声明读取器：{report['reader_usage']['declared']}；实际引用读取器：{report['reader_usage']['referenced']}。",
        "",
        "资源测量：`" + json.dumps(report["resource_measurement"], ensure_ascii=False) + "`。",
        "",
        "固定输入验证：`" + json.dumps(report["verification"], ensure_ascii=False) + "`。",
        "",
        "## 读取器口径",
        "",
        json.dumps(report["reader_usage"], ensure_ascii=False, indent=2),
        "",
        "## 国家路线、预算和生命周期参数",
        "",
        json.dumps(report["country_coordination"], ensure_ascii=False, indent=2),
        "",
        "## 规则注册样例（完整数据见 JSON/API）",
        "",
        "| consumer | id | field | domain | operation | value | range | conditions | why | counterexample |",
        "|---|---|---|---|---|---:|---|---|---|---|",
    ]

    def markdown_row(row: dict[str, Any]) -> str:
        why = str(row["why"]).replace("|", "\\|")
        counterexample = str(row["counterexample"]).replace("|", "\\|")
        conditions = json.dumps(row["conditions"], ensure_ascii=False, separators=(",", ":"))
        return f"| {row['consumer']} | {row['id']} | {row['field']} | {row['domain']} | {row['operation']} | {row['value']} | {row['range']['lower']}..{row['range']['upper']} | {conditions} | {why} | {counterexample} |"

    lines.extend(markdown_row(row) for row in rows)
    lines.extend(["", "## 限制", "", *[f"- {item}" for item in report["limits"]]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成规则参数与敏感性审计")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = build()
    output = args.out
    if output.suffix.lower() == ".json":
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    else:
        write_report(output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
