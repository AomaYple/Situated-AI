"""游戏自带官方 ``.md`` 的**清单与指纹**。

背景：为什么不再把原文入库
--------------------------
``research/official-docs/`` 曾是游戏自带 94 篇官方 ``.md`` 的**逐字镜像**，
而本仓库是 Apache-2.0 公开仓库 —— 那 230 KB 是 Paradox 的版权内容。

镜像的**功能价值**只有两条：① 检测「Paradox 改了官方文档」；
② 让没有游戏的人也能读原文。第一条几乎全部由**清单**承载 ——
文件名、字节数、逐篇 sha256 都是事实而不是创作内容。
第二条的替代品是知识库正文本身（重点已转述、并标注了原文缺陷）。

所以：**清单入库，原文不入库**。本地镜像可以保留（``.gitignore`` 忽略），
装了游戏的机器随时能用 :func:`build_manifest` 重建。

**历史核验**：`git log -- research/official-docs` 与 `git rev-list --objects --all` 均无该目录记录。官方镜像从未进入 Git 历史，因此无需重写历史；`.gitignore` 只阻止本机镜像进入索引。

它比镜像强在哪
--------------
以前只有「镜像 vs 本体」一条路可查，现在**任意克隆都能查**：
拿清单比对本机游戏，立刻知道「自清单生成以来，Paradox 动过哪几篇」。
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import config
from .doc_tables import KeyedTableSpec
from .textio import text_bytes
from .version_contracts import active_version

#: 清单文件名（放在 research/ 下，与镜像目录平级）
HISTORICAL_MANIFEST_NAME = "official-docs.manifest.json"
MANIFEST_NAME = (
    "official-docs-1.15.0.manifest.json"
    if config.DOCS == config.DOCS_115
    else HISTORICAL_MANIFEST_NAME
)

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
    name = (
        "official-docs-1.15.0.manifest.json"
        if active_version() == "1.15.0"
        else HISTORICAL_MANIFEST_NAME
    )
    return config.RESEARCH / name


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
        except OSError as exc:
            raise OSError(f"无法读取官方文档 {key} ({p}): {exc}") from exc
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise UnicodeError(f"官方文档不是有效UTF-8 {key} ({p}): {exc}") from exc
        mirror = text_bytes(decoded)
        entries[key] = {
            "字节": len(raw),
            "行数": decoded.count("\n") + (0 if raw.endswith(b"\n") else 1),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "镜像字节": len(mirror),
            "镜像sha256": hashlib.sha256(mirror).hexdigest(),
        }
    return {
        "说明": "游戏自带官方 .md 的清单与指纹。原文不入库，见 tools/README.md 的「官方文档清单」。",
        "来源": " ".join(f"{n}={b}" for n, b in _ROOTS),
        "版本": config.game_version(),
        "篇数": len(entries),
        "文档": entries,
    }


def write_manifest() -> Path:
    """完整构建非空清单后原子替换；读取或写入失败保留旧权威清单。"""
    path = manifest_path()
    data = build_manifest()
    version = data.get("版本")
    if (
        not isinstance(version, dict)
        or version.get("caligula_branch") != f"release/{active_version()}"
    ):
        raise ValueError("官方文档清单原版版本不匹配，拒绝覆盖其他版本证据")
    if not data["文档"]:
        roots = ", ".join(f"{name}={base}" for name, base in _ROOTS)
        raise ValueError(f"官方文档清单为空，拒绝覆盖权威清单；检查输入目录：{roots}")
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_manifest() -> dict[str, object]:
    """读当前版本清单；缺失返回空字典，已存在的损坏或版本不符清单硬失败。"""
    path = manifest_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"官方文档清单损坏：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"官方文档清单结构错误：{path}")
    version = data.get("版本")
    expected = f"release/{active_version()}"
    if not isinstance(version, dict) or version.get("caligula_branch") != expected:
        raise ValueError(f"官方文档清单版本不匹配：期望 {expected}，实际 {version!r}")
    return data


def entries(data: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    """取清单里的文档表。

    显式传 ``{}`` 与不传**不是一回事**：前者是「这份清单里一篇都没有」，
    后者才是「用磁盘上那份」。写成 ``data or load_manifest()`` 会把前者
    悄悄变成后者 —— 于是「空清单」这条路径永远测不到，也永远走不到。
    """
    raw = (load_manifest() if data is None else data).get("文档")
    return raw if isinstance(raw, dict) else {}


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 07 §0 那张「统计总览」——**全部由入库清单现算**（不需要游戏）。

    这张表原先 8 行全是手写的，其中 4 行有断言看守（篇数 / 总字节 / 最大字节 …），
    但「断言看守」只能告诉你数字**不一致**，仍要人去改；改成生成表之后，
    `v3 tables --write` 直接把它算对。顺带把 4 个此前没人管的行
    （总行数 / 平均字节 / 最小文档 / 两档大小分布）也纳入看守。
    """
    return [
        KeyedTableSpec(
            name="doc07 官方文档统计",
            header=OVERVIEW_HEADER,
            cells=overview_rows,
        )
    ]


#: doc 07 §0 那张表的表头（同文档里没有第二个同表头的表）。
OVERVIEW_HEADER = "| 指标 | 数值 |"


def overview_rows() -> list[tuple[str, dict[int, str]]]:
    """§0 的 8 行：篇数 / 总字节 / 总行数 / 平均 / 最小 / 最大 / 两档分布。"""
    docs = entries()
    if not docs:
        raise FileNotFoundError("官方文档清单不存在或为空 —— 先跑 `v3 mirror write`")
    # 清单是 JSON，值是 ``object``；这里显式收窄成 int（清单由本模块写，字段是稳定的）
    sizes = sorted((int(str(v["字节"])), k) for k, v in docs.items())
    total_bytes = sum(s for s, _ in sizes)
    total_lines = sum(int(str(v["行数"])) for v in docs.values())
    count = len(docs)
    small, big = sizes[0], sizes[-1]
    return [
        ("文档总数", {1: f"**{count:,}**"}),
        ("总字节数", {1: f"**{total_bytes:,}**"}),
        ("总行数", {1: f"**{total_lines:,}**"}),
        ("平均字节数", {1: f"{total_bytes / count:,.1f}"}),
        ("最小文档", {1: f"{small[0]:,} B（`{Path(small[1]).name}`）"}),
        ("最大文档", {1: f"{big[0]:,} B（`{Path(big[1]).name}`）"}),
        ("小于 600 B 的文档", {1: f"{sum(1 for s, _ in sizes if s < 600)} 个"}),
        ("≥ 5,000 B 的文档", {1: f"{sum(1 for s, _ in sizes if s >= 5000)} 个"}),
        ("≥ 10,000 B 的文档", {1: f"{sum(1 for s, _ in sizes if s >= 10000)} 个"}),
    ]


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
        if path.stat().st_size != meta.get("镜像字节", meta["字节"]) or sha256_of(path) != meta.get(
            "镜像sha256", meta["sha256"]
        ):
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
