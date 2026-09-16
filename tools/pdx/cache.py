"""解析缓存。

动机
----
剖析发现全量分析里有大量时间是**纯浪费** —— ``vanilla_prefix_count``
把整个游戏树又解析了一遍，而 ``game_analysis`` 刚刚才解析过。
mod 分析同理：多个 mod 覆盖同一个原版文件时，那个文件会被反复解析。

实现
----
直接用标准库的 :func:`functools.lru_cache`，不自己维护字典：

* 命中率统计由 ``cache_info()`` 提供，与 :func:`stats` 的三个字段一一对应
* 线程安全由 ``lru_cache`` 内部的锁保证（手写版只靠「dict 读写是原子的」，
  这个理由在多步读改写时不成立）
* ``maxsize=None`` 表示不淘汰 —— 与手写版行为一致。若将来内存吃紧，
  换成有限值即可获得 LRU 淘汰能力，手写版没有

正确性
------
缓存只按**文件路径**做记忆化。若源文件在运行期被修改，需要显式
:func:`clear` —— 本工具链的使用场景是「读一次、算多次」，
不存在边写边读的情形。
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from .parser import parse_file as _parse_file

if TYPE_CHECKING:
    from pathlib import Path

    from .model import ParsedFile


@cache
def _parse_by_key(key: str) -> ParsedFile:
    """真正干活的那一层。键必须是 ``str`` —— ``Path`` 与 ``str`` 会算成两条。

    单独抽一层的原因：``lru_cache`` 按**实参**做键，若直接装饰
    ``parse_cached``，``Path("a")`` 与 ``"a"`` 会各缓存一份，
    白白解析两次（实测确实如此）。统一在入口处 ``str()`` 化即可避免。
    """
    return _parse_file(key)


def parse_cached(path: str | Path) -> ParsedFile:
    """解析文件，带记忆化。同一路径只真正解析一次。"""
    return _parse_by_key(str(path))


def clear() -> None:
    """清空缓存并重置统计。"""
    _parse_by_key.cache_clear()


def stats() -> dict[str, int]:
    """缓存统计。字段名保持历史口径，避免调用方与文档大改。"""
    info = _parse_by_key.cache_info()
    return {
        "条目": info.currsize,
        "命中": info.hits,
        "未命中": info.misses,
    }
