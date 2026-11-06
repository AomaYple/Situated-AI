"""The combined graph retains exact explicit consumer identities."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pdx.situated.consumer_port_graph import combine
from pdx.situated.ports import PortUse


def graph(port_id, use):
    node = SimpleNamespace(id=port_id, dependencies=())
    return SimpleNamespace(
        ports=(node,),
        uses=(use,),
        topological=(port_id,),
        _index=SimpleNamespace(closures={port_id: (port_id,)}),
        node=lambda _key: node,
        origins=lambda _key: (),
    )


def test_combined_graph_exposes_and_validates_exact_explicit_uses():
    explicit_use = PortUse("a", "construction", "p1", "need", selector=("root",))
    batch_use = PortUse("b", "industry", "p2", "capacity")
    explicit = graph("p1", explicit_use)
    other = graph("p2", batch_use)
    batch = SimpleNamespace(
        partitions=(("industry", other),),
        origin_pool=(),
        ports_count=1,
        uses_count=1,
        by_port={"p2": other},
    )

    combined = combine(explicit, batch, rules_by_writer={}, readers_by_source={})

    assert combined.explicit_uses == (explicit_use,)
    assert combined.uses == (explicit_use, batch_use)
    assert combined.metrics["explicit_uses"] == 1
    with pytest.raises(ValueError, match="身份或顺序漂移"):
        replace(combined, explicit_uses=(batch_use,))
    with pytest.raises(ValueError, match="身份或顺序漂移"):
        replace(combined, explicit_uses=(replace(explicit_use, selector=("target",)),))
    with pytest.raises(ValueError, match="身份或顺序漂移"):
        replace(combined, metrics={**combined.metrics, "explicit_uses": 2})
