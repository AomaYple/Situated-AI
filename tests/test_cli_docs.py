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

为什么允许集要含**框架通用选项**（2026-09-25 实测）
--------------------------------------------------
`--help` **不是**子命令声明的 —— 它是 Click/Typer 在解析时按需生成的
（`Command.get_help_option()`），所以 `cmd.params` 里根本没有它。第一版判据只查
`cmd.params`，于是**任何文档只要提一句 `v3 citations --help` 就红**：窗口 3 整批
实测三处（`backlog.md:181` / `backlog.md:182` / `档案目标牌-实机读数.md:308`），
原文是「citations 没有这个选项（可用：`--offline` `paths`）」。

修法是把**确实存在**的通用选项加进允许集（:func:`framework_options`，实测得出），
**不是**跳过含 `--help` 的行 —— 后者会把判据弄瞎（假阴性比假阳性更难查）。
反向那一半同样钉住：未知选项仍会红（`test_未知选项仍然会红`）。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from pdx import cli, config

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

pytestmark = pytest.mark.unit

#: 文档里出现 `v3 …` 的形态：`v3 verify`、`v3.exe modgen --check`。
_INVOCATION = re.compile(r"\bv3(?:\.exe)?\s+([a-z][a-z0-9-]*)")
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_SPAN = re.compile(r"`([^`]+)`")

#: 代码块里的命令分隔符：一条 shell 行常常并列好几条命令。
_SPLIT = re.compile(r";|&&|\|")

#: 文档里提到的、**故意不检查**的目标：写清理由才许留。
SKIP: dict[str, str] = {}

#: 框架通用选项的**候选名单**。判据不从这张表来 —— 它只是待验证的输入；
#: 真正进允许集的是 :func:`framework_options` **实测**跑得通的那些。
_FRAMEWORK_OPT_CANDIDATES = ("--help", "--version")

#: 探针子命令：拿它去试每个候选（叶子；且正是窗口 3 被误报的那条）。
_FRAMEWORK_OPT_PROBE = "citations"

runner = CliRunner()


@lru_cache(maxsize=1)
def framework_options() -> frozenset[str]:
    """框架（Typer/Click）给每条子命令都提供的通用选项 —— **实测**得出，不硬编码。

    为什么必须有它：:func:`_options` 读的是 ``cmd.params``，而 ``--help`` 不在里面
    （Click 在解析时按需生成），于是「允许集」漏了它 ⇒ 文档里写一句
    ``v3 citations --help`` 就被误报成「citations 没有这个选项」。

    为什么是实测而不是写死 ``{"--help"}``：**写死会随框架漂移**，而实测自己会说话 ——
    顺带把「`--version` 到底有没有」也一次答掉。实测（2026-09-25，本机 1.14.4 环境）：

    * ``v3 citations --help`` = **exit 0 / 40 行**（``v3 snapshot --help`` = exit 0 / 16 行）；
    * ``v3 citations --version`` = **exit 2**（``v3 --version`` 也是 exit 2：
      「No such option: --version」）⇒ **顶层组也没有它**，所以它不进允许集；
    * 反例 ``v3 citations --definitely-not-a-flag`` = **exit 2** ⇒ 允许集不是「什么都行」
      （那一路由 ``test_未知选项仍然会红`` 钉住）。
    """
    return frozenset(
        flag
        for flag in _FRAMEWORK_OPT_CANDIDATES
        if runner.invoke(cli.app, [_FRAMEWORK_OPT_PROBE, flag]).exit_code == 0
    )


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
            if path.is_relative_to(config.REPORTS):
                continue  # 历史复核报告保留失败命令作为证据，不是操作手册。
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


def _option_offenders(frags: Iterable[tuple[str, int, str]] | None = None) -> list[str]:
    """判据本体：片段里写了、而该子命令**确实没有**的选项。

    允许集 = 子命令自己声明的选项（``cmd.params``）∪ **框架通用选项**
    （:func:`framework_options`）—— 后者是窗口 3 那次误报的根因，见模块文档。

    ``frags=None`` 走真实文档（:func:`fragments`）；传合成片段可以把**负例**喂回判据
    （见 ``test_未知选项仍然会红``），这样「两路」用的是同一段逻辑，不会各写一份。
    """
    tree = _command_tree()
    common = framework_options()
    bad: list[str] = []
    for doc, lineno, frag in fragments() if frags is None else frags:
        for match in _INVOCATION.finditer(frag):
            name = match.group(1)
            cmd = tree.get(name)
            if cmd is None:
                continue  # 「子命令不存在」由上面那条单独报
            opts = _options(cmd)
            if opts is None:
                continue  # 命令组：选项属于下一级
            allowed = opts | common
            bad.extend(
                f"{doc}:{lineno} `v3 {name} {flag}` —— {name} 没有这个选项"
                f"（可用：{' '.join(sorted(allowed)) or '无'}）"
                for flag in _FLAG.findall(frag[match.end() :])
                if flag not in allowed
            )
    return bad


def test_文档里的v3选项都真的存在() -> None:
    """`v3 tables --check` 就是这么暴露的：选项名没人核对过。"""
    bad = _option_offenders()
    assert not bad, "文档教了不存在的选项：\n  " + "\n  ".join(bad[:15])


def test_框架通用选项被认作合法() -> None:
    """① 通用选项（至少 `--help`）合法 —— 而且它**必须**被认出来。

    两个子断言缺一不可：`--help` 在允许集里；且它**不在任何子命令的 `params` 里**
    （那就是当初漏掉它的原因 —— 只查 `params` 必然误报）。最后抽查三条实机 exit 0。
    """
    assert "--help" in framework_options(), "框架通用选项没被认出来 ⇒ 会退回窗口 3 那种误报"
    tree = _command_tree()
    assert all("--help" not in (_options(cmd) or set()) for cmd in tree.values()), (
        "`--help` 居然被子命令声明了？那这条判据的立论要重写"
    )
    for name in (_FRAMEWORK_OPT_PROBE, "verify", "modgen"):
        assert runner.invoke(cli.app, [name, "--help"]).exit_code == 0


def test_未知选项仍然会红() -> None:
    """② 负例：允许集**没有**被放成「什么都行」。

    实测 `v3 citations --definitely-not-a-flag` = exit 2（Click 的 UsageError）⇒
    判据必须照样把它报出来；两半都断言，免得以后有人只把允许集放宽、没留反向那一半。
    """
    bogus = "--definitely-not-a-flag"
    assert runner.invoke(cli.app, [_FRAMEWORK_OPT_PROBE, bogus]).exit_code == 2
    assert bogus not in framework_options()
    flagged = _option_offenders([("<合成片段>", 1, f"v3 {_FRAMEWORK_OPT_PROBE} {bogus}")])
    assert len(flagged) == 1
    assert bogus in flagged[0]
    # 反向：同一段里合法的通用选项不该被报（否则文档一提 `--help` 就红，等于回到修复前）
    assert _option_offenders([("<合成片段>", 1, f"v3 {_FRAMEWORK_OPT_PROBE} --help")]) == []


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
