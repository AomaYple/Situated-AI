"""游戏自带官方 ``.md`` 的**清单与指纹**。

背景：为什么不再把原文入库
--------------------------
``research/official-docs/`` 曾是游戏自带 92 篇官方 ``.md`` 的**逐字镜像**，
而本仓库是 Apache-2.0 公开仓库 —— 那 230 KB 是 Paradox 的版权内容。

镜像的**功能价值**只有两条：① 检测「Paradox 改了官方文档」；
② 让没有游戏的人也能读原文。第一条几乎全部由**清单**承载 ——
文件名、字节数、逐篇 sha256 都是事实而不是创作内容。
第二条的替代品是知识库正文本身（重点已转述、并标注了原文缺陷）。

所以：**清单入库，原文不入库**。本地镜像可以保留（``.gitignore`` 忽略），
装了游戏的机器随时能用 :func:`build_manifest` 重建。

⚠️ **诚实说明**：从 git 移除只影响**当前树**；那 92 篇仍在仓库历史里。
若要彻底清除需要重写历史（``git filter-repo``），属于需要单独决定的动作。

它比镜像强在哪
--------------
以前只有「镜像 vs 本体」一条路可查，现在**任意克隆都能查**：
拿清单比对本机游戏，立刻知道「自清单生成以来，Paradox 动过哪几篇」。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from pathlib import Path

#: 清单文件名（放在 research/ 下，与镜像目录平级）
MANIFEST_NAME = "official-docs.manifest.json"

#: 内容根 → 目录名前缀。清单与镜像都用 ``<根>/<相对路径>`` 作键，
#: 因为不同内容根下可能有同名相对路径（只写相对路径会互相覆盖）。
_ROOTS: tuple[tuple[str, Path], ...] = (
    ("game", config.GAME),
    ("jomini", config.JOMINI),
    ("clausewitz", config.CLAUSEWITZ),
)


@dataclass(slots=True, frozen=True)
class DocEntry:
    """清单里的一条。"""

    key: str
    size: int
    sha256: str
    lines: int


def manifest_path() -> Path:
    return config.RESEARCH / MANIFEST_NAME


def iter_docs() -> list[tuple[str, Path]]:
    """列出本机三个内容根下的官方 ``.md``，返回 ``(键, 路径)`` 并按键排序。

    键是 ``<根>/<相对路径>``，不是裸相对路径：不同内容根下可能有同名文件，
    只写相对路径会让它们互相覆盖。生成清单与重建镜像共用这一个入口，
    两边不可能列出不同的篇目集合。
    """
    out: list[tuple[str, Path]] = []
    for name, base in _ROOTS:
        if not base.is_dir():
            continue
        out.extend((f"{name}/{p.relative_to(base).as_posix()}", p) for p in base.rglob("*.md"))
    out.sort()
    return out


def sha256_of(path: Path) -> str:
    """文件的 sha256，分块读 —— 这里唯一的「指纹」定义。

    生成清单与比对镜像共用它：两处各写一遍 `hashlib` 是这类工具最典型的
    漂移点（一边加了 BOM 剥离、另一边没加，于是所有篇目都报「内容变了」）。
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest() -> dict[str, object]:
    """扫描本机游戏安装，生成清单（三个内容根全扫）。"""
    entries: dict[str, dict[str, object]] = {}
    for key, p in iter_docs():
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        entries[key] = {
            "字节": len(raw),
            "行数": raw.decode("utf-8", errors="replace").count("\n")
            + (0 if raw.endswith(b"\n") else 1),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return {
        "说明": "游戏自带官方 .md 的清单与指纹。原文不入库，见 tools/README.md 的「官方文档清单」。",
        "来源": " ".join(f"{n}={b}" for n, b in _ROOTS),
        "版本": config.game_version(),
        "篇数": len(entries),
        "文档": entries,
    }


def write_manifest() -> Path:
    """把清单写入 ``research/official-docs.manifest.json``。"""
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_manifest() -> dict[str, object]:
    """读清单；不存在或损坏时返回空字典（调用方据此跳过）。"""
    path = manifest_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def entries(data: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    """取清单里的文档表。

    显式传 ``{}`` 与不传**不是一回事**：前者是「这份清单里一篇都没有」，
    后者才是「用磁盘上那份」。写成 ``data or load_manifest()`` 会把前者
    悄悄变成后者 —— 于是「空清单」这条路径永远测不到，也永远走不到。
    """
    raw = (load_manifest() if data is None else data).get("文档")
    return raw if isinstance(raw, dict) else {}


def diff_against_game(data: dict[str, object] | None = None) -> list[str]:
    """拿清单比对本机游戏，返回变更描述（空表 = 完全一致）。

    这是**清单替代镜像的核心能力**：任何一台装了游戏的机器都能跑，
    不需要先有一份镜像。
    """
    old = entries(data)
    if not old:
        return ["清单不存在或为空 —— 先跑 `v3 mirror write`"]
    new = entries(build_manifest())
    out: list[str] = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a is None:
            out.append(f"新增：{key}（{b['字节'] if b else '?'} 字节）")
        elif b is None:
            out.append(f"删除：{key}")
        elif a["sha256"] != b["sha256"]:
            out.append(
                f"内容变了：{key}（{a['字节']} → {b['字节']} 字节，"
                f"sha256 {str(a['sha256'])[:8]}… → {str(b['sha256'])[:8]}…）"
            )
    return out


def diff_mirror(data: dict[str, object] | None = None) -> list[str]:
    """拿清单比对**本地镜像**，返回差异（镜像不存在时返回空表）。

    本地镜像仍在（只是不入库），所以这台机器上这条路照跑。
    两个方向都查：清单里的篇目在镜像里是否**逐字节**相符，
    镜像里是否有多余文件（Paradox 删过文档、或 ``--sync`` 后留下的陈迹）。
    """
    root = config.OFFICIAL_DOCS_MIRROR
    if not root.is_dir():
        return []
    old = entries(data)
    if not old:
        return []
    out: list[str] = []
    for key, meta in sorted(old.items()):
        path = root / key
        if not path.is_file():
            out.append(f"镜像缺篇：{key}")
            continue
        if path.stat().st_size != meta["字节"] or sha256_of(path) != meta["sha256"]:
            out.append(f"镜像与清单不符：{key}")
    for name, _base in _ROOTS:
        sub = root / name
        if not sub.is_dir():
            continue
        out.extend(
            f"镜像多余：{f'{name}/{p.relative_to(sub).as_posix()}'}"
            for p in sorted(sub.rglob("*.md"))
            if f"{name}/{p.relative_to(sub).as_posix()}" not in old
        )
    return out
