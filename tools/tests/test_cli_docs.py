"""文档里写的 `v3 …` 命令必须**真的敲得出来**。

为什么需要这一条（实测踩过）
----------------------------
`exec/接续说明.md` 与 `exec/阶段7-长期维护.md` 长期写着 `v3 tables --check`，
而 `v3 tables` **没有 `--check`**（不带 `--write` 就是核对）。照着维护手册敲命令的人
会拿到一句 `No such option: --check` —— 文档在教一个不存在的命令，而没有任何东西看着它。

这类错误**不会**被现有门禁发现：`v3 verify` 管数字、`v3 tables` 管表格、
`test_inventory` 管散文数字 —— 命令与选项没人管。

切片口径（**踩过一次才定下来的**）
----------------------------------
第一版按"整行"切，于是同一行里**别的命令**的选项被算到了 `v3` 头上：
`v3 modguard` 与 `v3 ai-surface --check` 写在一行 ⇒ 报「modguard 没有 --check」；
`pytest --cov-report=…` 跟在 `v3 cov` 后面 ⇒ 报「cov 没有 --cov-report」；
连 `<!--claim:x-->` 里的 `--claim` 都被当成了选项。**假阳性会让人删掉这条用例**，
所以口径收紧成"命令必须自成一段"：

* **反引号跨度**：`` `v3 tables --write` `` 这样写的，只看这一对反引号里面；
* **围栏代码块**：```powershell 块里的**一条命令**（先去掉 `#` 注释，
  再按 `;` / `&&` / `|` 拆开 —— 实测踩过：`v3 verify ; v3 tables ; v3 ai-surface --check`
  写在一行时，`--check` 被算到了前两条头上）。

边界
----
* 只查**子命令存在**与**选项存在**；
* 子命令组（`v3 snapshot …` / `v3 mirror …`）**跳过选项检查** —— 选项属于下一级；
* 不检查位置参数与取值的形态。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from typer.main import get_command

from pdx import cli, config

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

#: 文档里出现 `v3 …` 的形态：`v3 verify`、`v3.exe modgen --check`。
_INVOCATION = re.compile(r"\bv3(?:\.exe)?\s+([a-z][a-z0-9-]*)")
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_SPAN = re.compile(r"`([^`]+)`")

#: 代码块里的命令分隔符：一条 shell 行常常并列好几条命令。
_SPLIT = re.compile(r";|&&|\|")

#: 文档里提到的、**故意不检查**的目标：写清理由才许留。
SKIP: dict[str, str] = {}


def _command_tree() -> dict[str, object]:
    """``{子命令名: click 命令对象}``。

    ``get_command()`` 的静态类型是 ``click.Command``，而 ``commands`` 只在
    ``click.Group`` 上有 —— 顶层是 Typer 的组，所以这里取属性而不是直接点出来
    （点出来 mypy 会报 `"Command" has no attribute "commands"`）。
    """
    return dict(getattr(get_command(cli.app), "commands", {}) or {})


def _options(cmd: object) -> set[str] | None:
    """一个子命令的选项集合；它是**命令组**时返回 ``None``（交给下一级）。"""
    if getattr(cmd, "commands", None):
        return None
    out: set[str] = set()
    for param in getattr(cmd, "params", []):
        out.update(getattr(param, "opts", []) or [])
        out.update(getattr(param, "secondary_opts", []) or [])
    return out


def fragments() -> Iterator[tuple[str, int, str]]:
    """``(文档名, 行号, 片段)`` —— 每个片段里最多只应有一条命令。"""
    seen: set[object] = set()
    for root in (config.DOCS, config.REPO / "docs"):
        for path in sorted(root.rglob("*.md")):
            if path in seen:
                continue
            seen.add(path)
            fenced = False
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("```"):
                    fenced = not fenced
                    continue
                if fenced:
                    body = line.split("#", 1)[0]
                    for piece in _SPLIT.split(body):
                        if piece.strip():
                            yield path.name, lineno, piece
                else:
                    for span in _SPAN.findall(line):
                        yield path.name, lineno, span


def test_文档里的v3命令都有对应的子命令() -> None:
    tree = _command_tree()
    bad = [
        f"{doc}:{lineno} 未知子命令 {name!r} —— {frag.strip()[:80]}"
        for doc, lineno, frag in fragments()
        for name in _INVOCATION.findall(frag)
        if name not in tree and name not in SKIP
    ]
    assert not bad, "文档提到了 CLI 里不存在的子命令：\n  " + "\n  ".join(bad[:15])


def test_文档里的v3选项都真的存在() -> None:
    """`v3 tables --check` 就是这么暴露的：选项名没人核对过。"""
    tree = _command_tree()
    bad: list[str] = []
    for doc, lineno, frag in fragments():
        for match in _INVOCATION.finditer(frag):
            name = match.group(1)
            cmd = tree.get(name)
            if cmd is None:
                continue  # 「子命令不存在」由上面那条单独报
            opts = _options(cmd)
            if opts is None:
                continue  # 命令组：选项属于下一级
            bad.extend(
                f"{doc}:{lineno} `v3 {name} {flag}` —— {name} 没有这个选项"
                f"（可用：{' '.join(sorted(opts)) or '无'}）"
                for flag in _FLAG.findall(frag[match.end() :])
                if flag not in opts
            )
    assert not bad, "文档教了不存在的选项：\n  " + "\n  ".join(bad[:15])


def test_命令树本身不是空的() -> None:
    """反向自检：上面两条只有在命令树读得到东西时才有意义。"""
    tree = _command_tree()
    assert {"tables", "verify", "modgen", "citations", "modguard"} <= set(tree)


def test_片段切分不会漏掉代码块里的命令() -> None:
    """反向自检：切片口径太紧就会**静默漏检**，那比误报更糟。

    `exec/接续说明.md` §4 那些命令写在 ```powershell 块里、没有反引号 ——
    如果切片只认反引号，这一整节就没人看了。
    """
    frags = list(fragments())
    joined = "\n".join(f for _d, _n, f in frags)
    assert "v3.exe modgen --check" in joined
    assert "v3.exe verify" in joined
