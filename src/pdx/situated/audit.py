"""内核审计门面。"""

from __future__ import annotations

from . import inventory, vanilla_inventory
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
    if scope_status != "complete" and coverage_status == "complete":
        coverage_status = "incomplete"
    return AuditResult(
        plan_version="31.4",
        status=coverage_status,
        pending=pending,
        blocked=blocked,
        unclassified=unclassified,
        rows=rows,
        receipts=receipts,
        scope_hash=surfaces.scope_hash,
        scope_status=scope_status,
    )
