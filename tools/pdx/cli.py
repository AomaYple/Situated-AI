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
# 解析命令签名，注解挪进 TYPE_CHECKING 块会让 ``v3 --help`` 直接 NameError
# （已实测）。所以这里不能按 TCH 规则处理，只能就地豁免。
from pathlib import Path  # noqa: TC003
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from pdx import (
    analyze,
    config,
    defines,
    doc_tables,
    docgen,
    docs_mirror,
    engine_log,
    exe_strings,
    snapshot,
    verify,
)
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
    ``--compact`` 产出**精简快照**（约 4.9 MiB）：结构域原样保留，
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
    """
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
    跳过，而精简快照（已入库、约 4.9 MiB）里带着 common 各目录的条目名、
    defines 命名空间与 DLC 清单，足以核验其中约一半。它证明的是「断言注册表
    仍与当时记录的真值一致」，**不**证明「游戏里现在还是这个数」。

    **``--fix``**：正文里带归属标记的数字（``205<!--claim:dip.group_files-->``）
    会被改写成断言期望值。它只碰**带标记的那一个数字**，包裹（``**`` / 反引号）
    与空格原样保留，因此不是「猜着改文本」，而是「按归属改」。不带 ``--fix``
    时同一套逻辑只报告不改 —— 两者共用一条实现，免得「说会改 A、实际改了 B」。
    """
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
                f"[yellow]共 {len(drift)} 处[/]。若确认是「口径不同、文档没错」，"
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

    bad_tokens = report.token_mismatches
    if bad_tokens:
        console.print("\n[red]token 行号不一致：[/]")
        for rel, line, tok, got in bad_tokens[:20]:
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
            },
        )

    if gaps or bad_tokens:
        raise typer.Exit(EXIT_FAILED)
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
) -> None:
    """开采 `victoria3.exe` 的字符串：引擎里有、脚本里没用的标识符。

    这是 `tools/README.md`「已知边界」里那个下一步的**可复算版本**：
    原先正文里的两个数字（17,821 / 16,535）是一次性采集值，口径没留、脚本没留。
    口径见 `pdx.exe_strings`（扫可打印 ASCII 串 → 取标识符形状 → 与脚本词表作差）。

    它给的是**线索**而不是结论：候选里混着编译器与 CRT 符号，哪些是 PDX 的
    字段枚举要人看。文件不存在时退出码 2。
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

    if show_list:
        rows = exe_strings.unused_identifiers()
        console.print(f"\n未使用候选（前 {min(limit, len(rows))} / {len(rows):,}）：")
        for name in rows[:limit]:
            console.print(f"  {escape(name)}")


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
