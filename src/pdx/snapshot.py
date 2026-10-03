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
import os
import tempfile
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import ai_surface, citations, config, vanilla_index
from .cache import parse_cached
from .defines import extract_defines
from .extract import entry_fields
from .model import Block
from .scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Iterable

SNAPSHOT_DIR = config.OUT / "snapshots"

#: 快照格式版本。结构变更时递增，避免旧快照被误读。
FORMAT = 1
ORDERED_SECTIONS = frozenset({"doc_tables"})


class SnapshotFormatError(ValueError):
    """快照文件格式不受支持或结构损坏。"""


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


def _scriptable_snapshot(
    root: Path, top: str = "common"
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """一次遍历并解析一个内容根，同时收集条目名和字段名。"""
    names: dict[str, list[str]] = {}
    fields: dict[str, set[str]] = {}
    for f, rel in _walk_scriptable(root, top):
        pf = parse_cached(f.path)
        bucket = names.setdefault(rel.parts[1], [])
        for assignment in pf.top_assignments:
            if assignment.is_variable:
                continue
            bucket.append(assignment.key)
            if isinstance(assignment.value, Block):
                key = f"{rel.parts[1]}/{assignment.key}"
                fields.setdefault(key, set()).update(entry_fields(assignment.value))
    return (
        {k: _sorted_names(v) for k, v in sorted(names.items())},
        {k: sorted(v) for k, v in sorted(fields.items())},
    )


def _scriptable_names(root: Path, top: str = "common") -> dict[str, list[str]]:
    """数据目录到排序后的顶层条目名。"""
    return _scriptable_snapshot(root, top)[0]


def _field_names(root: Path, top: str = "common") -> dict[str, list[str]]:
    """目录和条目到条目块内出现过的字段名。"""
    return _scriptable_snapshot(root, top)[1]


def _scriptable_domain_sections(
    root: Path = config.GAME,
    *,
    label: str = "",
    include_common: bool = False,
) -> dict[str, dict[str, list[str]]]:
    """返回某个内容根下每个可脚本目录的条目域和字段域。

    ``game`` 保持历史域名（例如 ``events_entries``），而引擎共享层使用
    ``jomini/events_entries`` 这类带内容根前缀的域名，避免同名目录互相覆盖。
    ``include_common`` 只对引擎层开启；游戏层的 ``common`` 由调用方单独收集，
    这样既保持旧快照兼容，又不会漏掉 Jomini/Clausewitz 的 common 定义。
    """
    sections: dict[str, dict[str, list[str]]] = {}
    for top in config.SCRIPTABLE_DIRS:
        if top == "common" and not include_common:
            continue
        if not (root / top).is_dir():
            names: dict[str, list[str]] = {}
            fields: dict[str, list[str]] = {}
        else:
            names, fields = _scriptable_snapshot(root, top)
        prefix = f"{label}/" if label else ""
        sections[f"{prefix}{top}_entries"] = names
        sections[f"{prefix}{top}_fields"] = fields
    return sections


def _engine_scriptable_sections() -> dict[str, dict[str, list[str]]]:
    """收集 Jomini 与 Clausewitz 内容根的可脚本化域。"""
    sections: dict[str, dict[str, list[str]]] = {}
    for label, root in (("jomini", config.JOMINI), ("clausewitz", config.CLAUSEWITZ)):
        if root.is_dir():
            sections.update(_scriptable_domain_sections(root, label=label, include_common=True))
    return sections


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


def _dlc_descriptor_snapshot(root: Path = config.GAME) -> dict[str, list[str]]:
    """保存 DLC 描述符的来源文件与全部键值，包含重复键。"""
    base = root / "dlc"
    out: dict[str, list[str]] = {}
    if not base.is_dir():
        return out
    for dlc in sorted(path for path in base.iterdir() if path.is_dir()):
        values: list[str] = []
        for descriptor in sorted(dlc.glob("*.dlc")):
            try:
                text = descriptor.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"')
                if key:
                    values.append(f"{descriptor.name}:{key}={value}")
        if values:
            out[dlc.name] = sorted(values)
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
        # newline="\n"：快照会入库（精简版），而 .gitattributes 规定 eol=lf。
        # 不传这个参数的话，Windows 上生成的快照与 Linux 上的**字节不同**，
        # 跨平台 diff 会整份报差异。
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)
        # 同目录临时文件 + os.replace：进程被中断时不会留下半个 JSON，
        # 且 replace 在 Windows/macOS/Linux 都是原子的（同一文件系统内）。
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(path)
        except BaseException:
            with suppress(FileNotFoundError):
                Path(temporary).unlink()
            raise

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SnapshotFormatError(f"无法读取快照 {path}: {exc}") from exc
        if not isinstance(d, dict) or d.get("格式版本") != FORMAT:
            raise SnapshotFormatError(
                f"{path} 的格式版本不受支持：{d.get('格式版本') if isinstance(d, dict) else type(d).__name__}"
            )
        version = d.get("版本")
        sections = d.get("域")
        compact = d.get("精简", False)
        if (
            not isinstance(version, dict)
            or not isinstance(sections, dict)
            or not isinstance(compact, bool)
        ):
            raise SnapshotFormatError(f"{path} 的快照字段类型错误")
        if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in sections.items()):
            raise SnapshotFormatError(f"{path} 的域结构错误")
        if any(
            not isinstance(k, str) or not isinstance(v, list)
            for body in sections.values()
            for k, v in body.items()
        ):
            raise SnapshotFormatError(f"{path} 的域条目结构错误")
        if any(
            not isinstance(item, str)
            for body in sections.values()
            for values in body.values()
            for item in values
        ):
            raise SnapshotFormatError(f"{path} 的域值必须全部是字符串")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in version.items()):
            raise SnapshotFormatError(f"{path} 的版本字段必须是字符串")
        return cls(
            version=dict(version),
            sections=sections,
            compact=compact,
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


def _doc_tables_snapshot() -> dict[str, list[str]]:
    """生成表的内容：``{文档名::表名: [数据行, …]}``。

    为什么要进快照：172 张生成表是文档里**大部分数字**的来源，而它们只有
    装了游戏才算得出来。把「当时算出来的行」记进入库的精简快照后，
    CI（没有游戏）就能回答「文档里的表还是当时生成的那份吗」——
    `v3 tables --offline` 只做比对，不假装能离线重算。
    """
    from . import docgen  # noqa: PLC0415 - docgen 依赖各领域模块，导入期较重

    return docgen.render_all()


def _localization_digest(root: Path) -> dict[str, list[str]]:
    """精简快照用：每个语言的**键数 + 键名指纹**，不带完整键名清单。

    完整快照里的 ``localization`` 域是体积大户；而「Paradox 有没有改本地化键」
    这个问题，用「键数 + sha256」就能回答。具体改了哪些键，回到本机那份完整快照去查。
    """
    out: dict[str, list[str]] = {}
    for lang, keys in _localization_keys(root).items():
        digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
        out[lang] = [f"{len(keys)} 键", f"sha256:{digest}"]
    return out


def build(*, compact: bool = False, verbose: bool = False) -> Snapshot:
    """生成当前游戏版本的快照。

    ``compact=True`` 产出**精简快照**：所有结构域（包括 ``common`` 之外的
    ``events`` / ``gui`` / ``map_data`` / ``gfx`` / ``dlc`` 等）原样保留，
    只把 ``localization`` 换成计数 + 指纹；体积从 ~41 MiB 降到 ~8.0 MiB，
    **小到足以入库**。

    两个模式**形状相同**（都是 ``域 -> 名称 -> 字符串列表``），因此
    :func:`compare` 对两者都能用；但**不要拿精简版与完整版对 diff** ——
    那会把整个 ``localization`` 域报成「全删 + 全增」。

    另外无条件写入**离线通道**要用的那几个域（``vanilla_keys`` / ``vocabulary``
    / ``modifier_fields`` / ``mod_paths`` / ``icon_paths`` / ``ai_surface``）：
    闸门 ①② 与 ``v3 ai-surface --check`` 在没游戏的机器上靠它们才跑得起来
    （G-EXIT-2）。内容由 :mod:`pdx.vanilla_index` 与 :mod:`pdx.ai_surface`
    产出 —— 与它们**在线**现算时用的是同一批函数，所以两条路的池子同源。
    """
    snap = Snapshot(version=config.game_version(), compact=compact)
    if verbose:
        print(f"  版本: {snap.version_label}  精简: {compact}")

    common_entries, common_fields = _scriptable_snapshot(config.GAME, "common")
    snap.sections["common_entries"] = common_entries
    if verbose:
        print(f"  common 目录: {len(snap.sections['common_entries'])}")

    snap.sections["fields"] = common_fields
    if verbose:
        print(f"  字段条目: {len(snap.sections['fields'])}")

    # common 之外的每个可脚本目录独立入域，避免事件、GUI、地图和 DLC
    # 的新增条目被旧的 common-only 快照悄悄漏掉。
    scriptable_sections = _scriptable_domain_sections()
    snap.sections.update(scriptable_sections)
    # 引擎共享层同样可以被 mod 依赖或覆盖；之前只把它们用于在线分析，
    # 导致版本快照无法发现 Jomini/Clausewitz 层的条目变更。
    engine_sections = _engine_scriptable_sections()
    snap.sections.update(engine_sections)
    if verbose:
        for name in sorted(scriptable_sections):
            print(f"  {name}: {len(snap.sections[name])} 组")
        for name in sorted(engine_sections):
            print(f"  {name}: {len(snap.sections[name])} 组")

    snap.sections["defines"] = _defines_snapshot()
    if verbose:
        print(f"  defines 命名空间: {len(snap.sections['defines'])}")

    if compact:
        snap.sections["localization_digest"] = _localization_digest(config.GAME)
        for label, root in (("jomini", config.JOMINI), ("clausewitz", config.CLAUSEWITZ)):
            if root.is_dir():
                snap.sections[f"{label}/localization_digest"] = _localization_digest(root)
        if verbose:
            print(
                f"  本地化指纹: {len(snap.sections['localization_digest'])} 种语言（键清单已省略）"
            )
    else:
        snap.sections["localization"] = _localization_keys(config.GAME)
        for label, root in (("jomini", config.JOMINI), ("clausewitz", config.CLAUSEWITZ)):
            if root.is_dir():
                snap.sections[f"{label}/localization"] = _localization_keys(root)
        if verbose:
            print(f"  本地化语言: {len(snap.sections['localization'])}")

    snap.sections["dlc"] = _dlc_snapshot()
    snap.sections["dlc_descriptors"] = _dlc_descriptor_snapshot()
    snap.sections["config"] = _checksum_and_paths()
    snap.sections["doc_tables"] = _doc_tables_snapshot()
    if verbose:
        print(f"  生成表: {len(snap.sections['doc_tables'])} 张")

    # ── 离线通道（G-EXIT-2）的原料 ──
    # 闸门 ①② 与 `v3 ai-surface --check` 要回答「这个名字原版里有没有」，而
    # CI runner 上没有游戏。这几域让它们能改用「当时记下来的原版真值」，
    # 且与在线路径共用同一批抽取函数（`pdx.vanilla_index` / `pdx.ai_surface`）
    # —— 不是另抄一份清单。
    snap.sections.update(vanilla_index.snapshot_sections(config.GAME))
    snap.sections[ai_surface.SECTION] = ai_surface.snapshot_section(config.GAME)
    # `v3 citations` 的离线通道（B77）：把「数据源引了哪些文件:行号、那一行长什么样」
    # 记进快照 —— 没有游戏的机器上，这一条纪律第一次守得住。
    snap.sections[citations.SECTION] = citations.support_domain()
    if verbose:
        for name in (*vanilla_index.SECTIONS, ai_surface.SECTION):
            body = snap.sections[name]
            print(f"  {name}: {len(body)} 项 / {sum(len(v) for v in body.values()):,} 条")
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
    """比对两份同口径快照，返回全部变更（按域、按名称排序）。"""
    if old.compact != new.compact:
        raise SnapshotFormatError("精简快照与完整快照不能直接比较")
    changes: list[Change] = []
    sections = sorted(set(old.sections) | set(new.sections))

    for sec in sections:
        a = old.sections.get(sec, {})
        b = new.sections.get(sec, {})
        for name in sorted(set(a) | set(b)):
            old_values = list(a.get(name, []))
            new_values = list(b.get(name, []))
            if sec in ORDERED_SECTIONS:
                added, removed = _ordered_delta(old_values, new_values)
            else:
                # 普通域语义上是集合，但重复项说明快照损坏；保留计数差异，
                # 避免静默吞掉结构变化。
                ca, cb = Counter(old_values), Counter(new_values)
                if ca == cb:
                    continue
                added = sorted((cb - ca).elements())
                removed = sorted((ca - cb).elements())
            if not added and not removed:
                continue
            changes.append(
                Change(
                    section=sec,
                    name=name,
                    added=added,
                    removed=removed,
                )
            )
    return changes


def _ordered_delta(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """为有序域保留重复项和顺序变化，返回新增/删除序列。"""
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag in {"replace", "delete"}:
            removed.extend(old[i1:i2])
        if tag in {"replace", "insert"}:
            added.extend(new[j1:j2])
    return added, removed


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
    """按**快照名**解析出文件路径；只写了版本号时优先完整快照，退回精简快照。

    为什么要退回：**只有精简快照是入库的**（8 MB vs 41 MB），
    所以「拿 1.14.3 与 1.14.4 比结构」在别的机器上只可能拿到 ``*.compact.json``。
    早先这里硬拼 ``<label>.json``，于是 `v3 snapshot diff release-1.14.3
    release-1.14.4` 在只有精简快照的机器上报「快照不存在」——
    而那正是这条命令最主要的用法（版本演练）。完整快照在本地仍然优先：
    它多带的本地化明细对 diff 更有用。
    """
    full = SNAPSHOT_DIR / f"{label or 'current'}.json"
    if full.is_file():
        return full
    compact = SNAPSHOT_DIR / f"{label or 'current'}.compact.json"
    return compact if compact.is_file() else full
