"""引擎日志：唯一的外部真值来源。

为什么需要这个模块
------------------
在整个项目里，解析器此前**唯一的比对对象是我们自己写的预言机**
（``tools/tests/_oracle_lexer.py``）。差分测试证明的是「没退化」，
不是「和引擎一致」—— 那是循环论证。

真正的真值只有引擎自己。而引擎**会把它看到的东西写进日志**：

* ``virtualfilesystem.cpp`` 记录它从哪些目录、按什么扩展名枚举文件
  —— 这是**覆盖面**的真值
* ``jomini_script_system.cpp`` 报脚本错误时带 ``Script location: 文件:行``
  —— 这是**行号与结构**的真值
* ``pdx_gui_localize.cpp`` 报未本地化文本时带 ``at 文件:行``
  —— 这是**token 识别**的真值

本模块把这些抽出来，供 :mod:`pdx.verify` 与测试交叉核对。

⚠️ 已知局限（必须说清楚，否则又是自我安慰）
--------------------------------------------
1. 日志只来自**运行过的那一次**。若游戏已升级，日志可能是旧版本的，
   而文件可能已经变了。因此 :func:`parse_logs` 会一并读出版本号，
   核对结果里也带着它 —— 版本不一致时结论要打折。
2. 日志**不含校验和数值**。``checksum_manifest.txt`` 只列出「哪些目录
   参与校验」，不含任何哈希；引擎把输入喂进校验和的过程记了日志
   （``Feeding into checksum: …``），但最终值不落盘。
   所以「用游戏校验和验证我们的读取」这条路**走不通** ——
   本模块提供的是另一条路：引擎的枚举清单与位置报告。
3. 它验证的是**枚举范围、行号、token 识别**，**不验证脚本语义**
   （加载顺序、覆盖规则、字段合法性仍无从得知）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003 —— 运行期要用 Path.is_dir()/glob()，不能只做标注

from . import config
from .lexer import Token  # noqa: TC001 —— 运行期用于类型标注之外，也用于缓存标注
from .parser import TOLERATED_ERRORS

#: 引擎枚举文件时打的行：``Starting pre-enumerating 'common/buildings'(.txt, , 0)``
_ENUM_RE = re.compile(r"pre-enumerating\s+'([^']+)'\((\.[A-Za-z0-9]+),\s*,\s*(-?\d+)\)")

#: 脚本错误的位置：``Script location: events/foo.txt:779``
_LOC_RE = re.compile(r"Script location:\s*([\w/.\-]+):(\d+)")

#: GUI 本地化报的位置与文本：``Unlocalized text 'KEY' at gui/x.gui:360``
_UNLOC_RE = re.compile(r"Unlocalized text '([^']+)' at ([\w/.\-]+):(\d+)")

#: ``gui/x.gui:3267 - Failed parsing localized text: KEY``
_FAILPARSE_RE = re.compile(r"([\w/.\-]+\.\w+):(\d+) - Failed parsing localized text:\s*(\S+)")

#: 引擎写进校验和的版本号：``Feeding game version into checksum: 1.14.2``
_VERSION_RE = re.compile(r"Feeding game version into checksum:\s*(\S+)")

#: 只关心文本类扩展名 —— 贴图与音频不归解析器管
TEXTUAL_SUFFIXES = frozenset(
    {".txt", ".gui", ".asset", ".font", ".settings", ".profile", ".shortcuts", ".layout"}
)


@dataclass(slots=True)
class EngineClaim:
    """从引擎日志里抽出的一条断言。"""

    kind: str  # enumeration / script_location / token_at
    detail: str  # 人类可读描述
    dir_rel: str = ""  # kind == enumeration
    suffix: str = ""
    file_rel: str = ""  # kind == script_location / token_at
    line: int = 0
    token: str = ""


@dataclass(slots=True)
class CrossCheckReport:
    """核对结果。"""

    #: 覆盖面：``(目录, 扩展名)`` -> ``(引擎枚举数, 我们解析数, 文件数)``
    coverage: dict[tuple[str, str], tuple[int, int, int]] = field(default_factory=dict)
    #: 引擎报告的位置 -> 判定
    locations: list[tuple[str, int, str]] = field(default_factory=list)
    #: token 核对：``(文件, 行, token)`` -> 我们给出的行号（None 表示找不到）
    tokens: list[tuple[str, int, str, int | None]] = field(default_factory=list)
    #: 每个 ``(文件, token)`` 在我们这边的**文件内是否出现过**（跨行搜索的结果）。
    #: 用来区分"日志比当前 mod 状态旧"（整份文件都没有）与"行号漂了"（有、只是不在那行）。
    tokens_anywhere: dict[tuple[str, str], int | None] = field(default_factory=dict)
    #: ``(文件, token)`` -> 引擎报的那一行上是否有**以它开头**的更长的 token。
    prefix_on_line: dict[tuple[str, str], bool] = field(default_factory=dict)
    #: ``(文件, token)`` -> 在**原版**文件里的行号（只对"生效文件里没找到"的 token 查）。
    #: 用来回答"这个 token 到底在我们的世界里存在吗" —— 见 :meth:`_stale`。
    vanilla_anywhere: dict[tuple[str, str], int | None] = field(default_factory=dict)
    #: 被 mod 覆盖、且**覆盖版与原版行数不同**的文件（这些文件的行号核对不可信）。
    overridden_files: set[str] = field(default_factory=set)
    #: 引擎报了 token、而**生效文件根本不存在**的文件（被某个 mod 删掉了整个文件）。
    missing_files: set[str] = field(default_factory=set)
    #: ``文件`` -> ``(生效版行数, 原版行数)``。两个数只要都读到了就记下来 ——
    #: :meth:`unverifiable_files` 要用它回答"这两份文件是不是同一套行号"。
    line_counts: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: 日志里的游戏版本（可能是旧版本的日志）
    log_version: str = ""
    #: 日志条数统计
    counts: Counter = field(default_factory=Counter)

    @property
    def coverage_gaps(self) -> list[tuple[str, str, int, int, int]]:
        """引擎枚举了、但我们没完全解析的 ``(目录, 扩展名, 引擎数, 我们数, 文件数)``。"""
        return [
            (d, e, engine_n, ours, total)
            for (d, e), (engine_n, ours, total) in self.coverage.items()
            if ours < total
        ]

    @property
    def token_mismatches(self) -> list[tuple[str, int, str, int | None]]:
        return [t for t in self.tokens if t[3] != t[1]]

    @property
    def absent_tokens(self) -> list[tuple[str, int, str, int | None]]:
        """**我们的世界里根本没有这个 token** 的断言 —— 日志描述的是另一套内容。

        判据：生效文件与原版文件里**都**没见过这个 token 出现。

        实测两类（2026-09-22）：
        * 探针往 ``gui/error_deer.gui`` 插的 `CLEAR`/`DUMP` 按钮（会话结束随 mod 消失）；
        * 被 1.13 版 mod 覆盖**删掉**的键。

        这个划分**不依赖"我们认不认识那个 mod"**，所以对我们的探针、用户的
        Workshop mod、以及将来任何改动都成立。判它等于判过期数据，是**假红**。
        """
        return [t for t in self.tokens if t[3] is None and self._stale(t)]

    @property
    def unverifiable_files(self) -> set[str]:
        """**行号本来就不可比**的文件。判据只有一条：**两份文件不是同一套行号**。

        三种情形都算（各自都是可测事实，不看"我们认不认识那个 mod"）：

        * 生效文件存在、但**行数与原版不同** ⇒ 引擎报的行号来自另一套内容；
        * 生效文件**根本不存在**（整个文件被删）⇒ 那条断言无从核对；
        * 两边都读不到行数（文件不可读）⇒ 同样不下结论。

        ⚠️ **行数相同不算**：那时覆盖版与原版是同一套行号，token 又整份文件都找不到，
        就是真不一致 —— 那种情况必须落进 :attr:`misplaced_tokens` 判红，
        不能收进本类悄悄放过（2026-09-22 修，见 :attr:`unverifiable_tokens`）。
        """
        out = set(self.missing_files) | set(self.overridden_files)
        # 判据落在行数上（行数相同 = 同一套行号），而不是"有没有覆盖"这个来源信息：
        # 覆盖映射是**我们**建的，而行数是**可观测**的 —— 后者才配当判据。
        for rel, (effective_lines, vanilla_lines) in self.line_counts.items():
            if effective_lines != vanilla_lines:
                out.add(rel)
        return out

    def _stale(self, t: tuple[str, int, str, int | None]) -> bool:
        """ "找不到"的断言是不是**日志与安装的版本错配**（而不是解析器的问题）。

        ⚠️ 只有**两边都找不到**才算。生效文件里没有、原版里**有**的情形是**歧义**的
        （可能被覆盖删了、也可能我们读漏了），这时**不下结论** —— 它既不算
        :attr:`absent_tokens`（会被跳过），也不算 :attr:`misplaced_tokens`
        （会被判红），而是落进 :attr:`unverifiable_tokens`（说出来、但不判红）。
        宁可让它显式地"不可核对"，也不能悄悄放过一个可能真漏读的 token。

        ⚠️ 判据统一写 ``is not None``：两个字典里存的是**行号**，"有没有"由 ``None``
        表示。用真值判断会把"存在"与"行号非零"混为一谈 —— 本模块的行号从 1 起，
        所以今天**恰好**不会出错，但那是巧合，不是设计。
        """
        rel, _line, tok, _got = t
        seen_effective = self.tokens_anywhere.get((rel, tok)) is not None
        seen_vanilla = self.vanilla_anywhere.get((rel, tok)) is not None
        return not (seen_effective or seen_vanilla)

    @property
    def unverifiable_tokens(self) -> list[tuple[str, int, str, int | None]]:
        """**"找不到"但无法判定责任**的断言 —— 既不是解析器错，也不能当过期数据丢掉。

        判据（逐 token + 逐文件，全部可测）：**这个 token 在生效文件里任何一行都没有**，
        而且**那个文件的行号核对本来就不可信**（覆盖版与原版行数不同），
        但**原版文件里有**它。两种解释分不开：

        * 覆盖把它删了（日志比安装旧）⇒ 判红是冤枉解析器；
        * 我们读漏了（**真问题**）⇒ 跳过就是放过 bug。

        所以单列一类：**说出来、但不判红**。实测 16 条全落在这一类 ——
        日志报的是**原版**行号（`FLEET_NO_INTERCEPT_TARGETS` 在原版 2621 行），
        而我们读到的覆盖版把那一段删了（原版 8098 行 / 覆盖版 7767 行）。

        ⚠️ **判据是"不该核对"，不是"找不到"**（2026-09-22 修）：本类专指
        **那个文件的行号本来就不可比**（被覆盖且行数不同）的情形。
        行数相同时覆盖版与原版是同一套行号，token 又有"别处也找不到"的实据 ⇒
        那是真不一致，落进 :attr:`misplaced_tokens` 判红。
        早期版本把"生效文件里别处有"也收进本类，结果是**真错位被判成不可核对**、
        悄悄放过 —— 与"宁可显式不可核对，也不悄悄放过"的初衷刚好相反。
        """
        return [
            t
            for t in self.tokens
            if t[3] is None
            and self.tokens_anywhere.get((t[0], t[2])) is None
            and self.vanilla_anywhere.get((t[0], t[2])) is not None
            and t[0] in self.unverifiable_files
        ]

    @property
    def misplaced_tokens(self) -> list[tuple[str, int, str, int | None]]:
        """token 在文件里**有**、但不在引擎报的那一行（文件被改过，行号变了）。

        ⚠️ 已排除**前缀关系**：实测 ``gui/military_formation_panel.gui:2621``
        报 `FLEET_NO_INTERCEPT_TARGETS`，而行 2621 上恰好是
        `FLEET_NO_INTERCEPT_TARGETS_TOOLTIP` —— 断言是「这一行有以它开头的
        token」，用逐行**精确相等**去判就会把它误报成行号错位。
        这类落进 :attr:`prefix_tokens`，不算错位。
        """
        skip = {id(t) for t in self.absent_tokens} | {id(t) for t in self.prefix_tokens}
        skip |= {id(t) for t in self.unverifiable_tokens}
        return [t for t in self.token_mismatches if id(t) not in skip]

    @property
    def prefix_tokens(self) -> list[tuple[str, int, str, int | None]]:
        """引擎报的 token 是**同一行上某个更长 token 的前缀**（断言成立，行号也对）。

        为什么会有这种断言：引擎报的是"这一行有个以 T 开头的文本键"，
        而 T 本身可能是 `T_TOOLTIP` 这类组合键的前缀。这不是错位，是断言粒度。
        """
        return [
            t for t in self.tokens if t[3] is None and self.prefix_on_line.get((t[0], t[2]), False)
        ]

    def summary(self) -> dict[str, object]:
        return {
            "日志版本": self.log_version or "未记录",
            "枚举组合": len(self.coverage),
            "覆盖面缺口": len(self.coverage_gaps),
            "位置断言": len(self.locations),
            "token 断言": len(self.tokens),
            "token 不一致": len(self.token_mismatches),
            "其中 token 整份文件都没有": len(self.absent_tokens),
            "其中所在文件被覆盖（行号不可比）": len(self.unverifiable_tokens),
            "其中 token 在但不在那一行": len(self.misplaced_tokens),
        }


def default_log_dir() -> Path:
    """引擎日志的默认位置。"""
    return config.USERDIR / "logs"


#: 探针 mod 在日志里留下的标识。**每加一个探针 mod 都要往这里补一行** ——
#: 判据是"这个名字只可能来自我们自己的探针"，不要用"排除原版"式的模糊条件
#: （本机路径里就有 ``Victoria 3``，模糊条件会把每一行都当成 mod 行）。
#: * ``zz_probe`` / ``ZZ Probe``：`tools/probe/` 早期探针的名字；
#: * ``Sitai Perf Probe`` / ``zz_sitai_perf``：`tools/probe/perf_mod.py` 的
#:   ``descriptor.mod`` 名字与 ``path``（G-EXIT-3 采样用的那个，实测在
#:   ``debug.1/3/4.log`` 里都留了 2 条记录 —— 就是它让 18 条假红现形的）。
PROBE_MARKERS: tuple[str, ...] = (
    "zz_probe",
    "ZZ Probe",
    "Sitai Perf Probe",
    "zz_sitai_perf",
)


def probe_session(log_dir: Path | None = None) -> bool:
    """当前日志集是不是**探针会话**（只加载了 `tools/probe/` 那几个 mod）。

    为什么要判它：`cross_check` 的整条逻辑是「拿游戏自己的日志当外部真值」——
    而日志里的位置与枚举清单**取决于那次会话加载了哪些 mod**。跑过
    `v3 experiment launch` 之后，日志描述的是「只有探针 mod」的世界，
    与仓库分析的「23 个 workshop mod」世界对不上，比对必然假红。

    ⚠️ **必须扫全部 ``*.log``，不能只看当前那份**（2026-09-22 实测踩到）：
    探针会话的日志滚到 ``debug.3.log``/``debug.4.log`` 之后，``debug.log``
    已经是另一次**挂载失败**的会话（`Mounted Data` 里没有探针 mod），
    于是"当前日志干净"并不意味着"日志集干净"。实测：只用当前日志判定 ⇒ 漏判，
    `test_token行号与引擎一致` 报 18 条不一致（其中 2 条是探针往
    ``gui/error_deer.gui`` 插的 `CLEAR`/`DUMP` 按钮），而失败原因与解析器无关。

    ⚠️ 另一个坑：**假脱字符**。本机 ``debug.log`` 的路径里有 ``Victoria 3``，
    判据若写成 ``"Victoria 3" not in line`` 会把**每一行**都当成 mod 行。
    所以这里只认**明确的探针标识**，不做"排除原版"式判断。
    """
    base = log_dir or default_log_dir()
    if not base.is_dir():
        return False
    for path in sorted(base.glob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue
        if any(marker in text for marker in PROBE_MARKERS):
            return True
    return False


def parse_logs(log_dir: Path | None = None) -> tuple[list[EngineClaim], str]:
    """从引擎日志里抽出全部可用断言，返回 ``(断言列表, 日志版本)``。

    找不到日志时返回空列表 —— 调用方据此跳过，而不是报错：
    日志不是仓库的一部分，换台机器就没有。
    """
    log_dir = log_dir or default_log_dir()
    claims: list[EngineClaim] = []
    version = ""
    if not log_dir.is_dir():
        return claims, version

    seen_enum: set[tuple[str, str]] = set()
    seen_loc: set[tuple[str, int]] = set()
    seen_tok: set[tuple[str, int, str]] = set()

    for log in sorted(log_dir.glob("*.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except TOLERATED_ERRORS:  # pragma: no cover - 单个日志读不了不该中断
            continue

        if not version:
            m = _VERSION_RE.search(text)
            if m:
                version = m.group(1)

        for m in _ENUM_RE.finditer(text):
            key = (m.group(1).rstrip("/"), m.group(2))
            if key in seen_enum or key[1] not in TEXTUAL_SUFFIXES:
                continue
            seen_enum.add(key)
            claims.append(
                EngineClaim(
                    kind="enumeration",
                    detail=f"引擎枚举 {key[0]} 下的 {key[1]}",
                    dir_rel=key[0],
                    suffix=key[1],
                )
            )

        for m in _LOC_RE.finditer(text):
            key = (m.group(1), int(m.group(2)))
            if key in seen_loc:
                continue
            seen_loc.add(key)
            claims.append(
                EngineClaim(
                    kind="script_location",
                    detail=f"引擎在 {key[0]}:{key[1]} 执行脚本时报错",
                    file_rel=key[0],
                    line=key[1],
                )
            )

        # 两种 GUI 日志的字段顺序相反，统一成 (文件, 行, token) 再处理。
        for rx, order in ((_UNLOC_RE, "tfl"), (_FAILPARSE_RE, "ftl")):
            for m in rx.finditer(text):
                if order == "tfl":
                    tok_text, file_text, line_no = m.group(1), m.group(2), int(m.group(3))
                else:
                    file_text, line_no, tok_text = m.group(1), int(m.group(2)), m.group(3)
                tok_key = (file_text, line_no, tok_text)
                if tok_key in seen_tok:
                    continue
                seen_tok.add(tok_key)
                claims.append(
                    EngineClaim(
                        kind="token_at",
                        detail=f"引擎说 {file_text}:{line_no} 处有 {tok_text!r}",
                        file_rel=file_text,
                        line=line_no,
                        token=tok_text,
                    )
                )
    return claims, version


def _line_count(path: Path) -> int | None:
    """文件行数；读不了给 ``None``（读不了就不下结论，不抛）。"""
    try:
        return len(path.read_bytes().splitlines())
    except OSError:  # pragma: no cover - 权限/占用等极端情况
        return None


def _scriptable_set(root: Path, dir_rel: str, suffix: str) -> tuple[int, int]:
    """返回 ``(该目录下此扩展名的文件数, 其中我们解析的数量)``。"""
    # 延迟导入：scan 会 import config，而本模块在 import 期就被 verify 用到
    from .scan import walk_files  # noqa: PLC0415

    base = root / dir_rel
    # 统一成 Path 列表 —— 引擎日志里既有目录也有单个文件
    # （``gfx/frontend/.../startscreen.dds`` 就是文件形态）。
    paths: list[Path] = []
    if base.is_file():
        if base.suffix == suffix:
            paths = [base]
    elif base.is_dir():
        paths = [f.path for f in walk_files(base) if f.suffix == suffix]
    else:
        return (0, 0)

    parsed = 0
    for p in paths:
        try:
            rel = p.relative_to(root)
        except ValueError:  # pragma: no cover
            continue
        if config.is_scriptable(rel.parts, p.suffix):
            parsed += 1
    return len(paths), parsed


def build_override_map() -> dict[str, Path]:
    """建立「原版相对路径 -> 实际生效的文件」映射。

    为什么必须有这个
    ----------------
    引擎是**在装了 mod 的状态下**运行的。mod 覆盖某个文件后，引擎读的是
    mod 的版本、报的也是 mod 里的行号；而我们一直在读原版文件 ——
    于是同一行号指向完全不同的内容。

    实测（2026-09）：4 条「不一致」全部是这类，而且行数差得很明显::

        gui/military_formation_panel.gui        原版 8098 行 / mod 7767 行
        gui/panel_military.gui                  原版 1223 行 / mod 1182 行
        common/ai_strategies/00_default_strategy.txt
                                                原版 9362 行 / mod 8739 行

    这不是解析器错，是核对工具错 —— 它没考虑覆盖关系。

    取哪个 mod
    ----------
    多个 mod 覆盖同一文件时，**引擎按加载顺序取最后一个**。本函数只按
    mod 名排序取一个，因此结果对「多个 mod 争同一文件」的情形是**近似**的。
    真正的加载顺序要从 playset 读，本工具链尚未解析它 —— 这一点如实标注，
    不假装精确。
    """
    mapping: dict[str, Path] = {}
    roots: list[Path] = []
    if config.WORKSHOP.is_dir():
        roots.append(config.WORKSHOP)
    if config.LOCAL_MODS.is_dir():
        roots.append(config.LOCAL_MODS)
    for base in roots:
        for mod in sorted(base.iterdir()):
            if not mod.is_dir():
                continue
            for f in mod.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(mod)
                if len(rel.parts) >= 2 and rel.parts[0] in config.SCRIPTABLE_DIRS:
                    mapping.setdefault(rel.as_posix(), f)
    return mapping


def cross_check(
    claims: list[EngineClaim],
    root: Path | None = None,
    log_version: str = "",
    overrides: dict[str, Path] | None = None,
) -> CrossCheckReport:
    """把引擎断言与我们这边的实际行为逐条核对。

    ``overrides`` 为「原版路径 -> 生效文件」映射；不传则自动建立。
    传 ``{}`` 可强制只读原版 —— 在引擎于无 mod 状态下跑过时用得上。
    """
    # 同上，避免 import 期的依赖链变长
    from .lexer import tokenize  # noqa: PLC0415

    root = root or config.GAME
    if overrides is None:
        overrides = build_override_map()
    report = CrossCheckReport(
        counts=Counter(c.kind for c in claims),
        log_version=log_version,
    )
    # 哪些文件被覆盖、且覆盖版与原版**行数不同** —— 这些文件行号不可比。
    # 只读行数（不是全文比对）是刻意的：它便宜、且足够判定"两套内容"。
    for rel in {c.file_rel for c in claims if c.file_rel}:
        base = root / rel
        before = _line_count(base)
        path = overrides.get(rel)
        after = _line_count(path) if path is not None else before
        if before is None or after is None:  # pragma: no cover - 读不到就不下结论
            continue
        report.line_counts[rel] = (after, before)
        if path is not None and before != after:
            report.overridden_files.add(rel)

    # 同一文件会被多条断言引用，缓存 token 流避免重复切分。
    # 标注成 ``list[Token]`` 而不是裸 ``list`` —— 后者会让下游全部退化成 Any。
    token_cache: dict[str, list[Token]] = {}
    #: 原版侧单独一份缓存（只在"生效文件里找不到"时才去查，用于判是否被覆盖删掉）。
    vanilla_cache: dict[str, list[Token]] = {}

    def resolve(rel: str) -> Path:
        """把原版相对路径解析成**引擎实际会读的那个文件**。"""
        return overrides.get(rel) or (root / rel)

    def tokens_of(rel: str) -> list[Token]:
        if rel not in token_cache:
            path = resolve(rel)
            try:
                token_cache[rel] = tokenize(path.read_text(encoding="utf-8-sig", errors="replace"))
            except TOLERATED_ERRORS:  # pragma: no cover
                token_cache[rel] = []
        return token_cache[rel]

    def vanilla_tokens_of(rel: str) -> list[Token]:
        if rel not in vanilla_cache:
            try:
                vanilla_cache[rel] = tokenize(
                    (root / rel).read_text(encoding="utf-8-sig", errors="replace")
                )
            except TOLERATED_ERRORS:  # pragma: no cover
                vanilla_cache[rel] = []
        return vanilla_cache[rel]

    for c in claims:
        if c.kind == "enumeration":
            total, parsed = _scriptable_set(root, c.dir_rel, c.suffix)
            report.coverage[(c.dir_rel, c.suffix)] = (total, parsed, total)

        elif c.kind == "script_location":
            if not resolve(c.file_rel).is_file():
                report.locations.append((c.file_rel, c.line, "文件不存在"))
                continue
            lines = {t.line for t in tokens_of(c.file_rel)}
            report.locations.append(
                (c.file_rel, c.line, "有 token" if c.line in lines else "该行无 token")
            )

        elif c.kind == "token_at":
            if not resolve(c.file_rel).is_file():
                report.missing_files.add(c.file_rel)
                report.tokens.append((c.file_rel, c.line, c.token, None))
                continue
            found: int | None = next(
                (t.line for t in tokens_of(c.file_rel) if t.line == c.line and c.token in t.value),
                None,
            )
            report.tokens.append((c.file_rel, c.line, c.token, found))
            # 只有没命中的才值得再搜两遍，这两遍决定了这条断言属于哪一类：
            #   * 整份文件都没有这个 token        ⇒ 日志比当前 mod 状态旧（absent）
            #   * 那一行有"以它开头"的更长的 token ⇒ 断言成立、只是粒度不同（prefix）
            #   * 其余                            ⇒ 真正的行号错位（misplaced）
            if found is None:
                key = (c.file_rel, c.token)
                toks = tokens_of(c.file_rel)
                if key not in report.tokens_anywhere:
                    report.tokens_anywhere[key] = next(
                        (t.line for t in toks if c.token in t.value),
                        None,
                    )
                report.prefix_on_line[key] = any(
                    t.line == c.line and t.value != c.token and c.token in t.value for t in toks
                )
                # 只有生效文件里找不到时才去读原版 —— 用来判"这个 token 在我们的
                # 世界里到底存不存在"。缓存按文件走，所以每个文件最多多切一次。
                if (root / c.file_rel).is_file():
                    vkey = (c.file_rel, c.token)
                    if vkey not in report.vanilla_anywhere:
                        report.vanilla_anywhere[vkey] = next(
                            (t.line for t in vanilla_tokens_of(c.file_rel) if c.token in t.value),
                            None,
                        )

    return report
