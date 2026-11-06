"""Independent native arithmetic versus production typed ports and parsed PDX."""

from dataclasses import replace

import pytest

from pdx.decision_rules import FactReference, Predicate, Reader
from pdx.parser import parse_text
from pdx.situated import decision_ir, pdx_eval, ports

SOURCE = "mod/decisions/adapters.toml"


def fixture(path=()):
    a = Reader(
        "innovation",
        "country_innovation",
        "root",
        "weekly_innovation_points",
        "number",
        minimum=0,
        path=path,
    )
    c = Reader(
        "innovation_cap",
        "modifier:country_weekly_innovation_max_add",
        "root",
        "weekly_innovation_points",
        "number",
        path=path,
    )
    readers = {(SOURCE, r.key): r for r in (a, c)}
    data = {
        "schema": 1,
        "limits": {"nodes": 32, "depth": 8, "expanded_leaves": 32, "evaluation_cost": 128},
        "ports": {
            "below_cap": {
                "domain": "education",
                "entity": "root",
                "entity_kind": "country",
                "unit": "flag",
                "direction": "need",
                "refresh": "consumer",
                "unknown": "vanilla",
                "cost": 1,
                "reader_source": SOURCE,
                "reader_key": a.key,
                "reader": ports.reader_signature(a),
                "op": "<",
                "value_fact": c.key,
                "value_reader": ports.reader_signature(c),
            }
        },
        "uses": [
            {"source": SOURCE, "definition": "university", "port": "below_cap", "role": "need"}
        ],
    }
    actor = decision_ir.ContextBinding("root", "country", "actor", "fixture/native.txt", 1)
    writers = {
        (SOURCE, "university"): decision_ir.EvaluationContext(
            actor, evidence=("fixture/native.txt:1",)
        )
    }
    return data, readers, writers


def load(data=None, readers=None, writers=None, **kwargs):
    if data is None:
        data, readers, writers = fixture()
    return ports.from_data(
        data,
        readers=readers,
        writers=writers,
        source_hashes={SOURCE: "1" * 64},
        source_proofs=kwargs.get(
            "source_proofs",
            {
                (SOURCE, "innovation"): ("native-A-exact",),
                (SOURCE, "innovation_cap"): ("native-C-exact",),
            },
        ),
    )


@pytest.mark.parametrize(
    ("raw", "cap", "expected"),
    [
        (80, 100, True),
        (120, 100, False),
        (100, 100, False),
        (80, 0, False),
        (80, -5, False),
        (-2, 100, True),
    ],
)
def test_native_algebra_and_exact_rhs_unknown(raw, cap, expected):
    # This arithmetic is the independently proven native getter, not a production reader.
    actual = 0 if raw <= 0 else min(raw, max(cap, 0))
    graph = load()
    assert (
        graph.evaluate(
            "below_cap", {(SOURCE, "innovation"): actual, (SOURCE, "innovation_cap"): cap}
        )
        is expected
    )
    for missing in ("innovation", "innovation_cap"):
        values = {(SOURCE, "innovation"): actual, (SOURCE, "innovation_cap"): cap}
        values[(SOURCE, missing)] = None
        assert graph.evaluate("below_cap", values) is None


def test_both_original_identities_and_rhs_only_proof_drift():
    graph = load()
    origins = graph.origins("below_cap")
    assert len(origins) == 2
    assert {o.observation.original_unit for o in origins} == {"weekly_innovation_points"}
    assert all(o.observation.roles == ("actor",) for o in origins)
    assert all(
        o.observation.timing == "consumer" and o.observation.evaluation_cost == 1 for o in origins
    )
    assert "native-A-exact" in origins[0].observation.proof
    assert "native-C-exact" not in origins[0].observation.proof
    assert "native-C-exact" in origins[1].observation.proof
    changed = load(
        source_proofs={
            (SOURCE, "innovation"): ("native-A-exact",),
            (SOURCE, "innovation_cap"): ("changed-C",),
        }
    )
    assert origins[0].identity == changed.origins("below_cap")[0].identity
    assert origins[1].identity != changed.origins("below_cap")[1].identity
    assert dict(graph.expansions)["below_cap"] == 2
    assert dict(graph.costs)["below_cap"] == 2
    graph.assert_predicates(
        "below_cap",
        [
            Predicate(
                "innovation",
                "<",
                FactReference("innovation_cap", "ROOT.modifier:country_weekly_innovation_max_add"),
            )
        ],
        {r.key: r for r in fixture()[1].values()},
    )


@pytest.mark.parametrize("change", ["unit", "path", "scope", "kind", "signature", "alias"])
def test_relative_leaf_rejects_unit_object_and_signature_substitution(change):
    data, readers, writers = fixture()
    rhs = readers[(SOURCE, "innovation_cap")]
    if change in {"unit", "path", "scope", "kind"}:
        rhs = replace(
            rhs,
            **{
                change: {
                    "unit": "ratio",
                    "path": ("owner",),
                    "scope": "target_country",
                    "kind": "boolean",
                }[change]
            },
        )
        readers[(SOURCE, "innovation_cap")] = rhs
        data["ports"]["below_cap"]["value_reader"] = ports.reader_signature(rhs)
    elif change == "signature":
        data["ports"]["below_cap"]["value_reader"]["minimum"] = 1
    else:
        data["ports"]["below_cap"]["value_fact"] = "innovation"
    with pytest.raises(ValueError):
        load(data, readers, writers)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (80, 100, True),
        (100, 100, False),
        (0, -5, False),
        (None, 100, None),
        (80, None, None),
        (80, True, None),
    ],
)
def test_parsed_comparison_with_exact_colon_rhs(left, right, expected):
    graph = load()
    guard = graph.guard(SOURCE, "university", "below_cap")
    parsed = parse_text(guard.when_true)
    assert not parsed.errors
    root = {"country_innovation": left, "modifier:country_weekly_innovation_max_add": right}
    assert pdx_eval.condition(parsed.root, {"ROOT": root}) is expected
