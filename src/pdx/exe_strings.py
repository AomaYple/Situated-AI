"""``victoria3.exe`` 的字符串开采：找出「引擎里有、脚本里没用」的标识符。

为什么有这个模块
--------------
``tools/README.md`` 的「已知边界」里写着本轮最值得做的下一步：
引擎二进制里有一批标识符从未在任何脚本里出现，那批词很可能包含**字段枚举与合法取值**。
但那句话里的两个数字（17,821 / 16,535）是**一次性采集值**：口径没记、脚本没留，
换一个游戏版本就没人能重算 —— 与 doc 04 §4.6 那个「682 行」是同一类问题。

所以这里把口径写成代码，五个问题一次答清楚：

* **扫的是什么**：``binaries/victoria3.exe`` 的**原始字节**里，连续 4 个以上
  可打印 ASCII 字符的串（PE 的字符串不会跨节对齐，所以直接扫字节即可，
  不引第三方反汇编库 —— 这一步只需要「有没有这个词」，不需要结构）；
* **算标识符的条件**：整串匹配 ``[A-Za-z_][A-Za-z0-9_]*``（去掉 ``.dll``、
  路径、错误消息这类含空格/符号的串）；
* **算「用过」的条件**：该标识符在 ``game`` 内容根的 ``.txt`` / ``.gui`` / ``.yml``
  里作为**词**出现过（同一套词法切分，避免 ``foo`` 命中 ``foobar``）；
* **给的是三个数**：``exe``（候选总数）、``unused``（未在脚本出现过的）、
  ``script``（脚本里出现过的标识符总数）；
* **怎么复算**：``v3 strings``（或本模块的三个函数）。

⚠️ **它不是断言，是线索**：未使用的标识符里混着编译器与 CRT 的符号
（``std``、``basic_string`` 之类）。判断「哪些是 PDX 字段名」需要人看 ——
这个模块负责把候选集**机械地**缩小到可以看的规模，而不是替人下结论。
"""

from __future__ import annotations

import re
from collections import deque
from functools import lru_cache
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from pathlib import Path

#: 可打印 ASCII 串（长度 ≥4）。4 是长度下界：3 个字符里噪音远多于线索。
_ASCII_RUN = re.compile(rb"[ -~]{4,}")

#: 标识符的形状（整串匹配，所以 `foo.dll` / `a b` 会被排除）。
_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")

#: 脚本侧的**词**切分（与标识符同一套字符类，避免子串误命中）。
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

#: 脚本侧要扫的扩展名。``.txt`` 是数据与脚本，``.gui`` 是界面，
#: ``.yml`` 是本地化（数据函数与键名都在里面）。
SCRIPT_SUFFIXES = (".txt", ".gui", ".yml")


def exe_path() -> Path:
    """``binaries/victoria3.exe``（安装根经 :mod:`pdx.config` 解析，不写死盘符）。"""
    return config.ROOT / "binaries" / "victoria3.exe"


@lru_cache(maxsize=1)
def exe_identifiers() -> frozenset[str]:
    """exe 里全部**标识符形状**的 ASCII 串（去重）。

    实测 1.14.3：97.3 MB 的 exe 里 125 万个 ASCII 串、**55,143** 个标识符形状。
    文件不存在时返回空集合（CI 上没有游戏本体，这条路径不该炸）。
    """
    path = exe_path()
    if not path.is_file():
        return frozenset()
    data = path.read_bytes()
    return frozenset(
        s.decode("ascii") for s in _ASCII_RUN.findall(data) if _IDENTIFIER.fullmatch(s)
    )


def _script_texts() -> Iterator[str]:
    base = config.GAME
    if not base.is_dir():
        return
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        if path.suffix not in SCRIPT_SUFFIXES:
            continue
        try:
            yield path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue


@lru_cache(maxsize=1)
def script_identifiers() -> frozenset[str]:
    """``game`` 内容根里 ``.txt`` / ``.gui`` / ``.yml`` 出现过的**词**（去重）。"""
    words: set[str] = set()
    for text in _script_texts():
        words.update(_WORD.findall(text))
    return frozenset(words)


@lru_cache(maxsize=1)
def identifier_stats() -> dict[str, int]:
    """``{exe, script, unused}`` —— exe 候选数、脚本词数、以及两者之差。

    实测 1.14.3：``exe = 55,143`` / ``script = 190,434`` / ``unused = 31,334``。

    ⚠️ 与 ``tools/README.md`` 里那句历史采集值（17,821 / 16,535）**口径不同**：
    那两个数来自一次没留脚本的采集，已无法复现，也不能与新口径直接比较。
    正文引用数字时应说明用的是哪一套（本模块这一套可随时重算）。
    """
    exe = exe_identifiers()
    script = script_identifiers()
    return {"exe": len(exe), "script": len(script), "unused": len(exe - script)}


def unused_identifiers() -> list[str]:
    """未在脚本里出现过的标识符（升序）—— 人工翻看用。"""
    return sorted(exe_identifiers() - script_identifiers())


def match_identifiers(needle: str, *, limit: int = 40) -> list[str]:
    """exe 标识符里**含** ``needle`` 的那些（大小写不敏感，升序）。

    用来查「引擎里有哪一族同名字段」：``--exe-grep scripted`` 会给出
    ``jomini_scripted_list_templates`` / ``scripted_effect`` /
    ``scripted_button_cooldowns`` 之类 —— 这正是 doc 04 §13 里
    「调用语法是什么」这类问题的**引擎侧线索**。

    ``limit=0`` 表示不截断（要真实条数时用它，例如 ``*_cw_duplicate_compat`` 那一族）。
    ⚠️ 早先 ``v3 evidence --exe-grep`` 把条数印成 `len(hits)`，而 hits 是**截断后**的
    40 条 —— 于是文档里的「161 个」用那条命令复算不出来。现在由调用方传 ``limit=0``。
    """
    low = needle.lower()
    hits = sorted(i for i in exe_identifiers() if low in i.lower())
    return hits if limit <= 0 else hits[:limit]


def identifier_neighbors(
    keys: Collection[str], *, span: int = 8
) -> dict[str, list[tuple[str, ...]]]:
    """每个键在 exe 字节流里的**邻近标识符**（前后各 ``span`` 个）。

    为什么需要它
    ----------
    :func:`exe_identifiers` 返回的是 ``frozenset`` —— 顺序丢了。而 PE 里的
    字符串常量**按数据表聚集**：一个字段名旁边往往就是同一张表的其它字段名。
    于是「这个键有哪些兄弟键」这个问题可以变成一次字节扫描。

    ⚠️ 依然是**线索不是结论**：邻居里混着同节的无关字面量（版本号、编译器符号）。
    中心词本身不在 exe 里时返回空列表。

    一次扫描处理全部 ``keys``（97 MB 只读一遍）。
    """
    wanted = {k for k in keys if k.isascii() and k}
    out: dict[str, list[tuple[str, ...]]] = {k: [] for k in wanted}
    if not wanted or span <= 0:
        return out
    path = exe_path()
    if not path.is_file():
        return out

    data = path.read_bytes()
    window: deque[str] = deque(maxlen=span)
    pending: tuple[str, deque[str]] | None = None  # 命中后正在收集的后继
    for raw in _ASCII_RUN.finditer(data):
        if not _IDENTIFIER.fullmatch(raw.group()):
            continue
        word = raw.group().decode("ascii")
        if pending is not None:
            key, after = pending
            after.append(word)
            if len(after) >= span:
                out[key].append(tuple(after))
                pending = None
        elif word in wanted:
            out[word].append(tuple(window))
            pending = (word, deque())
        window.append(word)

    # 收尾：文件末尾附近命中、后继没凑满 span 的那一次
    if pending is not None:
        key, after = pending
        if after:
            out[key].append(tuple(after))
    return out


def identifier_families(
    *, by: str = "suffix", min_size: int = 5, limit: int = 30
) -> list[tuple[str, list[str]]]:
    """把**未在脚本里出现过**的标识符按「同后缀 / 同前缀」聚成族。

    为什么按族看：31,334 个未使用标识符里绝大多数是编译器与 CRT 符号，
    逐个看没有意义；而 PDX 自己的字段名往往**成族出现** ——
    实测 ``*_cw_duplicate_compat`` 一族有 161 个成员，一眼就能看出
    「引擎里有一张按键名配置的重名策略表」（doc 04 §12.4 的证据就是这么来的）。

    * ``by="suffix"``：按最后一个 ``_`` 之后的部分聚（找 ``_compat`` / ``_cmd`` 这类）；
    * ``by="prefix"``：按第一个 ``_`` 之前的部分聚（找 ``code_`` / ``get_`` 这类）。

    只保留成员数 ≥ ``min_size``、族名长度 ≥ 3 的族，按成员数降序。
    ⚠️ **线索不是结论**：族里混着同节的无关字面量，哪些是 PDX 字段名要人看。
    """
    if by not in {"suffix", "prefix"}:
        raise ValueError("by 只能是 'suffix' 或 'prefix'")

    groups: dict[str, list[str]] = {}
    for name in unused_identifiers():
        parts = name.split("_")
        if len(parts) < 2:
            continue
        token = parts[-1] if by == "suffix" else parts[0]
        if len(token) < 3:
            continue
        groups.setdefault(token, []).append(name)
    picked = [(token, sorted(names)) for token, names in groups.items() if len(names) >= min_size]
    picked.sort(key=lambda item: (-len(item[1]), item[0]))
    return picked[:limit]


__all__ = [
    "SCRIPT_SUFFIXES",
    "exe_identifiers",
    "exe_path",
    "identifier_families",
    "identifier_neighbors",
    "identifier_stats",
    "match_identifiers",
    "script_identifiers",
    "unused_identifiers",
]
