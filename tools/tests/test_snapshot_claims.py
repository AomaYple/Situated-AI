"""用**入库的精简快照**核验一部分断言 —— CI 上唯一能真正核对断言的入口。

为什么需要这个文件
------------------
63 条断言全部要读游戏本体，而 CI 上没有游戏：``test_verify.py`` 打了
``integration`` 标记，在 CI 上被 conftest 自动跳过。于是「断言表是否仍然
与记录的真值一致」这件事，在 CI 上**完全没人看**。

精简快照（``tools/out/snapshots/*.compact.json``，约 4.9 MiB，**入库**）
带着 common 各目录的条目名、defines 命名空间与 DLC 清单，足以覆盖其中
约一半断言。这就是本文件跑的东西 —— 它**不需要游戏**，所以 CI 上会跑。

它证明什么、不证明什么
----------------------
* 证明：断言注册表仍然与当时记录的真值一致。有人改了 ``CLAIMS`` 却忘了
  同步快照，这里立刻会响。
* **不**证明：游戏里「现在」还是这个数 —— 那要读游戏本体，是
  ``v3 verify`` 的职责，只有装了游戏的机器能做。

两者合起来才完整。``v3 verify --from-snapshot`` 与本文件调用的是
**同一个函数** ``pdx.verify.verify_from_snapshot``，所以命令行与测试
不会分叉。
"""

from __future__ import annotations

import pytest

from pdx import verify

pytestmark = pytest.mark.unit

#: 快照至少要能覆盖这么多条断言 —— 低于这个数说明取值器退化或快照缺域。
#: 实测 33/63，留出余量取 25。
MIN_COVERED = 25


@pytest.fixture(scope="module")
def 快照():
    snap = verify.latest_compact_snapshot()
    if snap is None:
        pytest.skip("仓库里没有精简快照（tools/out/snapshots/*.compact.json）")
    return snap


def test_快照能覆盖足够多的断言(快照) -> None:
    covered = verify.verify_from_snapshot(快照)
    assert len(covered) >= MIN_COVERED, (
        f"快照只覆盖 {len(covered)} 条断言（预期 ≥{MIN_COVERED}）—— "
        f"检查 verify._SNAPSHOT_GETTERS 或快照是否缺域"
    )


def test_被覆盖的断言全部通过(快照) -> None:
    """**核心**：断言注册表必须与入库快照记录的真值一致。

    失败通常意味着两件事之一：改了 ``CLAIMS`` 的期望值但没重建快照，
    或者重建快照时游戏里的数字真的变了（那就该连带更新文档）。
    """
    bad = [r for r in verify.verify_from_snapshot(快照) if not r.ok]
    detail = "\n".join(
        f"  {r.claim.id}: 期望 {r.claim.expected}，快照给 {r.actual} {r.error or ''}" for r in bad
    )
    assert not bad, f"{len(bad)} 条断言与入库快照不一致：\n{detail}"


def test_没有取值器是死的() -> None:
    """``_SNAPSHOT_GETTERS`` 里每一项都必须真的有断言在用。

    这条防的正是本仓库踩过的那个坑：``prefix_in_mods`` 等检查函数
    注册好了却长期无人引用，于是「表里有的检查」与「真正跑的检查」
    悄悄分家。
    """
    used = {c.kind for c in verify.CLAIMS}
    dead = sorted(verify.snapshot_kinds() - used)
    assert not dead, f"这些快照取值器没有任何断言引用，应删除或补上断言：{dead}"


def test_没有快照时返回空表而不是抛(tmp_path, monkeypatch) -> None:
    """没有快照时必须能安静地退回「查不了」，而不是崩掉 CI。"""
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    assert verify.latest_compact_snapshot() is None
    assert verify.verify_from_snapshot(None) == []


def test_完整快照不算数(tmp_path, monkeypatch) -> None:
    """只认 ``*.compact.json`` —— 完整快照不入库，取了会得到 41 MB 的意外。"""
    (tmp_path / "release-1.14.3.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    assert verify.latest_compact_snapshot() is None
