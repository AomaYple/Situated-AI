"""Frozen vocabulary for offline lowering tests, independent of current readers."""

from pdx import country_state, decision_adapters, decision_interfaces, vanilla_index


def frozen_reader_words(native: str) -> frozenset[str]:
    index = vanilla_index.snapshot_index()
    assert index is not None, "offline lowering requires the committed snapshot"
    country_state.validate(country_state.load(), snapshot={"sections": index.sections})
    vocabulary = index.vocabulary()
    assert vocabulary is not None, "offline lowering requires complete vocabulary sections"
    inputs = {
        "common/ai_strategies/00_default_strategy.txt": native,
        "scripted-predicate": decision_interfaces.scripted_trigger_snapshot().decode("utf-8"),
    }
    return (
        frozenset(vocabulary)
        | frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )
