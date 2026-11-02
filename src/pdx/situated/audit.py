"""内核审计门面。"""

from __future__ import annotations

from pdx import config, decision_adapters

from . import domain_coverage, inventory, native_treatments, vanilla_inventory
from .compiler import audit, load_model
from .families import classify
from .receipts import AuditResult, CoverageRow, ReceiptStatus, StageReceipt, digest, status_for


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

    _policy, _extensions, generated = distribution.package_inputs()
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
