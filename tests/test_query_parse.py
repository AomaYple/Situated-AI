"""Query AST ownership preserves source validation and per-query semantics."""

from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from pdx import _query_parse, config, distribution, version_contracts
from pdx import company_observations as company
from pdx import observation_queries as country
from pdx import technology_opportunities as technology
from pdx.textio import normalized_text

TEXT = "native = { value = yes }"
SOURCE = "common/example.txt"
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()


def _parse():
    return _query_parse.parse_query_source(TEXT, SOURCE, DIGEST)


def test_successful_tree_reuse_is_limited_to_one_scope():
    outside = _parse()
    assert _parse() is not outside
    with _query_parse.query_parse_scope():
        inside = _parse()
        assert inside == outside
        assert _parse() is inside
    with _query_parse.query_parse_scope():
        assert _parse() is not inside
    assert _parse() is not inside


def test_nested_scope_restores_outer_owner_even_after_exception():
    with _query_parse.query_parse_scope():
        outer = _parse()

        def abort_inner():
            with _query_parse.query_parse_scope():
                inner = _parse()
                assert inner is not outer
                assert _parse() is inner
                raise RuntimeError("abort")

        with pytest.raises(RuntimeError, match="abort"):
            abort_inner()
        assert _parse() is outer
    assert _parse() is not outer


def test_exception_clears_dictionary_retained_by_copied_context():
    captured = []

    def abort_scope():
        with _query_parse.query_parse_scope():
            captured.append((_parse(), copy_context()))
            raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        abort_scope()
    parsed, retained = captured[0]
    after_exit = retained.run(_parse)
    assert after_exit is not parsed
    assert retained.run(_parse) is not after_exit


def test_source_digest_profile_and_exact_text_are_all_part_of_reuse():
    with _query_parse.query_parse_scope(), version_contracts.select_version("1.14.5"):
        original = _parse()
        other_path = _query_parse.parse_query_source(TEXT, "common/other.txt", DIGEST)
        assert other_path is not original
        assert other_path.path == "common/other.txt"
        assert _query_parse.parse_query_source(TEXT, SOURCE, "another-digest") is not original
        with version_contracts.select_version("1.15.0"):
            assert _parse() is not original
        assert _parse() is original
        # Even a colliding digest cannot make different source text borrow a tree.
        changed = _query_parse.parse_query_source("native = { value = no }", SOURCE, DIGEST)
        assert changed is not original
        assert changed.root != original.root
        assert _parse().root == original.root


def test_unsuccessful_parses_are_never_retained():
    with _query_parse.query_parse_scope():
        first = _query_parse.parse_query_source("native = {", SOURCE, DIGEST)
        second = _query_parse.parse_query_source("native = {", SOURCE, DIGEST)
        assert first.errors
        assert second.errors
        assert first is not second


@pytest.mark.parametrize("copied", [False, True])
def test_other_thread_cannot_borrow_tree_even_with_copied_context(copied):
    with _query_parse.query_parse_scope(), ThreadPoolExecutor(max_workers=1) as pool:
        owned = _parse()
        if copied:
            context = copy_context()
            first = pool.submit(context.run, _parse).result()
            second = pool.submit(context.run, _parse).result()
        else:
            first = pool.submit(_parse).result()
            second = pool.submit(_parse).result()
        assert first == second == owned
        assert first is not second
        assert first is not owned
        assert _parse() is owned


def test_each_installation_verification_owns_fresh_scope_and_cleans_up(monkeypatch):
    observed = []

    def abort(_game):
        parsed = _parse()
        assert _parse() is parsed
        observed.append(parsed)
        raise RuntimeError("stop at first real verification boundary")

    monkeypatch.setattr(distribution.engine_scope, "verify_strategy_game", abort)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="first real verification boundary"):
            distribution.verify_compatibility_installation()
    assert observed[0] is not observed[1]
    assert _parse() is not observed[-1]


@pytest.fixture(scope="module")
def native_texts():
    queries = (
        country.AnyStateMarketAccessBelow(0.9),
        company.RailInfrastructure(),
        technology.TechnologyBuildingQuery("building_art_academy"),
    )
    sources = {source for query in queries for source in country.required_sources(query)}
    return {source: (config.GAME / source).read_text(encoding="utf-8-sig") for source in sources}


@pytest.mark.integration
@pytest.mark.parametrize(
    "query",
    [
        country.AnyStateMarketAccessBelow(0.9),
        company.RailInfrastructure(),
        technology.TechnologyBuildingQuery("building_art_academy"),
    ],
)
def test_real_compilers_preserve_results_and_recheck_sources_after_hit(native_texts, query):
    expected = country.compile_query(query, native_texts)
    sources = country.required_sources(query)
    first, last = sources[0], sources[-1]
    with _query_parse.query_parse_scope():
        assert country.compile_query(query, native_texts) == expected
        assert country.compile_query(query, native_texts) == expected
        for invalid in (None, 1, native_texts[first] + "\n# drift\n"):
            changed = {**native_texts, first: invalid}
            if last != first:
                changed[last] = None
            with pytest.raises(ValueError, match=re.escape(first)):
                country.compile_query(query, changed)
        changed = {name: text for name, text in native_texts.items() if name != last}
        with pytest.raises(ValueError, match=re.escape(last)):
            country.compile_query(query, changed)
        assert country.compile_query(query, native_texts) == expected


@pytest.mark.integration
def test_reused_trees_still_run_complete_query_semantic_checks(native_texts, monkeypatch):
    query = company.RailInfrastructure()
    source = "common/production_method_groups/11_private_infrastructure.txt"
    changed, count = re.subn(
        r"(pmg_base_building_railway\s*=\s*\{.*?production_methods\s*=\s*)\{[^}]*\}",
        lambda match: match[1] + "{ pm_early_trains }",
        native_texts[source],
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    text = normalized_text(changed)
    digest = hashlib.sha256(text.encode()).hexdigest()
    with _query_parse.query_parse_scope():
        company.compile_query(query, native_texts)
        monkeypatch.setitem(company.source_hashes(), source, digest)
        # Prime the syntactically valid but semantically incomplete source, so
        # the rejection below must traverse cached trees rather than parse anew.
        assert not _query_parse.parse_query_source(text, source, digest).errors

        def reject_parse(*_args, **_kwargs):
            pytest.fail("a required source was reparsed instead of reusing its owned tree")

        monkeypatch.setattr(_query_parse, "parse_text", reject_parse)
        with pytest.raises(ValueError, match="铁路基础组必须完整非空"):
            company.compile_query(query, {**native_texts, source: changed})
