"""启动等待中的错误协作退出；不启动游戏，也不触碰真实窗口或输入。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from pdx import game_auto as ga


@pytest.mark.parametrize("stage", ["window", "boot", "readable", "running"])
def test_启动等待首错后退出并先解除守卫再清理(monkeypatch, stage):
    now = [0.0]
    actions = []
    original = RuntimeError("实时错误门禁：VFSOpen Error")

    def check():
        if now[0] >= 1:
            raise original

    def pause(seconds):
        now[0] += seconds

    def window():
        actions.append("window")
        return False

    def start(**_kwargs):
        match stage:
            case "window":
                return ga.wait_until(
                    window,
                    timeout=600,
                    interval=1,
                    clock=lambda: now[0],
                    sleeper=pause,
                )
            case "boot":
                return ga.wait_for_boot_settle(timeout=600, interval=1)
            case "readable":
                return ga.wait_until_readable(timeout=600, interval=1)
            case "running":
                return ga.wait_until_running(timeout=600, interval=1)
        pytest.fail("未知测试阶段")

    def cleanup():
        # 清理使用相同等待函数；若守卫泄漏，原错误会打断清理。
        ga.wait_until(lambda: True, timeout=1)
        actions.append("cleanup")

    monkeypatch.setattr(ga, "_monotonic", lambda: now[0])
    monkeypatch.setattr(ga, "_sleep", pause)
    monkeypatch.setattr(ga, "tick_mark", lambda _log=None: ga.TickMark(ga.NO_TICK, 0))
    monkeypatch.setattr(ga, "_process_pids", lambda: [1])
    monkeypatch.setattr(ga, "_log_size", lambda _path: 0)
    monkeypatch.setattr(ga, "_run_session_impl", start)
    monkeypatch.setattr(ga, "kill_owned_game", cleanup)

    with pytest.raises(RuntimeError) as caught:
        ga.run_session(health_check=check)
    assert caught.value is original
    assert now[0] == 1  # 不能等满 600 秒或继续完成启动输入。
    assert actions == (["window", "cleanup"] if stage == "window" else ["cleanup"])
    ga.wait_until(lambda: True, timeout=1)


def test_启动成功仍做最终检查且返回原结果(monkeypatch):
    checks = []
    result = object()
    monkeypatch.setattr(ga, "_run_session_impl", lambda **_kwargs: result)
    monkeypatch.setattr(ga, "kill_owned_game", lambda: pytest.fail("成功路径不能清理"))
    assert ga.run_session(health_check=lambda: checks.append("checked")) is result
    assert checks == ["checked", "checked"]
    assert ga.run_session() is result
    assert checks == ["checked", "checked"]


def test_返回前已发生的错误不能被成功结果覆盖(monkeypatch):
    ready = [False]
    original = RuntimeError("证据采集失败")
    cleanups = []

    def start(**_kwargs):
        ready[0] = True
        return object()

    def check():
        if ready[0]:
            raise original

    monkeypatch.setattr(ga, "_run_session_impl", start)
    monkeypatch.setattr(ga, "kill_owned_game", lambda: cleanups.append(True))
    with pytest.raises(RuntimeError) as caught:
        ga.run_session(health_check=check)
    assert caught.value is original
    assert cleanups == [True]


def test_嵌套与其它线程不串用会话守卫():
    calls = []
    with ga._session_health(lambda: calls.append("outer")):
        with (
            ga._session_health(lambda: calls.append("inner")),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            executor.submit(ga.wait_until, lambda: True, timeout=1).result()
        ga.wait_until(lambda: True, timeout=1)
    assert calls == ["outer", "inner", "inner", "outer", "outer"]


def test_无效守卫在启动或清理前拒绝(monkeypatch):
    monkeypatch.setattr(ga, "_run_session_impl", lambda **_kw: pytest.fail("不能启动"))
    monkeypatch.setattr(ga, "kill_owned_game", lambda: pytest.fail("不能清理"))
    with pytest.raises(TypeError, match="health_check"):
        ga.run_session(health_check=False)  # type: ignore[arg-type]
