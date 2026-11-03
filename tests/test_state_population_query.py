"""State population parameters retain target identity and three-valued semantics."""

import pytest

from pdx.parser import parse_text
from pdx.situated import pdx_eval


@pytest.mark.parametrize(
    ("observed", "expected"), [(None, None), (0, True), (0.019, True), (0.02, False)]
)
def test_state_peasant_share_uses_exact_target_value_parameters(observed, expected):
    block = parse_text("pop_type_percent_state = { target = pop_type:peasants value < 0.02 }").root
    assert (
        pdx_eval.condition(
            block,
            {
                "pop_type_percent_state": {
                    (("target", "pop_type:peasants"),): observed,
                    (("target", "pop_type:slaves"),): 0.01,
                },
                "pop_type_percent_country": {(("pop_type", "peasants"),): 0},
            },
        )
        is expected
    )


def test_other_population_or_country_observations_cannot_supply_a_state_share():
    block = parse_text("pop_type_percent_state = { target = pop_type:peasants value < 0.02 }").root
    assert (
        pdx_eval.condition(block, {"pop_type_percent_state": {(("target", "pop_type:slaves"),): 0}})
        is None
    )


@pytest.mark.parametrize(
    "query",
    [
        "pop_type_percent_state = { pop_type = peasants percent < .02 }",
        "pop_type_percent_state = { target = pop_type:peasants percent < .02 }",
        "pop_type_percent_state = { target = pop_type:peasants }",
        "pop_type_percent_state = pop_type:peasants",
    ],
)
def test_country_shaped_or_incomplete_state_queries_fail_closed(query):
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(parse_text(query).root, {})
