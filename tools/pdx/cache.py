"""解析缓存。

动机
----
剖析发现全量分析 78.8 秒里有 **41 秒是纯浪费** —— ``vanilla_prefix_count``
把整个游戏树又解析了一遍，而 ``game_analysis`` 刚刚才解析过。
mod 分析同理：多个 mod 覆盖同一个原版文件时，那个文件会被反复解析。

正确性不受影响：缓存只按**文件路径**做记忆化。若源文件在运行期被修改，
需要显式 :func:`clear` —— 本工具链的使用场景是「读一次、算多次」，
不存在边写边读的情形。

线程安全：CPython 的 dict 读写是原子的，且本工具链不做并发写缓存，
因此不加锁。
"""

from __future__ import annotations

from pathlib import Path

from .model import ParsedFile
from .parser import parse_file as _parse_file

_CACHE: dict[str, ParsedFile] = {}
_HITS = 0
_MISSES = 0


def parse_cached(path: str | Path) -> ParsedFile:
    """解析文件，带记忆化。同一路径只真正解析一次。"""
    global _HITS, _MISSES
    key = str(path)
    hit = _CACHE.get(key)
    if hit is not None:
        _HITS += 1
        return hit
    _MISSES += 1
    result = _parse_file(key)
    _CACHE[key] = result
    return result


def get(path: str | Path) -> ParsedFile | None:
    """只查缓存，不触发解析。"""
    return _CACHE.get(str(path))


def put(path: str | Path, parsed: ParsedFile) -> None:
    _CACHE[str(path)] = parsed


def clear() -> None:
    global _HITS, _MISSES
    _CACHE.clear()
    _HITS = _MISSES = 0


def stats() -> dict[str, int]:
    return {"条目": len(_CACHE), "命中": _HITS, "未命中": _MISSES}
