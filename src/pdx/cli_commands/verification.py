"""Verification commands for live and offline game evidence."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    verify,
)

from . import common
from .common import EXIT_FAILED, console
from .common import READ_ERRORS as _READ_ERRORS
from .common import fail as _fail
from .common import require_current_output as _require_current_output
from .common import write_json as _write_json


def _verify_from_snapshot(*, claims: list[verify.Claim], only: str | None, no_drift: bool) -> None:
    """``v3 verify --from-snapshot``：不读游戏，用**入库的离线真值**核验。

    两份真值：精简快照（目录条目、defines、DLC 清单）与官方文档清单
    （94 篇 ``.md`` 的篇数与逐篇字节数）。后者是新加的 —— 官方文档那几条断言
    本来就不需要游戏，白丢在 CI 覆盖之外没有道理。

    抽成独立函数而不是塞在 ``verify_cmd`` 里，是为了让「无游戏也能跑」
    这条路径足够显眼 —— 它是 CI 上唯一能真正核对断言的入口。
    """
    try:
        snap = verify.latest_compact_snapshot()
    except _READ_ERRORS as exc:
        _fail(f"当前版本离线快照无法读取：{type(exc).__name__}: {exc}")
    if snap is None:
        # 不再直接退出：官方文档清单是第二份离线真值，没有快照时它照样能核验。
        console.print(
            "[yellow]没有精简快照（tools/out/snapshots/*.compact.json）—— "
            "只核验官方文档清单那几条。在装有游戏的机器上跑 "
            "`v3 snapshot create --compact` 可补上一份（它是入库的）。[/]"
        )

    selected = [c for c in claims if not only or only in c.id]
    if only and not selected:
        _fail(f"没有 id 含 {only!r} 的断言（注册表共 {len(verify.current_claims())} 条）")

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
        f"    [dim]（离线真值覆盖 {covered}/{len(verify.current_claims())} 条；"
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
    跳过；入库精简快照里的 common 条目名、defines 命名空间与 DLC 清单只支持
    部分断言，实际覆盖范围以命令输出为准。它证明的是「断言注册表
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
        common.require_game()
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
        _require_current_output()
        try:
            changes = verify.fix_markers(write=True)
        except (ValueError, OSError) as exc:
            _fail(f"改写文档标记失败：{exc}")
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
        _verify_from_snapshot(claims=verify.current_claims(), only=only, no_drift=no_drift)
        return

    common.require_game()
    claims = verify.current_claims()
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
                f"（注册表共 {len(verify.current_claims())} 条；用 v3 verify 不带 --only 查看全部）"
            )

    machine = [claim for claim in claims if verify.claim_scope(claim) == "machine_snapshot"]
    if machine:
        console.print(f"[dim]{len(machine)} 条有日期的本机 Mod 观察值由文档断言保留。[/]")
        if len(machine) == len(claims):
            _fail("所选断言都属于附日期的本机 Mod 观察值。")
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
