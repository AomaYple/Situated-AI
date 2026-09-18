"""快照与比对：捕获某个游戏版本下全部 mod 相关信息的**规范形态**，供版本间 diff。

为什么需要
----------
2026-09-16 游戏静默从 1.14.2 升到 1.14.3，``00_ai.txt`` 的 AI 参数从 1,013
变成 1,017。文档里的数字「看起来一直对得上」，实际已经过期 —— 没有快照
就无从察觉。

设计要点
--------
**完备**：快照收录全部 mod 相关条目的**名字**（不是数量），因此增删改都能被 diff 出来。

**规范**：所有列表排序、所有字典按键排序、不写入时间戳等易变字段 ——
同一版本重复生成的快照应当**逐字节相同**。这条由测试保证。

**分层**：整份快照拆成若干「域」（sections），每个域是
``名称 -> 排序后的字符串列表``。域之间互不依赖，diff 结果按域分组呈现。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import config
from .cache import parse_cached
from .defines import extract_defines
from .model import Block
from .scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

SNAPSHOT_DIR = config.OUT / "snapshots"

#: 快照格式版本。结构变更时递增，避免旧快照被误读。
FORMAT = 1


# ── 构建 ────────────────────────────────────────────────────
def _sorted_names(items: Iterable[str]) -> list[str]:
    return sorted(set(items))


def _walk_scriptable(root: Path, top: str):
    """产出某一级目录下可脚本化的文件及其相对路径。

    注意：``config.is_scriptable`` 期望的路径是**相对内容根**的
    （因为 ``SCRIPTABLE_DIRS`` 里存的是 ``common`` / ``events`` 这类一级目录名）。
    直接对 ``game/common`` 做 walk 会得到 ``("buildings", "x.txt")``，
    一级目录名变成数据目录名，导致全部被判为不相关 —— 这是个真实踩过的错。
    """
    for f in walk_files(root / top):
        try:
            rel = f.path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) < 2 or rel.parts[0] != top:
            continue
        if config.is_scriptable(rel.parts, f.suffix):
            yield f, rel


def _scriptable_names(root: Path, top: str = "common") -> dict[str, list[str]]:
    """``数据目录 -> 排序后的顶层条目名``。"""
    out: dict[str, list[str]] = {}
    for f, rel in _walk_scriptable(root, top):
        pf = parse_cached(f.path)
        bucket = out.setdefault(rel.parts[1], [])
        bucket.extend(a.key for a in pf.top_assignments if not a.is_variable)
    return {k: _sorted_names(v) for k, v in sorted(out.items())}


def _field_names(root: Path, top: str = "common") -> dict[str, list[str]]:
    """``目录/条目 -> 该条目块内出现过的字段名``。

    这是「某类型支持哪些字段」的完整清单，字段增删都能被发现。
    """
    out: dict[str, set[str]] = {}
    for f, rel in _walk_scriptable(root, top):
        pf = parse_cached(f.path)
        for a in pf.top_assignments:
            if a.is_variable or not isinstance(a.value, Block):
                continue
            key = f"{rel.parts[1]}/{a.key}"
            out.setdefault(key, set()).update(s.key for s in a.value.assignments())
    return {k: sorted(v) for k, v in sorted(out.items())}


def _defines_snapshot() -> dict[str, list[str]]:
    """``层/命名空间 -> 参数名``。

    同名命名空间可能在**多个块**里出现（实测 ``NGUI`` 出现 24 次、
    ``NPops`` 2 次），必须**合并**参数而不是后写覆盖 —— 覆盖会
    让 92 个命名空间坍缩成 67 个。
    """
    merged: dict[str, set[str]] = {}
    for label, root in (
        ("game", config.GAME / "common" / "defines"),
        ("jomini", config.JOMINI / "common" / "defines"),
    ):
        rep = extract_defines(root)
        for ns in rep.namespaces:
            merged.setdefault(f"{label}/{ns.name}", set()).update(ns.param_names)
    return {k: sorted(v) for k, v in sorted(merged.items())}


def _localization_keys(root: Path) -> dict[str, list[str]]:
    """``语言 -> 排序后的本地化键``。键的增删能被 diff 出来。"""
    out: dict[str, set[str]] = {}
    loc = root / "localization"
    if not loc.is_dir():
        return {}
    for f in walk_files(loc):
        if f.suffix not in (".yml", ".yaml"):
            continue
        try:
            text = f.path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        lang = "?"
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("l_") and s.endswith(":"):
                lang = s[:-1]
                continue
            if ":" in s and not s.startswith("l_"):
                key = s.split(":", 1)[0].strip()
                if key:
                    out.setdefault(lang, set()).add(key)
    return {k: sorted(v) for k, v in sorted(out.items())}


def _dlc_snapshot() -> dict[str, list[str]]:
    """``DLC 名 -> 顶层条目``。"""
    base = config.GAME / "dlc"
    out: dict[str, list[str]] = {}
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        out[d.name] = _sorted_names([p.name for p in d.iterdir()] if d.is_dir() else [])
    return out


def _checksum_and_paths() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    man = config.GAME / "checksum_manifest.txt"
    if man.is_file():
        out["checksum_manifest"] = _sorted_names(
            ln.split("=", 1)[1].strip()
            for ln in man.read_text(encoding="utf-8-sig").splitlines()
            if ln.strip().startswith("name")
        )
    ps = config.GAME / "paths.settings"
    if ps.is_file():
        out["paths.settings"] = _sorted_names(
            ln.split("=", 1)[0].strip()
            for ln in ps.read_text(encoding="utf-8-sig").splitlines()
            if "=" in ln
        )
    return out


@dataclass
class Snapshot:
    version: dict[str, str] = field(default_factory=dict)
    sections: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    #: 是否为**精简快照**（本地化只留计数与指纹，见 :func:`build`）。
    compact: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "格式版本": FORMAT,
            "版本": self.version,
            "精简": self.compact,
            "域": {k: dict(v) for k, v in sorted(self.sections.items())},
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=d.get("版本", {}),
            sections=d.get("域", {}),
            compact=bool(d.get("精简", False)),
        )

    @property
    def version_label(self) -> str:
        return self.version.get("caligula_branch", "?") or "?"

    def counts(self) -> dict[str, int]:
        """各域的条目总数，用于快速概览。"""
        return {
            f"{sec}/{name}": len(names)
            for sec, body in self.sections.items()
            for name, names in body.items()
        }


def _localization_digest(root: Path) -> dict[str, list[str]]:
    """精简快照用：每个语言的**键数 + 键名指纹**，不带 14 万条键名清单。

    完整快照里 ``localization`` 一个域就占 30 MB（11 种语言 × 14.5 万键），
    是整份快照 73% 的体积。而「Paradox 有没有改本地化键」这个问题，
    用「键数 + sha256」就能回答；具体改了哪些键，回到本机那份完整快照去查。
    """
    out: dict[str, list[str]] = {}
    for lang, keys in _localization_keys(root).items():
        digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
        out[lang] = [f"{len(keys)} 键", f"sha256:{digest}"]
    return out


def build(*, compact: bool = False, verbose: bool = False) -> Snapshot:
    """生成当前游戏版本的快照。

    ``compact=True`` 产出**精简快照**：结构域（``common_entries`` / ``fields`` /
    ``defines`` / ``dlc`` / ``config``）原样保留 —— 它们才是「Paradox 增删了
    哪些字段与条目」的答案 —— 只把 ``localization`` 换成计数 + 指纹，
    体积从 ~41 MB 降到 ~4.4 MB，**小到足以入库**。

    两个模式**形状相同**（都是 ``域 -> 名称 -> 字符串列表``），因此
    :func:`compare` 对两者都能用；但**不要拿精简版与完整版对 diff** ——
    那会把整个 ``localization`` 域报成「全删 + 全增」。
    """
    snap = Snapshot(version=config.game_version(), compact=compact)
    if verbose:
        print(f"  版本: {snap.version_label}  精简: {compact}")

    snap.sections["common_entries"] = _scriptable_names(config.GAME, "common")
    if verbose:
        print(f"  common 目录: {len(snap.sections['common_entries'])}")

    snap.sections["fields"] = _field_names(config.GAME, "common")
    if verbose:
        print(f"  字段条目: {len(snap.sections['fields'])}")

    snap.sections["defines"] = _defines_snapshot()
    if verbose:
        print(f"  defines 命名空间: {len(snap.sections['defines'])}")

    if compact:
        snap.sections["localization_digest"] = _localization_digest(config.GAME)
        if verbose:
            print(
                f"  本地化指纹: {len(snap.sections['localization_digest'])} 种语言（键清单已省略）"
            )
    else:
        snap.sections["localization"] = _localization_keys(config.GAME)
        if verbose:
            print(f"  本地化语言: {len(snap.sections['localization'])}")

    snap.sections["dlc"] = _dlc_snapshot()
    snap.sections["config"] = _checksum_and_paths()
    return snap


# ── 比对 ────────────────────────────────────────────────────
@dataclass
class Change:
    """一个域内某项的变更。"""

    section: str
    name: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def line(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)}")
        if self.removed:
            parts.append(f"-{len(self.removed)}")
        return f"  [{self.section}] {self.name}: {' '.join(parts)}"


def compare(old: Snapshot, new: Snapshot) -> list[Change]:
    """比对两份快照，返回全部变更（按域、按名称排序）。"""
    changes: list[Change] = []
    sections = sorted(set(old.sections) | set(new.sections))

    for sec in sections:
        a = old.sections.get(sec, {})
        b = new.sections.get(sec, {})
        for name in sorted(set(a) | set(b)):
            sa, sb = set(a.get(name, [])), set(b.get(name, []))
            if sa == sb:
                continue
            changes.append(
                Change(
                    section=sec,
                    name=name,
                    added=sorted(sb - sa),
                    removed=sorted(sa - sb),
                )
            )
    return changes


def diff_summary(changes: list[Change]) -> dict[str, int]:
    return {
        "变更项数": len(changes),
        "新增条目": sum(len(c.added) for c in changes),
        "删除条目": sum(len(c.removed) for c in changes),
    }


def list_snapshots() -> list[Path]:
    if not SNAPSHOT_DIR.is_dir():
        return []
    return sorted(SNAPSHOT_DIR.glob("*.json"))


def snapshot_path(label: str | None = None) -> Path:
    return SNAPSHOT_DIR / f"{label or 'current'}.json"
