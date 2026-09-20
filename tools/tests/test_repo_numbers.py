"""README 里那些「机械数字」的看守 —— 它们全都能从仓库现算。

为什么需要这个文件
----------------
``README.md`` 与 ``tools/README.md`` 里有一批数字是**仓库自身的量**：
文档篇数与字符总量、生成表张数、断言条数（快/慢/离线各多少）、测试文件数、
用例数……它们一直靠手工同步 —— 而手写的机械数字**迟早会过期**，这不是纪律问题，
是结构问题：本轮做 docs 脚本化时就又发现四处（生成表 164→166、断言 226→231、
``--fast`` 206→208、知识库字符总量少记了三万多）。

所以这里把「现算」变成测试：数字对不上就红，改 README 即可 —— 与
``tools/tests/test_inventory.py`` 守欠债余额是同一个思路。

口径（写清楚，免得以后各算各的）
------------------------------
* **文档篇数 / 字符总量**：``docs/victoria3-modding/*.md``（含索引页），
  字符数 = 各文件按 UTF-8 解码后的 ``len(text)``（含 Markdown 记号与换行）；
* **生成表张数**：``docgen.targets()`` 里全部 spec 的条数（= ``v3 tables`` 报的那个数）；
* **断言条数**：``verify.CLAIMS``；**快/慢**按 ``verify.SLOW_KINDS`` 分，
  **离线**指 ``verify.snapshot_kinds()`` 覆盖得到的那些；
* **测试文件数**：``tools/tests/test_*.py``（不含 ``conftest.py`` / ``_table_guards.py``
  这些支撑文件）；
* **用例数**：``pytest --collect-only`` 的实测值 —— 这一条必须**真的收集一遍**，
  因为参数化与 subtest 会让它不等于 ``def test_`` 的个数。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

from pdx import config, docgen, exe_strings, verify

DOCS = sorted(config.DOCS.glob("*.md"))
TEST_FILES = sorted((config.REPO / "tools" / "tests").glob("test_*.py"))


def _docs_chars() -> int:
    return sum(len(p.read_text(encoding="utf-8")) for p in DOCS)


def _tables() -> int:
    return sum(len(t.specs) for t in docgen.targets())


def _claims() -> int:
    return len(verify.CLAIMS)


def _fast() -> int:
    return sum(1 for c in verify.CLAIMS if c.kind not in verify.SLOW_KINDS)


def _offline() -> int:
    return sum(1 for c in verify.CLAIMS if c.kind in verify.snapshot_kinds())


def _readmes() -> tuple[str, str]:
    return (
        (config.REPO / "README.md").read_text(encoding="utf-8"),
        (config.REPO / "tools" / "README.md").read_text(encoding="utf-8"),
    )


def test_README里的机械数字与仓库现状一致() -> None:
    """篇数 / 字符总量 / 生成表 / 断言 / 测试文件数 —— 逐项对账。"""
    root, tools = _readmes()
    checks: list[tuple[str, str]] = [
        ("README 的知识库篇数", f"**{len(DOCS)} 篇"),
        ("README 的知识库字符总量", f"| {_docs_chars():,} 字符 |"),
        ("README 的生成表张数", f"{_tables()} 张"),
        ("README 的测试文件数", f"{len(TEST_FILES)} 个测试文件"),
        ("tools/README 的断言条数", f"{_claims()} 条断言核验"),
        ("tools/README 的 verify 行", f"核对文档里的 **{_claims()} 条**数量断言"),
        ("tools/README 的 --fast 条数", f"`--fast` 跑不需要全库扫描的 {_fast()} 条"),
        ("tools/README 的离线可核验条数", f"{_claims()} 条断言里 {_offline()} 条"),
    ]
    missing = [
        f"{label}：找不到 {needle!r}" for label, needle in checks if needle not in root + tools
    ]
    assert not missing, (
        "README 里的机械数字与仓库现状对不上（改 README，别改这条测试）：\n  "
        + "\n  ".join(missing)
    )


def test_README里的用例数与实际收集一致() -> None:
    """用例数必须等于 ``pytest --collect-only`` 的实测值。

    不能数 ``def test_``：参数化与 subtest 会把它撑大 —— README 写的是
    「``pytest --collect-only`` 实测」，那这里就得真收集一遍。

    只在**有游戏**的机器上判定：无游戏时集成用例的 import/收集路径不同，
    硬比会把 README 钉死在某一种环境上（CI 上跳过，本机照查）。
    """
    if not config.GAME.is_dir():
        pytest.skip("无游戏：收集结果与本机口径不同，这一条只在装了游戏的机器上判定")
    # 子进程的输出编码必须显式钉成 UTF-8：本机 locale 是 GBK 时，pytest 会按 GBK
    # 打印中文用例名，而这边按 UTF-8 解码 —— 直接 UnicodeDecodeError（实测踩过）。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-n0",
            "-p",
            "no:randomly",
            "--no-header",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(config.REPO),
        check=False,
    )
    m = re.search(r"(\d+) tests collected", result.stdout or "")
    assert m, (
        f"收集测试用例失败（rc={result.returncode}）：\n{result.stdout[-800:]}\n{result.stderr[-800:]}"
    )
    collected = int(m.group(1))
    root, tools = _readmes()
    assert f"**{collected} 条**用例" in root, (
        f"README 写的用例数与实测（{collected}）不一致 —— 跑 `pytest --collect-only -q` 核对后改 README"
    )
    assert f"{collected} 条用例" in tools, f"tools/README 写的用例数与实测（{collected}）不一致"


def test_CI配置里的断言条数与现算一致() -> None:
    """CI 工作流注释里也有一处「N 条断言全部要读游戏本体」—— 同样是手写的机械数字。

    （它曾经写着 63，而断言表已经是 231 条。）
    """
    ci = (config.REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    needle = f"{_claims()} 条断言里 {_offline()} 条能用入库的离线真值核验"
    assert needle in ci, f"CI 配置里的断言条数与现算不一致（应为 {needle!r}）"


def test_toolsREADME的exe标识符数字与现算一致() -> None:
    """`v3 strings` 给的两个数也要现算。

    它们原先（17,821 / 16,535）是一批**没留口径的一次性采集值** ——
    换一个游戏版本就没人能重算，与 doc 04 §4.6 那个「682 行」同病。
    现在口径在 :mod:`pdx.exe_strings`，这条盯住 README 别写回旧数。
    """
    if not exe_strings.exe_path().is_file():
        pytest.skip("没有游戏本体（binaries/victoria3.exe）—— 这一条只在装了游戏的机器上判定")
    stats = exe_strings.identifier_stats()
    tools = (config.REPO / "tools" / "README.md").read_text(encoding="utf-8")
    assert f"**{stats['exe']:,} 个标识符形状的串**" in tools, (
        f"tools/README 的「exe 标识符数」与现算（{stats['exe']:,}）不一致"
    )
    assert f"**{stats['unused']:,} 个从未在" in tools, (
        f"tools/README 的「未使用数」与现算（{stats['unused']:,}）不一致"
    )
