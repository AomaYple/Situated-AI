"""Commands that generate and check project documentation."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    citations,
    config,
    doc_tables,
    docgen,
    docs_mirror,
    snapshot,
    tables_offline,
    unknowns,
    verify,
)
from pdx.extract import extract_dir
from pdx.generation_transaction import GenerationTransaction
from pdx.parser import parse_file

from . import common
from .common import EXIT_FAILED, console
from .common import fail as _fail
from .common import relative as _relative
from .common import require_current_output as _require_current_output

#: 全量键名索引的落点。由 `v3 index` 重新生成。
OUT_INDEX_DOC = config.DOCS / "13-common全量键名索引.md"
_STARTUP_OUT_INDEX_DOC = OUT_INDEX_DOC


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

本索引由 `v3 index` 生成（入口见 `src/pdx/cli.py`），口径如下：

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


def index_cmd(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只打印统计，不写文件")] = False,
) -> None:
    """重新生成当前知识库的 13-common全量键名索引.md。

    取代早期用 PowerShell 正则生成的那一版：本版由 pdx 包驱动，因此自动
    获得 BOM 剥离、引号感知注释、花括号深度判定与连字符键名支持。
    """
    common.require_game()
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

    output_doc = (
        OUT_INDEX_DOC
        if OUT_INDEX_DOC != _STARTUP_OUT_INDEX_DOC
        else config.docs_root() / OUT_INDEX_DOC.name
    )
    try:
        # newline="\n"：见 analyze.dump 的注释 —— 否则文档在 Windows 上写成
        # CRLF，与 .gitattributes 的 eol=lf 打架，每次 `v3 index` 都弄脏工作树。
        output_doc.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        _fail(f"无法写入 {output_doc}：{type(exc).__name__}: {exc}")
    console.print(
        f"[green]已写入[/] {escape(_relative(output_doc))}  "
        f"行数 {len(text.splitlines()):,}  字节 {output_doc.stat().st_size:,}"
    )


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
        common.require_game()
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


def mirror_write(
    sync: Annotated[bool, typer.Option("--sync", help="顺便把本地镜像从游戏重拷一份")] = False,
) -> None:
    """重新生成清单（要游戏）；``--sync`` 同时重建本地镜像。

    清单入库（约 17 KB），镜像不入库（Paradox 版权内容）。
    见 :mod:`pdx.docs_mirror` 的模块文档 —— 那里也写明了
    「移出版本控制 ≠ 从历史里清除」这个限制。
    """
    common.require_game()
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
            dst.write_bytes(docs_mirror.text_bytes(src.read_bytes().decode("utf-8-sig")))
            copied += 1
        console.print(f"[green]已同步本地镜像[/] {copied} 篇 → {escape(_relative(root))}")

    console.print(
        "[dim]清单里的字节/行数变了的话，记得同步 07-官方文档索引.md（v3 verify 会核对）[/]"
    )


def refresh_cmd(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只报告会改什么，不写盘")] = False,
) -> None:
    """**游戏升级后的一条命令**：重算生成表 + 按归属标记改写正文数字，再报剩下的红点。

    先在临时目录应用生成表与数字修订，再核对断言和文档。全部通过后写回。
    报告中的以下问题需要人工核对：

    * 无标记的数字（数字不在正文里 / 在表格里 / 形态不同）；
    * 判断类内容（叙述、历史对照句 —— 登记在 ``PROSE_NOT_COMPUTED``）；
    * 断言失败（真值变了但口径也需要人看一眼的那几条）。

    为什么要有它：这两步原先要人记得按顺序跑，而**忘记跑 = 文档静默过期**，
    正是这个仓库反复踩的坑（doc 04 的 682 行活了整整一个版本、README 的
    164/226 停了两轮）。跑完退出码 0 表示全绿；否则 1，并列出剩余项。
    """
    common.require_game()
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
        console.rule("[bold]2/3 按归属标记改写正文数字[/]")
        pending = verify.fix_markers(write=False)
        console.print(f"  [yellow]--dry-run：{len(pending)} 处需要改[/]")
        for item in pending[:20]:
            console.print(f"  {escape(item.describe())}")
        marker_issues = verify.check_markers()
        drift = verify.unknown_doc_drift()
    else:
        _require_current_output()
        try:
            originals = {path: path.read_bytes() for path in config.docs_root().glob("*.md")}
            documents, written = docgen.render_documents()
            if unexpected := documents.keys() - originals.keys():
                raise ValueError(f"生成表路径不在当前知识库：{sorted(unexpected)}")
            console.rule("[bold]2/3 按归属标记改写正文数字[/]")
            with TemporaryDirectory(prefix="sitai-doc-refresh-") as directory:
                preview = Path(directory)
                for path, content in originals.items():
                    generated = documents.get(path)
                    (preview / path.name).write_bytes(
                        content if generated is None else generated.encode("utf-8")
                    )
                fixes = verify.fix_markers(preview, write=True)
                marker_issues = verify.check_markers(preview)
                drift = verify.unknown_doc_drift(preview)
                outputs = {}
                for path, content in originals.items():
                    candidate = (preview / path.name).read_bytes()
                    if candidate != content:
                        outputs[path] = candidate
        except (doc_tables.TableNotFoundError, ValueError, OSError) as exc:
            _fail(f"准备文档失败：{type(exc).__name__}: {exc}")

    console.rule("[bold]3/3 核验剩下的[/]")
    results = verify.run_claims(verify.current_claims(), include_slow=True)
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
            f"  [red]❌[/] {escape(f'[{r.claim.id}]')} 期望 {escape(str(r.claim.expected))} 实得 {escape(str(r.actual))}"
        )
    if failed or drift or marker_issues:
        console.print(
            "[yellow]剩下的机器改不了[/] —— 上面每条都指到了具体行；"
            "判断类内容见 `test_inventory.PROSE_NOT_COMPUTED`。"
        )
        raise typer.Exit(EXIT_FAILED)
    if not dry_run:
        try:
            if any(path.read_bytes() != content for path, content in originals.items()):
                raise ValueError("文档在准备写入期间已变更")
            with GenerationTransaction() as transaction:
                transaction.replace(outputs)
        except (ValueError, OSError) as exc:
            _fail(f"写回文档失败：{exc}")
        console.print(f"  [green]重算 {len(written)} 张表 / {sum(written.values())} 行[/]")
        for item in fixes[:40]:
            console.print(f"  [cyan]{escape(item.describe())}[/]")
        console.print(f"  共改写 [bold]{len(fixes)}[/] 处")
    console.print("[green]全部一致：表格、正文数字、断言。没有需要人改的东西。[/]")


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
    if write:
        _require_current_output()
    if offline:
        _tables_offline(write=write, only=only)
        return
    if only:
        _fail("--only 只在 --offline 下有意义（在线核对是逐表与生成结果比对）")
    common.require_game()

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
    try:
        recorded = tables_offline.load_tables()
    except snapshot.SnapshotFormatError as exc:
        _fail(str(exc), EXIT_FAILED)
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

    covered = sum(not only or only in key.partition("::")[0] for key in recorded) - len(orphans)
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


def citations_cmd(
    paths: Annotated[
        list[str] | None,
        typer.Argument(help="要扫描的说明文件或目录"),
    ] = None,
) -> None:
    """核对说明文件里的 `文件:行号` 引用能否解析到当前游戏原版的唯一一行。

    ```text
    文件名写错（00_sikh_empire.txt 其实叫 04_sikh_empire.txt） ⇒ missing
    少了子路径（ai_strategies/… 其实在 common/ai_strategies/） ⇒ missing
    行号越界（文件 300 行，引了 :322）                          ⇒ out_of_range
    同名文件有几十个（modifiers.txt）                          ⇒ ambiguous
    ```

    必须显式提供路径，避免隐式扫描已删除的旧数据目录。此命令只检查引用路径、唯一性和行号，
    不判断被引内容是否支持说明中的结论；生产接口由 `modguard` 单独核验。
    """
    if not paths:
        _fail("至少指定一个说明文件或目录")
    common.require_game(optional=True)
    targets = [Path(item) for item in paths]
    missing = [str(path) for path in targets if not path.exists()]
    if missing:
        _fail(f"找不到：{'、'.join(missing)}")
    found = citations.scan_paths(targets)
    if not found:
        _fail("指定路径中没有发现文件:行号引用")
    problems = [item for item in found if not item.ok]
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
    if problems:
        console.print(table)
        console.print(f"[yellow]{len(problems)} 条引用指不到唯一一行[/]")
        raise typer.Exit(EXIT_FAILED)
    console.print(f"[green]{len(found)} 条引用全部指得到唯一一行 ✅[/]")


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
