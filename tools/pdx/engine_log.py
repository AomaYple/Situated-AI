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

    kind: str          # enumeration / script_location / token_at
    detail: str        # 人类可读描述
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

    def summary(self) -> dict[str, object]:
        return {
            "日志版本": self.log_version or "未记录",
            "枚举组合": len(self.coverage),
            "覆盖面缺口": len(self.coverage_gaps),
            "位置断言": len(self.locations),
            "token 断言": len(self.tokens),
            "token 不一致": len(self.token_mismatches),
        }


def default_log_dir() -> Path:
    """引擎日志的默认位置。"""
    return config.USERDIR / "logs"


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
        counts=Counter(c.kind for c in claims), log_version=log_version
    )

    # 同一文件会被多条断言引用，缓存 token 流避免重复切分。
    # 标注成 ``list[Token]`` 而不是裸 ``list`` —— 后者会让下游全部退化成 Any。
    token_cache: dict[str, list[Token]] = {}

    def resolve(rel: str) -> Path:
        """把原版相对路径解析成**引擎实际会读的那个文件**。"""
        return overrides.get(rel) or (root / rel)

    def tokens_of(rel: str) -> list[Token]:
        if rel not in token_cache:
            path = resolve(rel)
            try:
                token_cache[rel] = tokenize(
                    path.read_text(encoding="utf-8-sig", errors="replace")
                )
            except TOLERATED_ERRORS:  # pragma: no cover
                token_cache[rel] = []
        return token_cache[rel]

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
                report.tokens.append((c.file_rel, c.line, c.token, None))
                continue
            found: int | None = next(
                (
                    t.line
                    for t in tokens_of(c.file_rel)
                    if t.line == c.line and c.token in t.value
                ),
                None,
            )
            report.tokens.append((c.file_rel, c.line, c.token, found))

    return report
