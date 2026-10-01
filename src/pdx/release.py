"""发布流程的机械部分：**changelog ↔ 档案 ↔ 元数据**（阶段 7 的最后一件）。

为什么需要它
------------
`01-大方向.md` §3 阶段 7 的出口判据是「任意一个"为什么这么定"都能在文档里查到答案」，
而**发布说明是玩家唯一会读的那一份文档**。它原来只有一条人工纪律：

    `mod/data/<id>.toml` 的 `id` 必须出现在 changelog 条目里

§1 说过「**没有检查方式的原则不算原则**」。这一模块把那句话变成机器可查的四件事：

1. **版本对得上**：changelog 最新那一节的版本号 == 元数据的 `version`
   （发了新版却忘了写发布说明，玩家就不知道这次改了什么）；
2. **每份档案都被写过**：`mod/data` 里每个 id 都以条目形式出现在 changelog 里；
3. **没有幽灵条目**：changelog 里提到的每个档案 id 都真的存在
   （删了档案却留着发布说明 = 说明在骗人）；
4. **归档物对得上**：各档案声明的 `game_version` 必须一致
   （`modgen` 自己也会拦这一条；这里的价值是**在发布检查里也报一次**，
   而不是等到生成时才炸）。

格式（**机器可查的前提**，写在这里也写在 changelog 自己的开头）
----------------------------------------------------------------
档案条目一律写成列表项，id 用反引号包住、后跟一个破折号::

    - `ru_defeat` — 俄罗斯 · 战败求存：一句话说明它修的是什么毛病

版本标题一律写成::

    ## [0.1.0] - 2026-09-23

为什么不让 changelog 由生成器**整份产出**：发布说明是**散文**，是给人读的
（P9 要集中的是阈值/权重/文案这类**事实**，而"这次改了什么、为什么"是作者的判断）。
所以这里做的是「结构由机器守、散文由人写」—— 与 `modgen` 管产物、`why` 管依据同一分工。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config, modgen

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

#: 发布说明的位置（仓库根；给人读的那一份）。
CHANGELOG = config.REPO / "CHANGELOG.md"

#: 版本标题：``## [0.1.0] - 2026-09-23``（方括号与日期都可省）。
VERSION_RE = re.compile(r"^##\s+\[?v?(\d+\.\d+\.\d+)\]?", re.MULTILINE)

#: 档案条目：``- `ru_defeat` — …``（id 在反引号里，后面跟破折号）。
ENTRY_RE = re.compile(r"^-\s+`([a-z][a-z0-9_]*)`\s*[—–-]", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    """一次发布检查的结论（每一项都能单独看，便于在输出里逐条说清）。"""

    changelog: Path
    versions: tuple[str, ...]
    metadata_version: str
    supported: str
    declared_versions: tuple[str, ...]
    archives: tuple[str, ...]
    missing: tuple[str, ...]
    orphans: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def describe(self) -> str:
        lines = [
            f"发布说明      : {self.changelog.name}（{len(self.versions)} 个版本节）",
            f"  最新一节    : {self.versions[0] if self.versions else '（没有版本标题）'}",
            f"  元数据版本  : {self.metadata_version}",
            f"  支持的游戏版: {self.supported}",
            f"  档案        : {len(self.archives)} 份，其中 {len(self.archives) - len(self.missing)} 份写进了发布说明",
        ]
        if self.missing:
            lines.append("  没写进发布说明：" + "、".join(self.missing))
        if self.orphans:
            lines.append("  发布说明里的幽灵条目：" + "、".join(self.orphans))
        if len(self.declared_versions) > 1:
            lines.append("  各档案声明的游戏版本不一致：" + "、".join(self.declared_versions))
        return "\n".join(lines)


def parse_versions(text: str) -> tuple[str, ...]:
    """changelog 里的版本号，**按出现顺序**（最新的一般在最前面）。"""
    return tuple(VERSION_RE.findall(text))


def parse_entries(text: str) -> tuple[str, ...]:
    """changelog 里的**档案条目** id（按出现顺序、去重）。"""
    return tuple(dict.fromkeys(ENTRY_RE.findall(text)))


def check(
    changelog: Path | None = None, *, archives: Iterable[modgen.Archive] | None = None
) -> ReleaseReport:
    """跑一遍发布检查，返回结论（**不抛异常**：每一条问题都写进 `problems`）。"""
    path = changelog or CHANGELOG
    loaded = tuple(archives) if archives is not None else tuple(modgen.load_all())
    payload = modgen.metadata_payload(loaded)
    metadata_version = str(payload.get("version", ""))
    supported = str(payload.get("supported_game_version", ""))
    ids = tuple(sorted(archive.id for archive in loaded))
    declared = tuple(sorted({archive.game_version for archive in loaded}))

    problems: list[str] = []
    if not path.is_file():
        return ReleaseReport(
            changelog=path,
            versions=(),
            metadata_version=metadata_version,
            supported=supported,
            declared_versions=declared,
            archives=ids,
            missing=ids,
            orphans=(),
            problems=(f"没有发布说明：{path}（它是玩家唯一会读的那一份文档）",),
        )

    text = path.read_text(encoding="utf-8")
    versions = parse_versions(text)
    entries = parse_entries(text)
    known = set(ids)
    missing = tuple(archive for archive in ids if archive not in entries)
    orphans = tuple(entry for entry in entries if entry not in known)

    if not versions:
        problems.append("发布说明里没有任何版本标题（应为 `## [<x.y.z>] - <日期>`）")
    elif versions[0] != metadata_version:
        problems.append(
            f"最新一节写的是 {versions[0]}，而元数据是 {metadata_version} —— 发了版没写说明？"
        )
    if missing:
        problems.append("这些档案没有出现在发布说明里：" + "、".join(missing))
    if orphans:
        problems.append("发布说明里提到了不存在的档案：" + "、".join(orphans))
    if len(declared) > 1:
        problems.append("各档案声明的 game_version 不一致：" + "、".join(declared))
    # ⚠️ 这里**故意不**再核「declared[0] == supported」：`metadata_payload` 的
    # `supported_game_version` **就是** `archives[0].game_version`（`modgen.py:1458`），
    # 而档案之间不一致由 `build_all` → `_check_game_version` 拦下 ⇒ 在 `len(declared) == 1`
    # 的前提下那两句永远相等，写出来是一段**不可能失败**的检查（P13 的反面：检查要么能响，
    # 要么别写）。真正守住这件事的是 modgen 那一条，不在这里重复。

    return ReleaseReport(
        changelog=path,
        versions=versions,
        metadata_version=metadata_version,
        supported=supported,
        declared_versions=declared,
        archives=ids,
        missing=missing,
        orphans=orphans,
        problems=tuple(problems),
    )


def template(report: ReleaseReport, *, archives: Iterable[modgen.Archive] | None = None) -> str:
    """给"还没写进发布说明"的档案生成条目骨架 —— 省得人去猜格式。

    只**打印**，不写盘：发布说明是散文，写进去的那句话得人来说（P9 的分工）。
    标题取自数据源（`[archive].title`），所以骨架里不用再手打一遍国名与处境。
    """
    if not report.missing:
        return "（每份档案都已经写进发布说明了）"
    loaded = {archive.id: archive.title for archive in (archives or modgen.load_all())}
    return "\n".join(
        f"- `{archive}` — {loaded.get(archive, archive)}：<一句话说清它修的是什么毛病>"
        for archive in report.missing
    )


__all__ = [
    "CHANGELOG",
    "ENTRY_RE",
    "VERSION_RE",
    "ReleaseReport",
    "check",
    "parse_entries",
    "parse_versions",
    "template",
]
