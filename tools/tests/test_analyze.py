"""全量分析的集成测试。

设计要点
--------
全量分析跑一次约 21 秒，因此用 **session 级 fixture 只跑一次**，
所有用例共享结果。这样既能覆盖完整流程，又不会让测试套件变得无法忍受。

覆盖的内容
----------
* 游戏本体分析：目录数、条目数、本地化、DLC、官方文档、原版前缀
* mod 分析：元数据、覆盖/新增划分、前缀统计
* 交叉分析：原版条目被改动情况
* 产物渲染：JSON 与 Markdown 能否生成且结构正确

这些断言不只验证「能跑通」，更把**已核实的关键数字**钉住 ——
一旦游戏升级或代码回归，测试会立刻失败。
"""

from __future__ import annotations

import json

import pytest

from pdx import analyze, config

pytestmark = pytest.mark.integration

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


# ── session 级共享结果 ──────────────────────────────────────
@pytest.fixture(scope="session")
def ga():
    """游戏本体分析结果（整轮只跑一次）。"""
    return analyze.game_analysis()


@pytest.fixture(scope="session")
def ma():
    return analyze.mods_analysis()


@pytest.fixture(scope="session")
def ca(ga, ma):
    return analyze.cross_analysis(ma)


# ── 游戏本体 ────────────────────────────────────────────────
@_needs_game
class TestGameAnalysis:
    def test_version_recorded(self, ga):
        assert ga.version["caligula_branch"]
        assert ga.version["caligula_rev"]
        assert ga.version["clausewitz_branch"]

    def test_all_three_content_roots(self, ga):
        assert set(ga.roots) == {"game", "jomini", "clausewitz"}

    def test_common_has_138_dirs(self, ga):
        """空目录也必须收录 —— scripted_modifiers 只有 .md 没有 .txt。"""
        assert len(ga.common) == 138

    def test_scripted_modifiers_present_but_empty(self, ga):
        res = ga.common["scripted_modifiers"]
        assert res.files == 0
        assert res.unique_entries == 0

    def test_total_entries_plausible(self, ga):
        total = sum(e.unique_entries for e in ga.common.values())
        assert total > 25000

    def test_known_dir_entry_counts(self, ga):
        """把已核实的关键数字钉住。"""
        known = {
            "buildings": 115,
            "laws": 138,
            "interest_groups": 8,
            "modifier_type_definitions": 2365,
            "static_modifiers": 6128,
            "character_templates": 2011,
            "production_methods": 436,
            "on_actions": 264,
        }
        for name, want in known.items():
            assert ga.common[name].unique_entries == want, name

    def test_no_variables_in_entries(self, ga):
        """@变量 不得混进条目 —— coat_of_arms 曾因此虚高 14 个。"""
        for name, res in ga.common.items():
            leaked = [k for k in res.entries if k.startswith("@")]
            assert not leaked, f"{name}: {leaked[:3]}"

    def test_vanilla_uses_no_prefixes(self, ga):
        """原版一处都不用功能前缀 —— 这套机制专供 mod。"""
        assert sum(ga.vanilla_prefixes.values()) == 0

    def test_localization_has_11_languages(self, ga):
        assert len(ga.localization) == 11

    def test_localization_keys_counted(self, ga):
        total = sum(v["键"] for v in ga.localization.values())
        assert total > 1_000_000

    def test_official_docs_94(self, ga):
        assert len(ga.official_docs) == 94

    def test_dlc_count(self, ga):
        assert len(ga.dlcs) == 17

    def test_dlc_have_no_script_dirs(self, ga):
        """实测全部 DLC 只装资产，脚本内容都在主体 game/common 里。"""
        offenders = [d.name for d in ga.dlcs if d.has_script_dir]
        assert offenders == []

    def test_checksummed_dirs_parsed(self, ga):
        assert "common" in ga.checksummed
        assert "localization" in ga.checksummed

    def test_paths_settings_parsed(self, ga):
        assert len(ga.paths) > 30

    def test_gui_files_found(self, ga):
        assert len(ga.gui_files) > 100

    def test_summary_shape(self, ga):
        s = ga.summary()
        for k in ("文件总计", "体积MB", "common 目录数", "官方md"):
            assert k in s


# ── 辅助视图 ────────────────────────────────────────────────
@_needs_game
class TestGameViews:
    def test_all_keys_sorted(self, ga):
        for _name, keys in list(ga.all_keys().items())[:20]:
            assert keys == sorted(keys)

    def test_all_fields_structure(self, ga):
        fields = ga.all_fields()
        assert len(fields) == len(ga.common) + len(ga.scripts)
        for _name, names in list(fields.items())[:10]:
            assert isinstance(names, list)
            assert names == sorted(names)

    def test_field_usage_nonempty(self, ga):
        usage = ga.field_usage()
        assert len(usage) > 100


# ── mod ─────────────────────────────────────────────────────
@_needs_game
class TestModsAnalysis:
    def test_mods_found(self, ma):
        assert len(ma.mods) >= 20

    def test_each_mod_has_target(self, ma):
        for m in ma.mods:
            assert m.target

    def test_metadata_parsed(self, ma):
        named = [m for m in ma.mods if m.name]
        assert len(named) >= 15

    def test_override_and_addition_partition(self, ma):
        """覆盖 + 新增 必须等于文件总数（跳过 .metadata）。"""
        for m in ma.mods:
            assert len(m.overrides) + len(m.additions) == m.files, m.target

    def test_no_metadata_in_manifest(self, ma):
        for m in ma.mods:
            for rel in m.overrides + m.additions:
                assert not rel.startswith(".metadata"), m.target

    def test_prefix_total(self, ma):
        assert sum(ma.prefixes.values()) > 2000

    def test_prefix_names_are_known(self, ma):
        from pdx.parser import PREFIXES

        for name in ma.prefixes:
            assert name in PREFIXES

    def test_by_class_populated(self, ma):
        for m in ma.mods:
            assert m.target in ma.by_class

    def test_path_conflicts_structure(self, ma):
        for path, mods in ma.path_conflicts.items():
            assert isinstance(path, str)
            assert len(mods) >= 1


# ── 交叉 ────────────────────────────────────────────────────
@_needs_game
class TestCrossAnalysis:
    def test_dir_touched_populated(self, ca):
        assert len(ca.dir_touched_by) > 0

    def test_changed_entries_have_mod_lists(self, ca):
        for entries in ca.changed_entries.values():
            for key, mods in entries.items():
                assert isinstance(key, str)
                assert len(mods) >= 1

    def test_mod_prefixes_recorded(self, ca):
        assert len(ca.mod_prefixes) > 0


# ── 序列化与渲染 ────────────────────────────────────────────
@_needs_game
class TestSerialization:
    def test_game_dict_is_jsonable(self, ga):
        d = analyze.to_game_dict(ga)
        text = json.dumps(d, ensure_ascii=False)
        assert len(text) > 1000
        back = json.loads(text)
        assert back["概览"]["common 目录数"] == 138

    def test_mods_dict_is_jsonable(self, ma):
        d = analyze.to_mods_dict(ma)
        back = json.loads(json.dumps(d, ensure_ascii=False))
        assert len(back["各mod"]) == len(ma.mods)

    def test_cross_dict_is_jsonable(self, ca):
        d = analyze.to_cross_dict(ca)
        back = json.loads(json.dumps(d, ensure_ascii=False))
        assert "概览" in back

    def test_game_dict_excludes_mod_content(self, ga):
        """游戏本体的产物里不能混入 mod 内容 —— 两者必须分开存储。"""
        d = analyze.to_game_dict(ga)
        assert "各mod" not in d
        assert "路径冲突" not in d

    def test_mods_dict_excludes_game_content(self, ma):
        d = analyze.to_mods_dict(ma)
        assert "common" not in d
        assert "DLC" not in d

    def test_markdown_renders(self, ga, ma, ca):
        g = analyze.render_game_markdown(ga)
        m = analyze.render_mods_markdown(ma, ca)
        assert "# Victoria 3 游戏本体全量分析" in g
        assert "# Victoria 3 Mod 全量分析" in m
        assert "mod" in g  # 交叉引用提示
        assert "游戏本体" in m


# ── 渲染细节（用合成数据，不需要游戏）──────────────────────
class TestRenderingUnit:
    """渲染函数的单元测试 —— 用最小合成对象，跑得快。"""

    def _empty_game(self):
        ga = analyze.GameAnalysis()
        ga.version = {"caligula_branch": "t", "clausewitz_branch": "t"}
        return ga

    def test_game_markdown_minimal(self):
        text = analyze.render_game_markdown(self._empty_game())
        assert "# Victoria 3 游戏本体全量分析" in text
        assert "联机校验和" in text

    def test_mods_markdown_minimal(self):
        text = analyze.render_mods_markdown(analyze.ModsAnalysis(), analyze.CrossAnalysis())
        assert "# Victoria 3 Mod 全量分析" in text
        assert "无冲突" in text

    def test_mods_markdown_with_conflict(self):
        ma = analyze.ModsAnalysis()
        ma.path_conflicts = {"a/b.txt": ["m1", "m2"]}
        text = analyze.render_mods_markdown(ma, analyze.CrossAnalysis())
        assert "a/b.txt" in text

    def test_classify_extensions(self):
        assert analyze.classify(".txt") == "脚本"
        assert analyze.classify(".yml") == "本地化"
        assert analyze.classify(".gui") == "界面"
        assert analyze.classify(".dds") == "图形"
        assert analyze.classify(".wav") == "音频"
        assert analyze.classify(".xyz") == "其他"
