"""Current NAI rankings retain native counts and the historical author selection."""

from collections import Counter

import pytest

from pdx import ai, config, doc_tables, version_contracts

pytestmark = pytest.mark.unit


def test_current_nai_top25_uses_real_ranking_and_stable_boundary_ties(monkeypatch):
    # Twenty-four undisputed winners leave exactly one place for the tied
    # ALPHA/ZULU pair. Reversed insertion order cannot choose the loser.
    winners = {f"WINNER{i:02}": 100 for i in range(24)}
    counts = Counter({"ZULU": 2, "LOWER": 1, "ALPHA": 2, **winners})
    monkeypatch.setattr(ai, "nai_prefix_counts", lambda: counts)
    with version_contracts.select_version("1.15.0"):
        rows = ai.nai_prefix_rows()
        assert {name.strip("`") for name, _ in rows} == {*winners, "ALPHA"}
        assert rows[-1] == ("`ALPHA`", {1: "2"})
        assert isinstance(ai.doc_table_specs()[0], doc_tables.TableSpec)
        counts = Counter(dict(reversed(list(counts.items()))))
        assert ai.nai_prefix_rows() == rows
    with version_contracts.select_version("1.14.5"):
        assert [name.strip("`") for name, _ in ai.nai_prefix_rows()] == list(ai._NAI_PREFIXES)
        assert isinstance(ai.doc_table_specs()[0], doc_tables.KeyedTableSpec)


def test_current_ranking_counts_native_nai_keys_and_excludes_other_namespaces(
    tmp_path, monkeypatch
):
    source = tmp_path / "common/defines/00_ai.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        "NAI = { ZULU_ONLY = 2 ALPHA_FIRST = 0 ALPHA_SECOND = 1 }\nOTHER = { ALPHA_IGNORED = 1 }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "GAME", tmp_path)
    with version_contracts.select_version("1.15.0"):
        assert ai.nai_prefix_counts() == Counter(ALPHA=2, ZULU=1)
        assert ai.nai_prefix_rows() == [("`ALPHA`", {1: "2"}), ("`ZULU`", {1: "1"})]
