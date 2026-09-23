"""单一命令行入口 ``v3``。

动机
----
收敛之前，``tools/`` 下有 7 个各自为政的入口：4 个 argparse 脚本、1 个自带
subparsers 的脚本、2 个裸脚本（``show_outputs.py`` 连 ``main()`` 都没有，
靠 import 时的副作用输出）。它们各自重复了同一套样板：

* 手写 ``sys.stdout.reconfigure`` 编码兜底 —— 7 份拷贝，抄漏一份就有一条
  命令在 GBK 控制台上崩掉（现在统一走 :mod:`pdx.console`）
* 手写 ``"─" * 64`` 分隔线与 ``f"{name:<58}"`` 对齐 —— 列宽一改就全乱
* ``--json`` 语义各不相同：``run_verify.py`` 里是路径，
  ``run_defines.py`` / ``run_snapshot.py`` 里是布尔开关，落点还写死在代码里
* 退出码各写各的：``run_defines.py`` 用 1 表示「未找到命名空间」，
  与「检查未通过」撞在一起

收敛成一个 typer 应用后，这些约定只有一处定义，``--help`` 也只有一份。

退出码约定
----------
====  ==============================================================
0     成功
1     检查未通过（``verify`` / ``check-outputs`` / ``snapshot verify``）
2     用法错误，或前置条件缺失（游戏目录、产物、快照文件不存在）
====  ==============================================================

三者之外不存在「吞掉异常然后返回 0」的路径：需要容错时只捕
:data:`pdx.parser.TOLERATED_ERRORS` 这样的精确异常集合，并且必须把失败
原因打出来 —— 静默跳过是让检查表腐烂的最快方式。
"""

from __future__ import annotations

import json
import shutil
import time

# Path 必须能**在运行期**导入：typer 用 ``inspect.signature(eval_str=True)``
# 解析命令签名，注解挪进 TYPE_CHECKING 块会让 ``v3 --help`` 直接 NameError（已实测）。
# 另外 `v3 citations` 会真的构造 `Path`，所以它本来就是运行期依赖，不需要 TCH 豁免。
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table

from pdx import (
    ab,
    ab_auto,
    ab_probe,
    ai_surface,
    analyze,
    assets,
    backlog,
    cache,
    citations,
    config,
    covgate,
    defines,
    doc_tables,
    docgen,
    docs_mirror,
    engine_log,
    evidence,
    exe_strings,
    experiments,
    h1,
    h1_probe,
    lockfile,
    modgen,
    modguard,
    preflight,
    release,
    snapshot,
    tables_offline,
    tabular,
    unknowns,
    verify,
)
from pdx import mods as mods_mod
from pdx.console import enable_utf8_stdio
from pdx.extract import extract_dir
from pdx.parser import TOLERATED_ERRORS, parse_file

# 必须在构造 Console 之前调用 —— 理由见 pdx/console.py 的模块文档：
# rich 替代不了编码兜底，GBK 重定向下它自己就会抛 UnicodeEncodeError。
enable_utf8_stdio()

console = Console()

#: 「检查未通过」——只有真跑了检查、且结论是不一致时才用。
EXIT_FAILED = 1
#: 「用法错误 / 前置条件缺失」——click 对未定义选项、缺参数也用这个码，
#: 我们把「产物不存在」「命名空间不存在」也归到这一类，保持口径一致。
EXIT_USAGE = 2

app = typer.Typer(
    name="v3",
    help="Victoria 3 mod 开发研究工具链：全量分析、defines 提取、断言核对与产物核验。",
    # typer 默认会为 `--install-completion` 生成补全脚本并写进用户目录
    # （~/.bash_completion 等）。工具链不该在用户不知情时接管家目录，
    # 因此关掉 —— 代价是没有 shell 补全，换来的是「装包不留痕」。
    add_completion=False,
    no_args_is_help=True,
)


# ── 公共辅助 ────────────────────────────────────────────────
#: 读取已落盘产物时**可预期**的失败集合。
#:
#: 由「文件读不了」（:data:`pdx.parser.TOLERATED_ERRORS`，与解析器同一套
#: 口径）加「JSON 本身坏了」组成。刻意不含 ``Exception``：那会把代码 bug
#: （属性名打错、类型不符）降级成「产物缺失」，是最难查的一类问题 ——
#: 它让错误静默地变成合法输出。
_READ_ERRORS: tuple[type[BaseException], ...] = (*TOLERATED_ERRORS, json.JSONDecodeError)


def _fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """报错并终止。默认退出码 2（前置条件缺失），见模块文档。"""
    console.print(f"[red]{escape(message)}[/]")
    raise typer.Exit(code)


def _relative(path: Path) -> str:
    """优先显示仓库相对路径，不在仓库内时退回绝对路径。

    不能照抄 ``run_analyze.py`` 的 ``p.relative_to(Path.cwd())``：只要不是
    从仓库根运行就抛 ValueError。``v3`` 是装进 PATH 的命令，从任何目录调用
    都合理，因此基准换成仓库根 ``config.REPO``，并保留兜底。
    """
    try:
        return str(path.relative_to(config.REPO))
    except ValueError:
        return str(path)


def _require_game() -> None:
    """前置条件：游戏安装目录必须存在。

    缺了就退出码 2，而不是让它一路跑出满屏的「0 个文件」—— 后者看起来像
    「分析成功但游戏里没内容」，是最容易被误信的失败形态。
    """
    if not config.GAME.is_dir():
        _fail(f"找不到游戏目录 {config.GAME}（可用环境变量 V3_ROOT 指定）")


def _require_file(path: Path, what: str, hint: str = "") -> None:
    """前置条件：某个输入文件必须存在。"""
    if not path.is_file():
        suffix = f"（{hint}）" if hint else ""
        _fail(f"{what}不存在：{path}{suffix}")


def _load_product(path: Path, label: str) -> Any:
    """读一份已落盘的分析产物。

    两种失败都算前置条件缺失：文件不在（还没跑过 analyze），或文件在但读不
    出来（截断、写坏、根本不是 JSON）。都以退出码 2 终止并说明原因。
    """
    if not path.is_file():
        _fail(f"缺少产物：{_relative(path)}（请先运行 `v3 analyze` 生成{label}）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except _READ_ERRORS as exc:
        _fail(f"产物无法读取：{_relative(path)}（{type(exc).__name__}: {exc}）")
    if not isinstance(data, dict):
        _fail(f"产物结构异常：{_relative(path)}（顶层应为对象，实为 {type(data).__name__}）")
    return data


def _write_json(path: Path, payload: Any) -> None:
    """写 JSON 并回报字节数。失败即终止，绝不「写了但没说」。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        _fail(f"无法写入 {path}：{type(exc).__name__}: {exc}")
    console.print(f"[green]已写入[/] {escape(_relative(path))}  ({path.stat().st_size:,} 字节)")


def _describe(value: object) -> tuple[str, str]:
    """把一个 JSON 值描述成「类型 + 规模」。标量直接给值，长值截断。"""
    if isinstance(value, dict):
        return "字典", f"{len(value):,} 个键"
    if isinstance(value, list):
        return "列表", f"{len(value):,} 项"
    text = str(value)
    return type(value).__name__, text if len(text) <= 60 else f"{text[:59]}…"


def _structure_table(title: str, data: Any) -> Table:
    """把一层 JSON 对象的字段结构渲染成表格。"""
    table = Table(title=title or None, show_lines=False)
    table.add_column("字段")
    table.add_column("类型", style="dim")
    table.add_column("规模", justify="right", style="cyan")
    for key, value in data.items():
        kind, scale = _describe(value)
        table.add_row(escape(str(key)), kind, escape(scale))
    return table


def _size_text(path: Path) -> str:
    """文件大小的可读形式。文件不在就返回破折号 —— 表里不能因此缺行。"""
    if not path.is_file():
        return "—"
    n = path.stat().st_size
    return f"{n / 1048576:.2f} MB" if n > 1048576 else f"{n / 1024:.0f} KB"


# ── analyze ─────────────────────────────────────────────────
def _profile_run(
    *, with_mods: bool, with_cross: bool
) -> tuple[analyze.GameAnalysis, analyze.ModsAnalysis, analyze.CrossAnalysis, Any]:
    """用 pyinstrument 包住整个分析流程。

    pyinstrument 给的是**调用树**而不是我自己分段的粗粒度计时 —— 能直接
    看到时间花在哪个函数上，比手工埋点精确得多。

    ``--profile`` 下同样尊重 ``--no-mods`` / ``--no-cross``：旧脚本在剖析
    分支里漏判了 ``--no-cross``，两条路径的口径不该有差别。
    """
    # pyinstrument 是 dev 依赖。顶层导入会让没装 dev extras 的环境连
    # `v3 --help` 都跑不起来，所以只在这里按需导入。
    try:
        from pyinstrument import Profiler  # noqa: PLC0415
    except ImportError as exc:
        _fail(f'--profile 需要 pyinstrument，请先 pip install -e ".[dev]"：{exc}')

    profiler = Profiler(interval=0.001)
    profiler.start()

    ga = analyze.game_analysis()
    ma = analyze.ModsAnalysis()
    ca = analyze.CrossAnalysis()
    if with_mods:
        ma = analyze.mods_analysis()
        if with_cross:
            ca = analyze.cross_analysis(ma, verbose=False)

    profiler.stop()
    return ga, ma, ca, profiler


@app.command("analyze")
def analyze_cmd(
    mods: Annotated[
        bool, typer.Option("--mods/--no-mods", help="分析全部 mod（关闭则只看游戏本体）")
    ] = True,
    cross: Annotated[
        bool, typer.Option("--cross/--no-cross", help="做 mod 与原版的交叉分析")
    ] = True,
    write: Annotated[
        bool, typer.Option("--write/--no-write", help="把 JSON 与 Markdown 落盘")
    ] = True,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="不打印进度")] = False,
    profile: Annotated[
        bool, typer.Option("--profile", help="用 pyinstrument 输出调用树剖析")
    ] = False,
) -> None:
    """全量分析游戏本体与全部 mod。

    三段流水线默认全做：游戏本体 → mod → 交叉分析。--no-mods 只分析游戏
    本体；--no-cross 保留 mod 分析但不做覆盖关系交叉。--profile 用
    pyinstrument 输出调用树（仍然落盘），--quiet 关掉进度行。
    """
    _require_game()
    started = time.perf_counter()

    if profile:
        ga, ma, ca, profiler = _profile_run(with_mods=mods, with_cross=cross)
        elapsed = time.perf_counter() - started
        console.print()
        # 剖析结果是预格式化文本：关掉 markup/highlight/折行，免得被 rich 重排。
        console.print(
            profiler.output_text(unicode=True, color=False, show_all=False),
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
    else:
        if not quiet:
            console.print("[cyan]▶ 分析游戏本体 …[/]")
        ga = analyze.game_analysis()
        ma = analyze.ModsAnalysis()
        ca = analyze.CrossAnalysis()

        if mods:
            if not quiet:
                console.print("[cyan]▶ 分析 mod …[/]")
            ma = analyze.mods_analysis()

        if mods and cross:
            if not quiet:
                console.print("[cyan]▶ 交叉分析 …[/]")
            ca = analyze.cross_analysis(ma, verbose=False)

        elapsed = time.perf_counter() - started

    if write:
        paths = analyze.write_reports(ga, ma, ca)
        table = Table(title="产出", show_lines=False)
        table.add_column("类型")
        table.add_column("文件", style="cyan")
        table.add_column("字节", justify="right")
        for name, path in paths.items():
            table.add_row(escape(name), escape(_relative(path)), f"{path.stat().st_size:,}")
        console.print(table)

    console.print(f"\n总耗时 {elapsed:.1f} 秒")


# ── defines ─────────────────────────────────────────────────
@app.command("defines")
def defines_cmd(
    ns: Annotated[
        str | None,
        typer.Option("--ns", metavar="NAME", help="展开该命名空间的全部参数"),
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="把提取结果写入该 JSON 文件")
    ] = None,
    overlay: Annotated[
        Path | None,
        typer.Option("--overlay", help="预览该 mod defines 文件会覆盖哪些原版参数"),
    ] = None,
) -> None:
    """提取 defines 的命名空间与参数（游戏层 + Jomini 层）。

    默认只打摘要。--ns NAI 展开某个命名空间（即旧脚本的 --ai）；
    --overlay 预览一段 mod defines 的覆盖与新增范围；--json 落盘完整结构。
    命名空间不存在时退出码为 2 —— 旧脚本返回 1，与「检查未通过」撞车。

    > 早先这里还有一个 ``--tables``，用来重算 doc 05 的统计表。
    > 它已并入 **``v3 tables``** —— 那个命令同时覆盖 doc 05 与 doc 19，
    > 而且**默认就是核对**（不一致即退出码 1），因此能进 CI。
    """
    _require_game()

    reports = defines.extract_all_defines()
    game = reports["game"]

    table = Table(title="defines 提取", show_lines=False)
    table.add_column("来源")
    table.add_column("涉及文件", justify="right")
    table.add_column("命名空间块", justify="right")
    table.add_column("去重命名空间", justify="right")
    table.add_column("参数", justify="right", style="cyan")
    table.add_column("@变量", justify="right")
    for label, report in reports.items():
        summary = report.summary()
        table.add_row(
            escape(label),
            f"{summary['涉及文件']:,}",
            f"{summary['命名空间块数']:,}",
            f"{summary['去重命名空间']:,}",
            f"{summary['参数总数']:,}",
            f"{summary['@变量数']:,}",
        )
    console.print(table)

    # 直接读 namespace_files 而不是 summary()["跨文件重复的命名空间"]：
    # 后者的静态类型是 object，用它就得 cast 或绕过类型检查。
    duplicates = {name: files for name, files in game.namespace_files.items() if len(files) > 1}
    if duplicates:
        dup_table = Table(
            title="跨文件重复的命名空间（引擎按块名合并的直接证据）", show_lines=False
        )
        dup_table.add_column("命名空间")
        dup_table.add_column("出现的文件", style="dim")
        for name, files in duplicates.items():
            dup_table.add_row(escape(name), escape(", ".join(files)))
        console.print(dup_table)

    if overlay is not None:
        _require_file(overlay, "overlay 文件")
        # overlay() 返回的是嵌套的杂类字典（静态类型只有 object），这里按
        # JSON 语义消费，故整体当作 Any 处理。
        preview: Any = defines.overlay(game, overlay.read_text(encoding="utf-8-sig"))
        preview_table = Table(
            title=f"覆盖预览：{preview['命名空间数']} 个命名空间", show_lines=False
        )
        preview_table.add_column("状态")
        preview_table.add_column("命名空间")
        preview_table.add_column("覆盖参数", justify="right", style="cyan")
        preview_table.add_column("新增参数", justify="right", style="green")
        preview_table.add_column("样例（各取前 8 个）", style="dim")
        for item in preview["明细"]:
            covered = list(item.get("覆盖参数") or [])
            added = list(item.get("新增参数") or [])
            sample = ", ".join([*covered[:8], *added[:8]])
            preview_table.add_row(
                escape(str(item["状态"])),
                escape(str(item["命名空间"])),
                f"{len(covered):,}",
                f"{len(added):,}",
                escape(sample) or "—",
            )
        console.print(preview_table)

    if ns:
        hits = game.get(ns)
        if not hits:
            _fail(f"未找到命名空间 {ns}")
        for hit in hits:
            console.rule(f"{hit.name}  ({hit.file}:{hit.line})  {hit.count} 个参数")
            params = Table(show_header=True, header_style="bold", show_lines=False)
            params.add_column("参数")
            params.add_column("形态", style="dim")
            params.add_column("值", style="cyan")
            for param in hit.params:
                if param.kind == defines.SCALAR:
                    params.add_row(escape(param.name), "", escape(param.value))
                else:
                    params.add_row(escape(param.name), escape(param.kind), f"×{param.elements}")
            console.print(params)

    if json_out is not None:
        _write_json(
            json_out,
            {
                label: {
                    "概览": report.summary(),
                    "命名空间": [n.to_dict() for n in report.namespaces],
                    "@变量": [
                        {"名称": name, "值": value, "行": line}
                        for name, value, line in report.variables
                    ],
                }
                for label, report in reports.items()
            },
        )


# ── index ───────────────────────────────────────────────────
#: 全量键名索引的落点。由 `v3 index` 重新生成。
OUT_INDEX_DOC = config.DOCS / "13-common全量键名索引.md"


def _build_index_doc() -> tuple[str, dict[str, int]]:
    """生成键名索引正文与统计。

    口径由 :mod:`pdx` 包保证（BOM 剥离、引号感知注释、花括号深度判定、
    连字符键名）—— 这正是它取代早期 PowerShell 正则版的理由。
    """
    common = config.GAME / "common"
    dirs = sorted(p for p in common.iterdir() if p.is_dir())

    rows: list[str] = []
    total_entries = 0
    total_files = 0

    for directory in dirs:
        result = extract_dir(directory)
        keys = sorted(result.entries)
        total_entries += len(keys)
        total_files += result.files

        md = ", ".join(sorted(p.name for p in directory.glob("*.md")))
        sample = ", ".join(keys[:6]) if keys else "—"
        rows.append(
            f"| `{directory.name}` | {result.files} | {len(keys)} | {md or '—'} | {sample} |"
        )

    # `common\` 根下散装的 .txt（实测只有 achievement_groups.txt 一个）。
    # 它们不属于任何子目录，所以逐目录表覆盖不到 —— 但**必须收录**，
    # 否则「全量键名索引」名不副实（那些键在正文里一处都查不到）。
    # 同时把「子目录合计」与「全树合计」的差额写进文档，免得
    # 「本索引 3,025 个文件」与「common 全树 3,026 个 .txt」被当成矛盾。
    loose_files = sorted(common.glob("*.txt"))
    loose_rows: list[str] = []
    for path in loose_files:
        keys = sorted(parse_file(path).top_keys)
        total_entries += len(keys)
        loose_rows.append(
            f"| `{path.name}` | {len(keys)} | {', '.join(f'`{k}`' for k in keys) or '—'} |"
        )
    all_txt = total_files + len(loose_files)

    stats = {
        "目录数": len(dirs),
        "文件总数": total_files,
        "条目总数": total_entries,
    }

    tail = ""
    if loose_rows:
        tail = (
            f"\n## `common\\` 根下的散装文件（{len(loose_files)} 个）\n\n"
            "这些 `.txt` 不在任何子目录里，上面的逐目录表覆盖不到，单独列出：\n\n"
            "| 文件 | 顶层条目 | 顶层键 |\n|---|---:|---|\n" + "\n".join(loose_rows) + "\n"
            "\n> 键名重复是**如实反映**，不是 bug：PDX 允许同级重复键，"
            "而 `parse_file(...).top_keys` 如实返回全部出现。\n"
        )

    head = f"""# 13 · common 全量键名索引

> 对 `game\\common\\` 下**全部 {len(dirs)} 个子目录** + 根下 **{len(loose_files)} 个散装 `.txt`**
> 做机械提取，共 **{total_entries:,} 个顶层条目**。
> 本文回答「**什么东西定义在哪个目录**」。

> 数据版本：Victoria 3 `{config.game_version().get("caligula_branch", "?")}`
> （`caligula_rev = {config.game_version().get("caligula_rev", "?")[:12]}…`）。
> 本文**每次运行 `v3 index` 都会整体重新生成**，因此其中的数字始终对应当前安装，
> 不存在「文档数字过期」的问题 —— 这也是它与其他主题文档的区别。

## 提取口径

本索引由 `v3 index` 生成（实现见 `tools/pdx/cli.py`），口径如下：

```text
顶层判定   花括号深度 == 0，**与缩进无关**
编码       utf-8-sig，自动剥离 BOM
注释       引号感知地剥离 # 到行尾（在花括号计数之前）
键名字符集  非空白、非花括号、非等号、非引号（因此支持连字符）
@变量      不计入条目
```

**逐目录统计 + 根下散装文件**：本索引按 `common\\` 的 {len(dirs)} 个子目录逐个提取，
合计 **{total_files:,} 个文件**；`common\\` 根下另有 **{len(loose_files)} 个散装 `.txt`**
（{", ".join(p.name for p in loose_files) or "无"}）不在任何子目录里，列在本文末尾。
所以「本索引 {total_files:,} 个文件」与「`common` 全树 {all_txt:,} 个 `.txt`」
差的就是这 {len(loose_files)} 个 —— 两者都对，只是口径不同，**不要为了对齐而互相改**。

## 勘误记录

### 勘误 1：早期版本漏计含连字符的键

早期版本用**枚举字符类**匹配键名，静默漏掉了含连字符 `-` 的键。
全库共 **32 个**，分布在 4 个目录：

| 目录 | 含连字符键数 | 修正前 | 修正后 |
|---|---:|---:|---:|
| `character_templates` | 27 | 1,983 | **2,011** |
| `production_methods` | 3 | 433 | **436** |
| `technology` | 1 | 183 | **184** |
| `power_bloc_names` | 1 | 199 | **200** |

### 勘误 2：早期版本漏计文件首键（BOM）与缩进的顶层键

`common` 下 {all_txt:,} 个 `.txt` 中 **3,002 个带 UTF-8 BOM**，且部分文件的顶层键**带前导空格**。
用「行首无缩进」判定顶层的做法会漏掉它们。实测 `static_modifiers` 因此少算 7 个：

| 目录 | 修正前 | 修正后 |
|---|---:|---:|
| `static_modifiers` | 6,121 | **6,128** |

### 勘误 3：`.txt` 文件数曾用非递归统计

5 个含子目录的目录受影响：`history` 0→1152、`coat_of_arms` 0→23、
`technology` 0→4、`defines` 6→9、`terrain_manipulators` 1→2。

> **三条勘误的共同教训**：解析 PDX 数据不要假设字符集、不要假设文件平铺、
> 不要用缩进判断结构。全部改用花括号深度 + `utf-8-sig` + 取反字符组。

## 全部 {len(dirs)} 个目录

| 目录 | .txt 文件 | 顶层条目 | 官方文档 | 条目示例（前 6 个） |
|---|---:|---:|---|---|
"""
    return head + "\n".join(rows) + "\n" + tail, stats


@app.command("index")
def index_cmd(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只打印统计，不写文件")] = False,
) -> None:
    """重新生成 docs/victoria3-modding/13-common全量键名索引.md。

    取代早期用 PowerShell 正则生成的那一版：本版由 pdx 包驱动，因此自动
    获得 BOM 剥离、引号感知注释、花括号深度判定与连字符键名支持。
    """
    _require_game()
    text, stats = _build_index_doc()

    table = Table(title="键名索引统计", show_lines=False)
    table.add_column("项目")
    table.add_column("数值", justify="right", style="cyan")
    for key, value in stats.items():
        table.add_row(escape(key), f"{value:,}")
    console.print(table)

    if dry_run:
        console.print("[yellow]--dry-run：未写文件[/]")
        return

    try:
        # newline="\n"：见 analyze.dump 的注释 —— 否则文档在 Windows 上写成
        # CRLF，与 .gitattributes 的 eol=lf 打架，每次 `v3 index` 都弄脏工作树。
        OUT_INDEX_DOC.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        _fail(f"无法写入 {OUT_INDEX_DOC}：{type(exc).__name__}: {exc}")
    console.print(
        f"[green]已写入[/] {escape(_relative(OUT_INDEX_DOC))}  "
        f"行数 {len(text.splitlines()):,}  字节 {OUT_INDEX_DOC.stat().st_size:,}"
    )


# ── snapshot ────────────────────────────────────────────────
snapshot_app = typer.Typer(
    help="游戏版本快照：捕获某个版本的全部 mod 相关信息，Paradox 增删字段时一次 diff 就能全部发现。",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(snapshot_app, name="snapshot")


def _load_snapshot(path: Path) -> snapshot.Snapshot:
    """读快照。文件损坏属前置条件缺失，退出码 2。"""
    try:
        return snapshot.Snapshot.load(path)
    except _READ_ERRORS as exc:
        _fail(f"快照无法读取：{_relative(path)}（{type(exc).__name__}: {exc}）")


@snapshot_app.command("create")
def snap_create(
    label: Annotated[str | None, typer.Option("--label", help="快照名（默认为游戏版本号）")] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="精简模式：本地化只留计数与指纹，体积约 1/9，可入库"),
    ] = False,
) -> None:
    """生成当前版本快照，写入 tools/out/snapshots/。

    默认是**完整快照**（约 39 MiB，本地用，不入库）。
    ``--compact`` 产出**精简快照**（约 6.0 MiB）：结构域原样保留，
    只把 ``localization`` 的 14 万条键名换成「键数 + sha256」——
    小到可以随仓库分发，让「升级前后 diff 出字段增删」在别的机器上也能做。
    """
    _require_game()
    snap = snapshot.build(compact=compact, verbose=True)
    target = label or snap.version_label.replace("/", "-")
    if compact:
        target = f"{target}.compact"
    path = snapshot.snapshot_path(target)
    snap.write(path)

    counts = snap.counts()
    console.print(f"[green]已写入[/] {escape(_relative(path))}")
    console.print(
        f"域 {len(snap.sections)} 个，条目总计 {sum(counts.values()):,}，"
        f"字节 {path.stat().st_size:,}"
    )

    table = Table(show_lines=False)
    table.add_column("域")
    table.add_column("项", justify="right")
    table.add_column("条目", justify="right", style="cyan")
    for section, body in snap.sections.items():
        table.add_row(
            escape(section),
            f"{len(body):,}",
            f"{sum(len(names) for names in body.values()):,}",
        )
    console.print(table)


@snapshot_app.command("list")
def snap_list() -> None:
    """列出已有快照及其规模。"""
    paths = snapshot.list_snapshots()
    if not paths:
        console.print("[yellow]尚无快照。先运行 `v3 snapshot create`。[/]")
        return

    table = Table(title=f"共 {len(paths)} 份快照", show_lines=False)
    table.add_column("快照")
    table.add_column("版本")
    table.add_column("条目", justify="right", style="cyan")
    table.add_column("字节", justify="right")
    for path in paths:
        # 单份快照读不了不该让整个列表失败（旧脚本也是这样），但必须把
        # 异常类型与消息打出来，而不是显示成一个空行。
        try:
            snap = snapshot.Snapshot.load(path)
        except _READ_ERRORS as exc:
            table.add_row(
                escape(path.name),
                "[red]读取失败[/]",
                "—",
                escape(f"{type(exc).__name__}: {exc}"),
            )
            continue
        total = sum(len(names) for body in snap.sections.values() for names in body.values())
        table.add_row(
            escape(path.name),
            escape(snap.version_label),
            f"{total:,}",
            f"{path.stat().st_size:,}",
        )
    console.print(table)


@snapshot_app.command("diff")
def snap_diff(
    older: Annotated[str, typer.Argument(help="旧快照名（不含 .json）")],
    newer: Annotated[str, typer.Argument(help="新快照名")],
    detail: Annotated[bool, typer.Option("--detail", help="列出增删明细")] = False,
    json_out: Annotated[Path | None, typer.Option("--json", help="把差异写入该 JSON 文件")] = None,
) -> None:
    """比对两份快照，列出字段与条目的增删。

    检测到变更**不算失败**（退出码仍为 0）—— 变更是这个命令要报告的事实，
    不是错误。快照文件不存在时退出码 2。
    """
    a_path = snapshot.snapshot_path(older)
    b_path = snapshot.snapshot_path(newer)
    for path in (a_path, b_path):
        _require_file(path, "快照", "可用 `v3 snapshot list` 查看已有快照")

    a = _load_snapshot(a_path)
    b = _load_snapshot(b_path)

    console.rule(f"对比 {a.version_label}  →  {b.version_label}")
    console.print(
        f"A rev [dim]{escape(a.version.get('caligula_rev', '?'))}[/]    "
        f"B rev [dim]{escape(b.version.get('caligula_rev', '?'))}[/]"
    )

    changes = snapshot.compare(a, b)
    if not changes:
        console.print("[green]两份快照完全一致 —— 没有检测到任何字段增删。[/]")
        return

    # 域集合不同 = 两份快照不是**同一个口径**拍的（常见于拿入库的旧快照比新版：
    # 域是逐轮加上去的）。此时差异里混着「格式变化」，不能当成原版变化读 ——
    # 1.14.3 那份只有 6 个域（localization 存明细），1.14.4 有 14 个
    # （localization 换成 localization_digest + ai_surface/vocabulary 等），
    # 直接 diff 会报出 116 万条「删除」，而真正的原版变化只有几百处。
    only_a = sorted(set(a.sections) - set(b.sections))
    only_b = sorted(set(b.sections) - set(a.sections))
    if only_a or only_b:
        console.print(
            f"[yellow]⚠️ 两份快照的**域集合不同**[/] —— 下面的差异里混着格式变化，"
            f"别直接当成原版变化读。\n"
            f"   只有 A 有：{escape('、'.join(only_a) or '（无）')}\n"
            f"   只有 B 有：{escape('、'.join(only_b) or '（无）')}\n"
            f"   可比的是两侧都有的域：{escape('、'.join(sorted(set(a.sections) & set(b.sections))))}"
        )

    summary = snapshot.diff_summary(changes)
    table = Table(title="变更", show_lines=False)
    table.add_column("域")
    table.add_column("项")
    table.add_column("新增", justify="right", style="green")
    table.add_column("删除", justify="right", style="red")
    for change in changes:
        table.add_row(
            escape(change.section),
            escape(change.name),
            f"+{len(change.added)}" if change.added else "—",
            f"-{len(change.removed)}" if change.removed else "—",
        )
    console.print(table)
    console.print(
        f"变更项 {summary['变更项数']} 处，"
        f"新增条目 {summary['新增条目']}，删除条目 {summary['删除条目']}"
    )

    if detail:
        console.rule("明细")
        for change in changes:
            console.print(f"[bold]{escape(change.section)} / {escape(change.name)}[/]")
            for name in change.added:
                console.print(f"  [green]+ {escape(name)}[/]")
            for name in change.removed:
                console.print(f"  [red]- {escape(name)}[/]")

    if json_out is not None:
        _write_json(
            json_out,
            {
                "from": {"版本": a.version, "文件": a_path.name},
                "to": {"版本": b.version, "文件": b_path.name},
                "概览": summary,
                "变更": [
                    {
                        "域": change.section,
                        "名称": change.name,
                        "新增": change.added,
                        "删除": change.removed,
                    }
                    for change in changes
                ],
            },
        )


@snapshot_app.command("verify")
def snap_verify() -> None:
    """自我一致性检查：同一环境重复生成的快照必须逐字节相同。

    不稳定就退出码 1 —— 快照一抖，diff 里全是噪声，整个机制失去意义。
    """
    _require_game()
    console.print("构建快照两次并比较 …")
    first = snapshot.build()
    second = snapshot.build()
    da = json.dumps(first.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)
    db = json.dumps(second.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)

    if da == db:
        total = sum(len(names) for body in first.sections.values() for names in body.values())
        console.print("[green]✅ 两次构建结果完全一致 —— 快照是确定性的[/]")
        console.print(f"   域 {len(first.sections)} 个，条目总计 {total:,}")
        return

    console.print("[red]❌ 两次构建结果不同 —— 快照不稳定，diff 会充满噪声[/]")
    for change in snapshot.compare(first, second)[:20]:
        console.print(escape(change.line()))
    raise typer.Exit(EXIT_FAILED)


# ── mirror（官方文档清单与本地镜像）──────────────────────────
mirror_app = typer.Typer(help="官方 .md 的清单与本地镜像。", no_args_is_help=True)
app.add_typer(mirror_app, name="mirror")


@mirror_app.command("check")
def mirror_check() -> None:
    """核对清单：与本机游戏比对，并与本地镜像比对。

    **不修改任何文件**。有差异时退出码 1 —— 因此能当门禁。

    没有游戏（或没有本地镜像）时对应的那条**跳过而非判失败**：
    一条跑不了的检查不该把退出码弄脏，否则这个门禁在任何 CI 上都是红的。
    两条都跑不了才算「什么都没查成」，此时退出 2（前置条件缺失）—— 免得空过。
    """
    if not docs_mirror.load_manifest():
        _fail(f"读不到 {docs_mirror.MANIFEST_NAME} —— 先跑 `v3 mirror write`")

    checked = 0
    bad: list[str] = []

    if (config.GAME / "common").is_dir():
        checked += 1
        against_game = docs_mirror.diff_against_game()
        if against_game:
            console.rule("[red]清单与本机游戏不一致[/]")
            bad.extend(against_game)
        else:
            console.print("[green]清单与本机游戏完全一致[/]")
    else:
        console.print("[yellow]游戏目录不可用：跳过「清单 vs 本体」[/]")

    if config.OFFICIAL_DOCS_MIRROR.is_dir():
        checked += 1
        against_mirror = docs_mirror.diff_mirror()
        if against_mirror:
            console.rule("[red]本地镜像与清单不一致[/]")
            bad.extend(against_mirror)
        else:
            console.print("[green]本地镜像与清单完全一致[/]")
    else:
        console.print("[yellow]本地镜像不存在：跳过「清单 vs 镜像」[/]")

    for line in bad[:20]:
        console.print(f"[red]❌[/] {escape(line)}")
    if len(bad) > 20:
        console.print(f"[red]…还有 {len(bad) - 20} 条[/]")

    if bad:
        raise typer.Exit(EXIT_FAILED)
    if not checked:
        _fail("既没有游戏也没有本地镜像 —— 两条比对都没跑成")


@mirror_app.command("write")
def mirror_write(
    sync: Annotated[bool, typer.Option("--sync", help="顺便把本地镜像从游戏重拷一份")] = False,
) -> None:
    """重新生成清单（要游戏）；``--sync`` 同时重建本地镜像。

    清单入库（约 17 KB），镜像不入库（Paradox 版权内容）。
    见 :mod:`pdx.docs_mirror` 的模块文档 —— 那里也写明了
    「移出版本控制 ≠ 从历史里清除」这个限制。
    """
    _require_game()
    path = docs_mirror.write_manifest()
    data = docs_mirror.load_manifest()
    console.print(
        f"[green]已写入[/] {escape(_relative(path))}  "
        f"{data.get('篇数')} 篇，{path.stat().st_size:,} 字节"
    )

    if sync:
        root = config.OFFICIAL_DOCS_MIRROR
        copied = 0
        for key, src in docs_mirror.iter_docs():
            dst = root / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied += 1
        console.print(f"[green]已同步本地镜像[/] {copied} 篇 → {escape(_relative(root))}")

    console.print(
        "[dim]清单里的字节/行数变了的话，记得同步 07-官方文档索引.md（v3 verify 会核对）[/]"
    )


# ── refresh（游戏升级后的一条命令维护）──────────────────────
@app.command("refresh")
def refresh_cmd(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只报告会改什么，不写盘")] = False,
) -> None:
    """**游戏升级后的一条命令**：重算生成表 + 按归属标记改写正文数字，再报剩下的红点。

    等价于 ``v3 tables --write`` + ``v3 verify --fix``，但按顺序做完再核一遍，
    把「机器能改的」一次改完，只把**机器改不了的**列出来给人：

    * 无标记的数字（数字不在正文里 / 在表格里 / 形态不同）；
    * 判断类内容（叙述、历史对照句 —— 登记在 ``PROSE_NOT_COMPUTED``）；
    * 断言失败（真值变了但口径也需要人看一眼的那几条）。

    为什么要有它：这两步原先要人记得按顺序跑，而**忘记跑 = 文档静默过期**，
    正是这个仓库反复踩的坑（doc 04 的 682 行活了整整一个版本、README 的
    164/226 停了两轮）。跑完退出码 0 表示全绿；否则 1，并列出剩余项。
    """
    console.rule("[bold]1/3 重算生成表[/]")
    if dry_run:
        try:
            table_drift = docgen.check_all()
        except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
            _fail(f"核对表格失败：{type(exc).__name__}: {exc}")
        if table_drift:
            console.print(f"  [yellow]--dry-run：{len(table_drift)} 行与生成结果不一致[/]")
            for doc, line, now, want in table_drift[:20]:
                console.print(f"  {escape(doc)}:{line} 现值 {escape(now)} → 生成值 {escape(want)}")
        else:
            console.print("  [green]生成表与文档一致，无需改写[/]")
    else:
        try:
            written = docgen.write_all()
        except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
            _fail(f"重算表格失败：{type(exc).__name__}: {exc}")
        rows = sum(written.values())
        console.print(f"  [green]重算 {len(written)} 张表 / {rows} 行[/]（内容没变的表不会改盘）")

    console.rule("[bold]2/3 按归属标记改写正文数字[/]")
    if dry_run:
        pending = verify.fix_markers(write=False)
        console.print(f"  [yellow]--dry-run：{len(pending)} 处需要改[/]")
        for item in pending[:20]:
            console.print(f"  {escape(item.describe())}")
    else:
        fixes = verify.fix_markers(write=True)
        if fixes:
            for item in fixes[:40]:
                console.print(f"  [cyan]{escape(item.describe())}[/]")
            console.print(f"  共改写 [bold]{len(fixes)}[/] 处")
        else:
            console.print("  [green]标记处的数字全都与断言一致[/]")

    console.rule("[bold]3/3 核验剩下的[/]")
    marker_issues = verify.check_markers()
    drift = verify.unknown_doc_drift()
    results = verify.run_claims(verify.CLAIMS, include_slow=True)
    failed = [r for r in results if not r.ok]
    console.print(
        f"  断言 {len(results) - len(failed)} / {len(results)} 通过"
        f" · 标记问题 {len(marker_issues)} · 正文漂移 {len(drift)}"
    )
    for issue in marker_issues[:10]:
        console.print(f"  [red]❌[/] {escape(issue.describe())}")
    for d in drift[:10]:
        console.print(f"  [red]❌[/] {escape(d.describe())}")
    for r in failed[:10]:
        console.print(
            f"  [red]❌[/] [{escape(r.claim.id)}] 期望 {escape(str(r.claim.expected))} 实得 {escape(str(r.actual))}"
        )
    if failed or drift or marker_issues:
        console.print(
            "[yellow]剩下的机器改不了[/] —— 上面每条都指到了具体行；"
            "判断类内容见 `test_inventory.PROSE_NOT_COMPUTED`。"
        )
        raise typer.Exit(EXIT_FAILED)
    console.print("[green]全部一致：表格、正文数字、断言。没有需要人改的东西。[/]")


# ── tables（文档里由工具生成的表格）──────────────────────────
@app.command("tables")
def tables_cmd(
    write: Annotated[bool, typer.Option("--write", help="重算并写回文档")] = False,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="不读游戏：拿**入库快照**里记录的表内容核对文档（CI 用；可配 --write）",
        ),
    ] = False,
    only: Annotated[str, typer.Option("--only", help="只处理文档名含该子串的目标")] = "",
) -> None:
    """重算文档里**由工具生成**的表格（doc 05 的 defines 表、doc 08 的目录统计表、
    doc 19 的根目录与路径表）。

    不带 ``--write`` 时是**核对**：逐行比对文档现值与生成结果，
    有任何不一致就退出码 1 —— 这样它能进 CI / pre-commit，
    而不是又一个「要记得手动跑」的脚本。

    为什么需要它：这些表原先由一批已退休的 PowerShell 脚本产出，
    之后再没人重跑过，于是 doc 05 的 5 张表**整整落后了一个游戏版本**
    （参数总数 3434 应当变 3488），doc 19 的根目录文件数也从 12 漂到 13。

    替换规则见 :mod:`pdx.doc_tables`：只动数据行，表头、分隔线与散文一律不碰；
    散文列与行的顺序按文档保留。

    **``--offline``**：算表要读游戏，CI 上没有游戏 —— 于是「表格被手改」
    一直没人守。快照里现在带着**每张表当时的数据行**，所以离线可以比对，
    也可以 ``--write`` 把表恢复成最后一次已知正确的样子。
    它证明的是「表与入库快照一致」，**不是**「表与现在的游戏一致」
    （后者仍是 `v3 refresh` 的活）。口径见 :mod:`pdx.tables_offline`。
    """
    if offline:
        _tables_offline(write=write, only=only)
        return
    if only:
        _fail("--only 只在 --offline 下有意义（在线核对是逐表与生成结果比对）")

    if write:
        try:
            done = docgen.write_all()
        except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
            _fail(f"重算表格失败：{type(exc).__name__}: {exc}")
        table = Table(title="已重算的表格", show_lines=False)
        table.add_column("文档 · 表")
        table.add_column("数据行", justify="right", style="cyan")
        for name, n in done.items():
            table.add_row(escape(name), str(n))
        console.print(table)
        return

    try:
        diff = docgen.check_all()
    except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
        _fail(f"核对表格失败：{type(exc).__name__}: {exc}")

    if not diff:
        console.print(
            f"[green]全部 {sum(len(t.specs) for t in docgen.targets())} 张生成表都与文档一致[/]"
        )
        return

    table = Table(title=f"{len(diff)} 行与生成结果不一致", show_lines=False)
    table.add_column("文档", style="dim")
    table.add_column("行", justify="right")
    table.add_column("文档现值", overflow="fold")
    table.add_column("生成值", overflow="fold")
    for doc_name, line_no, actual, expected in diff[:30]:
        table.add_row(escape(doc_name), str(line_no), escape(actual[:70]), escape(expected[:70]))
    console.print(table)
    console.print("[yellow]跑 `v3 tables --write` 可按生成结果修正[/]")
    raise typer.Exit(EXIT_FAILED)


def _tables_offline(*, write: bool, only: str) -> None:
    """``v3 tables --offline``：只读快照与文档，不读游戏。"""
    recorded = tables_offline.load_tables()
    if not recorded:
        _fail(
            "快照里没有生成表记录（域 doc_tables）—— 在装有游戏的机器上跑 "
            "`v3 snapshot create --compact` 重建一份（它是入库的）"
        )

    if write:
        try:
            done = tables_offline.restore(recorded, only=only)
        except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
            _fail(f"按快照恢复表格失败：{type(exc).__name__}: {exc}")
        if not done:
            console.print("[green]全部生成表都与快照记录一致，无需改动[/]")
            return
        table = Table(title=f"已按快照恢复 {len(done)} 张表", show_lines=False)
        table.add_column("表")
        table.add_column("数据行", justify="right", style="cyan")
        for key, n in sorted(done.items()):
            table.add_row(escape(key), str(n))
        console.print(table)
        return

    try:
        diffs, missing, orphans = tables_offline.compare(recorded, only=only)
    except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
        _fail(f"离线核对表格失败：{type(exc).__name__}: {exc}")

    if diffs:
        table = Table(title=f"{len(diffs)} 行与快照记录不一致", show_lines=False)
        table.add_column("表", style="dim")
        table.add_column("行", justify="right")
        table.add_column("文档现值", overflow="fold")
        table.add_column("快照记录", overflow="fold")
        for d in diffs[:30]:
            table.add_row(
                escape(d.key), str(d.line), escape(d.actual[:60]), escape(d.expected[:60])
            )
        console.print(table)
        console.print("[yellow]跑 `v3 tables --offline --write` 可按快照恢复[/]")
        raise typer.Exit(EXIT_FAILED)

    covered = len(recorded) - len(orphans)
    console.print(f"[green]快照里记录的 {covered} 张生成表都与文档一致[/]")
    if missing:
        console.print(
            f"[yellow]另有 {len(missing)} 张登记在案的表不在快照里（多半是新增规格）—— "
            f"本机跑 `v3 refresh` 后重建快照即可：{escape(', '.join(missing[:5]))}"
            f"{' …' if len(missing) > 5 else ''}[/]"
        )
    if orphans:
        console.print(
            f"[yellow]快照里有 {len(orphans)} 张表已不在登记表里（规格被删或改名）："
            f"{escape(', '.join(orphans[:5]))}{' …' if len(orphans) > 5 else ''}[/]"
        )


# ── verify ──────────────────────────────────────────────────
def _verify_from_snapshot(*, claims: list[verify.Claim], only: str | None, no_drift: bool) -> None:
    """``v3 verify --from-snapshot``：不读游戏，用**入库的离线真值**核验。

    两份真值：精简快照（目录条目、defines、DLC 清单）与官方文档清单
    （92 篇 ``.md`` 的篇数与逐篇字节数）。后者是新加的 —— 官方文档那几条断言
    本来就不需要游戏，白丢在 CI 覆盖之外没有道理。

    抽成独立函数而不是塞在 ``verify_cmd`` 里，是为了让「无游戏也能跑」
    这条路径足够显眼 —— 它是 CI 上唯一能真正核对断言的入口。
    """
    snap = verify.latest_compact_snapshot()
    if snap is None:
        # 不再直接退出：官方文档清单是第二份离线真值，没有快照时它照样能核验。
        console.print(
            "[yellow]没有精简快照（tools/out/snapshots/*.compact.json）—— "
            "只核验官方文档清单那几条。在装有游戏的机器上跑 "
            "`v3 snapshot create --compact` 可补上一份（它是入库的）。[/]"
        )

    selected = [c for c in claims if not only or only in c.id]
    if only and not selected:
        _fail(f"没有 id 含 {only!r} 的断言（注册表共 {len(verify.CLAIMS)} 条）")

    results = verify.verify_from_snapshot(snap, selected)
    if not results:
        _fail(
            "没有任何断言能被离线真值覆盖 —— 检查 pdx.verify 的 "
            "_SNAPSHOT_GETTERS / _MANIFEST_GETTERS。"
            f"目前能覆盖的类型：{sorted(verify.snapshot_kinds())}"
        )

    table = Table(
        title=f"离线核验（{len(results)} 条，快照 {snap.version_label if snap else '无'}）",
        show_lines=False,
    )
    table.add_column("", width=2, justify="center")
    table.add_column("ID", style="dim")
    table.add_column("断言")
    table.add_column("快照", style="cyan")
    table.add_column("期望", justify="right")
    for r in results:
        table.add_row(
            "✅" if r.ok else "❌",
            escape(r.claim.id),
            escape(r.claim.text),
            escape(str(r.actual)),
            escape(str(r.claim.expected)),
        )
    console.print(table)

    failed = [r for r in results if not r.ok]
    covered = len(results)
    console.print(
        f"通过 {covered - len(failed)} / {covered}    失败 {len(failed)}"
        f"    [dim]（离线真值覆盖 {covered}/{len(verify.CLAIMS)} 条；"
        f"其余需读游戏本体，本地跑 v3 verify）[/]"
    )
    for r in failed:
        console.print(
            f"[red]❌[/] [{escape(r.claim.id)}] 期望 {escape(str(r.claim.expected))} "
            f"快照 {escape(str(r.actual))}  {escape(r.error)}"
        )

    drift = [] if no_drift else verify.unknown_doc_drift()
    if drift:
        console.rule("[red]文档正文与断言表脱节[/]")
        for d in drift:
            console.print(f"[red]❌[/] {escape(d.describe())}")
    elif not no_drift:
        console.print("[green]文档正文与断言表一致[/]")

    if failed or drift:
        raise typer.Exit(EXIT_FAILED)


@app.command("verify")
def verify_cmd(
    fast: Annotated[bool, typer.Option("--fast", help="跳过需要全库扫描的检查")] = False,
    json_out: Annotated[Path | None, typer.Option("--json", help="把结果写入该 JSON 文件")] = None,
    only: Annotated[str | None, typer.Option("--only", help="只跑 id 含该子串的断言")] = None,
    no_drift: Annotated[
        bool, typer.Option("--no-drift", help="跳过文档正文的数字漂移扫描")
    ] = False,
    unregistered: Annotated[
        bool, typer.Option("--unregistered", help="列出文档里**尚未登记**的数量断言后退出")
    ] = False,
    from_snapshot: Annotated[
        bool,
        typer.Option(
            "--from-snapshot",
            help="不读游戏，用**入库的离线真值**（精简快照 + 官方文档清单）核验（CI 用）",
        ),
    ] = False,
    fix: Annotated[
        bool,
        typer.Option("--fix", help="把带归属标记的数字改写成断言期望值（只改标记处，写盘）"),
    ] = False,
    fix_claims: Annotated[
        bool,
        typer.Option("--fix-claims", help="把**实测值**写回断言表的期望值（照单全收，写盘）"),
    ] = False,
) -> None:
    """核对知识库文档里的数量断言（游戏本体口径）。

    与 check-outputs 的分工：本命令查「游戏里到底有多少」，
    check-outputs 查「落盘的产物有没有写对」。两者共用同一份断言注册表
    ``verify.CLAIMS``，因此不可能再出现「脚本期望值与注册表冲突」那种
    结构性分歧。有断言失败时退出码为 1。

    **本命令同时跑文档正文的漂移扫描**（:func:`pdx.verify.find_doc_drift`）——
    断言表测对了不等于文档写对了：文档里可能仍躺着旧值，而断言表照样全绿。
    早在 T0 阶段这两者就号称共用一套逻辑，但 ``find_doc_drift`` 事实上一路
    只被测试调用，``v3 verify`` 从未跑过它，于是「工具报全绿、文档已过期」
    这个最要命的失效模式一直敞着。现在真的接上了（``--no-drift`` 可跳过）。

    ``--from-snapshot`` 是**给 CI 用的**：那里没有游戏，全部实测断言都会被
    跳过，而精简快照（已入库、约 6.0 MiB）里带着 common 各目录的条目名、
    defines 命名空间与 DLC 清单，足以核验其中约一半。它证明的是「断言注册表
    仍与当时记录的真值一致」，**不**证明「游戏里现在还是这个数」。

    **``--fix``**：正文里带归属标记的数字（``205<!--claim:dip.group_files-->``）
    会被改写成断言期望值。它只碰**带标记的那一个数字**，包裹（``**`` / 反引号）
    与空格原样保留，因此不是「猜着改文本」，而是「按归属改」。不带 ``--fix``
    时同一套逻辑只报告不改 —— 两者共用一条实现，免得「说会改 A、实际改了 B」。

    **``--fix-claims``**：官方更新之后用 —— 把**实测值**写回断言表
    ``CLAIMS`` 的期望值。它与 ``--fix`` 是**相反方向**的：``--fix`` 假定断言表
    是对的、改文档；``--fix-claims`` 假定实测是对的、改断言表。因此它照单全收，
    量错了就把错误一起写进闸门 —— 只该在"版本演练"里、且人逐条看过改动清单之后跑。
    ``--only`` 可以缩小到某几条（如 ``--only dip.``），改动清单永远逐条打印。
    """
    if fix_claims:
        _require_game()
        edits, skipped = verify.fix_claims(write=True, only=only or "")
        if not edits:
            console.print("[green]断言表与实测一致，无需改动[/]")
        else:
            table = Table(title=f"按实测改写 {len(edits)} 条断言", show_lines=False)
            table.add_column("ID", style="dim")
            table.add_column("旧期望", justify="right")
            table.add_column("新实测", justify="right", style="green")
            table.add_column("描述", overflow="fold")
            for edit in edits:
                table.add_row(
                    escape(edit.id),
                    escape(str(edit.old)),
                    escape(str(edit.new)),
                    escape(edit.text)
                    + ("  [yellow]← 描述里还写着旧值[/]" if edit.text_stale else ""),
                )
            console.print(table)
            stale = [edit for edit in edits if edit.text_stale]
            if stale:
                console.print(
                    f"[yellow]{len(stale)} 条断言的**描述**里还写着旧值[/]"
                    "（表里那一列会自相矛盾）—— 请手工改描述，工具不代改："
                    "有些旧数字是故意留的历史对照。"
                )
            console.print("改完请重跑 `v3 verify`（不带 --fix-claims）确认全绿。")
        if skipped:
            console.print(f"[yellow]{len(skipped)} 条没动[/]（期望值不是整数 / 量不出来）：")
            for line in skipped[:20]:
                console.print(f"   [dim]{escape(line)}[/]")
            if len(skipped) > 20:
                console.print(f"   …共 {len(skipped)} 条")
        return

    if fix:
        changes = verify.fix_markers(write=True)
        if not changes:
            console.print("[green]带标记的数字全都与断言一致，无需改动[/]")
            return
        table = Table(title=f"按断言改写 {len(changes)} 处", show_lines=False)
        table.add_column("文档", style="dim")
        table.add_column("行", justify="right")
        table.add_column("断言", style="dim")
        table.add_column("旧", justify="right")
        table.add_column("新", justify="right", style="green")
        for ch in changes:
            table.add_row(
                escape(ch.doc), str(ch.line), escape(ch.id), escape(ch.old), escape(ch.new)
            )
        console.print(table)
        console.print("改完请重跑 `v3 verify`（不带 --fix）确认全绿。")
        return

    if from_snapshot:
        _verify_from_snapshot(claims=verify.CLAIMS, only=only, no_drift=no_drift)
        return

    _require_game()
    claims = verify.CLAIMS
    if unregistered:
        # 覆盖率扫描：文档里还有哪些「数量」没进断言表。
        # 它是**排查工具**不是门禁 —— 输出刻意宽松（宁可多报），退出码 0。
        found = verify.find_unregistered_claims()
        if not found:
            console.print("[green]文档里没有未登记的数量断言[/]")
            return
        table = Table(title=f"{len(found)} 篇文档里有未登记的数量", show_lines=False)
        table.add_column("文档", style="dim")
        table.add_column("行", justify="right")
        table.add_column("原文", overflow="fold")
        for name, hits in sorted(found.items()):
            for line_no, text in hits[:20]:
                table.add_row(escape(name), str(line_no), escape(text.strip()[:90]))
        console.print(table)
        console.print(
            "[yellow]这些数字未必是错的[/] —— 只是没进断言表，因此没有看守。"
            "值得钉住的请登记到 pdx.verify.CLAIMS。"
        )
        return

    if only:
        claims = [c for c in claims if only in c.id]
        if not claims:
            # 不能筛出空列表就「全部通过」退出 0 —— 那样 --only 拼错一个字母
            # 会静默报成功，是最容易骗过 CI 的一类假绿灯。
            _fail(
                f"没有 id 含 {only!r} 的断言"
                f"（注册表共 {len(verify.CLAIMS)} 条；用 v3 verify 不带 --only 查看全部）"
            )

    results = verify.run_claims(claims, include_slow=not fast)
    failed = [r for r in results if not r.ok]

    table = Table(title=f"断言核对（{len(results)} 条）", show_lines=False)
    table.add_column("", width=2, justify="center")
    table.add_column("ID", style="dim")
    table.add_column("断言")
    table.add_column("实得", style="cyan")
    table.add_column("期望", justify="right")
    for result in results:
        table.add_row(
            "✅" if result.ok else "❌",
            escape(result.claim.id),
            escape(result.claim.text),
            escape(f"执行失败：{result.error}" if result.error else str(result.actual)),
            escape(str(result.claim.expected)),
        )
    console.print(table)

    summary = verify.summarize(results)
    console.print(f"通过 {summary['通过']} / {len(results)}    失败 {summary['失败']}")

    if failed:
        console.rule("[red]失败明细[/]")
        for result in failed:
            claim = result.claim
            console.print(f"[red]❌[/] [{escape(claim.id)}] [dim]{escape(claim.doc)}[/]")
            console.print(f"   {escape(claim.text)}")
            console.print(
                f"   期望 {escape(str(claim.expected))}  "
                f"实得 {escape(str(result.actual))}  {escape(result.error)}"
            )
            if claim.note:
                console.print(f"   备注：{escape(claim.note)}")

    # ── 归属标记的体检 ─────────────────────────────────
    # 与漂移扫描分工：标记是**精确绑定**（这个数字属于哪条断言），
    # 漂移扫描是**启发式**（锚点 + 量级），只管没有标记的断言。
    marker_issues = [] if only else verify.check_markers()
    if marker_issues:
        console.rule("[red]归属标记有问题[/]")
        for issue in marker_issues[:30]:
            console.print(f"[red]❌[/] {escape(issue.describe())}")
        if len(marker_issues) > 30:
            console.print(f"   …共 {len(marker_issues)} 处")
    elif not only:
        console.print(
            f"[green]归属标记全部对上[/]（{len(verify.all_markers())} 处，"
            f"数字不符时用 `v3 verify --fix`）"
        )

    # ── 文档正文的数字漂移 ──────────────────────────────
    # 用 unknown_doc_drift：已登记为「口径不同、文档其实没错」的那些不算失败。
    drift = [] if (no_drift or only) else verify.unknown_doc_drift()
    if not no_drift and not only:
        if drift:
            console.rule("[red]文档正文与断言表脱节[/]")
            for d in drift:
                console.print(f"[red]❌[/] {escape(d.describe())}")
            console.print(
                f"[yellow]共 {len(drift)} 处。若确认是「口径不同、文档没错」，"
                f"登记到 pdx.verify.KNOWN_METRIC_MIXUPS 并写明理由；否则请改文档。[/]"
            )
        else:
            mixups = len(verify.KNOWN_METRIC_MIXUPS)
            extra = f"（{mixups} 处已登记的口径错配不计）" if mixups else "（无已登记的口径错配）"
            console.print(f"[green]文档正文与断言表一致[/]{extra}")

    if json_out is not None:
        _write_json(
            json_out,
            {
                "summary": summary,
                "results": [
                    {
                        "id": r.claim.id,
                        "doc": r.claim.doc,
                        "text": r.claim.text,
                        "kind": r.claim.kind,
                        "target": r.claim.target,
                        "expected": r.claim.expected,
                        "actual": r.actual,
                        "ok": r.ok,
                        "error": r.error,
                    }
                    for r in results
                ],
                "文档漂移": [
                    {
                        "id": d.claim.id,
                        "doc": d.doc,
                        "line": d.line,
                        "found": d.found,
                        "expected": d.claim.expected,
                        "text": d.text.strip(),
                    }
                    for d in drift
                ],
                "标记问题": [
                    {"doc": i.doc, "line": i.line, "id": i.id, "detail": i.detail}
                    for i in marker_issues
                ],
            },
        )

    if failed or drift or marker_issues:
        raise typer.Exit(EXIT_FAILED)


# ── crosscheck（引擎交叉验证）───────────────────────────────
@app.command("crosscheck")
def crosscheck_cmd(
    json_out: Annotated[
        Path | None, typer.Option("--json", help="把核对结果写入该 JSON 文件")
    ] = None,
) -> None:
    """用游戏自己的日志交叉验证我们的解析。

    这是本工具链里**唯一一次由外部背书的核对**。其余所有测试的比对对象
    都是我们自己写的实现（差分测试的预言机、黄金基线），两份实现可以
    一起错。引擎日志给的是第三方口径：

    * 它从哪些目录按什么扩展名枚举文件 —— 对「全量」的直接检验
    * 它报错时所在的文件与行号 —— 对行号与结构检验
    * 它在某行看到的文本键 —— 对 token 识别与行号检验

    前提：本机**运行过游戏**，从而 ``Documents/Paradox Interactive/Victoria 3/logs``
    下有日志。没有日志时本命令报前置条件缺失（退出码 2），不假装通过。

    注意日志里的游戏版本可能与当前安装不一致 —— 命令会把它打出来，
    版本不符时结论要打折。
    """
    claims, version = engine_log.parse_logs()
    if not claims:
        _fail(f"找不到引擎日志：{engine_log.default_log_dir()}（需要先运行过一次游戏）")

    report = engine_log.cross_check(claims, log_version=version)
    s = report.summary()

    table = Table(title=f"引擎交叉验证（日志版本 {version or '未记录'}）", show_lines=False)
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    for k, v in s.items():
        table.add_row(str(k), str(v))
    console.print(table)

    gaps = report.coverage_gaps
    if gaps:
        console.print("\n[red]覆盖面缺口：[/]")
        for d, e, n, hit, t in gaps:
            console.print(f"  ❌ {d}  {e}   引擎枚举 {n}，我们解析 {hit}（共 {t}）")

    # token 不一致要**分三类**打，不能混成一坨"不一致"：
    #   ① 所在文件被覆盖且覆盖版与原版不同 ⇒ 行号**不可比**（拿两套内容对行号）；
    #   ② token 在当前安装里根本不存在 ⇒ 日志比安装旧；
    #   ③ token 在、但不在引擎报的那一行 ⇒ **这才是值得查的**。
    # 把①②也报成红，等于把"日志过期"记到解析器头上（2026-09-22 实测：18 条里 18 条如此）。
    unverifiable = report.unverifiable_tokens
    absent = report.absent_tokens
    misplaced = report.misplaced_tokens
    if unverifiable:
        console.print("\n[yellow]所在文件被 mod 覆盖且内容不同 ⇒ 行号不可比：[/]")
        for rel in sorted(report.overridden_files):
            console.print(f"  ⚠️ {rel}")
        console.print(
            f"  ⇒ 共 {len(unverifiable)} 条断言落在这类文件上，**不是**解析器问题："
            "日志来自另一套内容。跑一次常规游戏即可让日志与安装一致。"
        )
    if absent:
        console.print("\n[yellow]token 在当前安装中整份文件都找不到（日志比安装旧）：[/]")
        for rel, line, tok, _got in absent[:20]:
            console.print(f"  ⚠️ {rel}:{line}  {tok!r}")
        console.print(
            "  ⇒ 这些**不是**解析器问题：日志描述的是另一套 mod 状态。"
            "跑一次常规游戏即可让日志与安装一致。"
        )
    if misplaced:
        console.print("\n[red]token 行号不一致：[/]")
        for rel, line, tok, got in misplaced[:20]:
            console.print(f"  ❌ {rel}:{line}  {tok!r}  我们给出 {got}")

    if json_out is not None:
        _write_json(
            json_out,
            {
                "日志版本": version,
                "概览": s,
                "覆盖面": [
                    {"目录": d, "扩展名": e, "引擎枚举": n, "我们解析": hit, "文件数": t}
                    for (d, e), (n, hit, t) in sorted(report.coverage.items())
                ],
                "token核对": [
                    {"文件": rel, "行": line, "token": tok, "我们的行": got}
                    for rel, line, tok, got in report.tokens
                ],
                "位置核对": [
                    {"文件": rel, "行": line, "判定": why} for rel, line, why in report.locations
                ],
                "token分类": {
                    "所在文件被覆盖（行号不可比）": [
                        {"文件": rel, "行": line, "token": tok}
                        for rel, line, tok, _ in unverifiable
                    ],
                    "整份文件都没有": [
                        {"文件": rel, "行": line, "token": tok} for rel, line, tok, _ in absent
                    ],
                    "在但不在那一行": [
                        {"文件": rel, "行": line, "token": tok, "我们的行": got}
                        for rel, line, tok, got in misplaced
                    ],
                },
            },
        )

    # 退出码只认"真正该查的"两类：覆盖面缺口 与 行号错位。
    # 另两类不参与：① 文件被覆盖且内容不同（行号不可比）；
    # ② token 在当前安装里不存在（日志比安装旧）。判红就是把过期数据的账
    # 记到解析器头上 —— 实测 18 条不一致里，18 条属于这两类。
    if gaps or misplaced:
        raise typer.Exit(EXIT_FAILED)
    if absent or unverifiable:
        console.print("\n[yellow]除上述「日志与安装不一致」的项外，与引擎日志一致[/]")
        return
    console.print("\n[green]与引擎日志完全一致 ✅[/]")


# ── check-outputs ───────────────────────────────────────────
@app.command("check-outputs")
def check_outputs_cmd() -> None:
    """核验已落盘的分析产物是否与断言注册表一致。

    与 verify 的分工：verify 核验**游戏本体**（游戏里到底有多少条目），
    本命令核验**产物**（落盘的 JSON 有没有把它写对）。两者检查的是不同
    问题，但共用同一份注册表 ``verify.CLAIMS``。

    历史教训：早先这个脚本自己维护了一套写死的期望值，它的
    ``on_actions = 263`` 与注册表里的 264 长期冲突，又因为跑在 pytest
    管辖之外而无人发现。现在这种结构性分歧不可能再出现。

    缺少产物时退出码 2（先跑 `v3 analyze`），不一致时退出码 1。
    """
    game = _load_product(config.OUT_GAME / "游戏本体.json", "游戏本体分析")
    mods = _load_product(config.OUT_MODS / "mod.json", "mod 分析")
    cross = _load_product(config.OUT_CROSS / "交叉.json", "交叉分析")

    results = verify.verify_products(game, mods, cross)
    checkable = [r for r in results if r.claim.kind in verify.product_kinds()]

    table = Table(title="分析产物核验", show_lines=False)
    table.add_column("", width=2, justify="center")
    table.add_column("断言")
    table.add_column("实得", justify="right", style="cyan")
    table.add_column("期望", justify="right", style="dim")
    for result in checkable:
        table.add_row(
            "✅" if result.ok else "❌",
            escape(result.claim.text),
            escape(str(result.actual)),
            escape(str(result.claim.expected)),
        )
    console.print(table)

    failed = [r for r in checkable if not r.ok]
    skipped = len(results) - len(checkable)
    console.print(
        f"\n产物可核验 {len(checkable)} / {len(results)} 条断言"
        f"（其余 {skipped} 条需单独运行对应提取器，本命令不覆盖）"
    )

    if failed:
        console.print(f"[red]不一致 {len(failed)} 条：[/]")
        for result in failed:
            console.print(f"  ❌ [{escape(result.claim.id)}] {escape(result.line())}")
        raise typer.Exit(EXIT_FAILED)

    console.print("[green]产物与断言注册表完全一致 ✅[/]")


# ── show ────────────────────────────────────────────────────
@app.command("strings")
def strings_cmd(
    limit: int = typer.Option(40, "--limit", "-n", help="最多列出多少个未使用的标识符"),
    show_list: bool = typer.Option(True, "--list/--no-list", help="是否列出候选清单"),
    families: bool = typer.Option(False, "--families/--no-families", help="改按命名族聚类看"),
    by: str = typer.Option("suffix", "--by", help="族按后缀还是前缀聚：suffix / prefix"),
    min_size: int = typer.Option(8, "--min", help="族至少多少个成员才列出"),
) -> None:
    """开采 `victoria3.exe` 的字符串：引擎里有、脚本里没用的标识符。

    这条**不是**「下一步」了，而是已经在用的线索来源：`v3 evidence --exe-grep`
    按名字族取证、`--families` 按后缀/前缀聚类（PDX 字段名往往成族出现 ——
    实测 `*_command` 233 个、`*_cw_duplicate_compat` 161 个、`*_mult` 72 个）。

    口径见 `pdx.exe_strings`（扫可打印 ASCII 串 → 取标识符形状 → 与脚本词表作差）。
    它给的是**线索**而不是结论：候选里混着编译器与 CRT 符号（`SDL_` / `map_K*` 这种
    一眼能排除），哪些是 PDX 的字段枚举要人看。文件不存在时退出码 2。
    """
    if not exe_strings.exe_path().is_file():
        console.print(f"[red]找不到 {escape(str(exe_strings.exe_path()))}[/] —— 需要游戏本体")
        raise typer.Exit(2)

    stats = exe_strings.identifier_stats()
    table = Table(title="victoria3.exe 字符串开采", show_lines=False)
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    table.add_row("exe 里的标识符形状串", f"{stats['exe']:,}")
    table.add_row("脚本里出现过的词", f"{stats['script']:,}")
    table.add_row("未在脚本里出现过", f"{stats['unused']:,}")
    console.print(table)

    if families:
        picked = exe_strings.identifier_families(by=by, min_size=min_size, limit=limit)
        console.print(f"\n按{'后缀' if by == 'suffix' else '前缀'}聚出的族（≥{min_size} 个成员）：")
        for token, names in picked:
            shown = "、".join(names[:3])
            console.print(f"  [cyan]{len(names):5d}[/]  {escape(token)}  [dim]{escape(shown)}…[/]")
        return

    if show_list:
        rows = exe_strings.unused_identifiers()
        console.print(f"\n未使用候选（前 {min(limit, len(rows))} / {len(rows):,}）：")
        for name in rows[:limit]:
            console.print(f"  {escape(name)}")


@app.command("experiment")
def experiment_cmd(
    action: Annotated[
        str,
        typer.Argument(help="plan / install / uninstall / collect / launch（一键启动）/ restore"),
    ] = "plan",
    only: Annotated[
        list[str] | None, typer.Option("--only", help="只处理某些实验编号，如 --only P2 --only P11")
    ] = None,
    target: Annotated[
        Path | None, typer.Option("--target", help="安装目标（默认本机 mod 目录）")
    ] = None,
    force: bool = typer.Option(False, "--force", help="install 时覆盖已存在的探针目录"),
    no_debug: bool = typer.Option(False, "--no-debug", help="launch 时不加 -debug_mode"),
    risky: bool = typer.Option(
        False, "--risky", help="launch 时连「语法候选」探针一起启用（可能让游戏起不来）"
    ),
    content_load: Annotated[
        Path | None, typer.Option("--content-load", help="content_load.json 路径（默认用户目录）")
    ] = None,
) -> None:
    """游戏实测探针：一次启动收工。

    知识库里还剩一批「只能进游戏才能定」的问题（引擎的加载语义、运行期字段行为、
    调用语法 —— 见 `04-脚本系统.md` §13.1 的四条配方）。这个命令把探针 mod、
    操作清单、日志收割做成一条流水线：

    ```text
    v3 experiment plan        # 打印操作清单（点什么、看什么、回传什么）
    v3 experiment launch      # 一键：装探针 → 只启用探针 → 以 -debug_mode 启动游戏
    （开新档、点两个决议、退出）
    v3 experiment collect     # 收割 logs/，按实验编号归位证据
    v3 experiment restore     # 还原原来的 mod 启用列表
    v3 experiment uninstall   # 移除探针
    ```

    launch 凭什么能「一键」：**启用哪些 mod** 由用户目录的 content_load.json
    决定（启动器写、游戏读），**调试模式**就是给 `victoria3.exe` 加 `-debug_mode`
    （游戏自带 launcher-settings.json 里那条「以调试模式打开游戏」用的就是它）。
    所以它先备份那份 json、只写上两个探针，再直接起 exe —— 不用点启动器。

    判定优先走日志（`-debug_mode` 会把未知键/重复定义/scope 错误写进去），
    只有三处需要肉眼：国库数字、是否弹窗、决议标题的 loc 文案。
    `install` 只写**本机 mod 目录**（不是仓库），`collect` 只读日志。
    """
    name = action.strip().lower()
    if name == "plan":
        console.print(escape(experiments.plan(target)))
        return

    if name == "install":
        try:
            paths = experiments.install(target, mods=only, force=force)
        except OSError as exc:
            _fail(f"安装探针失败：{type(exc).__name__}: {exc}")
        table = Table(title="探针已就位（在启动器里启用它们）", show_lines=False)
        table.add_column("mod")
        table.add_column("路径", style="dim")
        for path in paths:
            table.add_row(escape(path.name), escape(str(path)))
        console.print(table)
        console.print("接下来跑 `v3 experiment plan` 照清单做。")
        return

    if name == "uninstall":
        # `--risky` 要跟着走：launch --risky 会把 zz_probe_risky 一起装上，
        # 卸载时不带它就会留一个「探针残留」在本机 mod 目录（实测踩过）。
        removed = experiments.uninstall(target, mods=only or None, risky=risky)
        if not removed:
            console.print("[yellow]本机 mod 目录里没有探针，无需移除[/]")
            return
        for path in removed:
            console.print(f"已移除 {escape(str(path))}")
        return

    if name in {"launch", "start"}:
        try:
            # launch 时**强制刷新**探针目录：不覆盖的话，改了探针源码却装着旧副本，
            # 实验会白跑（实测踩过：给 loc 补了 BOM，游戏里报的还是旧的 Missing BOM）。
            paths = experiments.install(target, mods=only, force=True, risky=risky)
            backup = experiments.set_enabled_mods(paths, path=content_load)
        except OSError as exc:
            _fail(f"准备启动失败：{type(exc).__name__}: {exc}")
        console.print(f"启用列表已改成只有探针（原列表备份在 {escape(str(backup or '（无）'))}）：")
        for path in paths:
            console.print(f"  {escape(str(path))}")
        try:
            proc = experiments.launch(debug=not no_debug)
        except (OSError, FileNotFoundError) as exc:
            _fail(f"启动游戏失败：{type(exc).__name__}: {exc}")
        console.print(
            f"[green]游戏已启动（pid {proc.pid}，调试模式{'开' if not no_debug else '关'}）[/]"
        )
        console.print(
            "照 `v3 experiment plan` 的清单做：开新档 → 记国库 → 点两个探针决议 → 等事件 → 退出。"
        )
        console.print(
            "退出后跑 `v3 experiment collect`，然后 `v3 experiment restore` 还原 mod 列表。"
        )
        return

    if name == "restore":
        done = experiments.restore_content_load(path=content_load)
        if done:
            console.print("[green]content_load.json 已还原成启动探针之前的那份[/]")
        else:
            console.print("[yellow]没有找到备份（没跑过 launch 就不用还原）[/]")
        return

    if name == "collect":
        report = experiments.collect()
        table = Table(title=f"探针日志收割（扫了 {report.files_scanned} 个文件）", show_lines=False)
        table.add_column("实验", style="cyan")
        table.add_column("来源", style="dim")
        table.add_column("证据", overflow="fold")
        for finding in report.findings[:60]:
            table.add_row(
                escape(finding.experiment), escape(finding.source), escape(finding.line[:110])
            )
        console.print(table)
        grouped = report.by_experiment()
        console.print(
            f"命中 {len(report.findings)} 行，覆盖 {len(grouped)} 个实验编号；"
            f"实验清单共 {len(experiments.EXPERIMENTS)} 个。"
        )
        for hint in report.hints:
            console.print(f"[yellow]{escape(hint)}[/]")
        for miss in report.missing:
            console.print(f"[yellow]{escape(miss)}[/]")
        console.print(
            "[dim]把这张表（或整份输出）贴回来即可；"
            "需要肉眼看的三处见 `v3 experiment plan` 末尾。[/]"
        )
        return

    _fail(f"不认识的 action：{action!r} —— 可用：plan / install / uninstall / collect")


@app.command("lock")
def lock_cmd(
    write: bool = typer.Option(False, "--write", help="按当前环境重写 requirements.lock"),
) -> None:
    """依赖锁：把本机解析出来的依赖版本组合写成可核对的文件。

    `pyproject.toml` 里全是下限（`typer>=0.27`）—— 下限保证装得上，
    **不保证装出来是同一套**：CI 与本地、今天与三个月后解析出的
    pytest / ruff / hypothesis 版本可能不同，于是「代码一行没改却一边红」
    就会发生。这个命令沿 `Requires-Dist` 展开本机已安装的闭包，
    `--write` 写成 `requirements.lock`；不带参数时与锁**对账**（有差异退出码 1）。

    为什么不引 pip-tools / uv：那是又一个要装、要维护、要联网解析的工具，
    而本仓库只有 15 条直接依赖，标准库的 `importlib.metadata` 就够了。
    口径与边界（含「标记保守求值」这条）见 `pdx.lockfile`。
    """
    actual = lockfile.resolve()
    if write:
        count = lockfile.write(actual)
        console.print(f"[green]已写入 {lockfile.LOCK_FILE}：{count} 条[/]")
        return

    locked = lockfile.read()
    if not locked:
        _fail(f"读不到 {lockfile.LOCK_FILE}（或它不是本工具生成的）—— 先跑 `v3 lock --write`")

    drift = lockfile.compare(actual, locked)
    if not drift:
        console.print(f"[green]{lockfile.LOCK_FILE} 与当前环境一致（{len(locked)} 条）[/]")
        return

    table = Table(title=f"锁与环境有 {len(drift)} 处不一致", show_lines=False)
    table.add_column("包")
    table.add_column("类别")
    table.add_column("锁", style="dim")
    table.add_column("当前", style="cyan")
    for d in drift:
        table.add_row(
            escape(d.name), escape(d.kind), escape(d.locked or "—"), escape(d.actual or "—")
        )
    console.print(table)
    console.print("[yellow]确认过是有意升级/降级后，跑 `v3 lock --write` 更新锁[/]")
    raise typer.Exit(EXIT_FAILED)


@app.command("cov")
def cov_cmd(
    check_only: bool = typer.Option(False, "--check-only", help="只读上次的数据，不重跑测试"),
    top: int = typer.Option(0, "--top", help="只列出覆盖率最低的 N 个模块（0 = 全列）"),
) -> None:
    """跑覆盖率门禁：整体 86% 之外，再按**核心模块**逐条核对下限。

    为什么整体门禁不够：删掉 200 行 `cli.py` 的测试、再给某个小模块补 200 行
    测试，总数可以纹丝不动，而最要紧的那几个模块（解析器、断言注册表、
    归属标记、表格生成）已经悄悄退化了。口径与下限见 `pdx.covgate`。

    `--check-only` 读上次 `v3 cov` 写下的 `tools/out/cov.json`（不重跑，秒级）；
    带覆盖率跑整套测试约 5 分钟，因此这条**不进 CI**（CI 上没有游戏，
    覆盖率口径完全不同，理由见 `.github/workflows/ci.yml` 的文件头注释）。
    """
    if not check_only:
        code = covgate.run_pytest()
        if code != 0:
            console.print(f"[yellow]pytest 退出码 {code} —— 先让测试全绿再看覆盖率[/]")

    rows = covgate.load_coverage()
    if not rows:
        _fail(f"读不到覆盖率数据（{covgate.COV_JSON}）—— 先跑一次 `v3 cov`（不带 --check-only）")

    if top:
        rows = sorted(rows, key=lambda r: r.percent)[:top]

    table = Table(title="模块覆盖率（分支）", show_lines=False)
    table.add_column("模块")
    table.add_column("覆盖率", justify="right", style="cyan")
    table.add_column("下限", justify="right")
    table.add_column("语句", justify="right", style="dim")
    table.add_column("", width=2, justify="center")
    for row in rows:
        floor = row.floor
        table.add_row(
            escape(row.module),
            f"{row.percent:.1f}%",
            "—" if floor is None else f"{floor:.0f}%",
            f"{row.statements:,}",
            "" if floor is None else ("✅" if row.ok else "❌"),
        )
    console.print(table)

    failed = covgate.check(rows)
    gone = covgate.missing_floors(rows)
    overall = covgate.total_percent(rows)
    floor_overall = covgate.overall_floor()
    below_overall = overall + 1e-9 < floor_overall
    console.print(
        f"整体 {overall:.2f}%    低于下限 {len(failed)} 个模块"
        f"    [dim]（整体下限 {floor_overall:.0f}% 读自 pyproject.toml，"
        f"模块下限表 {len(covgate.FLOORS)} 个，见 pdx.covgate）[/]"
    )
    if below_overall:
        console.print(f"  [red]❌ 整体 {overall:.2f}% < {floor_overall:.0f}%[/]")
    for row in failed:
        console.print(f"  [red]❌ {escape(row.module)}：{row.percent:.1f}% < {row.floor:.0f}%[/]")
    if gone:
        console.print(
            f"[yellow]下限表里这些模块这次没有数据（改名或删了？）：{escape(', '.join(gone))}[/]"
        )
    if failed or below_overall:
        raise typer.Exit(EXIT_FAILED)


@app.command("cache")
def cache_cmd(
    clear: bool = typer.Option(False, "--clear", help="清空磁盘缓存"),
    show_entries: bool = typer.Option(False, "--list", help="列出最旧的若干条目"),
) -> None:
    """解析缓存的状态与清理。

    全量分析、`v3 tables`、`v3 verify` 都要解析 6 千个脚本文件；内存缓存只管
    一次进程内的重复，**跨进程（`pytest -n auto` 的 16 个 worker、每次重跑）
    靠的是磁盘层**。缓存放在系统临时目录，按仓库路径分桶，不往仓库里塞文件。

    键 = `sha256(路径 + mtime + 大小 + 引擎指纹)`：源文件变了、解析器代码变了，
    旧条目自动失效，不需要谁记得清缓存。口径见 `pdx.cache` 模块文档。
    """
    mem = cache.stats()
    disk = cache.disk_counts()
    table = Table(title="解析缓存", show_lines=False)
    table.add_column("层")
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    table.add_row("内存", "条目", f"{mem['条目']:,}")
    table.add_row("内存", "命中 / 未命中", f"{mem['命中']:,} / {mem['未命中']:,}")
    table.add_row("磁盘", "可命中条目", f"{disk['条目']:,}")
    table.add_row("磁盘", "分片 / 占用", f"{disk['分片']} / {disk['字节'] / 1048576:.1f} MB")
    table.add_row("磁盘", "状态", cache.describe_state())
    console.print(table)

    if show_entries:
        for path, mtime, size in sorted(cache.disk_entries(), key=lambda item: item[1])[:20]:
            console.print(
                f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}  "
                f"{size / 1024:8.1f} KB  {escape(str(path))}"
            )

    if clear:
        removed = cache.clear_disk()
        console.print(f"[green]已清空磁盘缓存：{removed} 个分片[/]")


@app.command("evidence")
def evidence_cmd(
    keys: Annotated[list[str] | None, typer.Argument(help="要查证的键名，可给多个")] = None,
    mods: bool = typer.Option(False, "--mods/--no-mods", help="是否也扫本机 mod（③ 类证据）"),
    samples: bool = typer.Option(True, "--samples/--no-samples", help="是否列出原版样例"),
    exe_grep: str = typer.Option("", "--exe-grep", help="改查 exe 标识符里含该子串的一族名字"),
    directory: str = typer.Option("", "--dir", help="① 类只扫这个子树，如 common/scripted_lists"),
    values: bool = typer.Option(False, "--values/--no-values", help="列出该键的标量取值分布"),
) -> None:
    """查一个键名的四类证据：原版用法 / 官方 md / MOD 实践 / exe 字面量。

    doc 04 §13 那 28 项 **【未确认】** 里，相当一部分本地就有证据，只是散在
    四个地方。这个命令把它们一次摆出来，口径写在 `pdx.evidence`：

    ① 原版用法（`.txt`/`.gui` 过解析器，**注释不算用法**）
       键与**值**分开统计：`orphan` 是键，`character_event` 是值（`type = ...`）
    ② 官方 md 的篇名与行号，并区分「反引号/赋值」与「英文散文里恰好有这个单词」
    ③ 本机 mod 的使用次数（**本机快照**，不能写成断言）
    ④ `victoria3.exe` 里有没有这个字面量，以及它前后的邻居串（表内聚集）

    `--exe-grep` 换一个问法：引擎里有哪些同族名字（例如 `scripted` 一族）。
    ⚠️ ④ 只是线索：邻居里混着同节的无关字面量，"引擎里有" 不等于 "语法合法"。
    没有游戏本体时 ①②④ 为空，命令仍成功（退出码 0）。
    """
    if exe_grep:
        hits = exe_strings.match_identifiers(exe_grep, limit=0)
        console.print(f"exe 里含 [cyan]{escape(exe_grep)}[/] 的标识符（{len(hits)} 个）：")
        for name in hits[:200]:
            console.print(f"  {escape(name)}")
        if len(hits) > 200:
            console.print(f"  [dim]…（共 {len(hits)} 个，只列前 200）[/]")
        return
    if not keys:
        _fail("至少要给一个键名，例如 `v3 evidence is_shown_in_lobby`")

    reports = evidence.gather(
        keys, mods=mods, root=(config.GAME / directory) if directory else None
    )
    for ev in reports:
        console.print(f"\n[bold cyan]{escape(ev.key)}[/] —— {escape(ev.summary)}")
        v = ev.vanilla
        if v.total:
            by_dir = "、".join(f"{d}×{n}" for d, n in v.by_dir.most_common(4))
            parents = "、".join(f"{p}×{n}" for p, n in v.parents.most_common(4))
            forms = "、".join(f"{f}×{n}" for f, n in v.forms.most_common(3))
            console.print(f"  ① 目录：{escape(by_dir)}")
            console.print(f"    父键：{escape(parents)}")
            console.print(f"    形态：{escape(forms)}")
            if values and v.scalar_values:
                listed = "、".join(f"{k}×{n}" for k, n in v.scalar_values.most_common(12))
                console.print(f"    取值（{len(v.scalar_values)} 种）：{escape(listed)}")
            if samples:
                for s in v.samples:
                    console.print(f"    · [dim]{escape(s.where)}[/] {escape(s.text)}")
        if v.values:
            parents = "、".join(f"{p}×{n}" for p, n in v.value_parents.most_common(4))
            console.print(f"  ① 作为值：{v.values} 处，出现在：{escape(parents)}")
            if samples:
                for s in v.value_samples:
                    console.print(f"    · [dim]{escape(s.where)}[/] {escape(s.text)}")
        if ev.docs:
            code = ev.documented
            for hit in code[:4]:
                console.print(f"  ② [{hit.kind}] [dim]{escape(hit.where)}[/] {escape(hit.text)}")
            if len(code) > 4:
                console.print(f"     （另有 {len(code) - 4} 处）")
            if ev.prose:
                console.print(f"     （散文命中 {ev.prose} 处，不算「文档提到该键」）")
        if ev.mods:
            listed = "、".join(f"{m}×{n}" for m, n in ev.mods[:5])
            console.print(f"  ③ mod：{escape(listed)}")
        elif mods:
            console.print("  ③ mod：本机 mod 里 0 处")
        exe_state = "有" if ev.exe_exact else "无"
        console.print(f"  ④ exe 字面量：{exe_state}")
        if ev.exe_prev or ev.exe_next:
            if ev.exe_prev:
                console.print(f"     前：{escape(' '.join(ev.exe_prev))}")
            if ev.exe_next:
                console.print(f"     后：{escape(' '.join(ev.exe_next))}")


@app.command("prefixes")
def prefixes_cmd(
    directory: Annotated[
        str | None, typer.Argument(help="只看某个目录，例如 common/scripted_triggers")
    ] = None,
    top: int = typer.Option(12, "--top", "-n", help="最多列多少个目录"),
) -> None:
    """本机 mod 的**功能前缀按目录**用量 —— 「这个目录能不能带前缀」的证据。

    原版自己零使用功能前缀（`pdx.mods.vanilla_prefix_count`），所以 doc 04 §1
    那张表里「能否用 `REPLACE:` 之类的前缀」只能看 mod 实践。这个命令就是
    那 12 个 **【未确认】** 单元格的复算路径。

    ⚠️ 结果取决于本机装了哪些 mod（**本机快照**），不是游戏版本属性。
    没有 mod 时输出空表。
    """
    by_dir = mods_mod.prefix_usage_by_dir()
    if not by_dir:
        console.print("[yellow]没有发现任何 mod（workshop 与本地 mod 目录都为空）[/]")
        return
    if directory:
        counter = by_dir.get(directory)
        if not counter:
            console.print(f"[yellow]{escape(directory)} 下没有任何带前缀的条目[/]")
            return
        table = Table(title=f"{directory} 的功能前缀（本机快照）", show_lines=False)
        table.add_column("前缀")
        table.add_column("次数", justify="right", style="cyan")
        for prefix, count in counter.most_common():
            table.add_row(escape(prefix), str(count))
        console.print(table)
        return

    table = Table(title="各目录的功能前缀用量（本机 mod 快照）", show_lines=False)
    table.add_column("目录")
    table.add_column("前缀总计", justify="right", style="cyan")
    table.add_column("明细", style="dim")
    for rel_dir, counter in sorted(by_dir.items(), key=lambda item: -sum(item[1].values()))[:top]:
        detail = "、".join(f"{p}×{n}" for p, n in counter.most_common(5))
        table.add_row(escape(rel_dir), str(sum(counter.values())), escape(detail))
    console.print(table)


@app.command("assets")
def assets_cmd(
    json_out: Annotated[
        Path | None, typer.Option("--json", help="把普查结果写成 JSON（工作区相对路径）")
    ] = None,
    examples: bool = typer.Option(True, "--examples/--no-examples", help="列出非 2 的幂的样例"),
) -> None:
    """DDS 头普查：`game/gfx/**/*.dds` 的格式、尺寸与 mipmap。

    这三行结论此前来自**一次没留下脚本的全量扫描**（doc 06 §6.3）——
    也就是「下一个人无法复算」。现在口径写在 `pdx.assets`：读每个文件前 128 字节头，
    判据全部来自头内字段（mipmap 取 offset 28、标志位 `0x20000`、`fourCC` 取 84…）。

    ⚠️ 结果描述的是**本机这一份安装**，随 DLC 与美术更新而变；文档引用时
    应写成「本机快照 + 复算命令」。没有游戏时输出空表并成功退出。
    """
    result = assets.census()
    table = Table(title=f"DDS 头普查（{escape(result.root)}）", show_lines=False)
    table.add_column("指标")
    table.add_column("值", justify="right", style="cyan")
    for row in assets.format_rows(result):
        cells = [c.strip() for c in row.strip("|").split("|")]
        table.add_row(escape(cells[0]), escape(cells[1]))
    console.print(table)
    if examples and result.examples:
        console.print("非 2 的幂样例：" + escape("；".join(result.examples)))
    if json_out is not None:
        _write_json(json_out, result.summary())
        console.print(f"已写入 {escape(str(json_out))}")


@app.command("csv")
def csv_cmd(
    rel: Annotated[str, typer.Argument(help="游戏目录下的相对路径，如 map_data/adjacencies.csv")],
    column: Annotated[str, typer.Option("--column", "-c", help="只详列这一列的取值")] = "",
    limit: int = typer.Option(20, "--limit", "-n", help="--column 时最多列多少个取值"),
) -> None:
    """非 PDX 语法表格（`.csv` / `.tsv`）的取值分布。

    回答的是「这一列到底有哪些取值」这类问题 —— doc 06 §4.4 关于 `adjacencies.csv`
    的几条结论（`Type` 只有若干种取值、`Through` 全是 `-1`…）此前同样是一次性脚本的
    产物，现在可随时复算（口径见 `pdx.tabular`）。文件不存在时退出码 2。
    """
    path = (config.GAME / rel).resolve()
    _require_file(path, f"表格文件 {rel}", "路径按游戏目录算，例如 map_data/adjacencies.csv")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    delimiter, columns, rows = tabular.parse_table_text(text)
    sheet = tabular.Table(
        rel=rel, delimiter=delimiter, columns=columns, rows=rows, size=path.stat().st_size
    )
    console.print(
        f"[bold]{escape(rel)}[/] 分隔符 {escape(repr(delimiter))}  "
        f"列 {len(columns)}  数据行 {len(rows):,}"
    )

    stats = tabular.column_stats(sheet, top=limit)
    if column:
        picked = [s for s in stats if s.name == column]
        if not picked:
            _fail(f"没有列 {column!r}；该表有：{', '.join(columns)}")
        stat = picked[0]
        console.print(
            f"列 [cyan]{escape(stat.name)}[/]：不同取值 {stat.distinct}，空值 {stat.blanks}"
        )
        for value, count in stat.top:
            console.print(f"  {escape(value)} × {count}")
        return

    out = Table(title="逐列取值分布", show_lines=False)
    out.add_column("列")
    out.add_column("不同取值", justify="right", style="cyan")
    out.add_column("空值", justify="right", style="dim")
    out.add_column("最常见", style="dim")
    for stat in stats:
        common = "、".join(f"{v}×{n}" for v, n in stat.top[:3])
        out.add_row(escape(stat.name), str(stat.distinct), str(stat.blanks), escape(common))
    console.print(out)


# ── ai-surface（原版 AI 意图层的可执行面）────────────────────
@app.command("ai-surface")
def ai_surface_cmd(
    write: Annotated[
        bool, typer.Option("--write", help="生成/更新 docs/design/02-可执行面.md")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="核对文档与生成结果是否一致（退出码 1 = 已被手改）")
    ] = False,
    top: Annotated[int, typer.Option("--top", "-n", help="输入清单最多列多少条")] = 60,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="离线：原版 AI 面改读入库精简快照（CI 用），不读游戏本体"),
    ] = False,
) -> None:
    """原版 AI 意图层的**可执行面**：有哪些牌、牌在读什么、面有多大。

    这是 mod 阶段 1 的产物生成器，回答三个问题（全部**枚举**自原版文件，不手抄）：

    1. **有哪些牌**：`common/ai_strategies/*.txt` 里每张 `ai_strategy_*` 的槽位（`type =`）、
       权重基准、条件数、有无 `possible` 门、牌面上的字段数；
    2. **牌在读什么**：牌的 `weight` / `possible` 里出现的**触发器**与**脚本值引用** ——
       这张清单就是「可喂输入清单」：原版 AI 自己会读的量，我们移动它就能影响概率；
    3. **面有多大**：`common/defines/00_ai.txt` 的 `NAI` 块规模、`*_ENABLED` 原版子系统开关、
       以及 `STRATEGY_RANDOM_FACTOR` 这类直接决定"随机性"的全局旋钮。

    产物 `docs/design/02-可执行面.md` **由本命令生成，勿手改**；`--check` 就是防手改的闸门
    （不一致退出码 1，可进 CI）。

    `--offline`：上面三件事改从**入库精简快照**的 `ai_surface` 域读（生成快照时由
    同一个模块写进去），因此没有游戏本体的机器（CI）也能跑 `--check`。它证明的仍是
    「文档与**入库快照**一致」，不是「与现在的游戏一致」（后者要本机 `--write`）。
    快照缺失或缺这一域时报**前置条件缺失**（退出码 2），不是通过。
    """
    # 前置条件先挡一道（P13：缺前置条件要**明确报错**，不是抛 traceback）。
    # 本命令的三件事全部枚举自原版文件，没有游戏本体时它连第一条都做不了 ——
    # 实测过：不挡的话 `--check` 会在读 `common/defines/00_ai.txt` 时抛
    # `FileNotFoundError` 并把整个 traceback 打到用户脸上。
    # 与 `v3 modguard` / `v3 tables` 同一口径：报"前置条件缺失"，退出码 2。
    if offline:
        try:
            ai_surface.read_offline()
        except ai_surface.OfflineUnavailableError as exc:
            _fail(str(exc))
    elif not config.GAME.is_dir():
        _fail(
            f"前置条件缺失：找不到原版目录 {config.GAME}（可用环境变量 V3_ROOT 指定）"
            " —— 本命令的三件事全部枚举自原版 ai_strategies / defines，"
            "没有游戏本体时不可用；没有游戏的机器请用 `--offline`（读入库快照）"
        )

    if check:
        try:
            problem = ai_surface.check_doc(top=top, offline=offline)
        except ai_surface.OfflineUnavailableError as exc:
            _fail(str(exc))
        if problem:
            _fail(problem)
        console.print(f"[green]{escape(ai_surface.DOC_REL)} 与生成结果一致 ✅[/]")
        if offline:
            index = ai_surface.offline_source()
            source = index.describe() if index is not None else "?"
            console.print(
                f"[dim]离线模式：原版 AI 面来自{escape(source)} —— 证明的是"
                "「文档与入库快照一致」，不是「与现在的游戏一致」。[/]"
            )
        return

    if offline:
        cards, defines = ai_surface.read_offline()
    else:
        cards = ai_surface.read_cards()
        defines = ai_surface.read_defines()
    inputs = ai_surface.collect_inputs(cards)

    if write:
        try:
            path = ai_surface.write_doc(top=top, offline=offline)
        except ai_surface.OfflineUnavailableError as exc:
            _fail(str(exc))
        console.print(
            f"[green]已写入 {escape(str(path))}[/]：{len(cards)} 张牌 / {len(inputs)} 个不同的输入"
        )
        return

    hits = ai_surface.factor_report(inputs)

    slots: dict[str, int] = {}
    for card in cards:
        slots[card.slot] = slots.get(card.slot, 0) + 1
    table = Table(title=f"原版 AI 牌面：{len(cards)} 张", show_lines=False)
    table.add_column("槽位")
    table.add_column("张数", justify="right", style="cyan")
    for slot, n in sorted(slots.items()):
        table.add_row(escape(slot), str(n))
    console.print(table)

    console.print(f"\n被牌读到的不同输入：**{len(inputs)}** 个，前 {min(top, len(inputs))} 个：")
    for item in inputs[:top]:
        console.print(f"  [cyan]{item.cards:3d}[/]x {escape(item.name)}  [dim]({item.kind})[/]")

    console.print("\n候选账本因子 → 原版读点：")
    for hit in hits:
        mark = "[green]✅[/]" if hit.hits else "[yellow]❌[/]"
        console.print(f"  {mark} {escape(hit.factor.name)}：{escape(hit.verdict)}")

    console.print(
        f"\ndefines 面：`00_ai.txt` {defines.lines} 行 / NAI 块 {defines.nai_keys} 键 / "
        f"原版子系统开关 {len(defines.enabled_switches)} 个 / `AI_*` 条目 {len(defines.ai_keys)} 个。"
    )
    console.print("跑 `v3 ai-surface --write` 生成 `docs/design/02-可执行面.md`。")


# ── h1（阶段 2：H1 生死门的实验结果）────────────────────────
@app.command("h1")
def h1_cmd(
    logs: Annotated[
        Path | None, typer.Option("--logs", help="日志目录（默认用户目录下的 logs）")
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="输出机器可读的 JSON")] = False,
    health_only: Annotated[
        bool,
        typer.Option(
            "--health",
            help="只跑**开局自检**（开局一分钟内判断这一局的数据有没有在正常产生）",
        ),
    ] = False,
) -> None:
    """H1 实验：**改权重能否推动 AI 策略落点**（阶段 2 的 G1 生死门）。

    探针（`v3 h1-probe` 生成，装在 `tools/probe/zz_probe_h1/`）每月给每个国家写几行：

    ```text
    ZZPROBE H1;RUN;storm                              ← 本次启动的变体（用来切分多次启动）
    ZZPROBE H1;DOSE;HIGH;Russia                       ← 随机分到的剂量组
    ZZPROBE H1;POLI;sitai_probe_reform;Russia         ← 政治槽当前落点
    ZZPROBE H1;ADMI;agricultural_expansion;Russia     ← 行政槽
    ZZPROBE H1;DIPL;maintain_power_balance;Russia     ← 外交槽
    ```

    分组是**随机**的（探针里 `random_list` 25/25/25/25），组间唯一差异是我们那张牌的
    `weight`（对照 10 / 低 50 / 中 100 / 高 250）—— 所以这是一次**随机对照试验**：
    高剂量组的命中率显著高于对照组，就证明"权重能推动落点"（G1 通过）。

    报告同时给出**三个槽位各自的剂量反应**与**重抽节奏**：后者决定"喂输入去改变原版
    概率"这条路线在战役尺度上有没有用（政治槽实测 ≈1%/国家·月，即十年尺度才重抽）。

    统计用 Wilson 区间（小样本友好），判定口径是**区间不重叠**。
    """
    result = h1.analyze(logs)
    if health_only:
        # 开局自检（P13）：探针挂载点写错时脚本侧**毫无报错**，只有 error.log 有痕迹 ——
        # 阶段 2 因此白跑过一整局。这条让它在一分钟内红，而不是跑完才发现。
        items = h1.health(result, log_dir=logs)
        console.print(Markdown(h1.format_health(items)))
        if not all(item.ok for item in items):
            raise typer.Exit(1)
        return
    if json_out:
        payload = {
            "variant": result.variant,
            "runs": list(result.runs),
            "samples": len(result.samples),
            "tags": result.tags,
            "months": result.months,
            "unpaired": result.unpaired,
            "fourth_hits": result.fourth_hits,
            "noloc_hits": result.noloc_hits,
            "h3_events": list(result.h3_events),
            "groups": {
                dose: {
                    "weight": h1.DOSE_WEIGHT.get(dose),
                    "observations": group.observations,
                    "probe_hits": group.probe_hits,
                    "rate": group.rate,
                    "wilson": group.wilson(),
                    "countries": len(group.countries),
                }
                for dose, group in result.groups.items()
            },
            "by_slot": {
                slot: {
                    dose: {
                        "observations": cell.observations,
                        "hits": cell.hits,
                        "rate": cell.rate,
                        "wilson": cell.wilson(),
                        "implied_rival_weight": cell.implied_rival_weight(),
                    }
                    for dose, cell in cells.items()
                }
                for slot, cells in result.by_slot.items()
            },
            "tempo": {
                slot: {
                    "observations": tempo.observations,
                    "pairs": tempo.pairs,
                    "changes": tempo.changes,
                    "rate": tempo.rate,
                    "top": [list(item) for item in tempo.top],
                }
                for slot, tempo in result.tempo.items()
            },
        }
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    if not result.samples:
        console.print(
            "[yellow]日志里没有 H1 的观测行[/] —— 检查三件事：探针是否启用、"
            "是否进了一局游戏、日志目录是否是本机用户目录。"
        )
    console.print(Markdown(h1.format_report(result)))


# ── h1-probe（阶段 2：探针本身是生成的，不是手写的）────────────
@app.command("h1-probe")
def h1_probe_cmd(
    variant: Annotated[
        str, typer.Option("--variant", "-v", help="natural（引擎真实节奏）| storm（每周重抽）")
    ] = "natural",
    deploy: Annotated[
        bool, typer.Option("--deploy", help="同步进用户 mod 目录，并把 content_load.json 只留它")
    ] = False,
    archive: Annotated[
        str | None, typer.Option("--archive", help="先把现有日志挪进归档目录（给个标签）")
    ] = None,
    watch: Annotated[
        str | None,
        typer.Option("--watch", help="跟着游戏跑：按版本快照日志（给个标签），游戏退出即收工"),
    ] = None,
    interval: Annotated[float, typer.Option("--interval", help="快照间隔秒数（默认 40）")] = 40.0,
) -> None:
    """生成 H1 探针（**不要手改探针文件**，改 `tools/pdx/h1_probe.py`）。

    生成的理由：日志链要按 `type` 枚举原版全部 34 张牌（手写会随版本漂移，
    而漂移的表现是"某槽永远落进兜底桶"这种静默失真）；剂量阶梯又同时出现在牌文件
    与分析器里，只能有一个来源。

    两个变体：

    * `natural` —— 引擎的真实重抽节奏。回答"原版节奏有多快"。
    * `storm` —— 用独立小文件覆盖 `NAI` 的 `CHANGE_STRATEGY_THRESHOLD` 与
      `CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE`（KB 05 §1.7 证明可按「块+参数」覆盖），
      每周都可能重抽。回答"权重能不能推动落点"（大样本）与"mod 能不能接管重抽节奏"。
    """
    if watch:
        # 日志按 512KB 轮转、会删最老的：长跑不做版本化快照就会丢早期月份
        # （阶段 2 实测：自然局只剩最近约 4 个月）。这条跟着游戏跑到它退出。
        dest, rounds, copied, skipped = h1_probe.watch(watch, interval=interval)
        console.print(
            f"快照收工：[bold]{dest}[/]（{rounds} 轮 / 复制 {copied} 个"
            + (f" / 跳过 {skipped} 个被占用" if skipped else "")
            + "）"
        )
        console.print(f'分析并集：`v3 h1 --logs "{dest}"`')
        return
    if archive:
        dest, moved, skipped = h1_probe.archive_logs(archive)
        console.print(f"日志已归档：[bold]{dest}[/]（挪走 {moved} 个文件）")
        if skipped:
            console.print(
                f"[yellow]有 {skipped} 个日志挪不动[/] —— 游戏还开着时日志被独占，"
                "请先退出游戏再归档。"
            )
    built = h1_probe.build(variant=variant)
    written = h1_probe.write(variant=variant)
    console.print(h1_probe.summary(built))
    console.print(f"已写入 [bold]{len(written)}[/] 个文件 → {h1_probe.PROBE_DIR}")
    if deploy:
        dest = h1_probe.deploy(variant=variant)
        console.print(
            f"已部署到 [bold]{dest}[/]，`content_load.json` 只留这一个 mod（原列表已备份）"
        )
        console.print("接着：启动游戏 → 开一局 1836 新游戏 → 至少跑 3 个月 → 退出 → `v3 h1`。")


@app.command("modgen")
def modgen_cmd(
    write: Annotated[
        bool,
        typer.Option("--write", help="把数据源编译成 mod/ 下的产物（写盘 + 清理被取代的旧文件）"),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="核对盘上产物与数据源一致（被手改 / 过期 / 多余即退出码 1）"),
    ] = False,
    why: Annotated[bool, typer.Option("--why", help="只列出每个数字与它的依据（P10）")] = False,
) -> None:
    """把结构化数据源编译成 mod 产物：脚本 + 本地化 + 档案文档。

    P3「引擎脚本由 Python 生成，人只改数据源」的落点。数据源在 `mod/data/*.toml`，
    产物在 `mod/`（原版目录树的镜像）。**改产物没有用** —— 每个生成文件头都写着
    这句话，闸门 ⑤ 也会把与生成结果不一致的产物点出来。

    三种用法：

    ```text
    v3 modgen             # 只编译并打摘要（不写盘）
    v3 modgen --write     # 落盘，并清掉被取代的旧文件
    v3 modgen --check     # 核对盘上产物 = 生成结果（手改/过期/多余即退出码 1）
    v3 modgen --why       # 每个数字 + 它的依据（空 why 在编译期就会报错）
    ```

    数据源不合法的两种情形都在这里**当场**报错（退出码 2）：结构/类型不对、
    以及任何一张表缺 `why` —— 后者是 P10 的机械检查，不是靠人记得。
    """
    if write and check:
        _fail("--write 与 --check 互斥：先写盘，再另跑一次核对")
    try:
        archives = modgen.load_all()
        built = modgen.build_all(archives)
    except modgen.DataError as exc:
        _fail(f"数据源不合法：{exc}")

    if why:
        for archive in archives:
            console.rule(f"{archive.title}（{archive.source}）")
            console.print(
                Markdown(
                    "**每个数字与它的依据**\n\n"
                    + modgen.why_report(archive)
                    + "\n\n**每张表的依据**\n\n"
                    + modgen.why_tables(archive)
                )
            )
        return

    if write:
        try:
            written = modgen.write(built)
        except OSError as exc:
            _fail(f"写盘失败：{type(exc).__name__}: {exc}")
        table = Table(title=f"已写入 {len(written)} 个产物", show_lines=False)
        table.add_column("产物", style="cyan")
        table.add_column("字节", justify="right")
        table.add_column("BOM", justify="center")
        for path in written:
            rel = _relative(path)
            table.add_row(
                escape(rel),
                f"{path.stat().st_size:,}",
                "✓" if path.read_bytes().startswith(b"\xef\xbb\xbf") else "",
            )
        console.print(table)
        console.print(
            "游戏侧文件（.txt / .yml）带 UTF-8 BOM 写入；文档与元数据不带。"
            "接着跑 [bold]v3 modguard[/]——五道闸门全过才进游戏（冻结文档 §5）。"
        )
        return

    if check:
        problems = modgen.check(built)
        if problems:
            table = Table(title=f"{len(problems)} 处与数据源不一致", show_lines=False)
            table.add_column("问题", overflow="fold")
            for line in problems[:30]:
                table.add_row(escape(line))
            console.print(table)
            console.print("[yellow]跑 `v3 modgen --write` 重新生成（产物不许手改）[/]")
            raise typer.Exit(EXIT_FAILED)
        console.print(f"[green]盘上 {len(built.files)} 个产物与数据源逐字节一致 ✅[/]")
        return

    console.print(escape(modgen.summary(built)))
    console.print("[dim]--write 落盘 / --check 核对 / --why 列依据[/]")


@app.command("citations")
def citations_cmd(
    paths: Annotated[
        list[str] | None,
        typer.Argument(help="要扫的文件或目录（默认只扫数据源 mod/data）"),
    ] = None,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="离线：不读游戏本体，只核「与入库快照一致」（CI 用，B77）",
        ),
    ] = False,
) -> None:
    """核对数据源里的 `文件:行号` 引用**指得到真实文件的那一行**。

    P10 要求"每个数字都要有依据"，而依据最常用的一句话是"原版某文件某一行就是这么写的"。
    闸门 ⑤ 只查 `why` 非空 —— 它查不出**行号是编的**。这个命令补上那一步：

    ```text
    文件名写错（00_sikh_empire.txt 其实叫 04_sikh_empire.txt） ⇒ missing
    少了子路径（ai_strategies/… 其实在 common/ai_strategies/） ⇒ missing
    行号越界（文件 300 行，引了 :322）                          ⇒ out_of_range
    同名文件有几十个（modifiers.txt）                          ⇒ ambiguous
    ```

    ⚠️ **默认只扫 `mod/data`**：设计文档里的 `文件:行号` 有另一种含义（知识库章节、
    仓库内文件），拿同一把尺子去量会得到一片假红 —— 要扫别处就显式给路径。

    ⚠️ 它**不做语义判断**："那一行真的支持这条 why 吗"仍然要人看。这里只保证
    "引用存在且唯一"，把人的注意力从找文件挪到读内容。

    **``--offline``（B77）**：原来这条**进不了 CI** —— 它要打开原版文件，而 runner 上
    没有游戏（其余门禁都有离线通道，这是最后一个缺口）。现在精简快照里多了一个
    `citation_support` 域（`v3 snapshot create --compact` 写入）：每条引用记着
    **被引那一行的文本指纹 + 文件行数**。离线核的是「与入库快照一致」，
    **不是**「与现在的游戏一致」—— 后者是本机门禁的活（有游戏时本命令会顺手核
    "被引那一行还是不是那句话"，那正是官方更新挪走我们依据的信号）。
    """
    targets = [Path(item) for item in (paths or ["mod/data"])]
    missing = [str(path) for path in targets if not path.exists()]
    if missing:
        _fail(f"找不到：{'、'.join(missing)}")
    found = citations.scan_paths(targets)
    snap = verify.latest_compact_snapshot()
    support = (snap.sections.get(citations.SECTION) or {}) if snap is not None else {}

    if offline:
        if snap is None:
            _fail(
                "没有精简快照（tools/out/snapshots/*.compact.json）—— 离线核对要靠它里的"
                f"`{citations.SECTION}` 域；在装有游戏的机器上跑 `v3 snapshot create --compact`"
            )
        bad = citations.unsupported(found, support)
        _report_support(found, bad, offline=True, support=support)
        return

    problems = [item for item in found if not item.ok]
    malformed = [
        (item, detail)
        for item, detail in citations.unsupported(found, support, live=True)
        if item.ok  # 已经报成 missing/ambiguous/out_of_range 的不重复报
    ]
    table = Table(
        title=f"{len(found)} 条引用（{len(found) - len(problems)} 条指得到）",
        show_lines=False,
    )
    table.add_column("结论", style="cyan")
    table.add_column("引用", overflow="fold")
    table.add_column("出处", overflow="fold")
    table.add_column("说明", overflow="fold")
    for item in problems[:40]:
        table.add_row(
            f"[red]{item.status}[/]",
            escape(f"{item.file}:{item.start}"),
            escape(item.where),
            escape(item.detail),
        )
    for item, detail in malformed[:40]:
        table.add_row(
            "[red]unsupported[/]",
            escape(f"{item.file}:{item.start}"),
            escape(item.where),
            escape(detail),
        )
    if problems or malformed:
        console.print(table)
        if problems:
            console.print(
                f"[yellow]{len(problems)} 条引用指不到唯一一行[/]"
                " —— 要么改引用，要么把原版那一段原文贴进 why（P10）"
            )
        if malformed:
            _report_relocations([item for item, _ in malformed], support)
            console.print(
                f"[yellow]{len(malformed)} 条引用与入库支撑域对不上[/]"
                " —— 核对后跑 `v3 snapshot create --compact` 刷新（它是入库的）"
            )
        raise typer.Exit(EXIT_FAILED)
    console.print(f"[green]{len(found)} 条引用全部指得到唯一一行 ✅[/]")


@app.command("release")
def release_cmd(
    template: Annotated[
        bool,
        typer.Option("--template", help="只打印还没写进发布说明的档案条目骨架（不检查）"),
    ] = False,
) -> None:
    """检查**发布说明 ↔ 档案 ↔ 元数据**三边一致（阶段 7 的发布流程）。

    `01-大方向.md` §3 阶段 7 要的是「发布流程（changelog 对应到档案）」，而它原来只有一条
    人工纪律：`mod/data/<id>.toml` 的 `id` 必须出现在 changelog 条目里。§1 的原则是
    **没有检查方式的原则不算原则** —— 这条命令把那条纪律变成四件机器可查的事：

    ```text
    ① 版本对得上    changelog 最新一节 == 元数据的 version（发了版没写说明？）
    ② 每份档案都写过  mod/data 里每个 id 都以条目形式出现在 changelog 里
    ③ 没有幽灵条目  changelog 里提到的 id 都真的存在（删了档案还留着说明？）
    ④ 归档物对得上  各档案声明的 game_version == 元数据的 supported_game_version
    ```

    格式要求写在 `pdx/release.py` 的开头，也写在 `CHANGELOG.md` 自己的第一段 ——
    **机器可查的前提是格式固定**。条目骨架可以用 `--template` 打印出来（只打印，不写盘：
    那句话得人来说）。
    """
    report = release.check()
    if template:
        console.print(release.template(report))
        return
    console.print(report.describe())
    if not report.ok:
        for item in report.problems:
            console.print(f"  [red]❌ {escape(item)}[/]")
        console.print("[yellow]跑 `v3 release --template` 可以打印缺的条目骨架[/]")
        raise typer.Exit(EXIT_FAILED)
    console.print("[green]发布说明、档案、元数据三边一致 ✅[/]")


def _report_relocations(items: list[citations.Citation], support: dict[str, list[str]]) -> None:
    """报「只是行号漂移」的那些引用：按**入库支撑域**里的行指纹找回它现在在哪一行。

    为什么要专门说一句：编辑一个被大量引用的文件（`docs/design/backlog.md`、
    `tools/pdx/ab_probe.py` 这类）会让行号整体平移而内容一个字没变，
    此时闸门只会说"第 N 行的内容变了（原版更新？）"—— 那句话会把人往**错的方向**引
    （去看原版更新），而真相是自己刚编辑过那个文件。本轮实测踩过两次。
    ⚠️ 比对基准必须是**入库快照**里的域，不能现算一份：现算出来的指纹必然与现在一致，
    那样永远找不到漂移（第一版就是这么写错的）。
    """
    moves = citations.relocate(items, support)
    if not moves:
        return
    console.print(f"[yellow]{len(moves)} 条只是**行号漂移**[/]（内容没变）：")
    for move in moves[:40]:
        console.print(f"   {escape(move.describe())}")
    console.print(
        "   改完引用行号后重跑本命令；改的是数据源就再接 `v3 modgen --write`，"
        "最后 `v3 snapshot create --compact` 刷新入库支撑。"
    )


def _report_support(
    found: list[citations.Citation],
    bad: list[tuple[citations.Citation, str]],
    *,
    offline: bool,
    support: dict[str, list[str]] | None = None,
) -> None:
    """离线/在线共用的「支撑域」结果表（CI 只看这一张）。"""
    table = Table(
        title=f"{len(found)} 条引用（{len(found) - len(bad)} 条与入库快照一致）",
        show_lines=False,
    )
    table.add_column("结论", style="cyan")
    table.add_column("引用", overflow="fold")
    table.add_column("出处", overflow="fold")
    table.add_column("说明", overflow="fold")
    for item, detail in bad[:40]:
        table.add_row(
            "[red]unsupported[/]",
            escape(f"{item.file}:{item.start}"),
            escape(item.where),
            escape(detail),
        )
    if bad:
        console.print(table)
        # 报"内容变了"之前先按**指纹**找一遍：多半只是行号被编辑平移了。
        _report_relocations([item for item, _ in bad], support or {})
        console.print(
            f"[yellow]{len(bad)} 条引用与入库支撑域对不上[/]"
            " —— 核对后跑 `v3 snapshot create --compact` 刷新（它是入库的）"
        )
        raise typer.Exit(EXIT_FAILED)
    where = "离线：与入库快照一致" if offline else "在线"
    console.print(f"[green]{len(found)} 条引用全部有入库支撑（{where}）✅[/]")


@app.command("preflight")
def preflight_cmd(
    archive: Annotated[
        str,
        typer.Option(
            "--archive", help="要跑的那份档案 id（给了就一并查它可不可跑、探针盯的是不是它）"
        ),
    ] = "",
) -> None:
    """开局前的**前置条件自检**（只读：不改配置、不动日志、不写盘）。

    为什么要有这一条：一次实机会话的代价不是几秒钟 —— 起游戏到选国家界面实测约 137 秒，
    还要把用户的屏幕借走、跑几十个游戏月，而**失败常常在开局十几分钟后才暴露**
    （探针盯的国家不对、日志里混着上一局的自报、盘上产物是手改过的旧版本）。
    这些条件**开局前全部可查**，而且不需要游戏在跑。

    退出码与其它命令同一套口径：**0 = 可以开局；1 = 有该修的问题（如产物被手改、
    上次实验没还原用户配置）；2 = 这台机器现在跑不了**（没有游戏 / 数据源坏了 / 没有
    `content_load.json`）。它**只报告**，绝不顺带修 —— 检查脚本自己去改环境，
    就成了第二个会留下烂摊子的东西。
    """
    report = preflight.run(archive=archive or None)
    table = Table(title="开局前置条件", show_lines=False)
    table.add_column("", width=2, justify="center")
    table.add_column("条件")
    table.add_column("结论", overflow="fold")
    table.add_column("怎么修", overflow="fold")
    for check in report.checks:
        table.add_row(
            "✅" if check.ok else "❌",
            escape(check.name),
            escape(check.detail),
            escape(check.fix if not check.ok else ""),
        )
    console.print(table)
    code = report.exit_code()
    if code == 0:
        console.print("[green]可以开局[/]")
        if report.notes:
            console.print(f"[yellow]另有 {len(report.notes)} 条提示[/]（不拦路，先看一眼）：")
            for note in report.notes:
                console.print(f"   [dim]{escape(note.describe())}[/]")
        if archive:
            console.print(
                f"接着：`python tools/probe/stage3_rerun.py --months 66 --archive {archive} --fresh-logs`"
            )
        else:
            console.print("接着：`python -m pdx.game_auto run --wait-tests <秒>`")
        return
    if code == 2:
        _fail(f"{len(report.blocking)} 条前置条件缺失 —— 这台机器现在跑不了这一局")
    _fail(f"{len(report.wrong)} 条该先修（否则这一局会白跑）")


@app.command("modguard")
def modguard_cmd(
    only: Annotated[
        str,
        typer.Option(
            "--only",
            help="只跑某一道闸门（编号 1–5，或键名 keys/refs/dilution/roundtrip/determinism）",
        ),
    ] = "",
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="离线：①② 的原版真值改读入库精简快照（CI 用），不读游戏本体",
        ),
    ] = False,
) -> None:
    """五道闸门：键/路径不相交、引用完整性、稀释预算、往返净度、生成可复现。

    这是冻结文档 §5 里「每次生成后 / 每阶段结束」要跑的那套检查，逐条对应：

    ```text
    ① keys        键与路径与原版零交集（含 F7 命名空间与平铺不建子目录）
    ② refs        我们引用的每个变量/JE/修正/图标/本地化键/defines 参数都存在
    ③ dilution    递牌按阶段 2 的价格表定价，超预算即红（本档案 0 张牌）
    ④ roundtrip   生成 → 按 PDX 语法解析回来 → 与数据源逐条一致
    ⑤ determinism 两次生成逐字节一致 + 每个 why 非空 + 盘上产物确实由生成器产出
    ```

    `--offline`：①② 的原版真值改读**入库精简快照**
    （`tools/out/snapshots/*.compact.json`），于是没有游戏本体的机器（CI）也能
    真跑这两道闸门 —— 不是跳过它们。输出里逐项写明「本项由快照核验」，快照没
    覆盖到的项单列成**「离线未覆盖」并注明不算通过**（未覆盖不报红，否则 CI
    永远红；但也绝不算过，否则"没查"会被读成"通过"）。③④⑤ 本来就不读游戏。

    退出码：0 全过（或全过且只余"离线未覆盖"项）；1 有闸门不过（**不许进游戏**）；
    2 前置条件缺失（原版目录不可用、快照缺失或缺域、数据源不合法、`--only` 拼错）。

    **缺前置条件不算通过**：没有游戏、也没要离线时 ①/② 报退出码 2 而不是静默
    跳过 —— 跳过会被当成绿灯，这是这类门禁最危险的失效方式（P13）。
    """
    try:
        ctx = modguard.context(offline=offline)
        report = modguard.run(ctx, only)
    except modgen.DataError as exc:
        _fail(f"数据源不合法：{exc}")
    except ValueError as exc:
        _fail(f"{exc}")
    except OSError as exc:
        _fail(f"读产物/原版失败：{type(exc).__name__}: {exc}")

    table = Table(title=f"闸门（{len(report.findings)} 道）", show_lines=False)
    table.add_column("", width=2, justify="center")
    table.add_column("闸门")
    table.add_column("结论", overflow="fold")
    for finding in report.findings:
        mark = "✅" if finding.ok else ("⚠️" if finding.precondition else "❌")
        table.add_row(mark, escape(finding.title), escape(finding.headline))
    console.print(table)

    # 离线时**过也要有明细**：哪一项由快照核验、哪些没覆盖，都写在明细里
    # （P13：绿也得让人看得出"绿在哪"）。
    for finding in report.findings:
        if finding.ok and not offline:
            continue
        console.print(f"\n[bold]{escape(finding.title)}[/]")
        for line in finding.details:
            console.print(f"  {escape(line)}")

    if offline:
        console.print(
            "[dim]离线模式：①/② 的原版真值来自入库精简快照（版本见各闸门明细）；"
            "③/④/⑤ 本来就不读游戏。[/]"
        )
    if report.uncovered:
        console.print(
            f"[yellow]⚠️ 离线未覆盖 {len(report.uncovered)} 项（**不算通过**）—— 明细见上面各闸门[/]"
        )

    if report.missing_precondition:
        blockers = [f.headline for f in report.findings if f.precondition]
        _fail("前置条件缺失：" + "；".join(blockers))
    if not report.ok:
        console.print("[red]有闸门不过 —— 按上面的明细修完再跑一次[/]")
        raise typer.Exit(EXIT_FAILED)
    console.print("[green]五道闸门全过 ✅[/]")


@app.command("ab-probe")
def ab_probe_cmd(
    deploy: Annotated[
        bool, typer.Option("--deploy", help="同步探针与真 mod 进用户 mod 目录并只启用它们")
    ] = False,
    archive: Annotated[
        str,
        typer.Option(
            "--archive",
            help="盯哪一份档案（不给 = 数据源里按文件名排序的第一份，会在输出里写明）",
        ),
    ] = "",
) -> None:
    """生成阶段 3 的 A/B 探针（**不要手改探针文件**，改 `tools/pdx/ab_probe.py`）。

    两局点的是**同一个决议**，唯一差异是角色：A = 决议什么都不做，B = 决议调用真 mod 的
    `sitai_ru_defeat_shock`。自报只盯主角国家，每月记三个槽位落点 +
    改革窗口 JE + 冲击变量 + 6 条改革相关法律 —— **行为层与策略层分开记**，
    因为阶段 3 的失败长相写死了「只有策略层动 = H2 不成立」。

    ``--archive`` 显式指定盯哪一份档案：不写就取数据源里**按文件名排序的第一份**，
    而那个默认值会随着新档案入库而变（`au_revolution` 现在排在最前）——
    所以想复现某次实验的探针，必须把档案名写出来。
    """
    archive_id = archive or None
    built = ab_probe.build(target=ab_probe.load_target(archive_id))
    ab_probe.write(archive_id=archive_id)
    target = ab_probe.load_target(archive_id)
    console.print(
        f"盯的档案：[bold]{target.archive_id if target else '?'}[/]"
        f"（{target.subject if target else '?'}）"
        f"{'（按文件名排序的第一份）' if archive_id is None else ''}"
    )
    console.print(ab_probe.summary(built))
    if deploy:
        dest = ab_probe.deploy(archive_id=archive_id)
        console.print(f"已部署 [bold]{dest}[/]（连同真 mod 一起启用，原列表已备份）")
        console.print(
            f"接着：启动游戏 → 选 {target.subject if target else '主角国家'} 开 1836 → "
            "点【A】或【B】→ 不做任何操作 → 跑 6-8 年 → 退出。"
        )


@app.command("ab-auto")
def ab_auto_cmd(
    arm: Annotated[str, typer.Option("--arm", help="这一臂的归档标签（也是记录里的小节名）")] = (
        "ladder"
    ),
    months: Annotated[int, typer.Option("--months", help="目标观测月数（到点杀进程）")] = 60,
    expect: Annotated[
        str, typer.Option("--expect", help="预期跑到哪一臂：A | B | B2（默认 B2 = 阶梯跑满）")
    ] = "B2",
    repeat: Annotated[int, typer.Option("--repeat", help="臂队列长度（G2 要求两次同向 → 2）")] = 1,
    interval: Annotated[float, typer.Option("--interval", help="轮询间隔秒数")] = (
        ab_auto.POLL_INTERVAL
    ),
    max_polls: Annotated[int, typer.Option("--max-polls", help="轮询次数上限（防呆）")] = (
        ab_auto.MAX_POLLS
    ),
    plan: Annotated[
        bool, typer.Option("--plan", help="只打印臂队列与端口接线情况，不动游戏也不写记录")
    ] = False,
    record: Annotated[
        Path,
        typer.Option("--record", help="实验记录文件（默认 docs/design/exec/阶段3-实验记录.md）"),
    ] = ab_auto.RECORD_PATH,
) -> None:
    """阶段 3 的自动实验编排：启动 → 轮询 → 到点杀进程 → 归档 → 分析 → 写记录。

    **它自己不碰游戏本体**：启动/杀进程由 `game_auto`（并行轨）实现，通过
    :class:`pdx.ab_auto.Ports` 注入；没接上时**当场报错**（P13：不静默跳过）。

    进度的口径是**探针自己报的月度块**（`v3 ab` 去重后的观测数），不是墙钟 ——
    游戏暂停着的时候墙钟照走、月度块不走。

    ```text
    v3 ab-auto --plan                    # 只看队列与接线（安全）
    v3 ab-auto --arm ladder-1 --months 60 --expect B2 --repeat 2
    ```

    每一臂的结果会**追加**进 `docs/design/exec/阶段3-实验记录.md`（报告全文进折叠块），
    某臂没达标就地停下（后面的臂不跑，见 `QueueReport.stopped_early`）。
    """
    arms = [
        ab_auto.Arm(
            name=f"{arm}-{index + 1}" if repeat > 1 else arm,
            months=months,
            expect=expect,
            note=f"第 {index + 1} / {repeat} 局（G2 要的是两次同向）" if repeat > 1 else "",
        )
        for index in range(max(1, repeat))
    ]
    ports = ab_auto.default_ports()
    table = Table(title=f"臂队列（{len(arms)} 局）", show_lines=False)
    table.add_column("臂")
    table.add_column("目标月数", justify="right")
    table.add_column("预期", justify="center")
    table.add_column("备注")
    for item in arms:
        table.add_row(escape(item.name), str(item.months), item.expect, escape(item.note))
    console.print(table)
    console.print(f"日志目录：[bold]{ports.log_dir}[/]　记录：[bold]{ab_auto.RECORD_PATH}[/]")
    console.print(
        "接线：进程查询 ✅（`h1_probe.game_running`）；启动/杀进程 "
        "**未接**（传给 `ab_auto.Ports` 的 `start` / `stop`，由 `game_auto` 提供）"
    )
    if plan:
        console.print("[dim]--plan：什么都没跑、什么都没写。[/]")
        return
    try:
        report = ab_auto.run_queue(
            arms,
            ports_for=lambda _arm: ports,
            path=record,
            interval=interval,
            max_polls=max_polls,
        )
    except ab_auto.OrchestratorError as exc:
        _fail(f"编排中断：{exc}")
    console.print(Markdown(ab_auto.format_queue(report)))
    if not report.ok:
        raise typer.Exit(EXIT_FAILED)


# ── ab（阶段 3：A/B 实验的差分，H2）──────────────────────────
@app.command("ab")
def ab_cmd(
    logs: Annotated[
        Path | None, typer.Option("--logs", help="日志目录（默认用户目录下的 logs）")
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="输出机器可读的 JSON")] = False,
    health_only: Annotated[
        bool,
        typer.Option(
            "--health",
            help="只跑**开局自检**（RUN / 玩家 / 观测 / 角色 / SHOCK / 报错；任一不过退出码 1）",
        ),
    ] = False,
) -> None:
    """A/B 实验：**真实冲击能不能改行为**（阶段 3 的 H2）。

    探针（`v3 ab-probe` 生成）每月只给主角国家（俄罗斯）写几行：

    ```text
    ZZPROBE AB;RUN;A                          ← 开局标记：A=对照、B=处理（点哪个决议就写哪个）
    ZZPROBE AB;PLAYER;yes;俄罗斯               ← 玩家是谁（开错国家时用来自检）
    ZZPROBE AB;SHOCK;yes;俄罗斯                ← 冲击变量在不在（B 组点完决议后应为 yes）
    ZZPROBE AB;JE;active;俄罗斯                ← 行为层①：改革窗口
    ZZPROBE AB;LAW;law_serfdom;俄罗斯          ← 行为层②：当月生效的那条法律
    ZZPROBE AB;POLI;reactionary_agenda;俄罗斯  ← 策略层：三个槽位落点
    ```

    报告**先行为层、再策略层**，两层分开报 —— 执行文档把失败长相写死了：
    **只有策略层动 = H2 不成立（意图层是薄壳）**，那时该停下重估目标，不是加代码。
    同一个角色的多次启动会被合并；两个角色都要有观测才谈得上差分。

    判定分档（`Result.verdict`）：行为层有差分 → `g2_preliminary`（还要**两次同向**才定论）；
    只有策略层动 → `h2_shell`；都没有 → `no_diff`；缺一组 → `insufficient`。
    """
    result = ab.analyze(logs)
    if health_only:
        # 开局自检（P13）：探针没跑、开错国家、冲击没生效这些失败在脚本侧毫无报错，
        # 只有日志里的自报行能看出来 —— 这一条让它们在一分钟内红，而不是跑完才发现。
        items = ab.health(result, log_dir=logs)
        console.print(Markdown(ab.format_health(items)))
        if not all(item.ok for item in items):
            raise typer.Exit(EXIT_FAILED)
        return
    if json_out:
        payload = {
            "runs": list(result.runs),
            "verdict": result.verdict,
            "verdict_text": ab.verdict_text(result),
            "months": result.months,
            "tags": list(result.tags),
            "unpaired": result.unpaired,
            "player": result.player,
            "subject": result.subject,
            "behaviour_changed": result.behaviour_changed,
            "strategy_changed": result.strategy_changed,
            "segments": [
                {
                    "index": segment.index,
                    "declared": segment.declared,
                    "role": segment.role,
                    "blocks": segment.blocks,
                    "months": segment.months,
                }
                for segment in result.segments
            ],
            "roles": {
                role: {
                    "segments": behaviour.segments,
                    "observations": behaviour.observations,
                    "tags": list(behaviour.tags),
                    "shock_yes": behaviour.shock_yes,
                    "shock_rate": behaviour.shock_rate,
                    "input_yes": behaviour.input_yes,
                    "input_rate": behaviour.input_rate,
                    "je_active": behaviour.je_active,
                    "je_share": behaviour.je_share,
                    "je_first": behaviour.je_first,
                    "first_law": behaviour.first_law,
                    "law_change": behaviour.law_change,
                    "law_change_to": behaviour.law_change_to,
                    "bands": [
                        {"band": band.band, "months": band.months, "share": band.share}
                        for band in behaviour.bands
                    ],
                    "laws": [
                        {
                            "law": stat.law,
                            "months": stat.months,
                            "share": stat.share,
                            "first_month": stat.first_month,
                        }
                        for stat in behaviour.laws
                    ],
                }
                for role, behaviour in result.roles.items()
            },
            "slots": {
                role: {
                    slot: {
                        "observations": dist.observations,
                        "most_common": list(dist.most_common) if dist.most_common else None,
                        "counts": [list(item) for item in dist.counts],
                    }
                    for slot, dist in dists.items()
                }
                for role, dists in result.slots.items()
            },
            "behaviour_diffs": [
                {
                    "name": diff.name,
                    "a": diff.a,
                    "b": diff.b,
                    "changed": diff.changed,
                }
                for diff in result.behaviour_diffs
            ],
            "strategy_diffs": [
                {
                    "name": diff.name,
                    "a": diff.a,
                    "b": diff.b,
                    "changed": diff.changed,
                    "note": diff.note,
                }
                for diff in result.strategy_diffs
            ],
            # 第二对照（B → B2，改革侧输入步）：与 ① / ② 同形状，单独一组键 ——
            # 混进上面两组就分不出"哪一处处理起了作用"。
            "input_behaviour_diffs": [
                {
                    "name": diff.name,
                    "a": diff.a,
                    "b": diff.b,
                    "changed": diff.changed,
                }
                for diff in result.input_behaviour_diffs
            ],
            "input_strategy_diffs": [
                {
                    "name": diff.name,
                    "a": diff.a,
                    "b": diff.b,
                    "changed": diff.changed,
                    "note": diff.note,
                }
                for diff in result.input_strategy_diffs
            ],
            "verdict_roles": list(ab.VERDICT_ROLES),
        }
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    if not result.samples:
        console.print(
            "[yellow]日志里没有 AB 的观测行[/] —— 检查三件事：A/B 探针是否启用、"
            "是否进过一局游戏、`--logs` 是否指对了目录。"
        )
    console.print(Markdown(ab.format_report(result)))


@app.command("backlog")
def backlog_cmd(
    doc: str | None = typer.Option(None, "--doc", "-d", help="只看某篇，例如 14"),
    list_items: bool = typer.Option(False, "--list", help="逐条列出还开着的条目"),
    limit: int = typer.Option(30, "--limit", "-n", help="--list 时最多列多少条"),
) -> None:
    """还开着的「未确认 / 待办」条目 —— 把两套计数合成一个数字。

    知识库里有**两层**未解决项：

    * `v3 unverified`：带 `【未确认】` 标记的行 —— 那是承诺（没证据就必须标）；
    * 各篇末尾的「未确认项 / 待办 / 下一步」章节 —— 旧格式下**不带标记**，
      标记数与章节条目数长期各说各话。

    这个命令按章节里表格的**状态列**判定还开不开（`已答 / 已解决 / …` 即已关；
    列表项没有状态列，一律算开着），给出一个可复算的总数。
    ⚠️ 标记项大多也列在章节里，所以 **unverified ⊆ backlog**，两个数字不要相加。
    """
    if doc and not backlog.open_items(doc):
        console.print(f"[green]doc {escape(doc)} 没有还开着的条目[/]")
        return

    opened, closed = backlog.totals(doc)
    counts = backlog.counts_by_doc()
    if doc:
        counts = {k: v for k, v in counts.items() if k.startswith(doc) or doc in k}

    table = Table(title=f"还开着的条目：{opened}（已关 {closed}）", show_lines=False)
    table.add_column("文档")
    table.add_column("未关", justify="right", style="cyan")
    table.add_column("章节", style="dim")
    secs = backlog.sections()
    for name, n in counts.items():
        table.add_row(escape(name), str(n), escape("；".join(secs.get(name, []))[:60]))
    console.print(table)

    if list_items:
        rows = backlog.open_items(doc)
        console.print(f"\n前 {min(limit, len(rows))} / {len(rows)} 条：")
        for item in rows[:limit]:
            console.print(f"  [dim]{escape(item.where)}[/] {escape(item.text[:96])}")


@app.command("unverified")
def unverified_cmd(
    doc: str | None = typer.Option(None, "--doc", "-d", help="只看某篇，例如 04"),
    show_context: bool = typer.Option(True, "--context/--no-context", help="是否带上下文"),
) -> None:
    """列出文档里所有 **【未确认】** 项 —— 待验证清单的可复算版本。

    这些标记是**承诺**：凡是文档没证据的地方都必须标出来，不能凭印象断言。
    这个命令把承诺变成可数、可定位的清单（doc 04 §13 的 U 编号就是它的
    人工整理版），免得「还有多少没验证」只能靠人翻。

    没有未确认项时退出码 0；有则打印清单（退出码 0 —— 它是**清单**不是门禁，
    真正的门禁是 `v3 verify` 与 pytest）。
    """
    items = unknowns.unverified_items(doc=doc)
    if not items:
        scope = f"（doc {doc}）" if doc else ""
        console.print(f"[green]没有 【未确认】 项{scope}[/]")
        return

    by_doc: dict[str, list[unknowns.Unverified]] = {}
    for item in items:
        by_doc.setdefault(item.doc, []).append(item)

    table = Table(title=f"【未确认】清单（{len(items)} 处 / {len(by_doc)} 篇）", show_lines=False)
    table.add_column("文档")
    table.add_column("行", justify="right", style="cyan")
    table.add_column("章节", style="dim")
    table.add_column("上下文" if show_context else "内容")
    for name, group in sorted(by_doc.items()):
        for item in group:
            table.add_row(
                escape(name),
                str(item.line),
                escape(item.section),
                escape(item.context if show_context else item.text),
            )
    console.print(table)


@app.command("show")
def show_cmd() -> None:
    """转储已落盘产物的结构与规模。

    列出产出文件、各 JSON 的顶层字段、以及「一个 common 目录」和
    「一个 mod」记录了哪些内容 —— 改动提取逻辑后用它快速确认产物里
    到底有什么。产物不存在时退出码 2。
    """
    products = [
        ("游戏本体 JSON", config.OUT_GAME / "游戏本体.json"),
        ("mod JSON", config.OUT_MODS / "mod.json"),
        ("交叉 JSON", config.OUT_CROSS / "交叉.json"),
    ]
    game = _load_product(products[0][1], "游戏本体分析")
    mods = _load_product(products[1][1], "mod 分析")
    cross = _load_product(products[2][1], "交叉分析")

    files = [
        *products,
        ("游戏本体报告", config.REPORTS / "游戏本体分析.md"),
        ("mod 报告", config.REPORTS / "mod分析.md"),
    ]
    table = Table(title="产出文件", show_lines=False)
    table.add_column("名称")
    table.add_column("大小", justify="right", style="cyan")
    table.add_column("路径", style="dim")
    for label, path in files:
        table.add_row(escape(label), _size_text(path), escape(_relative(path)))
    console.print(table)

    console.print(_structure_table("游戏本体 JSON —— 顶层字段", game))

    common = game.get("common") or {}
    if common:
        # 样例取 buildings：它的字段最全。取不到就退回第一个目录 ——
        # 旧的 show_outputs.py 写的是 mods["各mod"][1]，产物结构一变就
        # IndexError，属于把「当前数据长什么样」硬编码进了展示代码。
        sample = "buildings" if "buildings" in common else next(iter(common))
        console.print(f"\n  · common 每个目录记录的内容（样例：{escape(sample)}）")
        console.print(_structure_table("", common[sample]))

        entries = sum(len(body.get("条目", [])) for body in common.values())
        fields = sum(len(body.get("字段", {})) for body in common.values())
        console.print(f"      common 条目名合计 {entries:,}")
        console.print(f"      common 字段名合计 {fields:,}")

    console.print(_structure_table("mod JSON —— 顶层字段", mods))

    mod_rows = mods.get("各mod") or []
    if mod_rows:
        first = mod_rows[0]
        name = first.get("名称") or first.get("目标") or "—"
        console.print(f"\n  · 每个 mod 记录的内容（样例：{escape(str(name))}）")
        console.print(_structure_table("", first))

    console.print(_structure_table("交叉 JSON —— 顶层字段", cross))


if __name__ == "__main__":  # pragma: no cover - 手工运行入口
    app()
