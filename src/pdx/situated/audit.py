"""内核审计门面。"""

from __future__ import annotations

from . import inventory
from .compiler import audit, load_model
from .families import classify
from .receipts import AuditResult, CoverageRow, StageReceipt, digest, status_for


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
    rows = tuple(
        CoverageRow(
            surface_id=item.surface_id,
            disposition=item.disposition_id,
            owner="situated_kernel",
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
    receipts = (
        StageReceipt(
            step_id="K0.2-K0.4",
            status="blocked" if surfaces.parse_failures else "verified",
            input_hashes={**surfaces.source_hashes, "scope": surfaces.scope_hash},
            output_paths=("tools/out/ci/situated-inventory/surface-inventory.json",),
            evidence_ids=(surfaces.scope_hash, digest(model.contract()["action_instances"])),
            dependencies=("K0.1",),
            failures=surfaces.parse_failures,
        ),
    )
    pending = tuple(item.surface_id for item in surfaces.surfaces if item.status == "pending")
    blocked = tuple(item.surface_id for item in surfaces.surfaces if item.status == "blocked")
    unclassified = tuple(
        item.surface_id for item in surfaces.surfaces if item.status == "unclassified"
    )
    return AuditResult(
        plan_version="30.0",
        status=status_for(rows),
        pending=pending,
        blocked=blocked,
        unclassified=unclassified,
        rows=rows,
        receipts=receipts,
        scope_hash=surfaces.scope_hash,
    )
