"""仓库文件口径闸门 —— 直击「一次小编辑变成整文件重写」与「游戏侧文件像没生效」两类事故。

五件被判的事
------------
1. **换行符**：仓库里全是 LF（``.gitattributes`` 写着 ``eol=lf``），而 Windows 上
   ``Path.write_text(text)`` **默认把 ``\\n`` 翻译成 ``\\r\\n``**。实测踩过：一次
   「改一个函数名」的脚本用 ``p.read_text()`` + ``p.write_text()`` 重写了
   ``tools/pdx/doc_tables.py``，文件从 LF 变成 CRLF —— ``git add`` 时 git 给出
   ``CRLF will be replaced by LF`` 的警告，提交后 diff 正常，但**本地工作树与索引
   长期不一致**（`git status` 反复报改动），而真正的原因（漏了 ``newline="\\n"``）
   藏在一句警告里。
2. **仓库侧不许带 BOM**：BOM 会让 ``ast.parse`` 直接 ``SyntaxError``（实测发生过，
   见 ``docs/design/exec/收口清单.md`` C.0）；``.json`` 的读取方（启动器）按 JSON 解析。
3. **引擎侧必须带 BOM**：``mod/**`` 与 ``tools/probe/**`` 下的 ``.txt`` / ``.yml`` 是
   被游戏引擎读的 —— `.yml` 缺 BOM 实测会 ``Missing UTF8 BOM …`` 后**退出加载**，
   ``.txt`` 缺了则只在 ``error.log`` 里刷提醒（``lexer.cpp:285``）。依据与实况见
   ``docs/design/exec/编码口径审计.md``（t2）：受控 369 条 = 清单① 117 条必带 BOM
   + 清单② 252 条必不带，当时两清单各 0 违规。
4. **孤立 CR**：``0D`` 后面**不接** ``0A``。这类控制字符混进文件后 ``git diff``
   看不出来，而它在别的编辑器/工具里会显示成怪字符。实测踩过：PowerShell 的双引号
   here-string 往台账文件里写出过 CR / NUL / TAB 三种污染，而当时只有「查 ``0D 0A``」
   一条判据，**看不见孤立 CR**（t84 补上）。
5. **NUL**：文本后缀的受控文件里一个 ``00`` 都不许有。这一条有个特殊之处：内容里有
   NUL 的文件会先被 :func:`_是二进制` 当成二进制**整份跳过**，于是「被 NUL 污染」恰好
   表现为「这条闸门一声不吭」。⇒ 二进制只许**由后缀声明**
   （:func:`test_二进制必须由后缀声明而不是靠内容嗅探`），不许靠内容嗅探蒙过去。
   ⚠️ **TAB（``09``）不判**：V3 脚本用 TAB 缩进是合法的，``mod/**`` 与
   ``tools/probe/**`` 里全是大片 TAB。
6. **用例不许往共享 ``tools/out/**`` 写固定名产物**（B116，2026-09-25 加）：用例里的
   固定名产物会让**同一台机器上的第二个 pytest 进程**与它互相覆盖/互删 —— ``t95`` 查明
   ``test_cli.py:269`` 那条并行红的触发条件正是这个（不是 ``-n 4`` 本身）。
   判法与边界见 :func:`test_没有用例往共享产物目录写固定名文件` 上方那一段。

判定刻意**不做**的事：不比对行尾风格、不重排、不猜编码、不管 TAB —— 只看
「前三字节是 BOM 吗」「有没有 ``0D 0A``」「有没有落单的 ``0D``」「有没有 ``00``」，
避免这条检查本身变成噪声源。（第 6 条是**静态扫查 AST**，不执行任何用例。）

为什么要用 ``git ls-files`` 而不是 ``rglob``
--------------------------------------------
* **只判「提交进去的东西」**。``rglob`` 会把忽略目录（``tools/out/`` 产物、
  ``research/official-docs/`` 官方文档镜像、``tools/probe/zz_console_probe/`` 引擎写出的
  数据）一起扫进来 —— 实测多出 95 个文件，而其中就有**合法带 BOM** 的数据产物，
  按 `rglob` 判会误报。
* ``git ls-files`` 也让「受控」与「提交」严格同义，判据不必自己维护排除清单。
"""

from __future__ import annotations

import ast
import functools
import importlib
import mmap
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pdx import config

#: 一条判据：读到的字节（可能是分块流）→ 违规说明（``None`` = 合规）。
_判据 = Callable[[Path, "_Source"], "str | None"]

#: UTF-8 BOM 的三个字节。用 ``bytes`` 字面量而不是 ``"\\ufeff".encode()``：判据是**字节级**的。
_BOM = bytes((0xEF, 0xBB, 0xBF))
#: 二进制嗅探窗口。与 git 自己的文本启发式同源：前 8000 字节里出现 NUL 就当二进制。
_BINARY_SNIFF = 8000
#: 引擎会读的文本后缀（与 ``modgen.GAME_SIDE_SUFFIXES`` 同源）。
_GAME_SIDE_SUFFIXES = (".txt", ".yml")
#: 引擎侧目录前缀：这两处的 ``.txt`` / ``.yml`` 是**游戏侧文件**。
_GAME_SIDE_PREFIXES = ("mod/", "tools/probe/")

# ── 读文件的两种方式 ────────────────────────────────────────────
# 大于这个字节数的受控文件改成「映射 + 分块扫描」，不在内存里放整份。
# 现场 366 个受控文本里只有**两个**超过它（``tools/out/snapshots/*.compact.json``，
# 各 6.36 MiB）—— 实测：整份读时每次 worker 的峰值常驻 12.6 MiB，分块扫之后降到 1.3 MiB。
_READ_WHOLE_MAX = 1 << 20
#: 分块扫描的块大小。8 KiB 与 `mmap` 的页大小同量级，切分代价可忽略。
_CHUNK = 8192
#: 一定不是文本的后缀（``.gitattributes`` 的 binary 组同源）。
#: 命中就**连读都不读** —— 探针 UI 的 3 个 PNG 走这条捷径。
_BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".dds", ".tga", ".ico",
    ".xlsx", ".pptx", ".prof", ".pyisession",
)  # fmt: skip

#: 扫描范围的下限（元测试用）。现场实测值：受控 369 · 文本 366 · 引擎侧 117（t2 审计）。
#: 取略低的值：目录改名 / 口径写错时当场红，而正常增删文件不会误报。
_MIN_TRACKED = 300
_MIN_TEXT = 300
_MIN_GAME_SIDE = 100


#: 违规名单的两句人话抬头（测试与失败信息共用，避免两处各写一遍）。
_仓库侧侧 = "仓库侧带了 UTF-8 BOM（`.py` 会让 `ast.parse` 失败、`.json` 会让读取方解析失败）"
_引擎侧侧 = (
    f"引擎侧（{'、'.join(_GAME_SIDE_PREFIXES)} 下的 {_GAME_SIDE_SUFFIXES}）"
    "少了 UTF-8 BOM —— 在游戏里会「像没生效」"
)


@functools.lru_cache(maxsize=1)
def _受控文件() -> tuple[str, ...]:
    """``git ls-files`` 的全量受控文件（仓库相对 POSIX 路径，字典序）。

    ``-z`` 是必须的：路径里有中文时，默认输出会给非 ASCII 路径加引号并转义八进制，
    于是那些文件**永远扫不到**（实测）。``git`` 不可用时跳过而不是判红 —— 这条闸门的
    价值依赖版本控制，没装 git 的环境不该因此变红。
    """
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
            cwd=str(config.REPO),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:  # pragma: no cover - 环境无 git
        pytest.skip("找不到 git —— 受控文件清单取不到")
    except subprocess.CalledProcessError as exc:  # pragma: no cover - 不是 git 工作树
        pytest.skip(f"git ls-files 失败（{exc.returncode}）")

    return tuple(sorted(chunk.decode("utf-8") for chunk in proc.stdout.split(b"\x00") if chunk))


def _是二进制(data: bytes) -> bool:
    """前 ``_BINARY_SNIFF`` 字节含 NUL ⇒ 按二进制对待，不做 BOM/LF 判定。"""
    return b"\x00" in data[:_BINARY_SNIFF]


@dataclass(frozen=True)
class _Source:
    """一个文件的原始字节：要么整份在内存里，要么是「映射 + 分块」的流。

    为什么要有这层：``-n auto`` 下 16 个 worker 各自扫全树，而全树 17.7 MiB 里
    12.14 MiB 是两份入库快照。整份读进来 = 每个 worker 多 12 MiB 常驻；
    分块扫 = 每个 worker 只多一个块（8 KiB），判定结果逐字节相同。
    """

    path: Path
    whole: bytes | None = None
    size: int | None = None

    def 前几字节(self, n: int) -> bytes:
        """前 ``n`` 字节（不足就少给）。``whole`` 与流两条路都只碰头部。"""
        if self.whole is not None:
            return self.whole[:n]
        if not self.size:
            return b""
        with self.path.open("rb") as fh:
            return fh.read(n)

    def 分块(self) -> Iterable[tuple[int, bytes]]:
        """``(起始偏移, 块)`` 序列；``whole`` 时只有一块。"""
        if self.whole is not None:
            yield 0, self.whole
            return
        with self.path.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as view:
            offset = 0
            while chunk := view[offset : offset + _CHUNK]:
                yield offset, chunk
                offset += len(chunk)


def _打开(path: Path) -> _Source | None:
    """读一个文件；``None`` = 按二进制跳过（后缀定死，或前 8000 字节里有 NUL）。"""
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return None
    size = path.stat().st_size
    if size > _READ_WHOLE_MAX:
        source = _Source(path=path, size=size)
        if _是二进制(source.前几字节(_BINARY_SNIFF)):
            return None
        return source
    data = path.read_bytes()
    return None if _是二进制(data) else _Source(path=path, whole=data, size=len(data))


def _相对路径(path: Path) -> str:
    """转成仓库相对 POSIX 路径；不在仓库里（``tmp_path``）就原样返回。"""
    try:
        return path.relative_to(config.REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _是引擎侧(rel: str) -> bool:
    """引擎侧 ⇔ 路径在 ``mod/`` 或 ``tools/probe/`` 下 **且** 后缀是 ``.txt`` / ``.yml``。

    两个条件缺一不可：全仓只有两个 ``.yml`` 不在那两个目录下
    （``.github/workflows/ci.yml`` 与本目录的 ``test_golden/test_artifact_digests.yml``），
    它们**必须不带 BOM** —— 任何「后缀即引擎侧」的写法都会当场判错。
    """
    return rel.endswith(_GAME_SIDE_SUFFIXES) and rel.startswith(_GAME_SIDE_PREFIXES)


def _第一处(source: _Source, needle: bytes) -> int | None:
    """跨块安全地找 ``needle``（命中可能**正好横跨两个块**）⇒ 绝对偏移；没有 ⇒ ``None``。

    ⚠️ 为什么不能每块各自 ``find``：``0D`` 与 ``0A`` 落在块边界上时（``0D`` 是前一块的
    最后一字节、``0A`` 是后一块的第一字节），那一处会被**静默漏掉**。把 ``_CHUNK`` 压到
    4 字节就能复现（见 :func:`test_分块扫描跨块边界也判得出`，t84 修的就是这一类）。
    手法是 carry 一个 ``len(needle)-1`` 字节的重叠窗口：命中处只可能跨一个字节。
    """
    overlap = len(needle) - 1
    carry = b""
    for offset, chunk in source.分块():
        window = carry + chunk
        at = window.find(needle)
        if at >= 0:
            return offset - len(carry) + at
        carry = window[-overlap:] if overlap else b""
    return None


def _第一处孤立CR(source: _Source) -> int | None:
    """第一处**孤立** ``0D``（后面不接 ``0A``）⇒ 绝对偏移；没有 ⇒ ``None``。

    ``0D`` 落在块尾、它的下一个字节在下一块时，靠 carry 的这一个 CR 再看一轮；
    **文件末尾**那个没有任何后继的 ``0D`` 同样是孤立 CR。
    """
    carry = b""
    for offset, chunk in source.分块():
        window = carry + chunk
        base = offset - len(carry)
        at = window.find(b"\r")
        while at >= 0:
            if at + 1 >= len(window):
                break  # 它的下一个字节要靠下一轮的 carry 才看得到
            if window[at + 1] != 0x0A:
                return base + at
            at = window.find(b"\r", at + 2)
        carry = window[-1:]
    if carry == b"\r":
        return (source.size or 0) - 1
    return None


def _行号(source: _Source, offset: int) -> int:
    """``offset`` 落在第几行（1 起，只数 ``0A``）。只在判红时算一次，代价可接受。"""
    seen = 0
    for chunk_offset, chunk in source.分块():
        if chunk_offset + len(chunk) <= offset:
            seen += chunk.count(b"\n")
            continue
        return seen + chunk[: max(0, offset - chunk_offset)].count(b"\n") + 1
    return seen + 1


def _计数对(source: _Source, needle: bytes) -> int:
    """整个文件里 ``needle`` 出现几次（**跨块的也算**）—— 与 :func:`_第一处` 同一套 carry 逻辑。

    ⚠️ 不能写成 ``sum(chunk.count(needle) for …)``：那样跨块的那一处会被数成 **0 次**
    （``0D 0A`` 各自待在相邻两块里）—— 于是"报了第几行"与"共几处"会互相矛盾
    （t84 的边界用例当场把这个不一致撞出来了）。carry 的窗口里**整个 needle 都装不下**
    （重叠只有 ``len-1`` 字节）⇒ 每个命中至少含当前块的一个字节，不会重复计数。
    """
    overlap = len(needle) - 1
    carry = b""
    total = 0
    for _offset, chunk in source.分块():
        window = carry + chunk
        start = 0
        while (at := window.find(needle, start)) >= 0:
            total += 1
            start = at + 1
        carry = window[-overlap:] if overlap else b""
    return total


def _CRLF违规(path: Path, source: _Source) -> str | None:
    """两侧共用的换行判据：字节里出现 ``0D 0A`` 即违规。

    BOM 只看头部，换行必须扫全 —— 于是按块扫、只在命中时才为了**数总量**多跑一遍。
    """
    at = _第一处(source, b"\r\n")
    if at is None:
        return None
    total = _计数对(source, b"\r\n")
    return f"{_相对路径(path)} 第 {_行号(source, at)} 行（共 {total} 处）"


def _仓库侧违规(path: Path, source: _Source) -> str | None:
    """仓库侧（引擎不读的那些）：不许带 BOM。"""
    return f"{_相对路径(path)} 带了 UTF-8 BOM" if source.前几字节(3) == _BOM else None


def _引擎侧违规(path: Path, source: _Source) -> str | None:
    """引擎侧：必须带 BOM —— 缺了在游戏里表现为「这份文件像没生效」。"""
    return None if source.前几字节(3) == _BOM else f"{_相对路径(path)} 少了 UTF-8 BOM"


def _孤立CR违规(path: Path, source: _Source) -> str | None:
    """两侧共用：不许有**落单**的 ``0D``（成对的 ``0D 0A`` 由 :func:`_CRLF违规` 报）。"""
    at = _第一处孤立CR(source)
    if at is None:
        return None
    return f"{_相对路径(path)} 第 {_行号(source, at)} 行有孤立 CR（偏移 {at}）"


def _NUL违规(path: Path, source: _Source) -> str | None:
    """两侧共用：文本后缀的受控文件里不许有 ``00``。

    前 8000 字节里的 NUL 到不了这里（:func:`_是二进制` 先把文件判成二进制跳过了）——
    那一类由 :func:`test_二进制必须由后缀声明而不是靠内容嗅探` 兜住：两条合起来才是
    「文本后缀的受控文件里一个 NUL 都不许有」。
    """
    at = _第一处(source, b"\x00")
    if at is None:
        return None
    return f"{_相对路径(path)} 有 NUL（偏移 {at}）"


#: 两侧共用的判据：任何受控文本文件都要过（换行风格 + 控制字符污染）。
_两侧共用判据 = (_CRLF违规, _孤立CR违规, _NUL违规)


def _判据适用于(rel: str, rule: _判据) -> bool:
    """这条判据该不该套在这个文件上：换行/污染类两侧共用，BOM 判据按分类二选一。"""
    if rule in _两侧共用判据:
        return True
    return rule is (_引擎侧违规 if _是引擎侧(rel) else _仓库侧违规)


def _违规明细(paths: Iterable[Path], rule: _判据) -> list[str]:
    """逐个文件套用一条判据；**一次只开一个文件**（不把整棵树读进内存）。"""
    out: list[str] = []
    for path in paths:
        source = _打开(path)
        if source is None:
            continue
        problem = rule(path, source)
        if problem:
            out.append(problem)
    return out


@functools.lru_cache(maxsize=1)
def _分组() -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    """把受控文件分成（引擎侧, 仓库侧文本, 二进制）——与 ``test_全部受控文件`` 同一口径。

    产出的三个元组只装路径、**不装文件内容**，且整棵树只扫一次（``lru_cache``）：
    ``-n auto`` 下 16 个 worker 各持一份，常驻内存要留在 KB 级。
    """
    engine: list[Path] = []
    repo_side: list[Path] = []
    binary: list[Path] = []
    for rel in _受控文件():
        path = config.REPO / rel
        if path.suffix.lower() in _BINARY_SUFFIXES:
            binary.append(path)
            continue
        source = _打开(path)
        if source is None:
            binary.append(path)
        elif _是引擎侧(rel):
            engine.append(path)
        else:
            repo_side.append(path)
    return tuple(engine), tuple(repo_side), tuple(binary)


def test_全部受控文件_两侧BOM口径() -> None:
    """扫描范围 = ``git ls-files`` 的全部受控文件（现场 369 条）。

    两条规则：**仓库侧必不带 BOM**（``.py`` 会让 ``ast.parse`` 失败、``.json`` 会让
    读取方解析失败），**引擎侧必带**（``.txt`` / ``.yml`` 缺了在游戏里「像没生效」）。
    """
    engine, repo_side, _ = _分组()
    assert len(_受控文件()) >= _MIN_TRACKED, (
        f"受控文件只剩 {len(_受控文件())} 条 —— 扫描范围多半失效了"
    )
    stray = _违规明细(repo_side, _仓库侧违规)
    missing = _违规明细(engine, _引擎侧违规)
    # 一次报全（合起来成一条断言）：否则第一条红就看不见第二条的名单，定位得跑两遍。
    problems = [f"{侧}：{名}" for 侧, 名 in ((_仓库侧侧, stray), (_引擎侧侧, missing)) if 名]
    assert not problems, (
        "受控文件的 BOM 口径被破坏 —— 仓库侧不许带、引擎侧必须带：\n  " + "\n  ".join(problems[:20])
    )


def test_全部受控文件_没有文件带CRLF() -> None:
    """两侧共用的换行判据：任何受控文本文件都不许有 ``0D 0A``。"""
    engine, repo_side, _ = _分组()
    bad = _违规明细(engine + repo_side, _CRLF违规)
    assert not bad, (
        "以下文件带 CRLF —— 多半是 `write_text` 漏了 `newline='\\n'`：\n  " + "\n  ".join(bad[:10])
    )


def test_全部受控文件_没有孤立CR与NUL() -> None:
    """两侧共用（t84 新增的两条判据）：不许有**落单**的 ``0D``，也不许有 ``00``。

    为什么与 CRLF 那条分开：``0D 0A`` 是"换行风格错了"，落单的 ``0D`` / ``00`` 是
    "文件里混进了控制字符" —— 后者在 ``git diff`` 里看不出来，而它会让别的工具把整行
    显示成怪字符（PowerShell 的 here-string 往台账文件上实测写出过 CR / NUL / TAB 三种）。
    ⚠️ **TAB 不在这两条里**：V3 脚本用 TAB 缩进合法，``mod/**`` 与 ``tools/probe/**`` 全是大片 TAB。
    """
    engine, repo_side, _ = _分组()
    texts = engine + repo_side
    problems = [
        f"{侧}：{名}"
        for 侧, 名 in (
            ("落单的 CR", _违规明细(texts, _孤立CR违规)),
            ("NUL", _违规明细(texts, _NUL违规)),
        )
        if 名
    ]
    assert not problems, (
        "受控文本里混进了控制字符 —— 多半是 PowerShell 的 here-string / 重定向写的：\n  "
        + "\n  ".join(problems[:20])
    )


def test_分块扫描跨块边界也判得出(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``0D`` 在前一块最后一字节、``0A`` 在后一块第一字节时，两条判据都必须判得出。

    这是 t84 修掉的一处**静默漏判**：旧写法每块各自 ``find(b"\\r\\n")``，横跨边界的那一处
    一声不吭（把 ``_CHUNK`` 压到 4 字节即可复现）。这里同时钉住 CRLF、孤立 CR，
    以及**文件末尾**那个没有任何后继的 ``0D``。
    """
    monkeypatch.setattr(sys.modules[__name__], "_CHUNK", 4)
    monkeypatch.setattr(sys.modules[__name__], "_READ_WHOLE_MAX", 1)  # 强制走分块那条路

    straddle = tmp_path / "tools/probe/zz_probe_a/docs/straddle.txt"
    straddle.parent.mkdir(parents=True)
    # 偏移 3 = \r（首块末）、偏移 4 = \n（次块首）⇒ 那一处横跨两块；偏移 8 = 文件末尾的落单 \r
    straddle.write_bytes(b"abc\r\ndef\r")
    assert _违规明细([straddle], _CRLF违规) == [f"{straddle.as_posix()} 第 1 行（共 1 处）"]
    assert _违规明细([straddle], _孤立CR违规) == [
        f"{straddle.as_posix()} 第 2 行有孤立 CR（偏移 8）"
    ]

    clean = straddle.with_name("clean.txt")
    clean.write_bytes(b"abcdef\n")
    assert not _违规明细([clean], _CRLF违规), "干净文件被 CRLF 判据误报了"
    assert not _违规明细([clean], _孤立CR违规), "干净文件被孤立 CR 判据误报了"


def test_NUL在嗅探窗口之外也判得出(tmp_path: Path) -> None:
    """前 8000 字节干净、NUL 藏在后面时，:func:`_NUL违规` 必须抓到（嗅探看不见它）。"""
    poisoned = tmp_path / "notes/late_nul.md"
    poisoned.parent.mkdir(parents=True)
    poisoned.write_bytes(b"# title\n" + b"filler line\n" * 900 + b"tail\x00\n")
    assert poisoned.stat().st_size > _BINARY_SNIFF, "这条用例要的正是「NUL 在嗅探窗口之外」"
    detail = _违规明细([poisoned], _NUL违规)
    assert detail, "藏在嗅探窗口之外的 NUL 没被抓到"
    assert "有 NUL" in detail[0], detail


def _嗅探出来的二进制(binary: Iterable[Path]) -> list[str]:
    """靠**内容嗅探**（而不是后缀）判成二进制的文件 —— 它们是编码闸门的盲区。"""
    return [
        f"{_相对路径(path)}（后缀 `{path.suffix or '无'}`）"
        for path in binary
        if path.suffix.lower() not in _BINARY_SUFFIXES
    ]


def test_二进制必须由后缀声明而不是靠内容嗅探(tmp_path: Path) -> None:
    """被 NUL 污染的**文本后缀**文件，绝不能因为「内容像二进制」被静默跳过。

    盲区长这样：``_是二进制`` 见到前 8000 字节里有 NUL 就把文件整份跳过 ⇒ BOM、CRLF、
    落单 CR、NUL 四条判据**一条都套不上**，而闸门什么也不说 —— 正是"看起来没事"那一类。
    今天现场 3 个二进制全是探针 UI 的 ``.png``（后缀都在表里）⇒ 这条判绿。
    """
    _, _, binary = _分组()
    undeclared = _嗅探出来的二进制(binary)
    assert not undeclared, (
        "以下文件是**靠内容嗅探**判成二进制的（后缀不在 `_BINARY_SUFFIXES` 里）：\n  "
        + "\n  ".join(undeclared[:20])
        + "\n⇒ 这类文件会被整份跳过（四条判据一条都套不上）。"
        "真实的二进制请把后缀加进 `_BINARY_SUFFIXES`，别让它靠嗅探蒙过去。"
    )

    # 阴性对照：同一条判据喂一份「后缀没声明、内容有 NUL」的临时文件时必须点名
    poisoned = tmp_path / "notes/poisoned.md"
    poisoned.parent.mkdir(parents=True)
    poisoned.write_bytes(b"# title\x00tail\n")
    assert _打开(poisoned) is None, "前提：嗅探确实会把它当二进制跳过"
    assert _嗅探出来的二进制([poisoned]), "阴性对照没点名 ⇒ 这条闸门是空转的"


def test_二进制文件被排除() -> None:
    """受控集里的二进制（现场 3 个探针 UI 的 PNG）既不判 BOM 也不判 LF。

    跳过它们的第一道闸是**后缀**（``.png`` 命中就根本不读）；万一将来有人把后缀表删了，
    还有第二道 NUL 嗅探兜底 —— 两条都在下面钉住。
    """
    _, _, binary = _分组()
    assert binary, "一个二进制文件都没识别出来 —— 排除规则多半失效了"
    for path in binary:
        assert path.suffix.lower() in _BINARY_SUFFIXES or _是二进制(path.read_bytes()[:8000]), (
            f"{_相对路径(path)} 被判成二进制，但后缀不在表里、字节里也没有 NUL"
        )


def test_大文件走分块扫描也判得出CRLF(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过 ``_READ_WHOLE_MAX`` 的文件走 ``mmap`` + 分块那条路（真仓库里是两份入库快照）。

    口径必须与整份读**逐字节相同**：这里把阈值压到 64 字节，逼出分块路径 ——
    含 CRLF 的判红、不含的判绿，两者都不能因为「块边界」而漏判。
    """
    monkeypatch.setattr(sys.modules[__name__], "_READ_WHOLE_MAX", 64)

    bad = tmp_path / "tools/probe/zz_probe_a/docs/big.txt"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"".join(f"line {i}\n".encode() for i in range(40)) + b"tail\r\n")
    assert bad.stat().st_size > 64, "这条用例要的正是「超过阈值」"
    assert _违规明细([bad], _CRLF违规) == [f"{bad.as_posix()} 第 41 行（共 1 处）"], (
        "分块扫描漏判了 CRLF"
    )

    good = bad.with_name("big_ok.txt")
    good.write_bytes(b"".join(f"line {i}\n".encode() for i in range(40)))
    assert not _违规明细([good], _CRLF违规), "分块扫描误报了"

    # BOM 走的是另一条路（只读头部）：分块那条路也必须看得见 BOM
    assert _违规明细([bad], _引擎侧违规) == [f"{bad.as_posix()} 少了 UTF-8 BOM"]
    good.write_bytes(_BOM + good.read_bytes())
    assert not _违规明细([good], _引擎侧违规)


@dataclass(frozen=True)
class _Case:
    """一条判据在某个文件上的期望结论：``期望`` 为 None 表示应当判绿。"""

    id: str
    文件: str
    内容: bytes
    判据: _判据
    期望: str | None
    引擎侧: bool = False  # 该文件是否落在「引擎侧」分类里（与 `_是引擎侧` 期望一致）


_实例 = (
    _Case(
        "仓库侧带BOM_判红", "notes/readme.md", _BOM + b"# title\n", _仓库侧违规, "带了 UTF-8 BOM"
    ),
    _Case("仓库侧无BOM_判绿", "notes/readme.md", b"# title\n", _仓库侧违规, None),
    _Case(
        "仓库侧CRLF_判红",
        "notes/readme.md",
        b"# title\r\nbody\r\n",
        _CRLF违规,
        "第 1 行（共 2 处）",
    ),
    _Case("仓库侧LF_判绿", "notes/readme.md", b"# title\nbody\n", _CRLF违规, None),
    _Case(
        "引擎侧无BOM_判红",
        "mod/common/static_modifiers/sitai_x.txt",
        b"x = 1\n",
        _引擎侧违规,
        "少了 UTF-8 BOM",
        True,
    ),
    _Case(
        "引擎侧带BOM且LF_判绿",
        "mod/common/static_modifiers/sitai_x.txt",
        _BOM + b"x = 1\n",
        _引擎侧违规,
        None,
        True,
    ),
    _Case(
        "引擎侧CRLF_判红",
        "tools/probe/zz_probe_a/common/decisions/zz_probe_decisions.txt",
        _BOM + b"d = 1\r\n",
        _CRLF违规,
        "第 1 行（共 1 处）",
        True,
    ),
    _Case(
        "二进制_后缀排除_判绿",
        "tools/probe/zz_probe_ab/ui/btn_x.png",
        _BOM + b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        _CRLF违规,
        None,
    ),
    _Case(
        "二进制_NUL嗅探排除_判绿",
        "tools/probe/zz_probe_b/common/scripted_effects/blob.dat",
        _BOM + b"binary\r\n\x00\x01\x02",
        _CRLF违规,
        None,
    ),
    _Case("仓库侧孤立CR_判红", "notes/readme.md", b"# title\rbody\n", _孤立CR违规, "有孤立 CR"),
    _Case("仓库侧CRLF_不是孤立CR_判绿", "notes/readme.md", b"# a\r\nb\n", _孤立CR违规, None),
    _Case("仓库侧无控制字符_判绿", "notes/readme.md", b"# a\nb\tc\n", _孤立CR违规, None),
    _Case(
        "引擎侧孤立CR_判红",
        "mod/common/static_modifiers/sitai_x.txt",
        _BOM + b"x = 1\ry = 2\n",
        _孤立CR违规,
        "有孤立 CR",
        True,
    ),
    _Case(
        "NUL在嗅探窗口之外_判红",
        "notes/big.md",
        b"# title\n" + b"filler line\n" * 900 + b"tail\x00\n",
        _NUL违规,
        "有 NUL",
    ),
    _Case("无NUL_判绿", "notes/readme.md", b"# title\nbody\twith\ttabs\n", _NUL违规, None),
)


@pytest.mark.parametrize("实例", _实例, ids=[c.id for c in _实例])
def test_判据在反证文件上会红也会绿(tmp_path: Path, 实例: _Case) -> None:
    """每一条判据都要有**反证**：坏文件点名报错、好文件一声不吭。

    只在 ``tmp_path`` 里造文件（B91：并行的用例只读仓库，要写就写临时副本）——
    既不动仓库，也不新建「受控文件」，因此与 ``git ls-files`` 的口径天然吻合。
    """
    path = tmp_path / 实例.文件
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(实例.内容)

    assert _是引擎侧(实例.文件) is 实例.引擎侧, (
        f"`{实例.文件}` 的分类与用例声明的（引擎侧={实例.引擎侧}）不一致 —— "
        "分类只看 `mod/`+`tools/probe/` 前缀与 `.txt`+`.yml` 后缀这两个条件"
    )
    assert _判据适用于(实例.文件, 实例.判据), (
        f"这条判据（{getattr(实例.判据, '__name__', 实例.判据)}）不该套在 {实例.文件} 上 —— "
        "BOM 判据按「引擎侧 / 仓库侧」二选一，换行判据两侧共用"
    )

    detail = _违规明细([path], 实例.判据)
    if 实例.期望 is None:
        assert not detail, f"应当判绿，却报了：{detail}"
    else:
        assert detail, "应当判红，却一声不吭"
        assert 实例.期望 in detail[0], f"报的错不指名：{detail[0]}"


def test_检查范围不为空() -> None:
    """元测试：目录改名 / 口径写错后，这条检查不能变成「扫了 0 个文件、永远通过」。"""
    engine, repo_side, binary = _分组()
    text = len(engine) + len(repo_side)
    assert len(_受控文件()) >= _MIN_TRACKED, f"受控文件只剩 {len(_受控文件())} 条"
    assert text >= _MIN_TEXT, f"只扫到 {text} 个文本文件 —— 检查范围多半失效了"
    assert len(engine) >= _MIN_GAME_SIDE, (
        f"引擎侧只剩 {len(engine)} 条（{'、'.join(_GAME_SIDE_PREFIXES)}）—— "
        "要么目录不见了，要么 `_是引擎侧` 的判法变了"
    )
    assert binary, "一个二进制文件都没识别出来"


@pytest.mark.parametrize("root", _GAME_SIDE_PREFIXES)
def test_引擎侧目录存在(root: str) -> None:
    assert (config.REPO / root).is_dir(), f"{root} 不见了 —— 上面那条检查会静默缩小范围"


# ────────────── 用例不许往共享产物目录写固定名文件（B116）──────────────
#
# 为什么单独立一条（现场，不是假想）：`t95` 查明 `test_cli.py:269` 那条并行红的触发条件
# **不是 `-n 4` 本身**（`--dist loadscope` 把同一模块钉在一个 worker 上），而是
# **同一台机器上第二个 pytest 进程**：两条用例用同一个固定 label 往**共享**的
# `tools/out/snapshots/` 写产物、随后按前缀删，于是互相删掉对方刚建好的文件。实测：
# 错峰 35 s 起两条并发，后一条在 `:269` 报 `快照不存在 …cli-test-tmp.json`（exit 2）。
# 修法是**进程内隔离**（`monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)`），
# 但那只是修了一次事故 —— 纪律本身没有被用例守着：下次谁再往共享目录写固定名产物，
# 只能等某一次并发跑出概率性红。这条扫查就是那道闸门。
#
# 扫什么（**静态**扫 AST，不执行用例）：
#
# * **共享根**：`config.OUT`；`<模块>.<常量>`（导入后确认取值落在 `config.OUT` 之下，
#   例如 `snapshot.SNAPSHOT_DIR` / `verify.SNAPSHOT_DIR`）；以及
#   `config.REPO / "tools" / "out" …` 这种**字面量拼出来**的路径。
# * **一跳以上的传播**：`paths = snapshot.list_snapshots()`、`for p in paths:` 里的名字
#   也算共享 —— `t95` 出事那两行长的就是
#   `for p in snapshot.list_snapshots(): … p.unlink(missing_ok=True)`。
# * **写/删动作**：`write_text` / `write_bytes` / `unlink` / `mkdir` / `rmdir` / `touch` /
#   `rename` / `replace` / `rmtree` / `copy*` / `move`，以及**写模式**的 `open(...)`（含
#   `Path.open("w")`）。
#
# **刻意不做的事**（免得这条扫查变成噪声源）：不执行代码；看不穿跨模块封装（把共享路径
# 交给 `pdx.*` 里的函数去写，这里看不见 —— `t95` 的修法正是"改常量"而不是"改调用"，
# 所以那条修法天然不触发本扫查）；**解析不了 `tools/probe/*` 那些不是包的脚本里的常量**
# （它们要按路径加载才拿得到值，而 import 那些脚本可能带副作用）⇒ 那种写法的路径本身通常
# 仍会经过 `config.OUT` 或字面量 `tools/out`，落在本扫查里；不追 `getattr`/`eval`/
# 子进程这类动态写法；不判 `_invoke(...)` 内部写到哪儿。
#
# ⚠️ **F8（t103 实测的反例，2026-09-25 改准）**：白名单**只给「看得见」的历史命中**留出口
# （"看得见但决定先留着"）。**看不见的写法加白名单没用**：那种写法命中 0 条 ⇒ 条目会被判
# 「已过期 ⇒ 删掉它们」而红 —— 这条语义由 `test_白名单开不了看不见的口子_F8` 钉住。
# 看不见的那几类（`getattr` / 子进程 / 跨模块封装 / `tools/probe/*` 脚本常量）只能**改代码
# 或扩判据**，不能靠白名单豁免。
#
# ⚠️ **「本文件内一跳 `return` 是跟的」**：`def _目标(): return config.OUT / "x"` 之后
# `_目标().write_text(...)` 会被点名（t103 的 F3）；**跨模块**的那种不跟（上面那条边界）。
#
# **文件集口径 = `rglob`**（现读 86 个 `.py`）：这条闸门守的是「**跑测试时**别写共享目录」，
# 与文件是否已提交**无关**（`tools/tests` 没被 `.gitignore` 忽略；`git ls-files` 口径 82，
# 差 4 个是当时未入库的新用例）。⚠️ 这与本文件另一批规则（BOM/CRLF 等）走 `_受控文件()` 的
# `git ls-files` 口径是**两套**，别混用。
#
# 覆盖范围由**对抗集**钉住（t103 拿 12 种"偷写共享目录"的写法撞出来的结果）：
# 见 :data:`_对抗集` 与 `test_共享写者扫查接得住对抗集里的每一种形态`。
# 本文件级 `pytest.skip` 有 **2 处**（`:120`/`:122`，`_受控文件()` 的环境兜底、带
# `# pragma: no cover`），与本节无关；**本节新增 0 处**。


@dataclass(frozen=True, slots=True)
class _SharedWrite:
    """一处「往共享 `tools/out/**` 写固定名产物」的静态证据（中文名留给扫查函数，类名按同文件 `_Case`/`_Source` 的写法）。"""

    file: str
    line: int
    text: str

    def 描述(self) -> str:
        return f"{self.file}:{self.line}　{self.text}"


#: 写 / 删动作的方法名（属性调用形式）。`open` 单独判 —— 它的模式位在后面而不是方法名里。
_写动作: frozenset[str] = frozenset(
    {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rmdir",
        "touch",
        "rename",
        "replace",
        "rmtree",
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "move",
    }
)

#: `open` 的写模式字符（`w`=覆盖写、`a`=追加、`x`=独占创建、`+`=读写）。
_写模式 = "wax+"

#: 会**返回**共享路径的模块级函数：跨模块拿共享产物路径的入口（`t95` 那两行用的就是第一个）。
_共享来源: frozenset[tuple[str, str]] = frozenset(
    {
        ("snapshot", "list_snapshots"),
        ("snapshot", "snapshot_path"),
        ("verify", "latest_compact_snapshot_path"),
    }
)

#: 白名单：**文件相对路径 → 为什么允许它留在盘上**。现读为空。
#:
#: 两种用法：① 这条扫查看不穿的间接写法（历史条目，必须写明理由）；② 故意放进去当
#: 反证样本的文件（例如将来某个用来测解析器的"坏语法"样本）。**条目一旦不再命中就必须删掉**
#: （见 :func:`test_没有用例往共享产物目录写固定名文件` 末尾的自清断言）——
#: 留着它就会变成"永久豁免"的暗门。
_共享写者白名单: dict[str, str] = {}

#: 扫查范围的下限（元测试用）：`tools/tests/` 下现在的 `.py` 文件数远不止这些，
#: 目录改名或 rglob 写错时这条会红，而不是"扫了 0 个文件、永远通过"。
_扫查最少文件数 = 50


@functools.cache
def _模块常量是共享的(模块: str, 常量: str) -> bool:
    """`<模块>.<常量>` 是不是一个落在 `config.OUT` 之下的 `Path`（如 `snapshot.SNAPSHOT_DIR`）。

    为什么真去 import 取一次值、而不是按名字猜：名字会漂（同一份东西在 `snapshot` /
    `mem_baseline` 里叫法不同），而**取值**不会撒谎。import 失败（依赖缺失等）就当"不是"，
    但那种情况另有闸门管（`mypy` / `pytest` 自己会红）。
    """
    try:
        module = importlib.import_module(f"pdx.{模块}")
    except Exception:  # pragma: no cover - pdx 包自己 import 不了时别处早就红了
        return False
    value = getattr(module, 常量, None)
    if not isinstance(value, Path):
        return False
    return value == config.OUT or config.OUT in value.parents


def _像共享目录片段(text: str) -> bool:
    """这段文本里有没有**连续的 `tools` / `out` 两段**（按路径分段比，**不是**子串比）。

    为什么分段：`"tools/output"` 含子串 `"tools/out"`，但它**不是**共享目录 —— 子串比会误报。
    覆盖两种真实写法：`"tools/out/mem/x"`（相对路径，开头就是）与
    `f"{config.REPO}/tools/out/auto/{name}"` 里那段字面量（前面带绝对路径）。t103 的 F1 就靠它。
    """
    段 = text.replace("\\", "/").split("/")
    return any(段[i] == "tools" and 段[i + 1] == "out" for i in range(len(段) - 1))


def _点号名(node: ast.AST) -> str | None:
    """把 `os.path.join` / `pathlib.Path` 这类点号链还原成字符串（还原不了给 `None`）。"""
    名字: list[str] = []
    cursor: ast.AST | None = node
    while isinstance(cursor, ast.Attribute):
        名字.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    名字.append(cursor.id)
    return ".".join(reversed(名字))


@dataclass(slots=True)
class _FileContext:
    """扫一个文件**之前**从它自己的 AST 里现读出来的三张小表（t103 的 F3/F7 靠它们）。

    * `模块别名`：`import pdx.snapshot as snap` ⇒ `{"snap": "snapshot"}`（`snap.SNAPSHOT_DIR` 认得出来）；
    * `常量别名`：`from pdx.snapshot import SNAPSHOT_DIR as SD` ⇒ `{"SD": ("snapshot", "SNAPSHOT_DIR")}`；
    * `本地共享函数`：`def _目标(): return config.OUT / "mem" / "t.txt"` ⇒ `{"_目标"}` ——
      **只跟本文件内一跳 `return`**；跨模块封装仍然看不见（见本节「刻意不做的事」）。
    """

    模块别名: dict[str, str] = field(default_factory=dict)
    常量别名: dict[str, tuple[str, str]] = field(default_factory=dict)
    本地共享函数: set[str] = field(default_factory=set)


def _读上下文(tree: ast.AST) -> _FileContext:
    """从 AST 现读别名表与「本文件内的共享来源」（顺序：先收别名，再拿它去认 helper 的 `return`）。"""
    ctx = _FileContext()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name.startswith("pdx."):
                    ctx.模块别名[alias.asname] = alias.name.removeprefix("pdx.")
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pdx."):
            模块 = node.module.removeprefix("pdx.")
            for alias in node.names:
                if alias.name != "*":
                    ctx.常量别名[alias.asname or alias.name] = (模块, alias.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Return)
                    and sub.value is not None
                    and _是共享路径(sub.value, ctx)
                ):
                    ctx.本地共享函数.add(node.name)
                    break
    return ctx


#: 路径**构造器**的点号名 —— t103 的 F2（`os.path.join`）与 F6（`Path("tools","out",…)` 位置参数）
#: 都落在这一张表上。加新构造器 = 加一行。
_路径构造器: frozenset[str] = frozenset(
    {"os.path.join", "Path", "pathlib.Path", "PurePath", "pathlib.PurePath"}
)


def _段里有共享目录(段: list[str | None]) -> bool:
    """这些**按顺序**的路径段里，有没有**相邻的 `tools` → `out`** 两段。

    分段比而不是子串比：`"tools/output"` 含子串 `"tools/out"` 但不是共享目录。
    `None`（链上某段不是字面量）会**打断相邻性** —— 宁可漏，也不把
    `a / "tools" / b / "out"` 这种拼出来的东西当成共享。
    """
    return any(段[i] == "tools" and 段[i + 1] == "out" for i in range(len(段) - 1))


def _路径段(node: ast.AST) -> list[str | None]:
    """把一条 `/` 链摊成**按顺序的段**：字面量给字符串、非字面量给 `None`。

    ⚠️ 为什么要连**头部构造器**一起看（t106 的 R1 回归）：`Path("tools") / "out" / "x.json"`
    这条链里，`"tools"` 段在**头部的 `Path("tools")` 调用**里、不在链上 —— 只看链尾巴
    （`"out/x.json"`）就认不出「连续的 tools/out」，于是这条**最短、最自然**的写法反而不报。
    t103 那一版认的是"尾巴以 `out/` 开头"，所以抓得住；t105 把判据收窄成"必须有相邻两段"
    时把它挤掉了。⇒ 头部是路径构造器时，把它的**字符串实参**也当段（t109 修回）。
    """
    尾巴: list[str | None] = []
    cursor = node
    while isinstance(cursor, ast.BinOp) and isinstance(cursor.op, ast.Div):
        right = cursor.right
        尾巴.append(
            right.value
            if isinstance(right, ast.Constant) and isinstance(right.value, str)
            else None
        )
        cursor = cursor.left
    尾巴.reverse()
    if isinstance(cursor, ast.Constant) and isinstance(cursor.value, str):
        头部: list[str | None] = [cursor.value]
    elif isinstance(cursor, ast.Call) and _点号名(cursor.func) in _路径构造器:
        头部 = [
            arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
            for arg in cursor.args
        ]
    else:
        头部 = [None]  # 已知基（config.REPO / Path.cwd()）或别的表达式：不给字面量段
    return [*头部, *尾巴]


def _是共享路径(
    node: ast.AST, ctx: _FileContext | None = None, 是共享: Callable[[ast.AST], bool] | None = None
) -> bool:
    """这个表达式是不是「共享产物目录下的东西」。

    认的形态（t103 的对抗集逐条钉在 :data:`_对抗集` 里）：
    共享根（`config.OUT` / `<模块>.<常量>`，含 `import pdx.x as y` 与 `from pdx.x import C as D` 两种别名）/
    共享路径的 `glob` 结果 / `_共享来源` 调用 / **f-string 拼出来**的路径 /
    `os.path.join(...)` 与 `Path(..., ...)` / **本文件内** helper 的返回值 /
    文本里含连续 `tools`/`out` 两段的字面量与 `a / "b"` 链（**含头部是 `Path("tools")` 的裸字面量链**，
    t106 的 R1 回归就出在这一条上）。

    ``是共享`` 是**带传播的**判据（`_扫共享写入` 里那个 `算共享`）：传进来之后，构造器的
    **实参**里出现「已经算共享的名字」也认得出（`pathlib.Path(target)` 这种，t103 的 F1 就卡在这）。
    不传就退化成「只看字面形态」（`_读上下文` 那条路用得上）。
    """
    ctx = ctx or _FileContext()
    是共享 = 是共享 or (lambda item: _是共享路径(item, ctx))
    if isinstance(node, ast.Name):
        if node.id in ctx.本地共享函数:
            return True
        绑定 = ctx.常量别名.get(node.id)
        return 绑定 is not None and _模块常量是共享的(*绑定)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "config" and node.attr == "OUT":
            return True
        return _模块常量是共享的(ctx.模块别名.get(node.value.id, node.value.id), node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if _是共享路径(node.left, ctx, 是共享) or _是共享路径(node.right, ctx, 是共享):
            return True
        # 识别 `config.REPO / "tools" / "out" / …` 与 `Path("tools") / "out" / …` 两条路：
        # 后者靠 `_路径段` 把**头部构造器的字符串实参**也算进来（t106 的 R1）。
        return _段里有共享目录(_路径段(node))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _像共享目录片段(node.value)
    if isinstance(node, ast.JoinedStr):
        # F1：f-string 拼路径 —— 只看**字面量片段**（插值部分另算：它是「另一半判据」的事）
        字面量 = "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
        return _像共享目录片段(字面量)
    if isinstance(node, ast.Call):
        return _调用返回共享路径(node, ctx, 是共享)
    return False


def _调用返回共享路径(
    node: ast.Call, ctx: _FileContext, 是共享: Callable[[ast.AST], bool] | None = None
) -> bool:
    """一次调用会不会**返回**共享路径（构造器 / `glob` 结果 / 共享来源 / 本文件内 helper）。"""
    是共享 = 是共享 or (lambda item: _是共享路径(item, ctx))
    func = node.func
    if _点号名(func) in _路径构造器:
        # F2 / F6：构造器 —— 实参里有共享的，或**字符串实参拼出来**带 tools/out 两段。
        # 为什么不要求"参数全是常量"：真实写法常把前缀与常量混着传
        # （`os.path.join(config.REPO, "tools", "out", "auto", "f.png")`）。
        if any(是共享(arg) for arg in node.args):
            return True
        字面量段 = "/".join(
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        )
        return _像共享目录片段(字面量段)
    if isinstance(func, ast.Attribute):
        if func.attr in {"glob", "rglob", "iterdir"}:
            return _是共享路径(func.value, ctx, 是共享)
        if isinstance(func.value, ast.Name):
            模块 = ctx.模块别名.get(func.value.id, func.value.id)
            if (模块, func.attr) in _共享来源:
                return True
    if isinstance(func, ast.Name):
        if func.id in ctx.本地共享函数:
            return True
        if func.id in {"map", "filter"}:
            # F4 的第二种变体：`map(f, <共享目录的迭代物>)` ⇒ 结果的每个元素都是共享路径
            return any(是共享(arg) for arg in node.args)
    return False


def _扫共享写入(root: Path) -> list[_SharedWrite]:
    """扫 `root` 下每个 `.py`，报出**往共享 `tools/out/**` 写固定名产物**的地方（静态、不执行）。

    做法三步：① 现读本文件的别名表与「本文件内的共享来源」（:func:`_读上下文`）；
    ② 按「赋值 / 循环 / **推导式** / **`map`/`filter` 的 lambda 形参**」传播到不动点
    （`:func:`_是共享路径` 为真，或来自一个已经算共享的名字）；③ 检查写/删动作的**接收者与全部实参**
    是不是共享。t103 的对抗集（:data:`_对抗集`）逐形态钉住这套判据的覆盖范围。
    """
    命中: list[_SharedWrite] = []
    for path in sorted(root.rglob("*.py")):
        rel = _相对路径(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # 解析不了 ⇒ 这条扫查**看不见**它里面的写入。静默跳过就等于给自己开暗门。
            命中.append(
                _SharedWrite(
                    file=rel, line=1, text=f"解析失败（{type(exc).__name__}）—— 这条扫查看不见它"
                )
            )
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        ctx = _读上下文(tree)
        共享名字: set[str] = set()

        def 算共享(node: ast.AST, _names: set[str] = 共享名字, _ctx: _FileContext = ctx) -> bool:
            # `_names` / `_ctx` 用默认参数绑住**同一个对象**（B023：闭包对循环里定义的名字晚绑定）；
            # 传播阶段往集合里 `add` 的改动仍然看得见 —— 绑的是对象，不是快照。
            if isinstance(node, ast.Name):
                return node.id in _names or _是共享路径(node, _ctx)
            if _是共享路径(node, _ctx, 算共享):
                # 含 `config.REPO / "tools" / "out" …` 这类**字面量拼出来**的路径：它的叶子
                # 是 `config.REPO`（本身不共享），共享性在整条链的尾巴上 ⇒ 必须先整体判一次。
                return True
            if isinstance(node, ast.BinOp):
                return 算共享(node.left) or 算共享(node.right)
            if isinstance(node, ast.Call):
                # `paths = (共享目录).glob(...)` 再 `for p in paths:` ⇒ 名字也要算共享
                return _调用返回共享路径(node, _ctx, 算共享)
            return False

        def 待绑定(tree: ast.AST) -> list[tuple[list[ast.AST], ast.AST]]:
            """把「谁会被绑成共享名字」的候选找齐（赋值 / 循环 / **推导式** / **`map`/`filter` 的 lambda 形参**）。"""
            候选: list[tuple[list[ast.AST], ast.AST]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    候选.append((list(node.targets), node.value))
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    候选.append(([node.target], node.value))
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    候选.append(([node.target], node.iter))
                elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                    # F4 的第一种变体：`[p.unlink() for p in snapshot.list_snapshots()]`
                    候选.extend(([comp.target], comp.iter) for comp in node.generators)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"map", "filter"}
                ):
                    # F4 的第二种变体：`map(lambda q: q.unlink(), snapshot.list_snapshots())`
                    for arg in node.args:
                        if not isinstance(arg, ast.Lambda):
                            continue
                        共享实参 = [
                            other for other in node.args if other is not arg and 算共享(other)
                        ]
                        if 共享实参:
                            候选.append((list(arg.args.args), 共享实参[0]))
            return 候选

        # 传播到不动点：`paths = snapshot.list_snapshots()` → `for p in paths:` → `p.unlink(...)`
        for _ in range(8):
            增长 = False
            for targets, value in 待绑定(tree):
                if not 算共享(value):
                    continue
                for target in targets:
                    # 名字有两种形状：赋值 / 循环 / 推导式里是 `ast.Name`，**lambda 形参是 `ast.arg`**
                    # （F4b 就卡在这里：只认 `Name` 的话 `map(lambda q: …)` 的 `q` 永远绑不上）。
                    名字 = target.id if isinstance(target, ast.Name) else None
                    if 名字 is None and isinstance(target, ast.arg):
                        名字 = target.arg
                    if 名字 is not None and 名字 not in 共享名字:
                        共享名字.add(名字)
                        增长 = True
            if not 增长:
                break

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            动作 = func.attr if isinstance(func, ast.Attribute) else ""
            # ① 方法形式的写/删：接收者**或任意一个实参**是共享的就算（F5：`shutil.move(src, dst)`
            #    的共享路径在**第 2 个**参数上）。检查全部实参与了 F5 与"源在共享、目标在别处"
            #    的保守取向：后者其实只是**从**共享读，但宁多报不放过（必要时写白名单）。
            if 动作 in _写动作:
                receiver = func.value if isinstance(func, ast.Attribute) else None
                实参 = [*([receiver] if receiver is not None else []), *node.args]
                实参 += [kw.value for kw in node.keywords]
                if any(算共享(item) for item in 实参):
                    命中.append(_SharedWrite(rel, node.lineno, lines[node.lineno - 1].strip()))
                    continue
            # ② 写模式的 open：内建 `open(path, "w")` 与 `Path.open("w")`
            if 动作 == "open" and node.args:
                mode = node.args[0]
                if (
                    isinstance(mode, ast.Constant)
                    and isinstance(mode.value, str)
                    and any(c in mode.value for c in _写模式)
                ):
                    receiver = func.value if isinstance(func, ast.Attribute) else None
                    if receiver is not None and 算共享(receiver):
                        命中.append(_SharedWrite(rel, node.lineno, lines[node.lineno - 1].strip()))
            elif isinstance(func, ast.Name) and func.id == "open" and len(node.args) > 1:
                mode = node.args[1]
                if (
                    isinstance(mode, ast.Constant)
                    and isinstance(mode.value, str)
                    and any(c in mode.value for c in _写模式)
                    and 算共享(node.args[0])
                ):
                    命中.append(_SharedWrite(rel, node.lineno, lines[node.lineno - 1].strip()))
    return 命中


def _白名单问题(命中: list[_SharedWrite], 白名单: dict[str, str]) -> str | None:
    """「该不该判红」拆成**纯函数**（``None`` = 放行）—— 两个方向都能用合成数据撞：

    * **未放行的命中** ⇒ 红（逐条点名到 `文件:行`，并给修法）；
    * **放行条目的文件已经没有命中**（它被修好了）⇒ 红，逼人删掉条目 —— 留着就是
      「永久豁免」的暗门；
    * 白名单为空、也没有命中 ⇒ 放行（**现读就是这一支**）。
    """
    未放行 = [item for item in 命中 if item.file not in 白名单]
    if 未放行:
        return (
            f"{len(未放行)} 处往共享产物目录写固定名文件（并行的第二个 pytest 进程会与它互相覆盖或互删，"
            "t95 实测：错峰 35 s 起两条并发 ⇒ 后一条报 `快照不存在 …cli-test-tmp.json`，exit 2）：\n  "
            + "\n  ".join(item.描述() for item in 未放行)
            + '\n修法：把产物隔离到 `tmp_path`（例：`monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)`）；'
            "确实必须留在共享目录的，写进 `_共享写者白名单` 并写明理由。"
        )
    过期的 = sorted(name for name in 白名单 if name not in {item.file for item in 命中})
    if 过期的:
        return (
            f"`_共享写者白名单` 这些条目已经过期（对应文件现在没有共享写入了）：{过期的} ⇒ 删掉它们"
        )
    return None


def test_没有用例往共享产物目录写固定名文件() -> None:
    """B116 的闸门：`tools/tests/**` 里不许有往共享 `tools/out/**` 写固定名产物的写者。

    为什么是**固定名**：并行（`-n auto`）或同一台机器上第二个 pytest 进程会让两条用例
    撞在同一个文件名上；产物写进 `tmp_path`（每个 worker 一份、每个用例一份）就没有这个问题。
    """
    root = config.REPO / "tools" / "tests"
    文件数 = len(list(root.rglob("*.py")))
    assert 文件数 >= _扫查最少文件数, f"只扫到 {文件数} 个用例文件 —— 扫查范围多半失效了"
    问题 = _白名单问题(_扫共享写入(root), _共享写者白名单)
    assert 问题 is None, 问题


def test_共享写者白名单机制_两个方向都被撞到() -> None:
    """白名单机制本身要**可执行**地测到（现读它为空 ⇒ 真盘上只覆盖了「空表放行」这一支）。

    合成三撞：① 命中但没放行 ⇒ 红且点名到 `文件:行`；② 命中且已写明理由放行 ⇒ 绿；
    ③ 放行的文件已经不再命中 ⇒ 红（自清：留着就是永久豁免的暗门）。
    """
    条目 = _SharedWrite(file="tools/tests/test_合成.py", line=7, text="p.unlink(missing_ok=True)")

    未放行 = _白名单问题([条目], {})
    assert 未放行 is not None, "命中且没放行时必须判红"
    assert "test_合成.py:7" in 未放行, "判红要点名到文件:行"
    assert "tmp_path" in 未放行, "判红要给修法"

    assert _白名单问题([条目], {条目.file: "历史条目：正在迁"}) is None, (
        "已经写明理由放行的条目不该再判红"
    )
    过期 = _白名单问题([], {条目.file: "历史条目：正在迁"})
    assert 过期 is not None, "白名单条目不再命中时必须判红（自清）"
    assert "过期" in 过期
    assert _白名单问题([], {}) is None, "空表 + 无命中 = 放行（现读就是这一支）"


#: 阴性对照用的一小段合成用例：**逐字照 `t95` 修前那两行的形状**写的
#: （固定 label + 建之前删一遍、`finally` 再删一遍 —— 出事那份文件就是这两处）。
_合成_共享写法 = """\
def test_合成_往共享目录写(monkeypatch):
    from pdx import snapshot

    label = "cli-test-tmp"
    for p in snapshot.list_snapshots():
        if p.stem.startswith(label):
            p.unlink(missing_ok=True)
    try:
        _invoke("snapshot", "create", "--label", label)
    finally:
        for p in snapshot.list_snapshots():
            if p.stem.startswith(label):
                p.unlink(missing_ok=True)
"""

#: 同一件事改成进程内隔离后的形状（写 `tmp_path`、常量也指过去）—— 必须判绿。
_合成_隔离写法 = """\
def test_合成_隔离到临时目录(tmp_path, monkeypatch):
    from pdx import snapshot

    monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
    label = "cli-test-tmp"
    (tmp_path / f"{label}.json").write_text("{}", encoding="utf-8", newline="\\n")
"""

#: 间接指向的几种写法（模块常量 / 拼出来的路径 / `glob` 结果 / `Path.open("w")`）。
_合成_间接写法 = """\
import json

from pdx import config, snapshot


def test_合成_间接写():
    out = snapshot.SNAPSHOT_DIR
    (out / "x.json").write_text(json.dumps({}), encoding="utf-8", newline="\\n")
    shared = config.REPO / "tools" / "out" / "auto"
    (shared / "frame.png").write_bytes(b"x")
    for item in (config.OUT / "evidence").glob("*.png"):
        item.unlink()
    with (config.OUT / "mem" / "t.txt").open("w", encoding="utf-8") as handle:
        handle.write("x")
"""


def test_共享写者扫查在合成用例上会红也会绿(tmp_path: Path) -> None:
    """阴性对照：合成一份"出事那两行"形状的用例 ⇒ **判红**；换成隔离写法 ⇒ **判绿**。

    只在 `tmp_path` 里造文件 —— **不动盘上任何既有用例**（B91：并行的用例只读仓库，
    要写就写临时副本）。没有这条对照，这条扫查就可能是"永远绿"的摆设。
    """
    样本 = tmp_path / "test_合成.py"
    样本.write_text(_合成_共享写法, encoding="utf-8", newline="\n")
    命中 = _扫共享写入(tmp_path)
    assert len(命中) >= 2, f"合成样本里那两处共享删除没被扫出来：{[i.描述() for i in 命中]}"
    assert any("unlink" in item.text for item in 命中), f"报的位置不对：{[i.描述() for i in 命中]}"

    样本.write_text(_合成_隔离写法, encoding="utf-8", newline="\n")
    assert _扫共享写入(tmp_path) == [], (
        f"隔离写法（写 tmp_path + 常量指过去）不该被报：{[i.描述() for i in _扫共享写入(tmp_path)]}"
    )


def test_共享写者扫查看得见间接写法(tmp_path: Path) -> None:
    """间接指向也要看得见：模块常量 / `config.REPO / "tools" / "out" …` / `glob` 结果 / `Path.open("w")`。"""
    样本 = tmp_path / "test_合成_间接.py"
    样本.write_text(_合成_间接写法, encoding="utf-8", newline="\n")
    命中 = _扫共享写入(tmp_path)
    文本 = "\n".join(item.text for item in 命中)
    for 期望 in ('out / "x.json"', 'shared / "frame.png"', "item.unlink()", 'open("w"'):
        assert 期望 in 文本, f"漏了间接写法 `{期望}`：\n{文本}"


#: t103 复核拿 12 种写法撞出来的**七种漏网形态**（F1–F7）+ 一条控制组，逐条钉在这里。
#:
#: 每条样本里"该被点名的那一行"带 `# ← 应命中` 标记 ⇒ 期望行号**从样本里现算**，
#: 样本加一行也不会漂（防的是"改了样本、判据悄悄失效"）。`应命中=False` 的是控制组
#: （隔离到 `tmp_path` 的写法必须判绿）。
_对抗集: tuple[tuple[str, str, bool], ...] = (
    (
        "F1_fstring拼绝对路径",
        """\
import pathlib

from pdx import config


def test_f1():
    name = "x.json"
    target = f"{config.REPO}/tools/out/auto/{name}"
    pathlib.Path(target).write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "F1b_fstring拼相对路径",
        """\
from pathlib import Path


def test_f1b():
    name = "x"
    Path(f"tools/out/mem/{name}").write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "F2_os.path.join加内建open",
        """\
import os

from pdx import config


def test_f2():
    path = os.path.join(config.REPO, "tools", "out", "auto", "f.png")
    with open(path, "w", encoding="utf-8") as handle:  # ← 应命中
        handle.write("x")
""",
        True,
    ),
    (
        "F3_本文件内helper返回共享路径",
        """\
from pdx import config


def _目标():
    return config.OUT / "mem" / "t.txt"


def test_f3():
    _目标().write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "F4a_推导式里的循环变量",
        """\
from pdx import snapshot


def test_f4a():
    [p.unlink(missing_ok=True) for p in snapshot.list_snapshots()]  # ← 应命中
""",
        True,
    ),
    (
        "F4b_map的lambda形参",
        """\
from pdx import snapshot


def test_f4b():
    list(map(lambda q: q.unlink(), snapshot.list_snapshots()))  # ← 应命中
""",
        True,
    ),
    (
        "F5_shutil.move的目标在第2参",
        """\
import shutil

from pdx import config


def test_f5(tmp_path):
    shutil.move(str(tmp_path / "a.png"), config.OUT / "evidence" / "a.png")  # ← 应命中
""",
        True,
    ),
    (
        "F6_Path位置参数",
        """\
from pathlib import Path


def test_f6():
    p = Path("tools", "out", "auto", "x.json")
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "F7_别名导入的常量",
        """\
from pdx.snapshot import SNAPSHOT_DIR as SD


def test_f7():
    (SD / "cli-test-tmp.json").write_text("{}", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "控制组_隔离到tmp_path不该被报",
        """\
def test_控制组(tmp_path, monkeypatch):
    from pdx import snapshot

    monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")  # ← 应命中
""",
        False,
    ),
)


@pytest.mark.parametrize(
    ("形态", "样本", "应命中"), _对抗集, ids=[形态 for 形态, _样本, _期望 in _对抗集]
)
def test_共享写者扫查接得住对抗集里的每一种形态(
    tmp_path: Path, 形态: str, 样本: str, 应命中: bool
) -> None:
    """t103 撞出来的每一种漏网形态都要**在合成用例上命中并点名到 `文件:行`**。

    这条是防复发的：只要哪一次改动让某种形态重新隐形，这里立刻红，而且红在**形态名**上。
    """
    (tmp_path / "test_合成_对抗.py").write_text(样本, encoding="utf-8", newline="\n")
    命中 = _扫共享写入(tmp_path)
    标记行 = [i for i, line in enumerate(样本.splitlines(), start=1) if "← 应命中" in line]
    assert len(标记行) == 1, f"{形态}：样本里应当恰好一处 `← 应命中` 标记，实得 {标记行}"
    if 应命中:
        assert any(item.line == 标记行[0] for item in 命中), (
            f"{形态}（t103 的漏网形态）没被扫出来、或行号不对："
            f"期望 `test_合成_对抗.py:{标记行[0]}`；实得 {[item.描述() for item in 命中]}"
        )
    else:
        assert 命中 == [], f"{形态} 是控制组，不该被报：{[item.描述() for item in 命中]}"


#: F8 用到的**看不见的写法**：产物是在**别的模块/子进程**里写的（`t95` 那次的真实形状 ——
#: 经 `_invoke("snapshot", "create", …)` 写共享目录）。它在 docstring 的边界里，本扫查看不见。
_看不见的写法 = """\
def test_看不见的写者():
    _invoke("snapshot", "create", "--label", "cli-test-tmp")
"""


def test_白名单开不了看不见的口子_F8(tmp_path: Path) -> None:
    """F8：白名单只能原谅**看得见**的命中；对"看不见的写者"，加条目会立刻判「已过期」。

    t103 实测反了旧 docstring 那句话（"白名单给看不穿的条目留出口"）：把看不见的写者写进
    白名单 ⇒ `_白名单问题` 立刻报「已过期 ⇒ 删掉它们」。⇒ 文档已改准，这条用例把语义钉住：
    谁想靠"加个白名单条目"豁免看不见的写法，**这条路走不通**（只能改代码或扩判据）。
    """
    (tmp_path / "test_合成_看不见.py").write_text(_看不见的写法, encoding="utf-8", newline="\n")
    命中 = _扫共享写入(tmp_path)
    assert 命中 == [], f"前提是「看不见的写者」，这里却命中了：{[item.描述() for item in 命中]}"

    问题 = _白名单问题(命中, {"test_合成_看不见.py": "想让这条豁免"})
    assert 问题 is not None, "看不见的写者加白名单必须判红 —— 白名单开不了这个口子"
    assert "过期" in 问题, f"红的理由应当是「已过期」，实得：{问题}"


def _跑合成样本(tmp_path: Path, 样本: str) -> list[_SharedWrite]:
    """把一段合成用例写进 `tmp_path` 再跑扫查（**不碰盘上任何既有用例**）。"""
    (tmp_path / "test_合成.py").write_text(样本, encoding="utf-8", newline="\n")
    return _扫共享写入(tmp_path)


def _标记行(样本: str, 标记: str) -> list[int]:
    return [i for i, line in enumerate(样本.splitlines(), start=1) if 标记 in line]


#: **回归守卫**（t106 的 R1，2026-09-25 补）：`t103` §2 判「**抓住**」的四种形状。
#:
#: 为什么单列一个集合：`t105` 收那 7 种漏网形态时**把 ① 裸字面量链挤掉了** ——
#: 因为新对抗集只钉了「我判漏掉的 7 种」，**没钉「已经抓住的 4 种」**，回归就没有守卫。
#: 命名与「新增应命中」那批（:data:`_对抗集` / `test_共享写者扫查接得住对抗集里的每一种形态`）
#: **刻意分开**：`test_回归_*` = 既有应命中；`test_共享写者扫查接得住…[F…]` = 新增应命中。
_回归集: tuple[tuple[str, str], ...] = (
    (
        "①分步拼字面量链",
        """\
from pathlib import Path


def test_一():
    p = Path("tools") / "out" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
    ),
    (
        "⑤a_t95出事那两行",
        """\
from pdx import snapshot


def test_五a():
    for p in snapshot.list_snapshots():
        p.unlink(missing_ok=True)  # ← 应命中
""",
    ),
    (
        "⑥a_rmtree共享目录",
        """\
import shutil

from pdx import config


def test_六a():
    shutil.rmtree(config.OUT / "mem")  # ← 应命中
""",
    ),
    (
        "⑦_共享目录上开写模式",
        """\
from pdx import config


def test_七():
    with (config.OUT / "mem" / "t.txt").open("w", encoding="utf-8") as handle:  # ← 应命中
        handle.write("x")
""",
    ),
)


@pytest.mark.parametrize(("形状", "样本"), _回归集, ids=[形状 for 形状, _样本 in _回归集])
def test_回归_t103判抓住的四种形状仍然命中(tmp_path: Path, 形状: str, 样本: str) -> None:
    """**既有应命中**的回归守卫：这四种在 `t103` 时被抓住，任何时候再漏掉就红。"""
    命中 = _跑合成样本(tmp_path, 样本)
    标记 = _标记行(样本, "← 应命中")
    assert len(标记) == 1, f"{形状}：样本里应当恰好一处 `← 应命中` 标记，实得 {标记}"
    assert any(item.line == 标记[0] for item in 命中), (
        f"{形状}（`t103` 判抓住；`t106` 的 R1 就是其中之一回归了）没被扫出来或行号不对："
        f"期望 `test_合成.py:{标记[0]}`；实得 {[item.描述() for item in 命中]}"
    )


#: `t106` §③ 的**六种边界探针**（A–F，全部**应当命中**）+ 一条**不得误报**的反例
#: （`tools/output` 这类含子串但不是共享目录的写法 —— 分段比、不是子串比）。
_探针集: tuple[tuple[str, str, bool], ...] = (
    (
        "A_原样分步链",
        """\
from pathlib import Path


def test_a():
    p = Path("tools") / "out" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "B_内联链",
        """\
from pathlib import Path


def test_b():
    (Path("tools") / "out" / "x.json").write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "C_pathlib.Path分步",
        """\
import pathlib


def test_c():
    p = pathlib.Path("tools") / "out" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "D_cwd起头",
        """\
from pathlib import Path


def test_d():
    p = Path.cwd() / "tools" / "out" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "E_只拼到tools_out再续",
        """\
from pathlib import Path


def test_e():
    base = Path("tools") / "out"
    (base / "x.json").write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "F_config.REPO起头",
        """\
from pdx import config


def test_f():
    p = config.REPO / "tools" / "out" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 应命中
""",
        True,
    ),
    (
        "N_反例_tools_output不得误报",
        """\
from pathlib import Path


def test_n():
    p = Path("tools") / "output" / "x.json"
    p.write_text("x", encoding="utf-8")  # ← 不应命中
    q = Path("not-tools/out/x.json")
    q.write_text("x", encoding="utf-8")  # ← 不应命中
""",
        False,
    ),
)


@pytest.mark.parametrize(
    ("探针", "样本", "应命中"), _探针集, ids=[探针 for 探针, _样本, _期望 in _探针集]
)
def test_探针_字面量链的六种边界形态(tmp_path: Path, 探针: str, 样本: str, 应命中: bool) -> None:
    """`t106` 的 A–F 六探针全部应命中；反例（`tools/output`）不得误报 —— **分段比，不是子串比**。"""
    命中 = _跑合成样本(tmp_path, 样本)
    if 应命中:
        标记 = _标记行(样本, "← 应命中")
        assert len(标记) == 1, f"{探针}：样本里应当恰好一处 `← 应命中` 标记，实得 {标记}"
        assert any(item.line == 标记[0] for item in 命中), (
            f"{探针} 没被扫出来或行号不对：期望 `test_合成.py:{标记[0]}`；"
            f"实得 {[item.描述() for item in 命中]}"
        )
    else:
        反例行 = _标记行(样本, "← 不应命中")
        assert len(反例行) == 2, f"{探针}：反例样本里应当有两处 `← 不应命中` 标记，实得 {反例行}"
        assert 命中 == [], (
            f"{探针}：含子串但不是共享目录的写法**不该**被报（分段比、不是子串比）："
            f"{[item.描述() for item in 命中]}"
        )


#: **有意保留的保守性**（t106 的 F5；队长 2026-09-25 裁决「可接受的保守、不是 finding」）。
#:
#: 写动作现在查**接收者与全部实参** ⇒ `shutil.copy(共享, tmp)` 这种「**从**共享读」也会被**多报**。
#: 三条理由（照抄裁决）：① 方向是**多报不是漏报** —— 不会放过任何一次真撞（`t95` 那次正是
#: **漏报**造成的）；② 误报**显式且可执行** —— 点名 `文件:行` 并给出 `tmp_path` / 白名单两条路；
#: ③ 真实树仍 **86 / 0**，不受污染。
#:
#: 为什么还要钉用例（B124 的**反向**情形）：**保留的行为也要有守卫** —— 否则将来有人
#: 「顺手改成只查目标实参」就会**悄悄丢掉**这条保守性。精确化（`copy*`/`move` 只查目标参数）
#: 是"精确化不是放宽"，今天**不做**；要做时这两条真命中用例必须一起绿。
_保守集: tuple[tuple[str, str, bool], ...] = (
    (
        "从共享拷到临时_保守多报",
        """\
import shutil

from pdx import config


def test_a(tmp_path):
    shutil.copy(config.OUT / "mem" / "baseline.json", tmp_path / "x.json")  # ← 应命中
""",
        True,
    ),
    (
        "从临时拷进共享_真命中",
        """\
import shutil

from pdx import config


def test_b(tmp_path):
    shutil.copy(tmp_path / "x.json", config.OUT / "mem" / "x.json")  # ← 应命中
""",
        True,
    ),
    (
        "两边都在临时_不该报",
        """\
import shutil


def test_c(tmp_path):
    shutil.copy(tmp_path / "a.json", tmp_path / "b.json")  # ← 不应命中
""",
        False,
    ),
    (
        "rmtree非共享路径_不该报",
        """\
import shutil


def test_d(tmp_path):
    shutil.rmtree(tmp_path / "out")  # ← 不应命中
""",
        False,
    ),
)


@pytest.mark.parametrize(
    ("探针", "样本", "应命中"), _保守集, ids=[探针 for 探针, _样本, _期望 in _保守集]
)
def test_保守_写动作查全部实参是有意保留的(
    tmp_path: Path, 探针: str, 样本: str, 应命中: bool
) -> None:
    """F5 的保守多报**有意保留**（三条理由见 :data:`_保守集` 上方）：钉住它，防"顺手收窄"。"""
    命中 = _跑合成样本(tmp_path, 样本)
    if 应命中:
        标记 = _标记行(样本, "← 应命中")
        assert len(标记) == 1, f"{探针}：样本里应当恰好一处 `← 应命中` 标记，实得 {标记}"
        assert any(item.line == 标记[0] for item in 命中), (
            f"{探针} 没被扫出来或行号不对（保守性被收窄了？）：期望 `test_合成.py:{标记[0]}`；"
            f"实得 {[item.描述() for item in 命中]}"
        )
    else:
        反例行 = _标记行(样本, "← 不应命中")
        assert len(反例行) == 1, f"{探针}：样本里应当恰好一处 `← 不应命中` 标记，实得 {反例行}"
        assert 命中 == [], f"{探针}：控制组不该被报：{[item.描述() for item in 命中]}"
