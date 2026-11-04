"""Small independent member-world regressions; no full model or generated fixtures."""

from dataclasses import replace

import pytest
import test_decision_adapters as adapters
import test_situated_writer_pdx_oracle as writer

from pdx import decision_rules
from pdx.parser import parse_text
from pdx.situated import pdx_eval

pytestmark = pytest.mark.unit


def _reader(tier):
    return decision_rules.Reader(
        tier,
        "any_scope_building",
        "root",
        "boolean",
        "boolean",
        parameters=(("company_query", "trade_business_pressure"), ("tier", tier)),
    )


def _member(*, kind="building_trade_center", level=1, profit=-1, cash=0):
    return {
        "is_building_type": {
            (("argument", "building_trade_center"),): kind == "building_trade_center"
        },
        "level": level,
        "weekly_profit": profit,
        "cash_reserves_ratio": cash,
    }


@pytest.mark.parametrize("reference", [writer._query_reference, adapters._adapter_query_reference])
@pytest.mark.parametrize(
    ("members", "base", "strong"),
    [
        (None, None, None),
        ([], False, False),
        ([_member()], True, True),
        ([_member(cash=0.25)], True, False),
        ([_member(cash=0.5)], True, False),
        ([_member(cash=None)], True, None),
        ([_member(profit=0)], False, False),
        ([_member(level=0, profit=None)], False, False),
        ([_member(kind="building_port", profit=None)], False, False),
        ([_member(profit=None)], None, None),
        ([_member(cash=0.5), _member(profit=1)], True, False),
        ([_member(profit=None), _member()], True, True),
    ],
)
def test_trade_pressure_references_use_one_member_and_three_valued_existence(
    reference, members, base, strong
):
    observations = {"any_scope_building": members}
    assert reference(_reader("base"), observations) is base
    assert reference(_reader("strong"), observations) is strong
    for tier, expected in (("base", base), ("strong", strong)):
        expression = parse_text(
            "any_scope_building = { is_building_type = building_trade_center "
            "level >= 1 weekly_profit < 0 "
            + ("cash_reserves_ratio < 0.25 " if tier == "strong" else "")
            + "}"
        ).root
        assert pdx_eval.condition(expression, observations) is expected


@pytest.mark.parametrize(
    ("requested", "base", "strong"),
    [
        ({"base": False, "strong": False}, False, False),
        ({"base": True}, True, False),
        ({"base": False, "strong": True}, True, True),
        ({"base": None}, None, None),
    ],
)
def test_trade_pressure_witnesses_recompute_related_queries(requested, base, strong):
    policy = replace(writer._collection_test_policy(), readers=(_reader("base"), _reader("strong")))
    values = writer._observed_values(writer._ReaderIndex.build(policy), requested)
    assert values["base"] is base
    assert values["strong"] is strong
    if base:
        building = values.collections["any_scope_building"][0]
        assert building is values.collections["any_scope_state"][0]["any_scope_building"][0]
        assert building["weekly_profit"] < 0


@pytest.mark.parametrize("technology", ["dialectics", "analytical_philosophy"])
def test_writer_knowledge_ready_witnesses_preserve_paper_observations(technology):
    reader = replace(
        _reader("knowledge"),
        parameters=(
            ("purpose", "knowledge_ready"),
            ("technology", technology),
            ("technology_query", "technology_use"),
        ),
    )
    policy = replace(writer._collection_test_policy(), readers=(reader,))
    values = writer._observed_values(writer._ReaderIndex.build(policy), {"knowledge": True})
    for reference in (writer._query_reference, adapters._adapter_query_reference):
        assert reference(reader, values.collections, values.root_facts) is True
    paper = values.root_facts["market"]["mg:paper"]
    for price, delta, expected in ((0.25, 0, True), (0.26, 0, False), (0.1, -1, False)):
        paper.update(market_goods_pricier=price, market_goods_delta=delta)
        for reference in (writer._query_reference, adapters._adapter_query_reference):
            assert reference(reader, values.collections, values.root_facts) is expected
    values.root_facts["market"].pop("mg:paper")
    for reference in (writer._query_reference, adapters._adapter_query_reference):
        assert reference(reader, values.collections, values.root_facts) is None
