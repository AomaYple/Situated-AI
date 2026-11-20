"""验证 Mod 扫描器按 metadata 身份排除本产品并保留其他本地 Mod。"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from pdx import config, distribution, mods, version_contracts

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _write_metadata(root: Path, ident: str) -> None:
    """给一个假 mod 目录写最小 `.metadata/metadata.json`。"""
    meta = root / mods.METADATA_REL
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps({"name": "SITAI 处境档案", "id": ident}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def 假环境(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """把 `LOCAL_MODS` / `WORKSHOP` 指到临时目录，返回 `(本地, workshop)`。"""
    local = tmp_path / "mod"
    workshop = tmp_path / "workshop"
    local.mkdir()
    workshop.mkdir()
    monkeypatch.setattr(mods.config, "LOCAL_MODS", local)
    monkeypatch.setattr(mods.config, "WORKSHOP", workshop)
    return local, workshop


def test_按当前id和历史前缀认出本项目mod(假环境) -> None:
    local, _ = 假环境
    ours = local / "whatever_name"
    _write_metadata(ours, config.MOD_ID)
    legacy = local / "legacy_name"
    _write_metadata(legacy, "sitai.ru_defeat")
    theirs = local / "别人的mod"
    _write_metadata(theirs, "someone_else.mod")
    bare = local / "没有元数据"
    bare.mkdir()

    assert mods.own_mod(ours) is True
    assert mods.own_mod(legacy) is True
    assert mods.own_mod(theirs) is False
    assert mods.own_mod(bare) is False, "没有 metadata 就不能认成我们的"


def test_自己的mod不计入本机mod统计(假环境) -> None:
    local, workshop = 假环境
    (workshop / "1234567890").mkdir()  # 别人的一个 Workshop mod
    _write_metadata(workshop / "1234567890", "some_workshop_mod")
    (local / "some_real_mod").mkdir()
    _write_metadata(local / "some_real_mod", "handmade.mod")
    _write_metadata(local / "situated-ai-install", distribution.MOD_ID)
    (local / "zz_probe_ab").mkdir()

    found = sorted(p.name for p in mods.discover_mods())
    assert found == ["1234567890", "some_real_mod", "zz_probe_ab"]
    assert "situated-ai-install" not in found, "本产品应通过 metadata ID 排除"


def test_只数workshop时本地目录一个都不算(假环境) -> None:
    local, workshop = 假环境
    (workshop / "1234567890").mkdir()
    (local / "some_real_mod").mkdir()

    found = [p.name for p in mods.discover_mods(include_local=False)]
    assert found == ["1234567890"]


def test_命名空间常量只有一份() -> None:
    """脚本资源命名空间和启动器 ID 分离，旧 ID 前缀仍供兼容识别。

    扫描器不能 import 发行器（`mods.py` 是被 `analyze / verify / evidence` 共用的
    底层模块），所以常量住在 `config` 里，两边都从那里取。
    """
    assert config.NAMESPACE_PREFIX == "sitai_"
    assert mods.OWN_MOD_ID_PREFIX == "sitai."
    assert config.MOD_ID == "situated-ai"


def test_本仓库自己的mod元数据对得上判据() -> None:
    """真产物自检：仓库里那份 metadata 必须用当前身份并能被认成我们自己的。

    判据和产物一起漂时，纯逻辑测试发现不了；因此直接检查仓库的生成元数据。
    """
    ident = distribution.MOD_ID
    assert ident == config.MOD_ID
    assert mods.own_mod(config.REPO / "mod") is True


def test_分析保留完整metadata并解析非txt脚本和本地化(tmp_path) -> None:
    root = tmp_path / "mod"
    vanilla = tmp_path / "game"
    (root / ".metadata").mkdir(parents=True)
    (root / "common" / "gui_test").mkdir(parents=True)
    (root / "gui").mkdir()
    (root / "localization" / "english").mkdir(parents=True)
    metadata = {
        "id": "example.mod",
        "name": "Example",
        "tags": ["Gameplay", "GUI"],
        "dependencies": ["base"],
        "remote_file_id": "123",
    }
    (root / ".metadata" / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (root / "gui" / "window.gui").write_text("window = { name = test_window }\n", encoding="utf-8")
    (root / "localization" / "english" / "example_l_english.yml").write_text(
        'l_english:\n example_key:0 "Example"\n', encoding="utf-8"
    )
    info = mods.analyse_mod(root, vanilla=vanilla)
    assert info.metadata == metadata
    assert info.added_entries["gui"] >= 1
    assert info.localization_keys["example_key"] == ("l_english",)


_DOC12_NAME = "12-真实mod解剖与改造面地图.md"
_DOC12 = config.docs_root(version_contracts.CURRENT_VERSION) / _DOC12_NAME
_SUMMARY_SOURCE_VERSION = "1.15.1"
_VER_ROW = re.compile(r"^(1\.[\d.*]*|空)$")
_CONTENT_ROOTS = {"common", "localization", "events", "gfx", "gui", "map_data"}


def _doc12_version_table(text: str) -> dict[str, int]:
    """解析 doc 12 §7 那张 `supported_game_version` 分布表。"""
    assert "## 7. 版本兼容性观察" in text, "doc 12 的 §7 标题变了，这条用例要跟着改"
    section = text.split("## 7. 版本兼容性观察", 1)[1].split("## 8.", 1)[0]
    out: dict[str, int] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = cells[0].strip("`").replace("**", "").strip()
        if not _VER_ROW.fullmatch(key):
            continue
        out[key] = int(cells[1].replace(",", ""))
    return out


def test_doc12_版本分布表与现场一致() -> None:
    """核对文档保留的分布快照，并从现场 metadata 独立复算订阅分布。"""
    text = _DOC12.read_text(encoding="utf-8")
    heading = f"> **历史 {_SUMMARY_SOURCE_VERSION} 机器扫描摘要**"
    introduction = text.partition("\n## ")[0]
    summary_lines = [line for line in introduction.splitlines() if line.startswith(heading)]
    assert len(summary_lines) == 1
    summary_counts = _scan_summary_counts(summary_lines[0])
    assert summary_counts == _scan_summary_counts(text)
    assert "第 1–9 节保留 1.14.5 时点" in text
    assert "历史表格、目录覆盖率、前缀用量、去重路径和重叠结论不描述当前订阅集合" in text
    assert sum(_doc12_version_table(text).values()) == 23

    scanned = mods.analyse_all()
    if not scanned:
        pytest.skip("本机没有可发现的 mod，无从对照（CI 环境正常）")
    versions, _duplicated = _assert_raw_scan(scanned)
    assert Counter(m.supported_game_version or "空" for m in scanned) == versions
    assert sum(versions.values()) == len(scanned)


def test_doc12_重复路径结论与现场一致() -> None:
    """文档必须区分全量路径重复与游戏内容路径重复。"""
    text = _DOC12.read_text(encoding="utf-8")
    section = text.split("## 2.", 1)[1].split("### 2.1", 1)[0]
    assert "历史 1.14.5 订阅快照" in section
    assert "游戏内容目录零重叠" in section
    assert "全量重复项集中在缩略图、说明文件和 IDE 元数据" in section
    assert "被 ≥2 个 mod 命中的路径只有 8 条" in text
    assert "且**没有一条在内容目录**" in text

    live = mods.analyse_all()
    if not live:
        pytest.skip("本机没有可发现的 mod，无从对照（CI 环境正常）")
    paths: dict[str, list[str]] = {}
    for info in live:
        for rel in (*info.overrides, *info.additions):
            paths.setdefault(rel, []).append(info.target)
    duplicated = {rel: owners for rel, owners in paths.items() if len(owners) > 1}
    duplicated_content = {
        rel: owners for rel, owners in duplicated.items() if rel.split("/", 1)[0] in _CONTENT_ROOTS
    }
    _versions, raw_duplicates = _assert_raw_scan(live)
    assert {rel: len(owners) for rel, owners in duplicated.items()} == raw_duplicates
    assert {rel: len(owners) for rel, owners in duplicated_content.items()} == {
        rel: count
        for rel, count in raw_duplicates.items()
        if rel.split("/", 1)[0] in _CONTENT_ROOTS
    }


def _scan_summary_counts(text: str) -> dict[str, int]:
    counts = {}
    for key in ("mod.total", "mod.files"):
        assert text.count(f"<!--claim:{key}-->") == 1
        values = re.findall(rf"([\d,]+)<!--claim:{re.escape(key)}-->", text)
        assert len(values) == 1
        counts[key] = int(values[0].replace(",", ""))
    return counts


def _assert_raw_scan(scanned: list[mods.ModInfo]) -> tuple[Counter, dict[str, int]]:
    """Check scanner results against raw JSON and an independent pathlib inventory."""
    versions: Counter = Counter()
    paths: Counter = Counter()
    for info in scanned:
        metadata_path = info.root / ".metadata/metadata.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8-sig"))
            if metadata_path.is_file()
            else {}
        )
        assert info.metadata == metadata
        assert info.supported_game_version == str(metadata.get("supported_game_version", ""))
        versions[info.supported_game_version or "空"] += 1
        files = {
            path.relative_to(info.root).as_posix(): path.stat().st_size
            for path in info.root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.relative_to(info.root).parts[0] != ".metadata"
        }
        assert info.files == len(files)
        assert info.size == sum(files.values())
        expected_overrides = sorted(rel for rel in files if (config.GAME / rel).is_file())
        assert info.overrides == expected_overrides
        assert info.additions == sorted(set(files) - set(expected_overrides))
        paths.update(files.keys())
    return versions, {rel: count for rel, count in paths.items() if count > 1}


@pytest.mark.parametrize("content_collision", [False, True])
def test_current_mod_statistics_keep_content_and_noncontent_collisions_separate(
    假环境, tmp_path, monkeypatch, content_collision
):
    local, workshop = 假环境
    game = tmp_path / "game"
    monkeypatch.setattr(config, "GAME", game)
    (game / "common").mkdir(parents=True)
    (game / "common/shared.txt").write_text("sample = {}\n", encoding="utf-8")
    roots = [workshop / "101", workshop / "202", local / "fixture_local"]
    for index, (root, version, prefix) in enumerate(
        zip(roots, ("1.15.*", "", "1.14.*"), ("INJECT", "REPLACE", "INJECT_OR_CREATE"), strict=True)
    ):
        metadata = root / ".metadata/metadata.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(
            json.dumps({"id": f"fixture.{index}", "supported_game_version": version}),
            encoding="utf-8",
        )
        (root / "common").mkdir()
        name = "shared.txt" if content_collision and index < 2 else f"unique_{index}.txt"
        (root / "common" / name).write_text(f"{prefix}:sample = {{}}\n", encoding="utf-8")
        (root / ("README.md" if index < 2 else "unique.md")).write_text(
            "fixture\n", encoding="utf-8"
        )
    scanned = mods.analyse_all()
    assert {info.root for info in scanned} == set(roots)
    versions, duplicated = _assert_raw_scan(scanned)
    assert versions == {"1.15.*": 1, "空": 1, "1.14.*": 1}
    assert duplicated == (
        {"README.md": 2, "common/shared.txt": 2} if content_collision else {"README.md": 2}
    )
    assert mods.aggregate_prefixes(scanned) == {"INJECT": 1, "REPLACE": 1, "INJECT_OR_CREATE": 1}
    summary = "3<!--claim:mod.total--> 6<!--claim:mod.files-->"
    expected_counts = {"mod.total": len(scanned), "mod.files": sum(info.files for info in scanned)}
    assert _scan_summary_counts(summary) == expected_counts
    for damaged in (
        summary.replace("3<!--claim:mod.total-->", "2<!--claim:mod.total-->"),
        summary.replace("6<!--claim:mod.files-->", "9<!--claim:mod.files-->"),
        summary + "3<!--claim:mod.total-->",
    ):
        with pytest.raises(AssertionError):
            assert _scan_summary_counts(damaged) == expected_counts
    scanned[0].files += 1
    with pytest.raises(AssertionError):
        _assert_raw_scan(scanned)
