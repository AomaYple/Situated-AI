"""看守 ``research/official-docs/`` —— 游戏自带官方 ``.md`` 的逐字镜像。

为什么需要这个测试
------------------
镜像的**时效性不是自动的**。游戏升级会就地改写这些 ``.md``，而镜像仍是旧版，
两者会安静地漂移。真实踩过一次：``common/treaty_articles/treaty_articles.md``
镜像停在 1.14.2（25,364 B / 604 行），1.14.3 本体已增至 28,171 B / 648 行，
新增的 ``scope:other_country``、``requirement_to_maintain`` 等规则镜像里没有 ——
**照镜像写条约 mod 会漏掉这些规则**，而当时没有任何断言会响。

所以这里钉三件事：篇目集合一致、逐字节一致、镜像里没有多余文件。
游戏不在本机的环境会自动跳过（``integration`` 标记由 conftest 处理）。

键的形态
--------
两边都用 ``<内容根>/<相对路径>``（正斜杠），例如
``game/common/treaty_articles/treaty_articles.md`` ——
``ga.official_docs`` 就是按这个口径产出的（见 :func:`pdx.analyze.game_analysis`）。

镜像过期时怎么办
----------------
重新镜像即可，保留原始相对路径::

    Copy-Item "<安装根>\\game\\common\\x\\x.md" "research\\official-docs\\game\\common\\x\\x.md"

然后同步更新 ``docs/victoria3-modding/07-官方文档索引.md`` 里的字节数/行数 ——
那些数字由 ``v3 verify`` 与文档一致性测试共同看守。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from pdx import analyze, config

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.regression,
    pytest.mark.docs,
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def 镜像文件() -> dict[str, Path]:
    """镜像里的全部 ``.md``，键为 ``<内容根>/<相对路径>``（正斜杠）。"""
    root = config.OFFICIAL_DOCS_MIRROR
    if not root.is_dir():
        pytest.skip(f"镜像目录不存在：{root}")
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*.md"))}


def test_镜像篇目与本体一致(镜像文件, ga) -> None:
    """镜像不得漏篇，也不得多篇。"""
    本体 = set(ga.official_docs)
    缺失 = sorted(本体 - set(镜像文件))
    多余 = sorted(set(镜像文件) - 本体)
    assert not 缺失, f"镜像缺少 {len(缺失)} 篇：{缺失[:5]}"
    assert not 多余, f"镜像多出 {len(多余)} 篇：{多余[:5]}"


def test_镜像逐字节一致(镜像文件, ga) -> None:
    """每一篇都必须与本体**逐字节相同**。

    只比大小是不够的：游戏升级后的改写完全可能保持字节数不变。
    """
    漂移: list[str] = []
    for key, size in ga.official_docs.items():
        mirror = 镜像文件.get(key)
        if mirror is None:
            continue  # 缺篇由 test_镜像篇目与本体一致 负责报出
        内容根, _, rel = key.partition("/")
        本体路径 = analyze.CONTENT_ROOTS[内容根] / rel
        if not 本体路径.is_file():
            continue
        if mirror.stat().st_size != size or _sha256(mirror) != _sha256(本体路径):
            漂移.append(f"{key}（镜像 {mirror.stat().st_size} B vs 本体 {size} B）")
    assert not 漂移, (
        f"{len(漂移)} 篇镜像已过期；重新镜像后需同步 "
        f"07-官方文档索引.md 的字节数与行数：\n" + "\n".join(f"  {d}" for d in 漂移[:10])
    )


def test_镜像里没有非_md_文件(镜像文件) -> None:
    """镜像目录下不应混入临时文件。"""
    root = config.OFFICIAL_DOCS_MIRROR
    杂项 = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() != ".md"
    ]
    assert not 杂项, f"镜像里混入了非 .md 文件：{杂项[:5]}"


def test_镜像篇数与产物一致(镜像文件, ga) -> None:
    """防止 rglob 写错导致「零篇也算通过」，并钉住产物里的篇数。"""
    assert len(镜像文件) == len(ga.official_docs)
    assert len(镜像文件) == 92, f"官方 .md 应为 92 篇，实测 {len(镜像文件)}"
