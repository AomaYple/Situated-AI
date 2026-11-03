"""内核审计门面。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from pdx import config, decision_adapters
from pdx.model import Block
from pdx.parser import parse_text

from . import domain_coverage, inventory, native_treatments, vanilla_inventory
from .compiler import audit, load_model
from .families import classify
from .receipts import AuditResult, CoverageRow, ReceiptStatus, StageReceipt, digest, status_for

if TYPE_CHECKING:
    from collections.abc import Mapping


def _production_continuous_bindings(
    generated: Mapping[str, str | bytes],
) -> tuple[domain_coverage.ContinuousProgramBinding, ...]:
    """Read continuous semantics from the same actual package output being audited.

    No extension config is loaded and no writer is synthesized from a feature
    switch. The complete serialized writer must match its sole physical write.
    """
    from pdx import decisions  # noqa: PLC0415

    from .decision_ir import (  # noqa: PLC0415
        ConsumerIRBundle,
        ContextBinding,
        EvaluationContext,
        WriterDecisionIR,
    )
    from .support_program import DefenseReason, EconomicDifference, SupportProgram  # noqa: PLC0415

    source = "common/ai_strategies/00_default_strategy.txt"
    writer_id = "diplomatic_play_support_program"
    field = "diplomatic_play_support"

    def text(value: str | bytes) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value

    def canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def without_lines(value: object) -> object:
        if isinstance(value, dict):
            return {key: without_lines(item) for key, item in value.items() if key != "line"}
        if isinstance(value, list):
            return [without_lines(item) for item in value]
        return value

    def support_node(content: str):
        parsed = parse_text(content)
        strategies = parsed.root.all("ai_strategy_default")
        if parsed.errors or len(strategies) != 1 or not isinstance(strategies[0].value, Block):
            raise ValueError("支持程序生产策略无法精确解析")
        nodes = strategies[0].value.all(field)
        if len(nodes) != 1 or not isinstance(nodes[0].value, Block):
            raise ValueError("支持程序物理消费者不是唯一数值块")
        return nodes[0]

    try:
        metadata_text = text(generated.get(".metadata/metadata.json", "{}"))
        metadata = json.loads(metadata_text)
        bundle = metadata.get("situated_actions", {}).get("consumer_ir", {})
        rows = bundle.get("writers", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("连续程序writer列表无效")
        support_rows = [
            row
            for row in rows
            if row.get("kind") == "support_program"
            or row.get("writer_id") == writer_id
            or row.get("field") in {field, f"ai_strategy_default.{field}"}
        ]
        marked_sources = [
            name
            for name, value in generated.items()
            if name.endswith(".txt")
            and (f"# SITAI BEGIN {field}" in text(value) or f"# ACTION {writer_id}" in text(value))
        ]
        if not support_rows:
            if (
                marked_sources
                or bundle.get("support_program_writer_count", 0) != 0
                or field in bundle.get("field_owners", {})
            ):
                raise ValueError("支持程序存在输出或owner却缺少实际writer")
            return ()
        if len(support_rows) != 1 or marked_sources != [source]:
            raise ValueError("支持程序writer或物理来源缺失/重复")
        row = support_rows[0]
        raw = row["program"]
        if not isinstance(raw, dict) or not isinstance(raw["defense"], list):
            raise ValueError("支持程序完整语义缺失")
        market = None if raw["market"] is None else EconomicDifference(**raw["market"])
        program = SupportProgram(
            market=market,
            defense=tuple(DefenseReason(**reason) for reason in raw["defense"]),
            consumer_max_delta=raw["consumer_max_delta"],
            writer_id=raw["writer_id"],
            description=raw["description"],
        )
        if canonical(program.as_dict()) != canonical(raw):
            raise ValueError("支持程序序列化语义与有类型合同不一致")
        context = row["evaluation_context"]
        evaluation_context = EvaluationContext(
            actor_scope=ContextBinding(**context["actor_scope"]),
            targets=tuple(ContextBinding(**target) for target in context["targets"]),
            auxiliary_scopes=tuple(
                ContextBinding(**target) for target in context["auxiliary_scopes"]
            ),
            evidence=tuple(context["evidence"]),
            status=context["status"],
        )
        writer = WriterDecisionIR(
            **{
                name: row[name]
                for name in (
                    "writer_id",
                    "kind",
                    "source",
                    "definition",
                    "consumer_id",
                    "field",
                    "actor",
                    "target",
                    "operation",
                    "vanilla_tail",
                    "owner",
                )
            },
            evaluation_context=evaluation_context,
            program=program,
        )
        expected_writer = ConsumerIRBundle(1, (), (writer,)).as_dict()["writers"][0]
        if canonical(expected_writer) != canonical(row):
            raise ValueError("支持程序writer完整字段不一致")
        ids = [item["writer_id"] for item in rows]
        if (
            len(ids) != len(set(ids))
            or type(bundle["writer_count"]) is not int
            or bundle["writer_count"] != len(rows)
            or type(bundle["support_program_writer_count"]) is not int
            or bundle["support_program_writer_count"] != 1
            or bundle["field_owners"].get(field) != "situated_kernel"
            or bundle["source_field_owners"].get(f"mod/decisions/extensions.toml:{field}")
            != "situated_kernel"
            or metadata["default_field_owners"].get(field) != "situated_kernel"
        ):
            raise ValueError("支持程序数量或物理字段owner不一致")
        content = text(generated[source])
        pattern = re.compile(
            rf"^\t\t# SITAI BEGIN {field}\n(?P<body>.*?)^\t\t# SITAI END {field}\n",
            flags=re.MULTILINE | re.DOTALL,
        )
        blocks = list(pattern.finditer(content))
        if (
            len(blocks) != 1
            or content.count(f"# SITAI BEGIN {field}") != 1
            or content.count(f"# SITAI END {field}") != 1
            or content.count(f"# ACTION {writer_id}") != 1
            or blocks[0].group("body") != program.render()
        ):
            raise ValueError("支持程序实际overlay与完整语义不一致或重复")
        restored = pattern.sub("", content)
        if without_lines(asdict(support_node(restored))) != without_lines(
            asdict(support_node(decisions.BASELINE.read_text(encoding="utf-8")))
        ):
            raise ValueError("支持程序存在未登记写入或原版尾部漂移")
        binding = domain_coverage.ContinuousProgramBinding(
            writer=writer,
            native=domain_coverage.NativeConsumerBinding(source, "ai_strategy_default", field),
            unit="score",
            production_source=source,
            production_sha256=hashlib.sha256(content.encode()).hexdigest(),
            overlay_sha256=hashlib.sha256(blocks[0].group("body").encode()).hexdigest(),
            metadata_sha256=hashlib.sha256(metadata_text.encode()).hexdigest(),
        )
        problem = domain_coverage.continuous_writer_issue(binding)
        if problem is not None:
            raise ValueError(f"支持连续程序上下文或字段合同不一致：{problem}")
        return (binding,)
    except (KeyError, TypeError, AttributeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"支持连续程序生产证据校验失败：{exc}") from exc


def check() -> list[str]:
    model = load_model()
    problems = audit(model)
    problems.extend(
        f"生产行动实例缺少唯一 owner：{item.action_id}"
        for item in model.action_instances
        if not item.owner
    )
    return problems


def native_report() -> dict[str, object]:
    """Compare the full native inventory with freshly built production bytes.

    Unlike the legacy production inventory, this denominator does not come
    from our current rules. Native inheritance is a protection responsibility,
    never evidence of a newly implemented decision or completed architecture.
    All game/source verification failures propagate to the caller.
    """
    from pdx import distribution  # noqa: PLC0415

    from .architecture_receipts import source_snapshot  # noqa: PLC0415

    _policy, _extensions, generated = distribution.package_inputs(include_engineering_metadata=True)
    model = load_model()
    scope = vanilla_inventory.discover()
    sources = {
        source: (config.GAME / source).read_bytes()
        for source in scope.source_hashes
        if not source.startswith("@")
    }
    coverage = domain_coverage.native_coverage(
        scope,
        model.action_instances,
        explicit_consumers={
            item.action_id: domain_coverage.NativeConsumerBinding(
                "common/ai_strategies/00_default_strategy.txt",
                "ai_strategy_default",
                item.consumer_field,
            )
            for item in model.action_instances
            if item.kind == "action_card"
        },
        native_sources=sources,
        production_policies=dict(decision_adapters.load().policies),
        continuous_programs=_production_continuous_bindings(generated),
    )
    treatments = native_treatments.native_treatments(
        scope,
        sources,
        {
            name: text.encode("utf-8") if isinstance(text, str) else text
            for name, text in generated.items()
        },
        coverage=coverage,
        production_complete=True,
    )
    return {
        "schema": 1,
        "plan_version": "A2",
        "evidence_category": "static_check",
        "production_output_contract": {
            "mode": "engineering_package_inputs",
            "include_engineering_metadata": True,
            "hash_scope": "same_invocation_outputs_including_engineering_metadata",
            "standard_zip_manifest": False,
            "standard_package_difference": "metadata_json_is_full_engineering_metadata",
        },
        "source_snapshot_sha256": digest(source_snapshot(config.REPO)),
        "scope": scope.as_dict(),
        "native_coverage": coverage,
        "native_treatments": treatments,
        "business_complete": False,
        "limits": [
            "native protections and numeric mappings are separate responsibilities",
            "functional witnesses and stage exits remain independent requirements",
            "runtime AI behavior, balance and performance are not verified",
        ],
    }


def report() -> AuditResult:
    """重新计算当前范围的机器可判定覆盖报告。"""

    model = load_model()
    surfaces = inventory.discover()
    instance_owner = {
        f"action_instance:{item.action_id}": item.owner for item in model.action_instances
    }
    rows = tuple(
        CoverageRow(
            surface_id=item.surface_id,
            disposition=item.disposition_id,
            owner=(
                instance_owner.get(item.disposition_id, "situated_kernel")
                if item.kind == "legacy_rule"
                else "situated_kernel"
            ),
            evidence_ids=item.evidence_ids,
            source=item.source,
            status=item.status,
            family_id=classify(domain=item.domain, field=item.field, source=item.source),
            consumer_id=(
                item.definition
                if item.kind == "consumer_contract"
                else next(
                    (
                        instance.consumer_field
                        for instance in model.action_instances
                        if instance.action_id
                        == item.disposition_id.removeprefix("action_instance:")
                    ),
                    "",
                )
            ),
            evidence_state=item.evidence_state,
        )
        for item in surfaces.surfaces
    )
    pending = tuple(item.surface_id for item in surfaces.surfaces if item.status == "pending")
    blocked = tuple(item.surface_id for item in surfaces.surfaces if item.status == "blocked")
    unclassified = tuple(
        item.surface_id for item in surfaces.surfaces if item.status == "unclassified"
    )
    receipt_status: ReceiptStatus = (
        "blocked"
        if surfaces.parse_failures
        else "in_progress"
        if pending or blocked or unclassified
        else "verified"
    )
    receipts = (
        StageReceipt(
            step_id="K0.2-K0.4",
            status=receipt_status,
            input_hashes={**surfaces.source_hashes, "scope": surfaces.scope_hash},
            output_paths=("tools/out/ci/situated-inventory/surface-inventory.json",),
            evidence_ids=(surfaces.scope_hash, digest(model.contract()["action_instances"])),
            dependencies=("K0.1",),
            failures=surfaces.parse_failures,
        ),
    )
    try:
        vanilla_scope = vanilla_inventory.discover()
    except (OSError, ValueError):
        vanilla_scope = None
    native = (
        domain_coverage.native_coverage(
            vanilla_scope,
            model.action_instances,
            explicit_consumers={
                item.action_id: domain_coverage.NativeConsumerBinding(
                    "common/ai_strategies/00_default_strategy.txt",
                    "ai_strategy_default",
                    item.consumer_field,
                )
                for item in model.action_instances
                if item.kind == "action_card"
            },
            native_sources={
                source: (config.GAME / source).read_bytes()
                for source in vanilla_scope.source_hashes
                if not source.startswith("@")
            },
            production_policies=dict(decision_adapters.load().policies),
        )
        if vanilla_scope is not None
        else None
    )
    # D0 freezes the complete discovered range; implementation pending is an
    # explicit input to the later D4--D13 responsibilities and must remain
    # visible there.  Only unresolved scope identity or parse failure makes
    # the independent range itself incomplete.
    scope_status = (
        "complete"
        if vanilla_scope is not None
        and not vanilla_scope.unknown_scopes
        and not vanilla_scope.parse_failures
        else "incomplete"
        if vanilla_scope is not None
        else "unverified"
    )
    coverage_status = status_for(rows)
    if (
        scope_status != "complete" or native is None or not native["binding_complete"]
    ) and coverage_status == "complete":
        coverage_status = "incomplete"
    return AuditResult(
        plan_version="A2",
        status=coverage_status,
        pending=pending,
        blocked=blocked,
        unclassified=unclassified,
        rows=rows,
        receipts=receipts,
        scope_hash=surfaces.scope_hash,
        scope_status=scope_status,
        native_coverage=native,
    )
