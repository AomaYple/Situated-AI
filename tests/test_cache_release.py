"""Memo release is a lifetime boundary, preserving callers, disk work and counts."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from pdx import analyze, cache, cli

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    cache.clear()
    monkeypatch.setenv(cache.CACHE_ENV, "0")
    monkeypatch.setattr(cache, "_state", cache._DiskState())
    yield
    cache.clear()


def _release():
    release = getattr(cache, "release_memo", None)
    assert release is not None, "completed CLI transactions must release memo ownership"
    return release


def _input(tmp_path, name="one"):
    path = tmp_path / f"{name}.txt"
    path.write_text(f"{name} = {{ value = 1 }}\n", encoding="utf-8")
    return path


def test_release_keeps_caller_ast_disk_state_engine_identity_and_cumulative_statistics(tmp_path):
    path = _input(tmp_path)
    parsed = cache.parse_cached(path)
    assert cache.parse_cached(path) is parsed
    cache._state.pending[0] = {"pending": (1, parsed)}
    cache._state.indexes[0] = {"index": (0, 10, 1)}
    cache._state.dirty.add(0)
    stamp = cache._engine_stamp()
    stamp_info = cache._engine_stamp.cache_info()
    pending, indexes, dirty = cache._state.pending, cache._state.indexes, cache._state.dirty
    _release()()
    assert cache.stats() == {"条目": 0, "命中": 1, "未命中": 1}
    assert parsed.top_keys == ["one"]
    assert cache._state.pending is pending
    assert pending[0]["pending"][1] is parsed
    assert cache._state.indexes is indexes
    assert indexes[0] == {"index": (0, 10, 1)}
    assert cache._state.dirty is dirty
    assert dirty == {0}
    assert cache._engine_stamp.cache_info() == stamp_info
    assert cache._engine_stamp() == stamp
    assert cache.parse_cached(path).top_keys == parsed.top_keys
    assert cache.stats() == {"条目": 1, "命中": 1, "未命中": 2}
    cache.clear()
    assert cache.stats() == {"条目": 0, "命中": 0, "未命中": 0}


@pytest.mark.parametrize("fails", [False, True])
def test_release_waits_for_inflight_parse_and_assigns_new_calls_to_the_next_generation(
    tmp_path, monkeypatch, fails
):
    release = _release()
    one, two = _input(tmp_path, "one"), _input(tmp_path, "two")
    entered, finish, new_attempt, second_entered = (threading.Event() for _ in range(4))
    parse = cache.parse_bytes

    def blocked_parse(raw, path):
        if path == str(one):
            entered.set()
            assert finish.wait(5)
            if fails:
                raise ValueError("parse failed")
        else:
            second_entered.set()
        return parse(raw, path)

    monkeypatch.setattr(cache, "parse_bytes", blocked_parse)

    def next_parse():
        new_attempt.set()
        return cache.parse_cached(two)

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.parse_cached, one)
        assert entered.wait(5)
        cleanup = pool.submit(release)
        with cache._memo.condition:
            assert cache._memo.condition.wait_for(lambda: cache._memo.release_requested, timeout=5)
        second = pool.submit(next_parse)
        assert new_attempt.wait(5)
        assert not second_entered.is_set()
        finish.set()
        if fails:
            with pytest.raises(ValueError, match="parse failed"):
                first.result(timeout=5)
        else:
            assert first.result(timeout=5).top_keys == ["one"]
        cleanup.result(timeout=5)
        assert second.result(timeout=5).top_keys == ["two"]
    assert cache.stats() == {"条目": 1, "命中": 0, "未命中": 2}
    assert not cache._memo.active
    assert not cache._memo.release_requested


def test_distinct_parses_still_execute_concurrently(tmp_path, monkeypatch):
    _release()
    one, two = _input(tmp_path, "one"), _input(tmp_path, "two")
    barrier = threading.Barrier(2)
    parse = cache.parse_bytes

    def concurrent_parse(raw, path):
        barrier.wait(timeout=5)
        return parse(raw, path)

    monkeypatch.setattr(cache, "parse_bytes", concurrent_parse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cache.parse_cached, path) for path in (one, two)]
        assert [future.result(timeout=5).top_keys for future in futures] == [["one"], ["two"]]
    assert cache.stats()["未命中"] == 2


def test_release_requested_inside_a_parse_does_not_deadlock_recursive_entry(tmp_path, monkeypatch):
    release = _release()
    one, two = _input(tmp_path, "one"), _input(tmp_path, "two")
    completed = threading.Event()
    results, errors = [], []
    parse = cache.parse_bytes

    def recursive_parse(raw, path):
        if path == str(one):
            release()
            assert cache.parse_cached(two).top_keys == ["two"]
        return parse(raw, path)

    monkeypatch.setattr(cache, "parse_bytes", recursive_parse)

    def execute():
        try:
            results.append(cache.parse_cached(one))
        except BaseException as error:
            errors.append(error)
        finally:
            completed.set()

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    assert completed.wait(5), "a parser cannot wait for its own active call to finish"
    thread.join(timeout=5)
    assert not errors
    assert results[0].top_keys == ["one"]
    assert cache.stats() == {"条目": 0, "命中": 0, "未命中": 2}


@pytest.mark.parametrize("fails", [False, True])
def test_cli_transaction_releases_memo_on_success_and_failure_without_losing_counts(
    tmp_path, monkeypatch, fails
):
    path = _input(tmp_path)
    retained = []
    monkeypatch.setattr(cli.app, "registered_commands", list(cli.app.registered_commands))

    @cli.app.command("resource-lifetime-fixture")
    def exercise():
        retained.append(cache.parse_cached(path))
        assert cache.parse_cached(path) is retained[-1]
        if fails:
            raise ValueError("transaction failed")

    result = CliRunner().invoke(cli.app, ["resource-lifetime-fixture"])
    assert result.exit_code == int(fails)
    if fails:
        assert isinstance(result.exception, ValueError)
    assert retained[0].top_keys == ["one"]
    assert cache.stats() == {"条目": 0, "命中": 1, "未命中": 1}


def test_explicit_disk_clear_also_resets_statistics_accumulated_before_release(
    tmp_path, monkeypatch
):
    path = _input(tmp_path)
    disk = tmp_path / "disk"
    monkeypatch.setattr(cache, "cache_dir", lambda: disk)
    cache.parse_cached(path)
    cache.parse_cached(path)
    _release()()
    assert cache.stats() == {"条目": 0, "命中": 1, "未命中": 1}
    cache.clear_disk()
    assert cache.stats() == {"条目": 0, "命中": 0, "未命中": 0}


@pytest.mark.parametrize("fails", [False, True])
def test_nested_lifetime_and_cli_close_collect_only_for_nonempty_release(
    tmp_path, monkeypatch, fails
):
    path = _input(tmp_path)
    collections = []
    collect = cache.gc.collect

    def record_collection():
        collections.append(cache.stats()["条目"])
        return collect()

    monkeypatch.setattr(cache.gc, "collect", record_collection)
    monkeypatch.setattr(cli.app, "registered_commands", list(cli.app.registered_commands))

    @cli.app.command("nested-lifetime-fixture")
    def exercise():
        with cache.memo_lifetime(), cache.memo_lifetime():
            assert cache.parse_cached(path).top_keys == ["one"]
            if fails:
                raise ValueError("transaction failed")

    result = CliRunner().invoke(cli.app, ["nested-lifetime-fixture"])
    assert result.exit_code == int(fails)
    if fails:
        assert isinstance(result.exception, ValueError)
    cache.release_memo()
    with cache.memo_lifetime():
        pass
    assert collections == [0]
    assert cache.stats() == {"条目": 0, "命中": 0, "未命中": 1}


@pytest.mark.parametrize("fails", [False, True])
def test_real_report_write_releases_memo_and_preserves_prior_json_on_serialization_failure(
    tmp_path, monkeypatch, fails
):
    source = tmp_path / "inputs" / "common" / "fixture" / "one.txt"
    source.parent.mkdir(parents=True)
    source.write_text("one = { value = 1 }\n", encoding="utf-8")
    monkeypatch.setattr(analyze, "CONTENT_ROOTS", {"game": tmp_path / "inputs"})
    monkeypatch.setattr(analyze, "GAME_OUT", tmp_path / "game")
    monkeypatch.setattr(analyze, "MODS_OUT", tmp_path / "mods")
    monkeypatch.setattr(analyze, "CROSS_OUT", tmp_path / "cross")
    monkeypatch.setattr(analyze.config, "REPORTS", tmp_path / "reports")
    ga, ma, ca = analyze.GameAnalysis(), analyze.ModsAnalysis(), analyze.CrossAnalysis()
    retained = cache.parse_cached(source)
    if fails:
        ga.resources = {"game": {"bad": [{"unserializable": object()}]}}
        target = analyze.GAME_OUT / "游戏本体.json"
        target.parent.mkdir()
        target.write_bytes(b"previous complete output\n")
        with pytest.raises(TypeError):
            analyze.write_reports(ga, ma, ca)
        assert target.read_bytes() == b"previous complete output\n"
    else:
        output = analyze.write_reports(ga, ma, ca)
        assert output["游戏数据 JSON"].read_text(encoding="utf-8").startswith('{"数据":')
    assert retained.top_keys == ["one"]
    assert cache.stats() == {"条目": 0, "命中": int(not fails), "未命中": 1}
