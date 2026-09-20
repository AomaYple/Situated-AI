"""探针实验：把「只能进游戏才能定」的问题做成**一次启动就能收工**的包。

为什么要有它
------------
知识库里还剩一批问题，答案不在文件里（引擎的加载语义、运行期字段行为、
调用语法）—— 详见 `docs/victoria3-modding/04-脚本系统.md` §13.1 的四条配方。
配方本身好写，难的是**别让人来回跑十趟**：所以这里把探针 mod、操作清单、
日志收割做成三件套：

* :func:`install` —— 把 `tools/probe/zz_probe_{a,b}` 复制进用户 mod 目录；
* :func:`plan` —— 打印**一次启动**的操作清单（点什么、看什么、回传什么）；
* :func:`collect` —— 游戏退出后解析 `logs/` 与用户目录，把证据按实验编号归位。

设计取舍
--------
* **判定优先走日志**：引擎在 `-debug_mode` 下会把未知键 / 重复定义 / scope 错误
  写进日志，这比「肉眼看行为」可靠得多。只有三条（国库数字、弹窗、loc 文案）
  需要肉眼，清单里单独列出。
* **一个候选一个文件**：语法错会让整个文件失效，混在一起就分不清是谁坏。
* **不碰存档**：所有效果只作用于新开局的国家，且只动国库与一个探针 JE。

⚠️ `install` 会往用户目录写文件（`Documents\\Paradox Interactive\\Victoria 3\\mod\\`），
这是**本机 mod 目录**、不是仓库；`collect` 只读日志。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: 探针包在仓库里的位置（入库的源）。
PROBE_DIR = config.REPO / "tools" / "probe"

#: 默认启用的两个探针 mod（A 主探针；B 只为「双 mod 同名键顺序」存在）。
PROBE_MODS = ("zz_probe_a", "zz_probe_b")

#: 「语法候选」探针 —— **故意写错**，用来问引擎认不认那些写法。
#:
#: 单独一个 mod 是因为实测踩过：第一次一键启动时游戏在加载阶段直接退出
#: （日志只停在本地化那几行）。候选语法是**可能致命**的，不能与交互部分同居一个 mod
#: —— 否则一个写错的候选就会让整场实验跑不成。要用它时显式 `--risky`。
RISKY_MOD = "zz_probe_risky"

#: 安装目标：用户 mod 目录。
TARGET_DIR = config.LOCAL_MODS

#: 日志目录（游戏写的，本仓库只读）。
LOG_DIR = config.USERDIR / "logs"


@dataclass(frozen=True, slots=True)
class Experiment:
    """一个实验：问题 → 探针文件 → 怎么读。"""

    id: str
    title: str
    question: str
    probe: tuple[str, ...]
    read: str  # 日志 / 肉眼
    how: str
    #: 是否属于「故意写错的语法候选」（在 zz_probe_risky 里，需 launch --risky）
    risky: bool = False


#: 全部实验。`probe` 是相对 `tools/probe/` 的路径，`how` 是判读方法。
EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment(
        "P2",
        "裸同名键（不带功能前缀）",
        "在**新增文件**里定义原版同名键，引擎是报错、替换、还是合并？",
        ("zz_probe_a/common/scripted_effects/zz_probe_effects.txt",),
        "肉眼 + 日志",
        "点主决议后看国库：+50,000 = 原版赢；+1 = 本 mod 替换了原版；"
        "+50,001 = 两者都跑（合并）；日志报 duplicate 或该效果未生效 = 重定义被拒。",
    ),
    Experiment(
        "P11",
        "两个 mod 抢同一个键，谁生效",
        "同名键的优先级由什么决定（加载顺序？前缀种类？）",
        (
            "zz_probe_a/common/scripted_effects/zz_probe_effects.txt",
            "zz_probe_b/common/scripted_effects/zz_probe_b_effects.txt",
        ),
        "肉眼",
        "两个 mod 都用 `REPLACE_OR_CREATE:zzprobe_shared`：+111 = A 赢；+222 = B 赢；"
        "+333 = 叠加（说明不是整体替换）。把生效方与你在启动器里的 mod 顺序对照，即可得出顺序规则。",
    ),
    Experiment(
        "P1",
        "官方 md 提到、原版零使用的写法是否合法",
        "`has_game_rule` 块形式 / `apply_modifier` / `type_set` 等写法引擎认不认？",
        (
            "zz_probe_risky/common/scripted_triggers/zz_probe_p1_t1.txt",
            "zz_probe_risky/common/scripted_triggers/zz_probe_p1_t2.txt",
            "zz_probe_risky/common/scripted_triggers/zz_probe_p1_t3.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_r_selftest.txt",
            "zz_probe_risky/common/on_actions/zz_probe_r_on_actions.txt",
            "zz_probe_a/common/game_rules/zz_probe_rules_v2.txt",
            "zz_probe_a/common/game_rules/zz_probe_rules_v3.txt",
        ),
        "日志",
        "自检效果对三个候选各求值一次，把 `ZZPROBE P1 block_form=…` / `scalar=…` / "
        "`custom_setting=…` 写进日志；⚠️ `has_game_rule = <X>` 的 X 是**设置名**而不是规则名"
        "（原版：规则 `free_construction` 下的设置 `free_construction_unscaled`），"
        "上一轮拿规则名当参数，引擎报 `Invalid database object`，判定被污染。",
        risky=True,
    ),
    Experiment(
        "P4",
        "`scripted_modifier` / `scripted_list` 的调用语法",
        "官方 md 只给定义形态、原版 0 个调用点 —— 候选写法哪个被接受？",
        (
            "zz_probe_risky/common/scripted_modifiers/zz_probe_s1_define.txt",
            "zz_probe_risky/events/zz_probe_r_ai_chance.txt",
            "zz_probe_a/events/zz_probe_mod_calls.txt",
            "zz_probe_risky/common/scripted_lists/zz_probe_l1_define.txt",
            "zz_probe_risky/common/scripted_lists/zz_probe_l2_call_direct.txt",
            "zz_probe_risky/common/scripted_lists/zz_probe_l3_call_key.txt",
        ),
        "日志",
        "定义形态合法已实测；调用候选放在**事件的 ai_chance** 里 —— 那是会做加载期校验的位置。"
        "已实测：`scripted_modifier = 名字` 被拒（`unknown command 'scripted_modifier' for MTTH`，"
        "见 `zz_probe_mod_calls.txt:27`）；另外几个候选尚无报错，结论见 `[P4]` 那一轮日志。"
        "scripted_list 的两个调用候选实测**都被拒**（Unexpected token）。",
        risky=True,
    ),
    Experiment(
        "P5",
        "`$PARAM$` 的默认值与 scope 传参",
        "`$X$` 支不支持默认值（`|` / `=`）？能不能传 scope 对象？省略参数会怎样？",
        (
            "zz_probe_risky/common/scripted_effects/zz_probe_p5_c1.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_p5_c2.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_p5_c3.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_p5_c4.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_r_selftest.txt",
        ),
        "日志",
        "每个候选都调用两次（显式传参一次、省略参数一次），效果体里的 `debug_log` 打出"
        "`$AMOUNT$` 实际被替换成什么（grep `ZZPROBE P5`）；国库差值可交叉验证（全跑通 +21M）。",
        risky=True,
    ),
    Experiment(
        "P6",
        "进度条自定义样式名",
        "能否在 MOD 里自定义新的进度条样式（而不是用引擎枚举的那几个）？",
        ("zz_probe_a/common/scripted_progress_bars/zz_probe_bars.txt",),
        "日志",
        "文件里写了一个引擎没有的样式名 `zzprobe_made_up_style`：日志报未知键 = 不接受自定义样式名。",
    ),
    Experiment(
        "P7",
        "JE 三个 md 未列字段的语义",
        "`is_shown_in_lobby` / `should_update_on_player_command` / `display_progressbar_as_months` 各自做什么？",
        ("zz_probe_a/common/journal_entries/zz_probe_je.txt",),
        "肉眼",
        "主决议会把这个 JE 加进来：看它是否显示、进度条是否按月（而不是按数值）显示、"
        "点决议后是否立刻刷新。",
    ),
    Experiment(
        "P8",
        "事件字段语义（after / show_as_tooltip / is_popup / orphan）",
        "官方 md 无记载、原版在用但不解释 —— 各自的实际行为是什么？",
        ("zz_probe_a/events/zz_probe_events.txt",),
        "肉眼 + 日志",
        "三个事件由主决议触发（2/3/4 天后）：事件 2 带 `is_popup = yes`（是否强制弹窗）；"
        "事件 3 带 `orphan = yes`；事件 1 的选项里有 `show_as_tooltip`（1000 是否**不**进国库）"
        "与事件体的 `after`（+100 在何时结算）。逐项记录国库变化即可。",
    ),
    Experiment(
        "P9",
        "`scripted_button` 的 `selected` / `cooldown` 与 root scope",
        "两个字段的官方语义是什么？按钮的 root scope 由什么决定？",
        ("zz_probe_a/common/scripted_buttons/zz_probe_buttons.txt",),
        "肉眼 + 日志",
        "看按钮是否出现、是否呈「已选中」、点一次后是否进入冷却；"
        "若 root scope 不对，日志会报 scope 错误（按钮挂法见文件头注释）。",
    ),
    Experiment(
        "P10",
        "本地化版本号 `:数字` 与块标量",
        "`:数字` 是否影响优先级？YAML 块标量（`|` / `>`）是否被支持？",
        (
            "zz_probe_a/localization/simp_chinese/zz_probe_l_simp_chinese.yml",
            "zz_probe_a/localization/simp_chinese/zz_probe_l_version_probe.yml",
            "zz_probe_risky/common/decisions/zz_probe_r_decisions.txt",
            "zz_probe_risky/localization/simp_chinese/zz_probe_r_l_simp_chinese.yml",
        ),
        "肉眼 + 日志",
        "版本号：同一个 loc 键在两个文件里分别写成 `:0` 与 `:1`，游戏里显示的是 `:0` 那句"
        "（实测已答）。块标量：zz_probe_risky 的两个决议**只差描述文案的写法** ——"
        "`|`（字面量）应显示两行、`>`（折叠）应显示一行；两个都不成行即说明不支持。",
        risky=True,
    ),
    Experiment(
        "P3",
        "重名 namespace 的后果",
        "在已有 namespace 下新增 id（或不带前缀同名 id）会发生什么？",
        ("zz_probe_a/events/zz_probe_dup_id.txt",),
        "日志",
        "文件在 `test` namespace 下定义了 `test.99999`：日志报错 = namespace 不能跨文件续写；"
        "不报错 = 可以（此时再看原版 `test.1` 是否仍正常）。",
    ),
    Experiment(
        "P22",
        "建筑字段：`can_build` / `owners` / `replaces_company`",
        "官方 md 未提、原版零使用的建筑字段引擎认不认？",
        ("zz_probe_a/common/buildings/zz_probe_buildings.txt",),
        "日志",
        "三个字段写在同一个建筑条目里，加载期逐个报 `Unexpected token: <字段>` = 该写法不被接受；"
        "同一文件里的对照字段（如 `ignore_stateregion_max_level`）无报错 = 被接受。",
    ),
    Experiment(
        "P25",
        "`common/<库>/` 的子目录是否被枚举",
        "把定义放进 `common/scripted_effects/子目录/` 里，引擎会读到吗？",
        (
            "zz_probe_risky/common/scripted_effects/zz_probe_subdir_probe/never_loaded.txt",
            "zz_probe_risky/common/scripted_effects/zz_probe_r_selftest.txt",
        ),
        "日志",
        "自检效果调用子目录里的 `zzprobe_subdir_never`：报 `Unknown effect zzprobe_subdir_never` "
        "= 子目录没被枚举（旧结论成立）；出现 `ZZPROBE SUBDIR LOADED` = 子目录其实会被读"
        "（推翻旧结论）。",
        risky=True,
    ),
)

#: 需要**肉眼**记录的地方（其余由日志判定）。
EYEBALL: tuple[tuple[str, str], ...] = (
    ("国库", "点主决议前后的国库数字（判定 P2 / P11，以及 P8 的 after 与 show_as_tooltip）"),
    ("窗口", "是否有事件窗口强制弹出（判定 P8 的 is_popup），以及选项点下去后国库再变多少"),
    ("决议标题", "第二个决议的标题是「无版本号」还是「带版本号 1」那一句（判定 P10）"),
    ("月度事件", "跑满一个月后，通知栏/弹窗里有没有 zzprobe.10（判定 P24 的 weight_multiplier）"),
    (
        "进度条",
        (
            "zzprobe_je 与 zzprobe_je_control 的进度条：显示「月」还是数值"
            "（判定 P7 的 display_progressbar_as_months，两个 JE 只差这三个字段）"
        ),
    ),
    (
        "块标量",
        (
            "zz_probe_risky 的两个【ZZ 探针】决议：描述分别是 `|` 与 `>` 块标量，"
            "前者应占两行、后者应折成一行（判定 P17）"
        ),
    ),
)


@dataclass(slots=True)
class Finding:
    """收割日志得到的一条证据。"""

    experiment: str
    source: str
    line: str

    def describe(self) -> str:
        return f"[{self.experiment}] {self.source}: {self.line}"


# ────────────────────────── 启动游戏（一键）──────────────────────────
#
# 机制（实测出来的，不是猜的）：
#   * **启用哪些 mod** 由用户目录的 `content_load.json` 决定，结构是
#     `{"enabledMods": [{"path": "<mod 根目录>"}, …], "disabledDLC": [], "enabledUGC": []}`
#     —— 启动器写它、游戏读它。所以「只启用探针」＝改这个文件，不需要点 GUI。
#   * **调试模式** 是给 `binaries/victoria3.exe` 加 `-debug_mode`：
#     游戏自带的 `launcher/launcher-settings.json` 里，「Open game in Debug Mode」
#     那条 `alternativeExecutables` 的 `exeArgs` 就是 `["-gdpr-compliant", "-debug_mode"]`。
#
# 因此一键启动 = 备份 content_load.json → 只写两个探针 → 直接起 exe。

#: 游戏读的「启用了哪些 mod」文件。
CONTENT_LOAD = config.USERDIR / "content_load.json"

#: 备份后缀（`restore` 靠它还原原来那套 mod）。
BACKUP_SUFFIX = ".v3probe-backup"

#: 游戏可执行文件（相对安装根）。
GAME_EXE_REL = ("binaries", "victoria3.exe")

#: 正常启动参数（与启动器一致）。
BASE_ARGS = ("-gdpr-compliant",)

#: 调试模式附加参数。
DEBUG_ARG = "-debug_mode"


def game_exe() -> Path:
    """`binaries/victoria3.exe`。"""
    return config.ROOT.joinpath(*GAME_EXE_REL)


def read_content_load(path: Path | None = None) -> dict[str, object]:
    """读 `content_load.json`（不存在或坏掉时给一个空骨架）。"""
    target = path or CONTENT_LOAD
    if not target.is_file():
        return {"enabledMods": [], "disabledDLC": [], "enabledUGC": []}
    try:
        data: dict[str, object] = json.loads(target.read_text(encoding="utf-8-sig"))
    except ValueError:  # pragma: no cover - 坏文件交给 writer 覆盖
        return {"enabledMods": [], "disabledDLC": [], "enabledUGC": []}
    for key in ("enabledMods", "disabledDLC", "enabledUGC"):
        data.setdefault(key, [])
    return data


def enabled_mod_paths(path: Path | None = None) -> list[str]:
    """当前启用的 mod 路径（原样返回，不解析）。"""
    mods = read_content_load(path)["enabledMods"]
    assert isinstance(mods, list)
    return [str(m.get("path", "")) for m in mods]


def set_enabled_mods(
    mod_paths: Iterable[Path | str], *, path: Path | None = None, backup: bool = True
) -> Path | None:
    """把启用列表**只**设成给定的这些 mod，返回备份路径。

    备份只做一次：第二次调用不会用「只剩探针」的内容覆盖掉真正的备份。
    """
    target = path or CONTENT_LOAD
    backup_path = target.with_name(target.name + BACKUP_SUFFIX)
    if backup and target.is_file() and not backup_path.is_file():
        shutil.copy2(target, backup_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = read_content_load(target)
    data["enabledMods"] = [{"path": str(p)} for p in mod_paths]
    target.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    return backup_path if backup_path.is_file() else None


def restore_content_load(*, path: Path | None = None) -> bool:
    """把 `content_load.json` 还原成备份（返回是否真的还原了）。"""
    target = path or CONTENT_LOAD
    backup_path = target.with_name(target.name + BACKUP_SUFFIX)
    if not backup_path.is_file():
        return False
    shutil.copy2(backup_path, target)
    backup_path.unlink()
    return True


def launch_command(*, debug: bool = True) -> list[str]:
    """拼出游戏启动命令（与启动器的 debug 变体一致）。"""
    args = [str(game_exe()), *BASE_ARGS]
    if debug:
        args.append(DEBUG_ARG)
    return args


def launch(*, debug: bool = True) -> subprocess.Popen:
    """启动游戏（分离进程，不等待）；工作目录设为安装根。"""
    exe = game_exe()
    if not exe.is_file():
        raise FileNotFoundError(f"找不到游戏可执行文件：{exe}")
    return subprocess.Popen(
        launch_command(debug=debug),
        cwd=str(config.ROOT),
        close_fds=True,
    )


@dataclass(slots=True)
class Report:
    """一次收割的结果。"""

    log_dir: str = ""
    files_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def by_experiment(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.experiment, []).append(f)
        return out


#: 日志里与探针有关的标记词。命中即收进报告（宽口径，宁可多收）。
MARKERS = ("zzprobe", "zz_probe")

#: 引擎报错的关键词 → 归类提示。
ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("unexpected token", "引擎不接受这个写法（加载期硬报错）"),
    ("unknown effect", "该效果没被加载：定义文件没读到，或名字写错"),
    ("unknown trigger", "该触发器没被加载：定义文件没读到，或名字写错"),
    ("unknown key", "未知键：该写法不被这个位置接受"),
    ("unknown command", "未知命令：该字段不被这个上下文接受"),
    ("unknown", "未知：该键/值不被识别"),
    ("invalid", "非法：写法被拒绝"),
    ("duplicate", "重复：同名键冲突被发现"),
    ("will not be created", "同名键先到先得：后写的不会生效"),
    ("already defined", "重复定义：同名键冲突被发现"),
    ("redefin", "重复定义：同名键冲突被发现"),
    ("wrong type", "取到了空值/错类型（常见于变量没创建）"),
    ("scope", "scope 相关：多半是 root scope 不对"),
    ("error", "错误：看原文"),
)


def experiments(only: Iterable[str] | None = None) -> list[Experiment]:
    """按编号取实验（不传则全部）。"""
    wanted = {o.upper() for o in (only or ())}
    return [e for e in EXPERIMENTS if not wanted or e.id in wanted]


def classify(line: str) -> str:
    """给一行日志归类（命中不了就给空串）。"""
    low = line.lower()
    for needle, why in ERROR_HINTS:
        if needle in low:
            return why
    return ""


def _experiment_of(line: str) -> str:
    """把一行日志归到实验编号：先看显式标记 `[P8]`，再看关键词。"""
    low = line.lower()
    for e in EXPERIMENTS:
        if e.id.lower() in low:
            return e.id
    if "debug_success" in low:
        return "P2"
    if "zzprobe_shared" in low:
        return "P11"
    if "subdir loaded" in low or "zzprobe_subdir_never" in low:
        return "P25"
    if "scripted_modifier" in low or "scripted_list" in low:
        return "P4"
    if "zzprobe_p5" in low:
        return "P5"
    if "localization_reader" in low or "missing quoted string" in low:
        return "P10"
    if "unknown modifier" in low or "zzprobe_r_ai_chance" in low:
        return "P4"
    if "can_build" in low or "replaces_company" in low or "zz_probe_buildings" in low:
        return "P22"
    if "zzprobe_made_up_style" in low:
        return "P6"
    if "zzprobe_je" in low:
        return "P7"
    if "zzprobe.1" in low or "zzprobe.2" in low or "zzprobe.3" in low:
        return "P8"
    if "zzprobe_button" in low:
        return "P9"
    if "zzprobe_loc_version" in low:
        return "P10"
    if "test.99999" in low:
        return "P3"
    if "zzprobe_rule" in low or "has_game_rule" in low or "block_form" in low:
        return "P1"
    return "?"


def collect(log_dir: Path | None = None, *, extra_dirs: Iterable[Path] = ()) -> Report:
    """收割日志：把所有提到探针的行按实验编号归位。

    只读：`logs/` 里每个 ``*.log``、``*.txt``，外加调用方指定的目录（默认再看
    一眼用户目录下与本地化缓存有关的位置，那一条对应 doc 06 的缓存问题）。
    """
    base = log_dir or LOG_DIR
    report = Report(log_dir=str(base))
    if not base.is_dir():
        report.missing.append(f"日志目录不存在：{base}（游戏跑过了吗？）")
        return report

    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".log", ".txt"}:
            continue
        report.files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue
        for line in text.splitlines():
            low = line.lower()
            if not any(m in low for m in MARKERS):
                continue
            report.findings.append(Finding(_experiment_of(line), path.name, line.strip()[:200]))

    for other in extra_dirs:
        if other.is_dir():
            report.hints.append(f"{other} 下 {len(list(other.iterdir()))} 项（本地化缓存观察点）")
        else:
            report.missing.append(f"未找到 {other}（本地化缓存问题需要它）")

    if not report.findings:
        report.hints.append(
            "日志里没有 zzprobe 字样 —— 检查三件事：mod 是否启用、是否以 -debug_mode 启动、"
            "日志目录是否是本机用户目录。"
        )
    return report


def install(
    target: Path | None = None,
    *,
    mods: Iterable[str] | None = None,
    force: bool = False,
    risky: bool = False,
) -> list[Path]:
    """把探针 mod 复制进用户 mod 目录，返回装好的路径。

    已存在时**不覆盖**（除非 ``force``）—— 用户可能正在里面改东西，
    静默覆盖比报错更糟。
    """
    dest = target or TARGET_DIR
    dest.mkdir(parents=True, exist_ok=True)
    names = list(mods) if mods else list(PROBE_MODS)
    if risky and RISKY_MOD not in names:
        names.append(RISKY_MOD)
    out: list[Path] = []
    for name in names:
        src = PROBE_DIR / name
        if not src.is_dir():
            raise FileNotFoundError(f"探针源不存在：{src}（跑 `v3 experiment plan` 看说明）")
        dst = dest / name
        if dst.exists() and not force:
            out.append(dst)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        out.append(dst)
    return out


def uninstall(
    target: Path | None = None, *, mods: Iterable[str] | None = None, risky: bool = False
) -> list[Path]:
    """把探针 mod 从用户 mod 目录移除，返回被移除的路径。

    ``risky=True`` 时连 `zz_probe_risky` 一起移除 —— `launch --risky` 会装上它，
    卸载时必须能对上，否则本机 mod 目录会留一个探针残留。
    """
    dest = target or TARGET_DIR
    names = list(mods) if mods else list(PROBE_MODS)
    if risky and RISKY_MOD not in names:
        names.append(RISKY_MOD)
    removed: list[Path] = []
    for name in names:
        path = dest / name
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(path)
    return removed


def plan(target: Path | None = None) -> str:
    """打印**一次启动**的操作清单（给人照做）。"""
    dest = target or TARGET_DIR
    lines = [
        "探针实验：一次游戏启动收工",
        "=" * 40,
        "",
        "0. 一条命令搞定：`v3 experiment launch --risky`",
        "   —— 它把探针 mod 复制到本机 mod 目录、只启用探针、备份原来的启用列表，",
        "      再以 -debug_mode 直接起游戏（全程不用点启动器）：",
        f"      {dest}",
        "",
        "1. 进游戏（读档或新开档都行）：`on_game_started` 会自动跑一次语法自检，",
        "   结论按 `ZZPROBE …` 写进 logs；再跑满一个月可顺带判 P24。",
        "",
        "2. 打开决议面板，点【探针】主决议（**点之前记下国库**）；",
        "   万一自检没自动跑，再点一下 zz_probe_risky 的【跑语法自检】决议。",
        "",
        "3. 事件会在 2/3/4 天后弹出；把看到的都记下来。",
        "",
        "4. 退出游戏（让日志落盘），然后依次跑：",
        "      v3 experiment collect     # 按实验编号归位全部证据",
        "      v3 experiment restore     # 还原原来的 mod 启用列表",
        "      v3 experiment uninstall   # 移除探针 mod",
        "",
        "要肉眼记录的几处（其余交给日志）：",
    ]
    lines += [f"   - {name}：{how}" for name, how in EYEBALL]
    lines += [
        "",
        "注意：P1 / P4 / P5 / P25 是**故意写错的语法候选**（在 zz_probe_risky 里，",
        "默认不随 `launch` 启用）—— 只用来问引擎「认不认」，要问就加 `--risky`。",
        "那一趟的判定由自检效果用 `debug_log` 写进日志，基本不用点任何东西。",
        "",
        "实验清单（编号 → 问题 → 判读）：",
    ]
    for e in EXPERIMENTS:
        lines += [
            f"   [{e.id}] {e.title}",
            f"        问题：{e.question}",
            f"        判读（{e.read}）：{e.how}",
        ]
    lines += [
        "",
        "6. 想验证「加载顺序」这一条：把启动器里的 A/B 顺序对调再跑一次，",
        "   对比 P11 的国库数字即可（这是唯一需要第二次启动的实验）。",
        "",
        "收尾：`v3 experiment uninstall` 移除探针（或直接在启动器里不启用它）。",
    ]
    return "\n".join(lines)


__all__ = [
    "ERROR_HINTS",
    "EXPERIMENTS",
    "EYEBALL",
    "LOG_DIR",
    "MARKERS",
    "PROBE_DIR",
    "PROBE_MODS",
    "RISKY_MOD",
    "TARGET_DIR",
    "Experiment",
    "Finding",
    "Report",
    "classify",
    "collect",
    "experiments",
    "install",
    "plan",
    "uninstall",
]
