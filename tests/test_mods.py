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


#: doc 12 的两处版本分布：§7 的表（给人看的）与 §9 第 1 条的散文（给结论看的）。
#: 它们**曾经互相矛盾**（表写 `1.13*` 8 / 空 10，散文写 9 / 9），而且两边都没有看守，
#: 所以只能靠人偶然发现。这条用例把「表 == 现场」钉死，散文那一侧由 §7 反向引用。
_DOC12 = config.DOCS / "12-真实mod解剖与改造面地图.md"
_HISTORICAL_DOC12 = config.REPO / "docs/victoria3-modding/12-真实mod解剖与改造面地图.md"
_VER_ROW = re.compile(r"^(1\.[\d.*]*|空)$")
_CONTENT_ROOTS = {"common", "localization", "events", "gfx", "gui", "map_data"}


def _doc12_version_table(text: str | None = None) -> dict[str, int]:
    """解析 doc 12 §7 那张 `supported_game_version` 分布表。"""
    text = _DOC12.read_text(encoding="utf-8") if text is None else text
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
    """**本机快照类数字也要有看守**（B83 的教训：没有看守的分布数会安静地烂掉）。

    跳过条件：本机没有可发现的 mod（CI 上没有 Workshop 内容）—— 这条测的是
    「文档与**这台机器**一致」，没有 mod 就没有可比的东西，跳过而不是假装通过。
    """
    scanned = mods.analyse_all()
    if version_contracts.is_115():
        text = _DOC12.read_text(encoding="utf-8")
        _assert_current_summary(text, scanned)
        versions, _duplicated = _assert_raw_scan(scanned)
        assert Counter(m.supported_game_version or "空" for m in scanned) == versions
        assert "第 1–9 节保留 1.14.5 时点" in text
        assert "历史表格、目录覆盖率、前缀用量、去重路径和重叠结论不描述当前订阅集合" in text
        assert _doc12_version_table(text) == _doc12_version_table(
            _HISTORICAL_DOC12.read_text(encoding="utf-8")
        )
        return
    live = Counter(m.supported_game_version or "空" for m in scanned)
    if not live:
        pytest.skip("本机没有可发现的 mod，无从对照（CI 环境正常）")

    got = _doc12_version_table()
    assert got, "§7 那张版本分布表没解析到任何行（表格被改过？）"
    assert got == dict(live), f"doc 12 §7 与现场不符：文档 {got}，现场 {dict(live)}"
    assert sum(got.values()) == len(mods.analyse_all())


def test_doc12_重复路径结论与现场一致() -> None:
    """文档必须区分全量路径重复与游戏内容路径重复。"""
    live = mods.analyse_all()
    paths: dict[str, list[str]] = {}
    for info in live:
        for rel in (*info.overrides, *info.additions):
            paths.setdefault(rel, []).append(info.target)
    duplicated = {rel: owners for rel, owners in paths.items() if len(owners) > 1}
    content_roots = {"common", "localization", "events", "gfx", "gui", "map_data"}
    duplicated_content = {
        rel: owners for rel, owners in duplicated.items() if rel.split("/", 1)[0] in content_roots
    }
    text = _DOC12.read_text(encoding="utf-8")
    if version_contracts.is_115():
        _assert_current_summary(text, live)
        _versions, raw_duplicates = _assert_raw_scan(live)
        assert {rel: len(owners) for rel, owners in duplicated.items()} == raw_duplicates
        assert {rel: len(owners) for rel, owners in duplicated_content.items()} == {
            rel: count
            for rel, count in raw_duplicates.items()
            if rel.split("/", 1)[0] in _CONTENT_ROOTS
        }
        # These are retained historical observations, never current scan totals.
        historical_section = text.split("## 2.", 1)[1].split("### 2.1", 1)[0]
        assert "历史 1.14.5 订阅快照" in historical_section
        assert "全量相对路径中被 2 个及以上 mod 提供的路径数 = 8" in historical_section
        assert "游戏内容目录中被 2 个及以上 mod 提供的路径数 = 0" in historical_section
        return
    assert "全量相对路径中被 2 个及以上 mod 提供的路径数 = 8" in text
    assert "游戏内容目录中被 2 个及以上 mod 提供的路径数 = 0" in text
    if not live:
        pytest.skip("本机没有可发现的 mod，无从对照（CI 环境正常）")
    assert len(duplicated) == 8
    assert not duplicated_content


def _assert_current_summary(text: str, scanned: list[mods.ModInfo]) -> None:
    """Current markers are unique and describe this scan, not the historical tables."""
    assert "当前 1.15.0 机器扫描摘要" in text
    for key, expected in (
        ("mod.total", len(scanned)),
        ("mod.files", sum(info.files for info in scanned)),
    ):
        assert text.count(f"<!--claim:{key}-->") == 1
        values = re.findall(rf"([\d,]+)<!--claim:{re.escape(key)}-->", text)
        assert len(values) == 1
        assert int(values[0].replace(",", "")) == expected


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
    summary = "当前 1.15.0 机器扫描摘要 3<!--claim:mod.total--> 6<!--claim:mod.files-->"
    _assert_current_summary(summary, scanned)
    for damaged in (
        summary.replace("3<!--claim:mod.total-->", "2<!--claim:mod.total-->"),
        summary.replace("6<!--claim:mod.files-->", "9<!--claim:mod.files-->"),
        summary + "3<!--claim:mod.total-->",
    ):
        with pytest.raises(AssertionError):
            _assert_current_summary(damaged, scanned)
    scanned[0].files += 1
    with pytest.raises(AssertionError):
        _assert_raw_scan(scanned)
