"""Complete speech-law family: actual agendas and native authority tradeoffs."""

from __future__ import annotations

import pytest
from test_x1_governance_transitions import build_focused, witness

from pdx.model import Block, Scalar
from pdx.parser import parse_text

pytestmark = pytest.mark.integration
SOURCE = "common/laws/02_free_speech.txt"


@pytest.fixture(scope="module")
def focused():
    return build_focused()


AUTHORITIES = {
    "law_outlawed_dissent": 200,
    "law_censorship": 100,
    "law_right_of_assembly": 50,
    "law_protected_speech": 0,
}


def test_speech_complete_native_denominator_and_authority_effects(focused):
    _, _, inputs = focused
    definitions = parse_text(inputs[SOURCE]).root
    actual = {}
    for row in definitions.assignments():
        if not isinstance(row.value, Block) or not row.value.all("ai_enact_weight_modifier"):
            continue
        modifiers = row.value.all("modifier")
        assert len(modifiers) == 1
        assert isinstance(modifiers[0].value, Block)
        effects = modifiers[0].value.all("country_authority_add")
        if effects:
            assert len(effects) == 1
            assert isinstance(effects[0].value, Scalar)
            actual[row.key] = int(effects[0].value.unquoted)
        else:
            actual[row.key] = 0
    assert actual == AUTHORITIES


@pytest.mark.parametrize("law", AUTHORITIES)
def test_all_speech_candidates_have_independent_agenda_adoption_and_player_boundaries(focused, law):
    witness(focused, law, {}, 6)
    witness(focused, law, {}, 10, support=0.25)
    witness(focused, law, {}, 0, support=None)
    witness(focused, law, {}, 0, is_ai=False)
    witness(focused, law, {f"law_context_current_{law}": True}, 0, support=0.25)
    witness(focused, law, {f"law_context_current_{law}": None}, 6)


@pytest.mark.parametrize(
    ("law", "origin", "balance", "support", "expected"),
    [
        ("law_protected_speech", "law_outlawed_dissent", 199, 0.1, -2),
        ("law_protected_speech", "law_outlawed_dissent", 200, 0.1, 6),
        ("law_protected_speech", "law_censorship", 99, 0.25, 2),
        ("law_right_of_assembly", "law_censorship", 49, 0.1, -2),
        ("law_right_of_assembly", "law_censorship", 50, 0.1, 6),
        ("law_outlawed_dissent", "law_protected_speech", -1, 0.1, 12),
        ("law_censorship", "law_protected_speech", -1, None, 6),
        ("law_protected_speech", "law_outlawed_dissent", None, 0.1, 6),
        ("law_protected_speech", "law_outlawed_dissent", 0, None, -8),
    ],
)
def test_speech_current_effect_delta_joins_need_without_predicting_population_benefit(
    focused, law, origin, balance, support, expected
):
    witness(
        focused,
        law,
        {f"law_context_current_{origin}": True, "authority": balance},
        expected,
        support=support,
    )
