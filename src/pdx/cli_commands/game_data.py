"""Inspect the installed game and export its data and supported surfaces."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    ai_surface,
    assets,
    config,
    defines,
    political_surface,
    tabular,
)
from pdx import mods as mods_mod

from . import common
from .common import console
from .common import fail as _fail
from .common import require_current_output as _require_current_output
from .common import require_file as _require_file
from .common import write_json as _write_json


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
    common.require_game()

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
    common.require_game(optional=True)
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
    common.require_game(optional=True)
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
    common.require_game()
    path = (config.GAME / rel).resolve()
    if not path.is_relative_to(config.GAME.resolve()):
        _fail("表格路径必须位于锁定游戏目录内")
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
        top_values = "、".join(f"{v}×{n}" for v, n in stat.top[:3])
        out.add_row(escape(stat.name), str(stat.distinct), str(stat.blanks), escape(top_values))
    console.print(out)


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

    这是当前 Mod 信息目录的机械生成器，回答三个问题（全部**枚举**自原版文件，不手抄）：

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
    if write or check or offline:
        common.require_workspace()
    if write:
        _require_current_output()
    if offline:
        try:
            ai_surface.read_offline()
        except ai_surface.OfflineUnavailableError as exc:
            _fail(str(exc))
    else:
        common.require_game()

    if check:
        try:
            problem = ai_surface.check_doc(game=config.GAME, top=top, offline=offline)
        except ai_surface.OfflineUnavailableError as exc:
            _fail(str(exc))
        if problem:
            _fail(problem)
        console.print(f"[green]{escape(ai_surface.doc_path().as_posix())} 与生成结果一致 ✅[/]")
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
        cards = ai_surface.read_cards(config.GAME)
        defines = ai_surface.read_defines(config.GAME)
    inputs = ai_surface.collect_inputs(cards)

    if write:
        try:
            path = ai_surface.write_doc(game=config.GAME, top=top, offline=offline)
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
    console.print(f"跑 `v3 ai-surface --write` 生成 `{ai_surface.doc_path().as_posix()}`。")


def political_surface_cmd(
    write: Annotated[
        bool, typer.Option("--write", help="生成/更新 docs/design/02-政治候选面.md")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="核对文档与当前原版政治策略是否一致")
    ] = False,
    json_path: Annotated[
        Path | None,
        typer.Option("--json", help="另写一份结构化 JSON 索引（可选路径）"),
    ] = None,
) -> None:
    """枚举原版政治策略的法律候选输入与静态字段。

    该命令解析 ``change_law_chance``、通过率阈值、方向上限、革命厌恶和
    IG/运动偏好，并保留每个条件加法的来源行。它不计算引擎最终启动概率、
    候选排序或随机抽签；这些仍需实机 Getter 或行为证据。
    """
    if write or check:
        common.require_workspace()
    common.require_game()
    try:
        strategies = political_surface.read_strategies(config.GAME)
        default_strategy = political_surface.read_default_strategy(config.GAME)
    except (OSError, ValueError) as exc:
        _fail(f"原版政治策略无法读取：{exc}")
    if check:
        problem = political_surface.check_doc(game=config.GAME)
        if problem:
            _fail(problem)
        console.print(f"[green]{escape(political_surface.DOC_REL)} 与生成结果一致 ✅[/]")
    if write:
        path = political_surface.write_doc(game=config.GAME)
        console.print(
            f"[green]已写入 {escape(str(path))}[/]：{len(strategies)} 张政治策略牌 + 默认层"
        )
    if json_path is not None:
        path = political_surface.write_json(json_path, game=config.GAME)
        console.print(f"[green]已写入 {escape(str(path))}[/]")
    if write or check or json_path is not None:
        return
    table = Table(title=f"原版政治策略：{len(strategies)} 张 + 默认层", show_lines=False)
    table.add_column("策略")
    table.add_column("change_law_chance")
    table.add_column("通过阈值")
    table.add_column("进度/倒退上限")
    table.add_column("来源")
    for strategy in strategies:
        change = political_surface._format_summary(strategy.change_law_chance)
        minimum = political_surface._format_summary(strategy.min_law_chance_to_pass)
        direction = (
            f"{political_surface._format_summary(strategy.max_progressiveness)} / "
            f"{political_surface._format_summary(strategy.max_regressiveness)}"
        )
        table.add_row(
            escape(strategy.name),
            escape(change),
            escape(minimum),
            escape(direction),
            escape(f"{strategy.file}:{strategy.line}"),
        )
    table.add_row(
        escape(default_strategy.name),
        escape(political_surface._format_summary(default_strategy.change_law_chance)),
        "—",
        "—",
        escape(f"{default_strategy.file}:{default_strategy.line}"),
    )
    console.print(table)
    console.print(
        "静态字段不等于最终引擎启动概率；运行 `v3 political-surface --write` 生成可追踪文档。"
    )
