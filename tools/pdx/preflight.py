"""开局前的**前置条件自检**（P13：前置条件缺失要说清，不是"跑起来才知道"）。

为什么值得单独一个模块：一次实机会话的代价不是"几秒钟" —— 它要启动游戏
（实测到选国家界面约 137 秒）、把用户屏幕借走、跑几十个游戏月，
**而失败往往在开局后十几分钟才暴露**（比如探针盯的国家不对、日志里混着上一局的自报、
盘上产物是手改过的旧版本）。这些条件**在开局前全部可查**，而且不需要游戏在跑。

三条设计约束（都是被真实事故逼出来的）：

* **一条都不许"顺带修"**：这里只**报告**，不改用户的 `content_load.json`、不动日志、不写盘。
  检查脚本自己去改环境，就变成了第二个会留下烂摊子的东西。
* **每条都要给出"怎么修"**：只说"不一致"等于把问题原样丢回给人。
* **缺条件与"跑不了"分开**：游戏没装、没数据源这类是**前置条件缺失**（退出码 2），
  而"产物被手改过""配置没恢复"是**真的有问题**（退出码 1）—— 混在一起会让人分不清
  该修什么、还是该换台机器。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pdx import config, modgen

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: 「跑不了」与「跑得起来但会白跑」的分界。
#:
#: ``BLOCKING``：缺了它这一局根本开不起来（游戏本体 / 数据源）⇒ 退出码 2。
#: ``WRONG``：开得起来，但读数会是错的或用户环境被动过 ⇒ 退出码 1。
BLOCKING = "blocking"
WRONG = "wrong"
INFO = "info"


@dataclass(frozen=True, slots=True)
class Check:
    """一条前置条件。``level`` 只影响**怎么报/退出码**，不影响要不要显示。"""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    level: str = WRONG

    def describe(self) -> str:
        # ⚠️ 提示（INFO）用 ⚠️ 不用 ❌：它**不拦路**，用红叉会让人以为开局被挡住了。
        mark = "✅" if self.ok else ("⚠️" if self.level == INFO else "❌")
        tail = f"   → {self.fix}" if (self.fix and not self.ok) else ""
        return f"{mark} {self.name}：{self.detail}{tail}"


@dataclass(frozen=True, slots=True)
class Report:
    """一次自检的全部结论。"""

    checks: list[Check] = field(default_factory=list)

    #: 真的有问题（退出码 1）：开得起来但会白跑 / 动了用户环境。
    @property
    def wrong(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.level == WRONG]

    #: 前置条件缺失（退出码 2）：这台机器现在跑不了这一局。
    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.level == BLOCKING]

    @property
    def ok(self) -> bool:
        return not self.wrong and not self.blocking

    def exit_code(self) -> int:
        """0 = 可以开局；1 = 有该修的问题；2 = 这台机器现在跑不了。"""
        if self.blocking:
            return 2
        return 1 if self.wrong else 0

    #: 提示（不拦路）：值得知道，但不该阻止开局。
    @property
    def notes(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.level == INFO]

    def lines(self) -> list[str]:
        out = [c.describe() for c in self.checks]
        bad = self.wrong + self.blocking
        if bad:
            out.append("")
            out.append(f"共 {len(bad)} 条不满足（{len(self.blocking)} 条是前置条件缺失）")
        if self.notes:
            out.append(f"另有 {len(self.notes)} 条提示（不拦路）")
        return out


def _game_version() -> str:
    """启动器声明的版本号（``1.14.4``）—— 与 mod 元数据比对用的就是这个。"""
    settings = config.ROOT / "launcher" / "launcher-settings.json"
    if not settings.is_file():
        return ""
    try:
        data = json.loads(settings.read_text(encoding="utf-8-sig"))
    except ValueError:  # pragma: no cover - 坏文件由「游戏本体」那条报出来
        return ""
    return str(data.get("rawVersion") or "")


def _mod_metadata() -> dict[str, object]:
    path = config.REPO / "mod" / ".metadata" / "metadata.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:  # pragma: no cover - 生成物坏了由「产物一致」那条报出来
        return {}
    return data if isinstance(data, dict) else {}


def check_game() -> Check:
    """游戏本体在不在（这是"这台机器能不能跑"的第一条）。"""
    if not config.GAME.is_dir():
        return Check(
            "游戏本体",
            False,
            f"找不到 {config.GAME}",
            "装游戏，或在 config 里指到正确的安装根（`v3 doctor` 可看路径来源）",
            level=BLOCKING,
        )
    exe = config.ROOT / "binaries" / "victoria3.exe"
    if not exe.is_file():  # pragma: no cover - 正常安装都有
        return Check("游戏本体", False, f"没有 {exe.name}", "检查安装是否完整", level=BLOCKING)
    return Check("游戏本体", True, f"{_game_version() or '版本读不到'} · {config.GAME}")


def check_version_matches_mod() -> Check:
    """游戏版本 == mod 元数据声明的 ``supported_game_version``。

    不一致不会让游戏开不起来，但它意味着**这一局的读数与 mod 声明的支持面不符**：
    启动器会对 mod 弹版本警告，而更麻烦的是"版本警告"与"mod 真的坏了"在截图里长得像。
    """
    want = str(_mod_metadata().get("supported_game_version") or "")
    got = _game_version()
    if not want or not got:  # pragma: no cover - 缺元数据由「产物一致」那条报
        return Check(
            "版本一致",
            False,
            f"读不到版本（mod 声明 {want!r}，游戏 {got!r}）",
            "跑 v3 modgen --write",
        )
    if want == got:
        return Check("版本一致", True, f"{got}")
    return Check(
        "版本一致",
        False,
        f"mod 声明 {want}，本机游戏是 {got}",
        "改 mod/data/*.toml 的 game_version 后 `v3 modgen --write`（或把游戏升/降到同一版）",
    )


def check_products() -> Check:
    """盘上产物 == 数据源（P3：产物不许手改）。

    这条必须在开局前查：手改过的产物**照样能加载**，于是"这一局的读数为什么怪"
    会变成一场考古。走的是与 `v3 modgen --check` **同一个** `modgen.check`，
    且必须用 `build_all`（单档案的 `build()` 只覆盖一份）。
    """
    try:
        built = modgen.build_all(modgen.load_all())
    except Exception as exc:
        return Check(
            "产物一致",
            False,
            f"编译数据源失败：{type(exc).__name__}: {exc}",
            "先修 mod/data 里的数据源",
            level=BLOCKING,
        )
    diffs = modgen.check(built)
    if diffs:
        return Check(
            "产物一致",
            False,
            f"{len(diffs)} 处不一致：{diffs[0]}",
            "跑 `v3 modgen --write`（产物由数据源生成，不要手改）",
        )
    return Check("产物一致", True, f"{len(built.files)} 个产物与数据源逐字节一致")


def check_no_leftover_game(pids: Iterable[int] | None = None) -> Check:
    """没有残留的 ``victoria3`` 进程。

    有残留时开局会失败在"窗口找到了但不是这一局的"这类难查的地方，
    而探针脚本会**先杀掉**它 —— 那意味着人正在玩的存档会被强杀，所以要在开局前说清。
    """
    from pdx import game_auto  # noqa: PLC0415  -- 只有这条检查要拉 pywin32 那一串

    alive = list(pids if pids is not None else game_auto._process_pids())
    if alive:
        return Check(
            "无残留进程",
            False,
            f"还有 {len(alive)} 个 victoria3 在跑：{alive}",
            "先关掉游戏（探针脚本会强杀它 —— 正在玩的存档会丢）",
        )
    return Check("无残留进程", True, "干净")


def check_user_config() -> Check:
    """用户的 mod 配置**现在是原样**的（不是上一次实验留下的状态）。

    判据三条，缺一不可（第三条是 2026-09-24 补的，见下）：

    1. 有没有残留备份（``*.v3probe-backup`` / ``*.sitai-backup``）—— 备份还在，
       说明上一次跑完没有还原，用户那套 Workshop 配置此刻正躺在备份里；
    2. **当前启用的列表里有没有 ``zz_probe*``** —— 有就是"探针态"；
    3. 启用数量 —— 只有 1–2 条时几乎必然是实验留下的（探针 + 真 mod）。

    ⚠️ **为什么必须有第 2 条**（真实事故，2026-09-24）：原先只看
    ``.v3probe-backup`` 这一个后缀。那次实验被中途强杀，``finally`` 没跑，
    用户配置留在了探针态；而当时的**备份文件叫 ``.sitai-backup``**（更早一轮的命名）
    ⇒ 这条检查报了 ✅「启用 2 个 mod，无残留备份」—— **假通过**，
    而它正是用来防这件事的。教训：**判据要盯状态本身（列表内容），
    不能只盯"有没有留下痕迹"** —— 痕迹的命名会变，状态不会。

    ⚠️ 这条检查**只读**：它绝不自己去还原（会不会覆盖用户后来手动改的列表，只有人知道）。
    """
    from pdx import experiments  # noqa: PLC0415

    target = experiments.CONTENT_LOAD
    if not target.is_file():
        return Check(
            "用户配置",
            False,
            f"没有 {target}",
            "先启动一次游戏（它会生成默认配置），否则探针无处记录要启用的 mod",
            level=BLOCKING,
        )
    enabled = experiments.enabled_mod_paths(target)
    backups = sorted(
        path.name
        for path in target.parent.glob(target.name + "*")
        if path.name != target.name and path.is_file()
    )
    probes = [path for path in enabled if "zz_probe" in path]
    if probes:
        return Check(
            "用户配置",
            False,
            f"当前是**探针态**（启用 {len(enabled)} 个 mod，含 {len(probes)} 个 zz_probe*）"
            + (f"；备份还在：{'、'.join(backups)}" if backups else "；**没找到备份文件**"),
            (
                f"把 {backups[0]} 拷回 {target.name}（备份文件都在就没事；"
                "一个都没有的话，用 `pdx.mods.discover_mods()` 按原来的订阅重建列表）"
                if backups
                else "先别开局：确认用户的 mod 列表该是什么样（`v3 mods` 能列出订阅到的全部）"
            ),
        )
    if len(enabled) <= 2:
        return Check(
            "用户配置",
            False,
            f"只启用了 {len(enabled)} 个 mod（{enabled}）—— 不像用户平时那套"
            + (f"；备份还在：{'、'.join(backups)}" if backups else ""),
            "确认这是有意的（`v3 mods` 列出订阅到的全部；用户原列表通常是二十几条）",
        )
    if backups:
        # 配置本身正常、只是留了个旧备份：**提示**而不是拦路 —— 备份文件本身无害，
        # 而且它往往正是"用户原来那套"的唯一副本（`.sitai-backup` 就是这种情况）。
        return Check(
            "用户配置",
            False,
            f"配置正常（{len(enabled)} 个 mod），但旁边留着备份 {'、'.join(backups)}",
            "核对内容一致后可删（也可能正是用户原列表的唯一副本 —— 不确定就留着）",
            level=INFO,
        )
    return Check("用户配置", True, f"启用 {len(enabled)} 个 mod，无探针态、无残留备份")


#: 备份文件的可能后缀。**不止一个**：`.v3probe-backup` 是 `experiments` 那一套的，
#: `.sitai-backup` 是更早一轮 `perf_compare` 那一套留下的 —— 只看前者就会漏掉真实事故
#: （2026-09-24 那次就是这么漏的：配置停在探针态而检查报了 ✅）。
BACKUP_SUFFIXES: tuple[str, ...] = (".v3probe-backup", ".sitai-backup")


def config_backups() -> list[Path]:
    """``content_load.json`` 旁边现存的备份（按名字排序）。"""
    from pdx import experiments  # noqa: PLC0415

    target = experiments.CONTENT_LOAD
    return sorted(
        path
        for path in (target.with_name(target.name + suffix) for suffix in BACKUP_SUFFIXES)
        if path.is_file()
    )


def probe_state_backup() -> Path | None:
    """当前处于**探针态**时，返回"该拿哪份备份还原"；否则 ``None``。

    给**驱动脚本**用的（它们才改环境）：探针态一定是实验自己造成的
    （用户不会把 `zz_probe*` 加进自己的列表），所以拿备份还原是安全的。
    这条路径存在的理由是一次真实事故：实验被中途强杀时 ``finally`` 不跑，
    用户的 23 条配置就留在"只剩探针"的状态里，直到下一次开局才被发现。
    """
    from pdx import experiments  # noqa: PLC0415

    enabled = experiments.enabled_mod_paths()
    if not any("zz_probe" in path for path in enabled):
        return None
    backups = config_backups()
    return backups[0] if backups else None


def check_logs_fresh() -> Check:
    """日志里没有**上一局**的探针自报（否则读数会混两局）。

    B85 那一族的根因：分析器读错轮转顺序时会把两段拼接起来。
    现在顺序修好了，而且探针驱动会用 `--fresh-logs` 把旧日志挪走 —— 所以这一条是**提示**
    而不是拦路：它的价值在于「你以为这一局的读数有 1355 行，其实是上一局的」。
    """
    from pdx import game_auto  # noqa: PLC0415

    logs_dir = game_auto.DEBUG_LOG.parent
    if not logs_dir.is_dir():
        return Check("日志干净", True, "日志目录还不存在（第一局）")
    total = 0
    files = game_auto.rotated_logs(logs_dir, "debug")
    for path in files:
        try:
            total += path.read_text(encoding="utf-8", errors="replace").count("ZZPROBE")
        except OSError:  # pragma: no cover - 被占用的日志由 quarantine 跳过
            continue
    if total:
        return Check(
            "日志干净",
            False,
            f"盘上还有 {total} 行上一局的探针自报（{len(files)} 个 debug 日志）",
            "跑探针局时加 `--fresh-logs`（把旧日志挪去临时目录）；不加的话分析会把两局混起来",
            level=INFO,
        )
    return Check("日志干净", True, f"{len(files)} 个 debug 日志，无探针自报")


def check_archive(archive_id: str) -> Check:
    """要跑的那份档案：存在、国家查得到、``[probe]`` 该声明的都声明了。"""
    try:
        archives = modgen.load_all()
    except Exception as exc:
        return Check("档案可跑", False, f"读数据源失败：{exc}", "先修 mod/data", level=BLOCKING)
    chosen = [a for a in archives if a.id == archive_id]
    if not chosen:
        return Check(
            "档案可跑",
            False,
            f"数据源里没有 {archive_id!r}",
            f"现有：{'、'.join(a.id for a in archives) or '（一个都没有）'}",
            level=BLOCKING,
        )
    archive = chosen[0]
    problems: list[str] = []
    if not archive.country:
        problems.append("没写国家 tag")
    if archive.probe is None:
        problems.append("没有 [probe] 表（读数无处可判）")
    else:
        if not archive.probe.reform_law:
            problems.append("`[probe].reform_law` 为空（「法律换没换」将不判）")
        if not archive.probe.reform_card:
            problems.append("`[probe].reform_card` 为空（「意图层动没动」将不判）")
    if problems:
        return Check(
            "档案可跑",
            False,
            f"{archive_id}（{archive.country}）：{'；'.join(problems)}",
            "补齐数据源后 `v3 modgen --write`（空值是合法的，但要知道那一格不会被判）",
        )
    return Check("档案可跑", True, f"{archive_id}（{archive.country}）· 两条读数都声明了")


def check_probe(archive_id: str | None) -> Check:
    """探针能在**这一份档案**上生成，且盘上那份盯的就是它。

    为什么这条值得单列：探针盯 A、这一局开的是 B 时读数是空的，
    而"空的"看起来像"没发生"（B87 就是这一族的另一面）。

    ⚠️ **不一致只是提示**（``INFO``）：探针驱动（`stage3_rerun`）在 deploy 时会按
    ``--archive`` **重新生成**探针，所以盘上那份是旧的很正常。它值钱的地方在于
    「你以为装的是这一份的探针」—— 用 `python -m pdx.game_auto run` 开局时没有任何东西
    会重装探针，那时这份不一致就真的会让读数对不上。
    """
    from pdx import ab_probe  # noqa: PLC0415

    if archive_id is None:
        return Check("探针就绪", True, "（这一局不用探针）", level=INFO)
    on_actions = ab_probe.PROBE_DIR / "common" / "on_actions" / "zz_probe_ab_on_actions.txt"
    if not on_actions.is_file():
        return Check(
            "探针就绪",
            False,
            f"探针目录里没有 {on_actions.name}",
            "跑 `v3 ab-probe --archive <id>` 生成",
            level=INFO,
        )
    try:
        target = ab_probe.load_target(archive_id)
    except KeyError as exc:
        return Check("探针就绪", False, str(exc), "用数据源里真实存在的档案 id", level=BLOCKING)
    if target is None:  # pragma: no cover - 由「档案可跑」先报
        return Check("探针就绪", False, "读不到档案", "先修数据源", level=BLOCKING)
    text = on_actions.read_text(encoding="utf-8-sig", errors="replace")
    want = f"c:{target.subject} ?= this"
    if want in text:
        return Check("探针就绪", True, f"盯着 {target.subject}（{archive_id}）")
    return Check(
        "探针就绪",
        False,
        f"盘上的探针不盯 {target.subject}（要的是 `{want}`）",
        f"`v3 ab-probe --archive {archive_id}` 重新生成；"
        "stage3_rerun 会在 deploy 时自己重生成，但 `python -m pdx.game_auto run` 不会",
        level=INFO,
    )


def run(*, archive: str | None = None, root: Path | None = None) -> Report:
    """跑完所有自检，返回报告（**只读**：不改配置、不动日志、不写盘）。

    ``root`` 预留给测试（指到临时目录）；正常调用不传。
    """
    _ = root  # 目前所有检查都走 config；保留参数是为了调用方对称
    checks = [
        check_game(),
        check_version_matches_mod(),
        check_products(),
        check_user_config(),
        check_no_leftover_game(),
        check_logs_fresh(),
    ]
    if archive:
        checks.extend([check_archive(archive), check_probe(archive)])
    return Report(checks)
