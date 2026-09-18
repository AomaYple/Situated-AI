"""看守 conftest 的「游戏不在本机就自动跳过集成用例」机制。

为什么需要这个文件
------------------
``conftest.pytest_collection_modifyitems(config, items)`` 的形参名必须是
``config``（pluggy 按 hookspec 的形参名注入 pytest 自己的 ``Config`` 对象），
而这个形参会**遮蔽** ``pdx.config`` 模块。若模块里写 ``config.GAME``，
在没有游戏安装的机器上就会炸成 ``INTERNALERROR``，而不是干净地跳过。

这个缺陷的隐蔽之处在于：**装了游戏的开发机上永远不会触发** ——
函数在读到 ``config.GAME`` 之前就 ``if GAME_OK: return`` 了。
换句话说，「换台机器自动 skip」这条设计全靠一行在本地跑不到的代码。

所以这里用子进程真跑一次**收集**：把 ``V3_ROOT`` 指到一个不存在的路径，
断言 pytest 仍然以 0 退出（收集成功），而不是 INTERNALERROR。
用 ``--collect-only`` 是为了不真的执行（集成用例会被 mark 成 skip，
但收集阶段就会调用那个 hook，足够暴露问题，且只要 1-2 秒）。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from pdx import config

pytestmark = pytest.mark.unit


def _run_collect(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-n0",
            "--no-cov",
            "-p",
            "no:randomly",
            "tools/tests",
        ],
        cwd=config.REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


def test_游戏不可用时收集不会崩() -> None:
    """没有游戏安装的环境（CI、新克隆）必须能正常收集并跳过，而不是报错。"""
    proc = _run_collect(
        {
            "V3_ROOT": "Z:/nope",
            "V3_USERDIR": "Z:/nope",
            "V3_WORKSHOP": "Z:/nope",
        }
    )
    assert proc.returncode == 0, (
        "游戏不可用时 pytest 收集失败了；多半是 conftest 里 "
        "`config` 形参遮蔽了 `pdx.config` 模块。\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-3000:]}"
    )
    assert "INTERNALERROR" not in proc.stdout + proc.stderr
    # 仍然应该有测试被收集到（单元测试不依赖游戏）
    assert " tests collected" in proc.stdout or "/" in proc.stdout


def test_游戏可用时也照常收集() -> None:
    """本机（装了游戏）同样要能收集 —— 防止上个用例的修法把正常路径改坏。"""
    if not (config.GAME / "common").is_dir():
        pytest.skip("本机没有游戏，这条只验证有游戏时的路径")
    proc = _run_collect({})
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
