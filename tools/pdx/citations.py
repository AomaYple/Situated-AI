"""数据源里 ``文件:行号`` 引用的**机械核对**（P10 从纪律变成可执行检查）。

为什么需要它
------------
`ru_defeat.toml` / `tr_defeat.toml` 的每条 `why` 都靠「原版某文件某一行就是这么写的」
立论（P10：每个数字都要有依据）。但闸门 ⑤ 只能查 `why` **非空** —— 它查不出
"行号是编的"。一份 28 KB 的档案里有几十条引用，人眼逐条核不可持续：

* 文件名打错（`00_code_static_modifiers.txt` 写成 `00_static_modifiers.txt`）；
* 行号越界（文件只有 300 行，引了 `:322`）；
* 文件名在游戏里**不唯一**（`modifiers.txt` 有几十个同名的），于是"那条依据"根本指不到唯一一行。

这个模块把这三件事变成一次 `v3 citations` 就能看到的表。**它不做语义判断**：
"那一行真的支持这条 why 吗"仍然要人看 —— 这里只保证"引用的东西**存在且唯一**"，
把人的注意力从"找文件"挪到"读内容"。

口径（写在明处）
----------------
* 引用写法：``文件名:行号`` 或 ``文件名:起-止``（例如 ``content_1_modifiers.txt:1462-1470``）；
* 文件名允许带子路径（``common/defines/00_defines.txt:12``），也允许只写 basename；
* 解析范围：默认在**游戏内容层** ``config.GAME`` 下按 basename 建索引（一次遍历、缓存）；
  带子路径的引用直接按相对路径探；**仓库内**文件（``modgen.py:123`` 这类）也认；
* 行号校验：``1 <= 行号 <= 文件行数``；
* 唯一性：basename 在索引里命中多个路径时，**只有显式写了子路径才算可解析**，
  否则报"歧义"（这是最容易骗过人的一类引用）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pdx import config

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

#: 引用：``名字:行号`` / ``名字:起-止``。
#:
#: ⚠️ 名字里**必须**有扩展名（`.txt` / `.gui` / `.py` / `.md` / `.toml`）——
#: 否则 `03_political_strategies.txt:528-544` 没问题，而 `P2:F9` 这种非文件引用
#: （文档章节号）会被误当成引用。实测 why 里两类都写，所以这条限定是必须的。
CITATION_RE = re.compile(
    # ⚠️ 名字里**可以带空格**：原版历史文件就叫 `rus - russia.txt`（实测：写全路径时
    # 扫描器原样不认，报 4 条假 missing）。首字符仍限死非空格，避免从行首一路吃过来。
    r"(?P<file>[0-9A-Za-z_./\\-][0-9A-Za-z_./\\ -]*?\.(?:txt|gui|py|md|toml|json|yml))"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)

#: 建索引时跳过的目录名（大且无用：图形资源、着色器缓存）。
SKIP_DIRS = frozenset({"gfx", "sound", "music", "shadercache", "__pycache__", ".git"})


@dataclass(frozen=True, slots=True)
class Citation:
    """一条引用 + 它的核对结论。"""

    file: str
    start: int
    end: int
    where: str  #: 引用出现在哪个文件的哪一段（人读用）
    resolved: str  #: 解析到的绝对路径；没解析到是空串
    status: str  #: ok / missing / ambiguous / out_of_range
    detail: str  #: 一句话说明（歧义时列出候选）

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def describe(self) -> str:
        head = f"{self.file}:{self.start}" + (f"-{self.end}" if self.end != self.start else "")
        return f"{self.status:12s} {head}  ← {self.where}  {self.detail}".rstrip()


def _index(root: Path) -> dict[str, list[Path]]:
    """``basename -> [绝对路径…]``。"""
    index: dict[str, list[Path]] = {}
    if not root.is_dir():
        return index
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        index.setdefault(path.name, []).append(path)
    return index


_INDEX_CACHE: dict[Path, dict[str, list[Path]]] = {}


def game_index(root: Path | None = None) -> dict[str, list[Path]]:
    """游戏内容层的 basename 索引（进程内缓存；``clear_cache()`` 可清）。"""
    base = root or config.GAME
    if base not in _INDEX_CACHE:
        _INDEX_CACHE[base] = _index(base)
    return _INDEX_CACHE[base]


def clear_cache() -> None:
    _INDEX_CACHE.clear()


def _line_count(path: Path) -> int:
    """文件行数（``errors='replace'``：个别原版文件不是干净 UTF-8）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(text.splitlines())


def _resolve(name: str, *, root: Path | None = None) -> tuple[Path | None, str, str]:
    """把引用里的文件名解析成唯一个文件；返回 ``(路径|None, 状态, 说明)``。"""
    base = root or config.GAME
    cleaned = name.replace("\\", "/")
    if "/" in cleaned:
        direct = base / cleaned
        if direct.is_file():
            return (direct, "ok", "")
        # 带子路径也可能是"仓库内文件"的写法
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base / cleaned} 不存在（也试过 {repo}）")
    hits = game_index(base).get(cleaned, [])
    if not hits:
        repo = config.REPO / cleaned
        if repo.is_file():
            return (repo, "ok", "")
        return (None, "missing", f"{base} 下没有任何文件叫这个名字")
    if len(hits) > 1:
        sample = "、".join(str(p.relative_to(base)) for p in hits[:4])
        return (
            None,
            "ambiguous",
            f"同名 {len(hits)} 个：{sample}…（引用要么写子路径，要么换一个）",
        )
    return (hits[0], "ok", "")


def scan_text(text: str, *, where: str, root: Path | None = None) -> list[Citation]:
    """扫一段文本（通常是整个数据源文件）里的全部引用并逐条核对。"""
    found: list[Citation] = []
    for match in CITATION_RE.finditer(text):
        name = match.group("file").strip()
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        path, status, detail = _resolve(name, root=root)
        resolved = str(path) if path else ""
        if status == "ok" and path is not None:
            lines = _line_count(path)
            if not (1 <= start <= lines) or not (1 <= end <= lines):
                status = "out_of_range"
                detail = f"文件只有 {lines} 行"
            elif end < start:
                status = "out_of_range"
                detail = f"起止反了（{start}-{end}）"
        found.append(
            Citation(
                file=name,
                start=start,
                end=end,
                where=where,
                resolved=resolved,
                status=status,
                detail=detail,
            )
        )
    return found


def scan_file(path: Path, *, root: Path | None = None) -> list[Citation]:
    """扫一个文件（数据源 / 文档）里的全部引用。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    return scan_text(text, where=path.name, root=root)


def scan_paths(paths: Iterable[Path], *, root: Path | None = None) -> list[Citation]:
    """扫一批文件（目录会展开成它下面的数据源 / 文档）。"""
    found: list[Citation] = []
    for path in _expand(paths):
        found.extend(scan_file(path, root=root))
    return found


def _expand(paths: Iterable[Path]) -> Iterator[Path]:
    suffixes = {".toml", ".md", ".txt", ".py"}
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix in suffixes:
                    yield child
        elif path.is_file():
            yield path


def summarize(citations: Iterable[Citation]) -> dict[str, object]:
    """按状态计数 + 列出问题条目（给 CLI / 测试用）。"""
    items = list(citations)
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
    return {
        "total": len(items),
        "by_status": by_status,
        "problems": [item for item in items if not item.ok],
    }


# ── 入库的「引用支撑域」：让这条纪律在**没有游戏的机器**上也守得住（B77）──
#
# 为什么需要它：`v3 citations` 要**打开原版文件**确认那一行在不在，而 CI runner 上没有游戏。
# 其余门禁都有离线通道（`verify --from-snapshot` / `tables --offline` / `modguard --offline`
# / `ai-surface --offline`），只有这一条没有 —— 这是当前 CI 的唯一实质缺口。
#
# 口径（与其它离线通道一致）：**证明"与入库快照一致"，不证明"与现在的游戏一致"**。
# 后者永远是本机门禁的活（那边 `live=True` 会顺手核一遍"被引那一行还是不是那句话"，
# 也就是"官方更新把我们的依据挪走了"这个信号）。

#: 精简快照里的域名（形状与其余域一致：``域 -> 名称 -> 字符串列表``）。
SECTION = "citation_support"

#: 指纹取 sha256 的前多少位。每行一条、全仓不到一千条 ⇒ 16 位足够，体积减半。
DIGEST_LEN = 16


def line_digest(text: str) -> str:
    """被引那一行的文本指纹（**去首尾空白**后取 sha256 前 :data:`DIGEST_LEN` 位）。

    为什么去空白：行尾空格在原版文件里没有语义，算进去只会制造假漂移。
    """
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:DIGEST_LEN]


def support_domain(
    targets: Iterable[Path] | None = None, *, root: Path | None = None
) -> dict[str, list[str]]:
    """产出引用支撑域：``引用写法 -> ["lines=N", "<行号>:<指纹>", …]``。

    为什么按**引用写法**（而不是解析后的相对路径）建键：离线通道没有游戏树，
    解析不了 `00_defines.txt` 到底指谁 —— 那边能核的只有「这条引用与入库时一模一样」。

    解析不到的引用**不入域**：它本来就该在在线检查里报错，不该被记成"有支撑"。

    ⚠️ 返回值必须**排序**：快照有一条不变量 —— 每个域的字符串列表都是有序的
    （`test_snapshot.py::TestDeterminism::test_lists_are_sorted` 守着它），
    否则两份内容相同的快照会因为遍历顺序不同而"逐字节不同"（本次实测踩到：
    第一版返回的是插入序，那一条一次红出 50 个子项）。
    """
    out: dict[str, list[str]] = {}
    cache: dict[Path, list[str]] = {}
    for item in scan_paths(targets if targets is not None else [Path("mod/data")], root=root):
        if not item.ok:
            continue
        path = Path(item.resolved)
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[path]
        body = out.setdefault(item.file, [f"lines={len(lines)}"])
        for number in range(item.start, min(item.end, len(lines)) + 1):
            body.append(f"{number}:{line_digest(lines[number - 1])}")
    return {name: sorted(set(body)) for name, body in out.items()}


def parse_support(body: Iterable[str]) -> tuple[int, dict[int, str]]:
    """把域里的一条记录解成 ``(文件行数, {行号: 指纹})``。"""
    total = 0
    digests: dict[int, str] = {}
    for raw in body:
        text = raw.strip()
        if text.startswith("lines="):
            total = int(text[len("lines=") :])
        elif ":" in text:
            number, _, digest = text.partition(":")
            digests[int(number)] = digest
    return total, digests


def unsupported(
    items: Iterable[Citation],
    support: Mapping[str, list[str]],
    *,
    live: bool = False,
    root: Path | None = None,
) -> list[tuple[Citation, str]]:
    """把引用对到**入库支撑域**上；返回对不上的那些 + 原因。

    ``live=True``（有游戏本体）时**再核一遍**「被引那一行还是不是那句话」——
    那正是「官方更新把我们的依据挪走了」这第一手信号（`01-大方向.md` §5 的版本演练要的就是它）。
    ``live=False``（CI）只核「与入库快照一致」。

    域里没有的引用**不算通过**：那是"这条依据从来没被记下来过"（或刚加、忘了刷新快照）。
    """
    out: list[tuple[Citation, str]] = []
    cache: dict[Path, list[str]] = {}
    for item in items:
        body = support.get(item.file)
        if body is None:
            out.append(
                (item, "不在入库支撑域里 —— 新加的引用要刷新快照（v3 snapshot create --compact）")
            )
            continue
        total, digests = parse_support(body)
        if item.start > total or item.end > total:
            out.append((item, f"入库时该文件只有 {total} 行"))
            continue
        if not live:
            continue
        path, status, detail = _resolve(item.file, root=root)
        if path is None:
            out.append((item, f"现在解析不到了（{status}）：{detail}"))
            continue
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[path]
        for number in range(item.start, item.end + 1):
            recorded = digests.get(number)
            if recorded is None:
                out.append((item, f"第 {number} 行没被记进支撑域"))
                break
            if number > len(lines) or line_digest(lines[number - 1]) != recorded:
                out.append((item, f"第 {number} 行的内容变了（原版更新？）—— 核对后刷新快照"))
                break
    return out


@dataclass(frozen=True, slots=True)
class CitationMove:
    """一条**位置漂移**的引用：那一行的内容还在，只是行号变了。"""

    file: str
    old_line: int
    new_line: int
    where: str
    #: 同文多处时取"离原行号最近"的那一处，并在这里说明（不静默）。
    note: str = ""

    def describe(self) -> str:
        tail = f"（{self.note}）" if self.note else ""
        return f"{self.file}:{self.old_line} → :{self.new_line}  ← {self.where}{tail}"


def relocate(
    items: Iterable[Citation],
    support: Mapping[str, list[str]],
    *,
    root: Path | None = None,
) -> list[CitationMove]:
    """按**内容指纹**指出漂移的引用现在在哪一行。

    这不是"猜"：支撑域里记着被引那一行的 sha256 前 :data:`DIGEST_LEN` 位，
    所以能在**同一个文件**里精确找回它。为什么会需要它 —— 编辑一个被大量引用的文件
    （`docs/design/backlog.md`、`tools/pdx/ab_probe.py` 这类）时行号会整体平移，
    而内容一个字没动：`v3 citations` 会报"第 N 行的内容变了"，但**不说它去哪了**，
    人得自己 grep 一遍找回来（本轮实测踩过两次：`ab_probe.py:805→852`、
    `backlog.md:161→168`）。这一步补的就是那一句。

    同文多处（同一行文本在文件里出现多次）时取**离原行号最近**的那一处，
    并在 ``note`` 里写明 —— 不静默挑一个。
    """
    out: list[CitationMove] = []
    cache: dict[Path, list[str]] = {}
    for item in items:
        body = support.get(item.file)
        if body is None:
            continue
        _total, digests = parse_support(body)
        path, _status, _detail = _resolve(item.file, root=root)
        if path is None:
            continue
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[path]
        index: dict[str, list[int]] = {}
        for number, text in enumerate(lines, start=1):
            index.setdefault(line_digest(text), []).append(number)
        for number in range(item.start, item.end + 1):
            recorded = digests.get(number)
            if recorded is None:
                continue
            if number <= len(lines) and line_digest(lines[number - 1]) == recorded:
                continue
            found = index.get(recorded, [])
            if not found:
                # 内容真的变了（不是漂移）—— 那要人判断，不在这里编一个位置。
                break
            if len(found) == 1:
                note = ""
            elif all(not lines[n - 1].strip() for n in found):
                # 入库记的是一个**空行** —— 那说明这条引用本来就指错了（空行不可能是依据），
                # 不是"漂移"。实测：`backlog.md:161` 的 why 写着"（B22）"，
                # 而行号落在空行上，空了 32 处 ⇒ 谁也找不回"正确的那一行"。
                note = (
                    f"⚠️ 入库记的那一行是**空行**（重复出现 {len(found)} 次）"
                    "—— 这条引用本来就指错了，请按语义改到正确的那一行"
                )
            else:
                note = f"同一行文本出现 {len(found)} 次，取最近的一处"
            nearest = min(found, key=lambda n: abs(n - number))
            out.append(CitationMove(item.file, number, nearest, item.where, note))
            break
    return out


__all__ = [
    "CITATION_RE",
    "DIGEST_LEN",
    "SECTION",
    "Citation",
    "CitationMove",
    "clear_cache",
    "game_index",
    "line_digest",
    "parse_support",
    "relocate",
    "scan_file",
    "scan_paths",
    "scan_text",
    "summarize",
    "support_domain",
    "unsupported",
]
