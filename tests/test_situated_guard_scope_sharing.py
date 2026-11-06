"""Structural and truth checks for root-limited scope sharing."""

from dataclasses import replace
from typing import Any

import pytest

from pdx.decision_rules import Reader
from pdx.parser import parse_text
from pdx.situated import pdx_eval, ports

LEGACY = {
    ("not", "root", (), False): (
        "OR = { AND = { exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } } AND = { exists = ROOT ROOT = { income >= 0 NOT = { income > 0 } } } }",
        "AND = { exists = ROOT ROOT = { loans >= 0 loans > 0 } exists = ROOT ROOT = { income >= 0 income > 0 } }",
    ),
    ("any", "root", (), False): (
        "OR = { AND = { AND = { exists = ROOT ROOT = { loans >= 0 loans > 0 } exists = ROOT ROOT = { income >= 0 income > 0 } } } AND = { exists = ROOT ROOT = { loans >= 0 loans > 0 } } }",
        "AND = { OR = { AND = { exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } } AND = { exists = ROOT ROOT = { income >= 0 NOT = { income > 0 } } } } exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } }",
    ),
    ("all", "root", (), False): (
        "AND = { AND = { exists = ROOT ROOT = { loans >= 0 loans > 0 } exists = ROOT ROOT = { income >= 0 income > 0 } } exists = ROOT ROOT = { loans >= 0 loans > 0 } }",
        "OR = { AND = { OR = { AND = { exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } } AND = { exists = ROOT ROOT = { income >= 0 NOT = { income > 0 } } } } } AND = { exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } } }",
    ),
    (None, "root", (), False): (
        "AND = { exists = ROOT ROOT = { loans >= 0 loans > 0 } exists = ROOT ROOT = { income >= 0 income > 0 } }",
        "OR = { AND = { exists = ROOT ROOT = { loans >= 0 NOT = { loans > 0 } } } AND = { exists = ROOT ROOT = { income >= 0 NOT = { income > 0 } } } }",
    ),
    (None, "root", ("owner",), False): (
        "AND = { exists = ROOT ROOT = { exists = owner owner = { loans >= 0 loans > 0 } } exists = ROOT ROOT = { exists = owner owner = { income >= 0 income > 0 } } }",
        "OR = { AND = { exists = ROOT ROOT = { exists = owner owner = { loans >= 0 NOT = { loans > 0 } } } } AND = { exists = ROOT ROOT = { exists = owner owner = { income >= 0 NOT = { income > 0 } } } } }",
    ),
    (None, "root", ("owner", "market"), False): (
        "AND = { exists = ROOT ROOT = { exists = owner owner = { exists = market market = { loans >= 0 loans > 0 } } } exists = ROOT ROOT = { exists = owner owner = { exists = market market = { income >= 0 income > 0 } } } }",
        "OR = { AND = { exists = ROOT ROOT = { exists = owner owner = { exists = market market = { loans >= 0 NOT = { loans > 0 } } } } } AND = { exists = ROOT ROOT = { exists = owner owner = { exists = market market = { income >= 0 NOT = { income > 0 } } } } } }",
    ),
    (None, "target_country", (), False): (
        "AND = { exists = scope:target_country scope:target_country = { loans >= 0 loans > 0 } exists = scope:target_country scope:target_country = { income >= 0 income > 0 } }",
        "OR = { AND = { exists = scope:target_country scope:target_country = { loans >= 0 NOT = { loans > 0 } } } AND = { exists = scope:target_country scope:target_country = { income >= 0 NOT = { income > 0 } } } }",
    ),
    (None, "root", (), True): (
        'AND = { exists = ROOT ROOT = { income >= 0 } exists = ROOT ROOT = { loans >= 0 loans > "ROOT.income" } exists = ROOT ROOT = { income >= 0 income > 0 } }',
        'OR = { AND = { exists = ROOT ROOT = { income >= 0 } exists = ROOT ROOT = { loans >= 0 NOT = { loans > "ROOT.income" } } } AND = { exists = ROOT ROOT = { income >= 0 NOT = { income > 0 } } } }',
    ),
}


def original(g, key):
    node = g.node(key)
    parent = node.mode if key == "parent" else None
    reader = g.node("a").reader
    return LEGACY[(parent, reader.scope, reader.path, g.node("a").reference_reader is not None)]


def graph(*, parent=None, scope="root", path=(), rhs=False):
    a = Reader("a", "loans", scope, "currency", "number", minimum=0, path=path)
    b = Reader("b", "income", scope, "currency", "number", minimum=0, path=path)
    rows = [
        ports.Port(
            "a",
            "fixture",
            "root",
            "country",
            "condition",
            "vanilla",
            1,
            "leaf",
            reader=a,
            op=">",
            expected=0,
        ),
        ports.Port(
            "b",
            "fixture",
            "root",
            "country",
            "condition",
            "vanilla",
            1,
            "leaf",
            reader=b,
            op=">",
            expected=0,
        ),
        ports.Port(
            "both",
            "fixture",
            "root",
            "country",
            "condition",
            "vanilla",
            1,
            "all",
            dependencies=("a", "b"),
        ),
    ]
    if rhs:
        rows[0] = replace(rows[0], reference_reader=b)
    if parent:
        rows.append(
            ports.Port(
                "parent",
                "fixture",
                "root",
                "country",
                "condition",
                "vanilla",
                1,
                parent,
                dependencies=("both",) if parent == "not" else ("both", "a"),
            )
        )
    ids = tuple(x.id for x in rows)
    return ports.PortGraph(
        tuple(rows),
        (),
        ids,
        tuple((k, ()) for k in ids),
        tuple((k, 1) for k in ids),
        tuple((k, 1) for k in ids),
    )


@pytest.mark.parametrize("parent", ["not", "any", "all"])
def test_nested_all_never_changes_either_parent_branch(parent):
    g = graph(parent=parent)
    assert original(g, "parent") == g._render_guard("parent")


@pytest.mark.parametrize(
    ("scope", "path"),
    [("root", ()), ("root", ("owner",)), ("root", ("owner", "market")), ("target_country", ())],
)
@pytest.mark.parametrize("values", [(1, 1), (0, 1), (-1, 1), (None, 1), (1, None)])
def test_shared_prefix_keeps_actual_pdx_three_value_result(scope, path, values):
    g = graph(scope=scope, path=path)
    old = original(g, "both")
    new = g._render_guard("both")
    assert old[1] == new[1]
    anchor = "ROOT" if scope == "root" else f"scope:{scope}"
    for absent in ("present", "missing", "null", "null_path"):
        world: dict[str, Any] = {"ROOT": {"loans": 999, "income": 999}, anchor: {}}
        node = world[anchor]
        for key in path:
            node = node.setdefault(key, {})
        node.update(loans=values[0], income=values[1])
        if absent == "missing":
            world.pop(anchor, None)
        if absent == "null":
            world[anchor] = None
        if absent == "null_path" and path:
            world[anchor][path[0]] = None
        assert pdx_eval.condition(parse_text(old[0]).root, world) is pdx_eval.condition(
            parse_text(new[0]).root, world
        )


@pytest.mark.parametrize(
    ("scope", "path", "rhs"), [("root", (), True), ("article_input_market_goods", (), False)]
)
def test_reference_rhs_and_article_alias_keep_original_pair(scope, path, rhs):
    g = graph(scope=scope, path=path, rhs=rhs)
    if scope == "article_input_market_goods":
        # Alias renderer rejects nonexact signatures equally; prove that path is excluded before rendering.
        assert g._conjunctive_leaf_guard(g.node("both")) is None
    else:
        assert original(g, "both") == g._render_guard("both")
