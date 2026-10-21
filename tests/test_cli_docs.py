"""检查当前操作文档中的 CLI 命令和选项；历史记录保留当时的命令文本。"""

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

#: 退役变更说明命令与未接线编排器。仅允许以下原始历史记录保留旧调用；
#: 当前操作文档仍须通过命令存在性检查，其他未知命令不享有历史豁免。
HISTORICAL_COMMAND_REFERENCES: dict[str, frozenset[str]] = {
    "release": frozenset(
        {
            "docs/design/exec/阶段4-压力剧本-首跑.md",
            "docs/design/exec/阶段7-版本演练-1.14.4.md",
        }
    ),
    "ab-auto": frozenset(
        {
            "docs/design/exec/阶段3-结果.md",
            "docs/design/exec/阶段3-实验记录.md",
        }
    ),
}

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
    archived_exec_docs = {
        "docs/design/exec/README.md",
        "docs/design/exec/工程基线-1.0.md",
        "docs/design/exec/mod重设计-实施计划.md",
    }
    for root in (config.DOCS, config.REPO / "docs"):
        for path in sorted(root.rglob("*.md")):
            if path in seen:
                continue
            if path.is_relative_to(config.REPORTS):
                continue  # 历史复核报告保留失败命令作为证据，不是操作手册。
            seen.add(path)
            document = path.relative_to(config.REPO).as_posix()
            if document.startswith(
                (
                    "docs/audits/",
                    "docs/reports/",
                    "docs/victoria3-modding/",
                    "docs/superpowers/",
                )
            ):
                continue  # 日期化证据和知识库保留当时的复现方式，不是当前操作入口。
            if document in {"docs/design/backlog.md", "docs/design/01a-依据与参考.md"}:
                continue
            if document.startswith("docs/design/exec/") and document not in archived_exec_docs:
                continue  # 执行索引仅列的三份当前文档参与命令接口检查。
            fenced = False
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("```"):
                    fenced = not fenced
                    continue
                if fenced:
                    body = line.split("#", 1)[0]
                    for piece in _SPLIT.split(body):
                        if piece.strip():
                            yield document, lineno, piece
                else:
                    for span in _SPAN.findall(line):
                        yield document, lineno, span


def _command_offenders(frags: Iterable[tuple[str, int, str]] | None = None) -> list[str]:
    tree = _command_tree()
    return [
        f"{doc}:{lineno} 未知子命令 {name!r} —— {frag.strip()[:80]}"
        for doc, lineno, frag in (fragments() if frags is None else frags)
        for name in _INVOCATION.findall(frag)
        if name not in tree
        and name not in SKIP
        and doc not in HISTORICAL_COMMAND_REFERENCES.get(name, frozenset())
    ]


def test_文档里的v3命令都有对应的子命令() -> None:
    bad = _command_offenders()
    assert not bad, "文档提到了 CLI 里不存在的子命令：\n  " + "\n  ".join(bad[:15])


@pytest.mark.parametrize(
    ("command", "document"),
    [
        ("release", "docs/design/exec/阶段7-版本演练-1.14.4.md"),
        ("ab-auto", "docs/design/exec/阶段3-实验记录.md"),
    ],
)
def test_退役命令只允许出现在登记的历史记录中(command: str, document: str) -> None:
    assert runner.invoke(cli.app, [command, "--help"]).exit_code == 2
    bad = _command_offenders(
        [
            (document, 22, f"v3.exe {command} --help"),
            ("CONTRIBUTING.md", 3, f"v3 {command}"),
            (document, 24, "v3 definitely-missing"),
            ("docs/guides/操作指南.md", 5, f"v3 {command}"),
        ]
    )
    assert len(bad) == 3
    assert "CONTRIBUTING.md:3" in bad[0]
    assert f"'{command}'" in bad[0]
    assert f"{document}:24" in bad[1]
    assert "'definitely-missing'" in bad[1]
    assert "docs/guides/操作指南.md:5" in bad[2]


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


def test_片段切分不会漏掉代码块里的命令(tmp_path, monkeypatch) -> None:
    """围栏内的并列命令与内联命令都被独立提取，不依赖某份旧文档仍存在。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "操作指南.md").write_text(
        "```text\nv3.exe modgen --check; v3.exe verify # 注释\n```\n"
        "`v3 tables` 和 `v3 ai-surface --check`\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "DOCS", docs)
    frags = list(fragments())
    assert [fragment.strip() for _doc, _line, fragment in frags] == [
        "v3.exe modgen --check",
        "v3.exe verify",
        "v3 tables",
        "v3 ai-surface --check",
    ]
    assert _command_offenders(frags) == []
    assert _option_offenders(frags) == []
