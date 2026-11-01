"""D9 联合链严格来源绑定与真实条件追踪。"""

from dataclasses import replace
from typing import cast

import pytest

from pdx.situated import joint_chain_contract

pytestmark = pytest.mark.unit


def test_仅绑定已有生产来源和规则且字段一致():
    rows = joint_chain_contract.build()
    assert len(rows) == 6
    assert {(row.chain_id, row.role) for row in rows} == {
        ("LJ01", "upstream"),
        ("LJ01", "downstream"),
        ("LJ05", "fiscal"),
        ("LJ05", "fiscal_recovery"),
        ("LJ11", "war_recovery"),
        ("LJ11", "social_recovery"),
    }
    assert all(row.field and row.rule_id and row.condition_fingerprint for row in rows)
    assert all(row.status in {"observed", "gap"} for row in rows)


def test_条件指纹和事实集合来自真实规则():
    rows = joint_chain_contract.build()
    assert all(row.condition_facts for row in rows)
    assert all(len(row.condition_fingerprint) == 64 for row in rows)
    assert any(row.bridge_facts for row in rows)
    joint_chain_contract.validate(rows)


def test_指纹漂移或来源规则变更会拒绝():
    rows = joint_chain_contract.build()
    drifted = replace(rows[0], condition_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="指纹"):
        joint_chain_contract.validate((drifted, *rows[1:]))


def test_合同明确只提供静态证据不声称行为完成():
    contract = joint_chain_contract.contract()
    assert contract["status"] == "observed_static_only"
    assert contract["count"] == 6
    bindings = cast("list[dict[str, object]]", contract["bindings"])
    assert all(item["status"] in {"observed", "gap"} for item in bindings)


def test_链绑定不创建第二套规则():
    rows = joint_chain_contract.build()
    assert {row.operation for row in rows} <= {"add", "multiply"}
    assert all("__" not in row.rule_id for row in rows)
