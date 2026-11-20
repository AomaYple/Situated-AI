"""Commands for engine logs, executable strings, and evidence summaries."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    config,
    engine_log,
    evidence,
    exe_strings,
)

from . import common
from .common import EXIT_FAILED, EXIT_UNVERIFIABLE, console
from .common import fail as _fail
from .common import relative as _relative
from .common import write_json as _write_json

#: 它是 :meth:`pdx.engine_log.CrossCheckReport.token_verdicts` 的职责，本命令只**消费**。
#:
#: ⚠️ 曾经这里有一个 ``_judge_token_line`` 自己拿 ``line_counts`` 再判一遍（2026-09-28
#: 定、同日收口时删掉）：那就有两套判据，同一份输入两个结论 —— 生效文件整份缺失时
#: 模块判「不可核对」，而命令层因为 ``line_counts.get(rel, (0, 0))`` 两值相等判「真错配」。
#: 判据只能有一处；删掉之后的复现命令与本轮口径修正的来龙去脉见
#: 用户提供日志后的分类只写入 `tools/out/`，不把运行期推断混入当前规则。


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

    退出码分四档（见模块文档）：0 = 完全一致；1 = 有该修的问题（覆盖面缺口、
    或**行号可比的**真错配）；2 = 前置条件缺失；**3 = 不可核对** —— 检查跑了，
    但被核对的文件被 mod 覆盖、与原版不是同一套行号（行数不同 / 文件整份被删），
    「token 在不在那一行」这个问题本身无从回答。打 3 而不是 0/1，
    是因为这一档既不是通过（0 会把"没核对"说成"核对通过"），
    也不是不一致（1 会把两套行号的差记到解析器头上）——
    同族教训见历史审计 B85。
    """
    claims, version = engine_log.parse_logs()
    if not claims:
        _fail(f"找不到引擎日志：{engine_log.default_log_dir()}（需要先运行过一次游戏）")
    common.require_game()

    # 覆盖映射要留着 —— 「结论 = 不可核对」那一档必须写出**覆盖来源**
    # （哪个 mod 的哪份文件顶替了原版），否则读的人只看到"对不上"却不知道在跟谁对。
    overrides = engine_log.build_override_map()
    report = engine_log.cross_check(claims, log_version=version, overrides=overrides)
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

    # token 不一致要**判到底该不该核对**，不能混成一坨"不一致"。
    # ⚠️ 判据只有一处：:meth:`pdx.engine_log.CrossCheckReport.token_verdicts`（三态）。
    # 本命令只**消费**结论、只负责措辞与退出码 —— 不再自己读 ``line_counts`` 判一遍
    # （曾经命令层重判过一次，于是同一份输入两个结论，2026-09-28 收口时删掉）：
    #   ① 不可核对（行号不可比 / 日志比安装旧）⇒ 既不是通过，也不是不一致，退出码 3；
    #   ② 真错配（行号可比却对不上）⇒ 判红，这才是值得查的。
    # 把①②报成红，等于把"日志过期/两套行号"的账记到解析器头上（2026-09-22 实测 18/18）。
    verdicts = report.token_verdicts()
    #: 日志比安装旧的那一支（生效与原版都找不到这个 token）—— 与"行号不可比"分列说。
    absent = report.absent_tokens
    #: 行号不可比那一档（不可核对的主档）：既不能用 0 冒充成功，也不能用 1 冒充失败。
    unverifiable = [
        v
        for v in verdicts
        if v.state == engine_log.TOKEN_UNVERIFIABLE and v.kind != engine_log.KIND_STALE_ABSENT
    ]
    #: 真错配（行号可比却对不上）—— 唯一判红的一档，也是唯一要看行号的一档。
    misplaced_v = [v for v in verdicts if v.state == engine_log.TOKEN_MISPLACED]
    misplaced = [v.as_tuple for v in misplaced_v]
    #: 行号不可比的文件 -> 覆盖它的那个 mod 文件（"覆盖来源"，人要看的就是它）。
    override_source: dict[str, Path] = {
        v.file_rel: overrides[v.file_rel] for v in unverifiable if v.file_rel in overrides
    }

    # 摘要表已在上面打印过；模块的 ``summary()`` 里已经带三态读数，所以这里不再另加
    # 一行"重判"（两处各说一个数正是这轮要消灭的东西），表也不重印第二遍。

    if unverifiable:
        console.print(
            f"\n[yellow]⚠️ 不可核对：{len(unverifiable)} 条 token 断言的版本或行号不具备可比性。[/]"
        )
        console.print(
            "[yellow]   结论 = 不可核对（既不是通过，也不是不一致；本命令退出码 3）："
            "验不了的不是解析器，是我们与引擎读的不是同一份内容。[/]"
        )
        for v in unverifiable:
            console.print(
                f"   ⚠️ {escape(v.file_rel)}  日志第 {v.line} 行 {escape(repr(v.token))}"
                f" —— {escape(v.reason)}"
            )
        if override_source:
            console.print("   覆盖来源（引擎读的是它，我们读的也是它）：")
            for rel in sorted(override_source):
                console.print(f"     ⚠️ {rel}  ←  {_relative(override_source[rel])}")
        elif not any(v.kind == engine_log.KIND_VERSION_INCOMPARABLE for v in unverifiable):
            # 文件整份缺失的那一档没有覆盖来源可写：宁可少写一行，也不写空标题。
            console.print("   覆盖来源：无（生效文件整份缺失，不是被覆盖版持有）。")
        if misplaced:
            console.print("   这一档**不参与**下面的判红，也不用跑一次常规游戏去修它。")
        else:
            console.print("   ⇒ 跑一次常规游戏（与当前 mod 集一致）即可让行号重新可比。")
    if absent:
        console.print("\n[yellow]token 在当前安装中整份文件都找不到（日志比安装旧）：[/]")
        for rel, line, tok, _got in absent[:20]:
            console.print(f"  ⚠️ {rel}:{line}  {tok!r}")
        console.print(
            "  ⇒ 这些**不是**解析器问题：日志描述的是另一套 mod 状态。"
            "跑一次常规游戏即可让日志与安装一致。"
        )
    if misplaced:
        console.print("\n[red]token 行号不一致（真错配）：[/]")
        for rel, line, tok, got in misplaced[:20]:
            # got 是「那一行上有没有」；没有时再看跨行搜索命中的第几行 ——
            # 直接印 None 会读成「我们什么都没找到」，与事实不符（行号可比时刻意打印行号）。
            our_line: int | None = (
                got if got is not None else report.tokens_anywhere.get((rel, tok))
            )
            where = f"第 {our_line} 行" if our_line is not None else "整份文件都没有"
            console.print(f"  ❌ {rel}:{line}  {tok!r}  我们给出：{where}")

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
                    "不可核对（行号不可比）": len(unverifiable),
                    "真错配（行号可比）": len(misplaced),
                    "不可核对": [
                        {
                            "文件": v.file_rel,
                            "日志行": v.line,
                            "token": v.token,
                            "覆盖版的行": v.ours,
                            "说明": v.reason,
                            "来源细分": v.kind,
                            "覆盖来源": (
                                _relative(override_source[v.file_rel])
                                if v.file_rel in override_source
                                else None
                            ),
                        }
                        for v in unverifiable
                    ],
                    "整份文件都没有": [
                        {"文件": rel, "行": line, "token": tok} for rel, line, tok, _ in absent
                    ],
                    "真错配（在但不在那一行、且行号可比）": [
                        {
                            "文件": v.file_rel,
                            "行": v.line,
                            "token": v.token,
                            # 与上面同一口径：我们没有它对，但我们知道它在第几行时不许写 None 搪塞。
                            "我们的行": v.ours,
                        }
                        for v in misplaced_v
                    ],
                    "引擎日志模块的三态读数（本命令与它同源）": s,
                },
            },
        )

    # 退出码只认"真正该查的"一类：覆盖面缺口 与**行号可比的**真错配。
    # 不参与的两类：① 行号不可比（文件被覆盖、行数不同／文件被删）；② token 在当前安装里
    # 不存在（日志比安装旧）。判红就是把过期数据/两套行号的账记到解析器头上 ——
    # 实测 18 条不一致里 18 条属于这两类，2026-09-28 那 2 条也落在①。
    # 「不可核对」单独一档（退出码 3）：既不能用 0 冒充成功，也不能用 1 冒充失败。
    # ⚠️ 退出码与三态**一一对应**（判据同源，见上面 verdicts）：
    #   1 = 覆盖面缺口 或 至少一条 TOKEN_MISPLACED；
    #   3 = 至少一条 TOKEN_UNVERIFIABLE（行号不可比 / 日志比安装旧）；
    #   0 = 其余（全部 TOKEN_MATCH）。
    if gaps or misplaced:
        raise typer.Exit(EXIT_FAILED)
    if unverifiable or absent:
        console.print(
            f"\n[yellow]结论 = 不可核对：{len(unverifiable)} 条 token 行号不可比"
            f"（另有 {len(absent)} 条 token 在当前安装里整份文件都找不到）；"
            f"除此以外与引擎日志一致。本命令退出码 {EXIT_UNVERIFIABLE}"
            "（既不是通过，也不是不一致）。[/]"
        )
        console.print(
            "[yellow]   ⇒ 跑一次常规游戏、让引擎日志与当前 mod 集一致，这一档即可核对。[/]"
        )
        raise typer.Exit(EXIT_UNVERIFIABLE)
    console.print("\n[green]与引擎日志完全一致 ✅[/]")


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
    common.require_game()
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
    common.require_game(optional=True)
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

    root = (config.GAME / directory).resolve() if directory else None
    if root is not None and not root.is_relative_to(config.GAME.resolve()):
        _fail("原版检索路径必须位于锁定游戏目录内")
    reports = evidence.gather(keys, mods=mods, root=root)
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
