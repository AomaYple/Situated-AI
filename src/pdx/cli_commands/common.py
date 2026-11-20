"""Shared terminal output, exit codes, and CLI preconditions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from pdx import config, snapshot, version_contracts
from pdx.console import enable_utf8_stdio
from pdx.parser import TOLERATED_ERRORS

if TYPE_CHECKING:
    from pathlib import Path

# 必须在构造 Console 之前调用 —— 理由见 pdx/console.py 的模块文档：
# rich 替代不了编码兜底，GBK 重定向下它自己就会抛 UnicodeEncodeError。
enable_utf8_stdio()

console = Console()

#: 「检查未通过」——只有真跑了检查、且结论是不一致时才用。
EXIT_FAILED = 1
#: 「用法错误 / 前置条件缺失」——click 对未定义选项、缺参数也用这个码，
#: 我们把「产物不存在」「命名空间不存在」也归到这一类，保持口径一致。
EXIT_USAGE = 2
#: 「核对不了」——检查确实跑了，但**输入使结论不可得**（不是通过，也不是不通过）。
#:
#: 只有 ``crosscheck`` 用它，且只用在一种情形上：引擎日志核对的那个文件
#: 被 mod 覆盖、覆盖版与原版**不是同一套行号**（行数不同）⇒ 「token 在不在
#: 那一行」这个问题本身无从回答。口径同 ``unverifiable_files`` 的 docstring：
#: 判据是可测事实（行数），不看「我们认不认识那个 mod」。
#:
#: ⚠️ 不许把它读成「软化的红」：真错配（行号可比、token 就在别的行）仍然走
#: :data:`EXIT_FAILED`。这一族教训见历史审计 B85 ——
#: 「我们在 error.log 里没看到」曾被当成「没有」，把「核不了」写成了「对不上」。
EXIT_UNVERIFIABLE = 3


#: 读取已落盘产物时**可预期**的失败集合。
#:
#: 由「文件读不了」（:data:`pdx.parser.TOLERATED_ERRORS`，与解析器同一套
#: 口径）加「JSON 本身坏了」组成。刻意不含 ``Exception``：那会把代码 bug
#: （属性名打错、类型不符）降级成「产物缺失」，是最难查的一类问题 ——
#: 它让错误静默地变成合法输出。
READ_ERRORS: tuple[type[BaseException], ...] = (
    *TOLERATED_ERRORS,
    json.JSONDecodeError,
    snapshot.SnapshotFormatError,
)


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """报错并终止。默认退出码 2（前置条件缺失），见模块文档。"""
    console.print(f"[red]{escape(message)}[/]")
    raise typer.Exit(code)


def relative(path: Path) -> str:
    """优先显示仓库相对路径，不在仓库内时退回绝对路径。

    不能照抄 ``run_analyze.py`` 的 ``p.relative_to(Path.cwd())``：只要不是
    从仓库根运行就抛 ValueError。``v3`` 是装进 PATH 的命令，从任何目录调用
    都合理，因此基准换成仓库根 ``config.REPO``，并保留兜底。
    """
    try:
        return str(path.relative_to(config.REPO))
    except ValueError:
        return str(path)


def require_workspace() -> None:
    """Reject operations that need the repository's files or output directories."""
    if config.WORKSPACE_ROOT is None:
        fail("此命令需要完整的 Situated AI 工作区。请在项目根目录运行。")


def require_game(*, optional: bool = False) -> None:
    """在读取本机原版前核对安装身份。"""
    if optional and not config.ROOT.is_dir() and not config.GAME.is_dir():
        return
    if not config.GAME.is_dir():
        fail(f"前置条件缺失：找不到游戏目录 {config.GAME}（可用环境变量 V3_ROOT 指定）")
    try:
        installation = config.ROOT.resolve(strict=True)
        if config.GAME.resolve(strict=True) != installation / "game":
            raise ValueError("内容目录与 V3_ROOT 的 game/ 不一致")
        version_contracts.verify_installation_identity(installation)
    except (OSError, ValueError) as exc:
        fail(f"无法使用本机原版（V3_ROOT）：{exc}")


def require_current_output() -> None:
    try:
        version_contracts.require_current()
    except ValueError as exc:
        fail(str(exc))


def require_file(path: Path, what: str, hint: str = "") -> None:
    """前置条件：某个输入文件必须存在。"""
    if not path.is_file():
        suffix = f"（{hint}）" if hint else ""
        fail(f"{what}不存在：{path}{suffix}")


def write_json(path: Path, payload: Any) -> None:
    """写 JSON 并回报字节数。失败即终止，绝不「写了但没说」。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        fail(f"无法写入 {path}：{type(exc).__name__}: {exc}")
    console.print(f"[green]已写入[/] {escape(relative(path))}  ({path.stat().st_size:,} 字节)")
