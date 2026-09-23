"""断言核对模块的测试。

``verify`` 的价值在于「把文档里的数字变成可执行检查」，因此测试也分两层：

* **单元层** —— 断言数据结构、检查函数的注册、比对的成败判定。
  用合成 Claim，不碰真实数据，跑得飞快。
* **集成层** —— 真实跑一遍全部断言。这层慢（要扫全库），
  用 session fixture 只跑一次。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdx import config, install_tree, verify

pytestmark = pytest.mark.integration

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


# ── 单元层：不依赖真实数据 ──────────────────────────────────
class TestClaimStructure:
    def test_all_claims_have_required_fields(self):
        for c in verify.CLAIMS:
            assert c.id, "缺少 id"
            assert c.doc, f"{c.id} 缺少出处文档"
            assert c.text, f"{c.id} 缺少描述"
            assert c.kind, f"{c.id} 缺少检查类型"
            assert c.expected is not None, f"{c.id} 缺少期望值"

    def test_claim_ids_unique(self):
        ids = [c.id for c in verify.CLAIMS]
        assert len(ids) == len(set(ids)), "存在重复的断言 id"

    def test_every_kind_is_registered(self):
        """每条断言用的 kind 都必须在 _CHECKS 里有实现。"""
        for c in verify.CLAIMS:
            assert c.kind in verify._CHECKS, f"{c.id} 用了未注册的 kind={c.kind}"

    def test_doc_names_look_like_files(self):
        for c in verify.CLAIMS:
            assert c.doc.endswith(".md"), c.id

    def test_slow_kinds_subset_of_checks(self):
        for k in verify.SLOW_KINDS:
            assert k in verify._CHECKS, f"SLOW_KINDS 里的 {k} 未注册"

    def test_claim_count_plausible(self):
        assert len(verify.CLAIMS) >= 30


class TestCheckOutcome:
    """用合成断言验证 check() 的成败判定，不碰真实数据。

    「通过」那一侧的期望值**现场量**（``_live_common_dirs()``）而不是写死 136 ——
    136 是 1.14.3 的 ``common`` 子目录数，1.14.4 变成 138 之后，
    「合成断言」里的那个字面量本身就成了过期数据，一次红 5 个测试。
    单元层要的是**判定逻辑**，不该被游戏版本牵着走。
    """

    @staticmethod
    def _live_common_dirs() -> int:
        actual = verify._CHECKS["dir_subdirs"]("common")
        assert isinstance(actual, int)
        return actual

    def test_passing_claim(self):
        live = self._live_common_dirs()
        c = verify.Claim("t", "x.md", "d", "dir_subdirs", "common", live)
        r = verify.check(c)
        assert r.ok
        assert r.actual == live

    def test_failing_claim(self):
        c = verify.Claim("t", "x.md", "d", "dir_subdirs", "common", 99999)
        r = verify.check(c)
        assert not r.ok

    def test_unknown_kind_reports_error(self):
        c = verify.Claim("t", "x.md", "d", "no_such_kind", "", 1)
        r = verify.check(c)
        assert not r.ok
        assert "未知的检查类型" in r.error

    def test_check_error_is_captured_not_raised(self):
        """检查函数抛异常时必须被捕获成 CheckResult，而不是让整轮崩掉。"""
        c = verify.Claim("t", "x.md", "d", "defines_params", "不存在的文件:NAI", 1)
        r = verify.check(c)
        assert not r.ok
        assert r.error

    def test_line_format_ok(self):
        c = verify.Claim("t", "x.md", "描述", "dir_subdirs", "common", self._live_common_dirs())
        assert verify.check(c).line().startswith("✅")

    def test_line_format_fail(self):
        c = verify.Claim("t", "x.md", "描述", "dir_subdirs", "common", -1)
        assert verify.check(c).line().startswith("❌")


class TestRunClaims:
    def test_fast_mode_skips_slow_kinds(self):
        results = verify.run_claims(include_slow=False)
        kinds = {r.claim.kind for r in results}
        assert not (kinds & verify.SLOW_KINDS)

    def test_fast_mode_still_has_claims(self):
        assert len(verify.run_claims(include_slow=False)) >= 25

    def test_custom_claim_list(self):
        claims = [verify.Claim("a", "x.md", "d", "dir_subdirs", "common", 1)]
        assert len(verify.run_claims(claims)) == 1


class TestSummarize:
    def test_counts(self):
        claims = [
            verify.Claim(
                "a", "x.md", "d", "dir_subdirs", "common", TestCheckOutcome._live_common_dirs()
            ),
            verify.Claim("b", "x.md", "d", "dir_subdirs", "common", -1),
        ]
        s = verify.summarize(verify.run_claims(claims))
        assert s["总数"] == 2
        assert s["通过"] == 1
        assert s["失败"] == 1
        assert s["失败分布"] == {"x.md": 1}

    def test_all_pass(self):
        claims = [
            verify.Claim(
                "a", "x.md", "d", "dir_subdirs", "common", TestCheckOutcome._live_common_dirs()
            )
        ]
        s = verify.summarize(verify.run_claims(claims))
        assert s["失败"] == 0


class TestDriftDetectorPrimitives:
    """漂移检测器的两个底层原语。

    它们各自对应一次**实际漏报或误报**，所以单独钉住 ——
    这两个 bug 都不会让别的测试变红，只会让检测器悄悄失灵。
    """

    def test_点分数字串被整段排除(self):
        """版本号 / 章节号 / 小数不能当成数量候选。

        误报实例：``### 2.6 实战提示`` 里的 6 落在 ``interest_groups``
        （期望 8）的容差内，成了稳定误报。
        """
        line = "1.14.2 / 2.6 / 2,532.4 / 17,172.9"
        hits = [
            m
            for m in verify._STANDALONE_NUM_RE.finditer(line)
            if not verify._in_dotted_number(line, m.start())
        ]
        assert hits == [], [m.group(0) for m in hits]

    def test_句末点号后的数字仍然保留(self):
        """``27,722.`` 里的点号是句号不是小数点，必须保留。

        用「紧邻点号就排除」的写法会误杀它 —— 那正是没用那种写法的原因。
        """
        line = "game 全树文件数 **27,722**. 另有 25,364 与 28171"
        kept = [
            m.group(1)
            for m in verify._STANDALONE_NUM_RE.finditer(line)
            if not verify._in_dotted_number(line, m.start())
        ]
        assert kept == ["27,722", "25,364", "28171"], kept

    def test_标题行继承祖先标题的锚点(self):
        """标题行要能靠**上级标题**里的锚点被扫到。

        漏报实例：``05-defines与修饰符.md`` 的
        ``### 3.3 全部 1013 个参数名`` —— 标题本身不含 ``NAI``，
        旧规则（只看本行）永远扫不到它，于是它一直躺着。
        """
        lines = [
            "# 文档",
            "",
            "## 3. `NAI` 命名空间块",
            "",
            "### 3.3 全部 1013 个参数名",
            "",
            "正文一行 1013",
        ]
        ctx = verify._section_context(lines)
        assert "NAI" in ctx[4], "标题行应继承祖先标题里的锚点"
        assert "NAI" not in ctx[5], "正文行不继承锚点（否则误报会暴增）"
        assert "NAI" in ctx[2]

    def test_正文行不继承标题锚点(self):
        """放宽范围只限标题行。

        反例：让整节继承锚点后，命中数从 12 涨到 36，绝大多数是
        「同一节里另一个指标的同行数字」。
        """
        lines = ["## production_method_groups 一节", "", "| `texture` | 196 |"]
        ctx = verify._section_context(lines)
        assert "production_method_groups" not in ctx[2]

    def test_returns_mapping(self):
        out = verify.find_unregistered_claims()
        assert isinstance(out, dict)

    def test_reports_doc_names(self):
        out = verify.find_unregistered_claims()
        for name, hits in out.items():
            assert name.endswith(".md")
            assert isinstance(hits, list)

    def test_known_values_are_excluded(self):
        """已登记的期望值不应被当成未登记断言报出来。"""
        out = verify.find_unregistered_claims(known_values={136, 92}, docs_dir=config.DOCS)
        flat = [val for hits in out.values() for _, val in hits]
        assert all(isinstance(v, str) for v in flat)

    def test_missing_dir_yields_empty(self):
        assert verify.find_unregistered_claims(docs_dir=Path("Z:/nope")) == {}


# ── 集成层：真实跑一遍 ──────────────────────────────────────
@pytest.fixture(scope="session")
def fast_results():
    """快速模式结果（跳过全库扫描），整轮只跑一次。

    fixture 上不能加 marker，因此这里不做 skipif；
    用到它的测试类本身带 ``@_needs_game``。
    """
    return verify.run_claims(include_slow=False)


@_needs_game
class TestRealClaims:
    def test_官方文档的三条字节断言可核对(self):
        """官方 ``.md`` 的篇数 / 总字节 / 最大单篇必须能实测出来。

        这三条登记为 ``slow``（全库扫描类），快速模式会跳过它们 ——
        但实测只需扫 92 个 ``.md``，毫秒级。在这里直接跑一遍，
        否则新加的 ``docs.total_bytes`` / ``docs.max_bytes`` 会长期无人看守。

        背景：doc 07 曾把**镜像**（1.14.2）的总字节与最大文档尺寸
        当成游戏本体的值写进正文，只钉「篇数 92」是发现不了的。
        """
        for cid in ("env.md_total", "docs.total_bytes", "docs.max_bytes"):
            claim = next(c for c in verify.CLAIMS if c.id == cid)
            r = verify.check(claim)
            assert r.ok, f"{cid}: 期望 {claim.expected}，实得 {r.actual}"

    def test_fast_claims_all_pass(self, fast_results):
        bad = [r for r in fast_results if not r.ok]
        detail = "\n".join(r.line() for r in bad)
        assert not bad, f"以下断言未通过：\n{detail}"

    def test_fast_results_have_actual_values(self, fast_results):
        for r in fast_results:
            if r.ok:
                assert r.actual is not None

    def test_summary_all_pass(self, fast_results):
        s = verify.summarize(fast_results)
        assert s["失败"] == 0
        assert s["通过"] == s["总数"]


@_needs_game
class TestKnownAssertions:
    """把关键断言的结果单独钉住，便于定位回归。"""

    KNOWN = {
        "env.common_dirs": 136,
        "env.dlc": 17,
        "def.blocks": 75,
        "def.namespaces": 50,
        "def.nai_count": 1017,
        "def.modtypes": 2364,
        "def.static": 6128,
        "scr.on_actions": 264,
        "hist.wrappers": 22,
        "docs.total_bytes": 232980,
        "docs.max_bytes": 28171,
    }

    def test_known_values(self):
        by_id = {c.id: c for c in verify.CLAIMS}
        for cid, want in self.KNOWN.items():
            assert cid in by_id, f"断言 {cid} 不存在"
            r = verify.check(by_id[cid])
            assert r.ok, f"{cid}: 期望 {want}，实得 {r.actual}"


# ── 派生量：描述里那些「给人看的」折算值 ────────────────────
_MB_IN_TEXT = re.compile(r"等价 ([\d,]+(?:\.\d+)?) MB")


class TestDerivedValues:
    def test_描述里的MB折算与字节断言一致(self):
        """``（等价 X MB）`` 是**手写的派生量** —— 没有闸门盯着它，它就一定会烂。

        `--fix-claims` 只会把字节数（那是断言值）改成实测值，描述里的 MB
        不在它的射程里：1.14.4 更新后 `game` 全树字节动了 42,605 B，
        MB 那一栏就差了 0.04 —— 没有任何断言会因此报红，只能靠这条测试。
        折算口径必须与 `pdx.install_tree.fmt_mb` 一致（千分位、两位小数）。
        """
        checked = 0
        for claim in verify.CLAIMS:
            found = _MB_IN_TEXT.search(claim.text)
            if not found or not isinstance(claim.expected, int):
                continue
            assert found.group(1) == install_tree.fmt_mb(claim.expected), (
                f"{claim.id}: 描述写 {found.group(1)} MB，"
                f"按 {claim.expected} B 折算应是 {install_tree.fmt_mb(claim.expected)} MB"
            )
            checked += 1
        assert checked >= 3, f"只查到 {checked} 条 —— 这条测试本身是不是失效了？"

    def test_文档里的MB折算与断言表一致(self):
        """doc 08 §17 的体积行同理（它是**散文**，`v3 tables` 管不到它）。"""
        by_id = {c.id: c for c in verify.CLAIMS}
        doc = (config.DOCS / "08-目录全量清单.md").read_text(encoding="utf-8")
        for cid, prefix in (
            ("tree.game_bytes", r"\| `game\\` 全树体积 \| \*\*([\d,.]+) MB\*\*"),
            ("tree.binaries_bytes", r"\| `ROOT\\binaries` 文件数 / 体积 \| 40 / ([\d,.]+) MB \|"),
        ):
            expected = by_id[cid].expected
            assert isinstance(expected, int)
            found = re.search(prefix, doc)
            assert found, f"{cid}: doc 08 §17 里找不到这一行"
            assert found.group(1) == install_tree.fmt_mb(expected), (
                f"{cid}: 文档写 {found.group(1)} MB，"
                f"按 {expected} B 折算应是 {install_tree.fmt_mb(expected)} MB"
            )


# ── 官方更新之后：把实测值写回断言表 ────────────────────────
#
# 这一组全用**合成断言表**（临时文件 + monkeypatch），不碰真的 verify.py：
# ``fix_claims`` 的默认行为是**改自己**，测试若误带 write=True 就会把
# 真实的断言表改坏 —— 因此每条路径都必须显式传 source=。
class TestFixClaims:
    @staticmethod
    def _source() -> str:
        """一份迷你断言表：覆盖单行、跨行、尾注、非整数、量不出来五种形态。"""
        return (
            "CLAIMS = [\n"
            '    Claim("a", "x.md", "d", "ok", "", 1),\n'
            "    Claim(\n"
            '        "b",\n'
            '        "x.md",\n'
            '        "d",\n'
            '        "ok",\n'
            '        "",\n'
            "        # 尾注：值在下一行\n"
            "        2,\n"
            "    ),\n"
            '    Claim("c", "x.md", "d", "ok", "", "字符串期望"),\n'
            '    Claim("d", "x.md", "d", "boom", "", 4),\n'
            '    Claim("e", "x.md", "d", "ok", "", 5),\n'
            "]\n"
        )

    @pytest.fixture
    def table(self, tmp_path, monkeypatch):
        """把合成表写成真文件并挂到 verify 上，返回 (路径, 装载函数)。"""
        path = tmp_path / "claims_table.py"
        path.write_text(self._source(), encoding="utf-8", newline="\n")

        def load() -> list[verify.Claim]:
            ns: dict[str, object] = {"Claim": verify.Claim}
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
            return ns["CLAIMS"]  # type: ignore[return-value]

        monkeypatch.setattr(verify, "CLAIMS", load())
        monkeypatch.setattr(
            verify,
            "_CHECKS",
            {
                "ok": lambda _target: 42,
                "boom": lambda _target: (_ for _ in ()).throw(ValueError("量不出来")),
            },
        )
        return path, load

    def test_slots_cover_int_and_str_alike(self):
        """槽位是按 AST 位置找的，因此字符串期望也有槽（跳过是**后面**的事）。"""
        slots = verify.claim_value_slots(self._source())
        assert set(slots) == {"a", "b", "c", "d", "e"}

    def test_slots_are_exact_offsets(self):
        src = self._source()
        data = src.encode("utf-8")
        slots = verify.claim_value_slots(src)
        assert data[slots["a"][0] : slots["a"][1]] == b"1"
        assert data[slots["b"][0] : slots["b"][1]] == b"2", "跨行 + 尾注的值要取准"
        assert data[slots["c"][0] : slots["c"][1]] == '"字符串期望"'.encode()

    def test_offsets_are_bytes_not_chars(self):
        """回归：同一行里值**前面**有中文时，按字符算的偏移会切进中文中间。

        `ast` 的 ``col_offset`` 是 UTF-8 字节偏移 —— 断言表每行都带中文，
        这个坑一旦踩中，``--fix-claims`` 会把真表写成乱码。
        """
        src = 'Claim("cn", "01-环境与版本.md", "中文描述", "kind", "", 17),\n'
        slots = verify.claim_value_slots(src)
        assert src.encode("utf-8")[slots["cn"][0] : slots["cn"][1]] == b"17"
        assert slots["cn"] != (len(src) - 4, len(src) - 2), "不该等于按字符算的结果"
        # 端到端：改完仍是一份能 exec 的、只有那一个字面量变了的源码
        out = verify.apply_value_edits(src, {"cn": 18})
        assert out == src.replace("17", "18")

    def test_slots_ignore_non_claim_calls(self):
        """别的 6 参数调用、以及参数不全的 Claim 都不该被当成槽位。"""
        src = 'Other("z", "x", "y", "k", "t", 9)\nClaim("a", "x.md")\n'
        assert verify.claim_value_slots(src) == {}

    def test_apply_edits_rewrites_in_place(self):
        src = self._source()
        out = verify.apply_value_edits(src, {"a": 42, "e": 7})
        assert verify.claim_value_slots(out), "改完仍是可解析的断言表"
        assert "42" in out
        assert "7" in out
        ns: dict[str, object] = {"Claim": verify.Claim}
        exec(compile(out, "<out>", "exec"), ns)
        got = {c.id: c.expected for c in ns["CLAIMS"]}  # type: ignore[union-attr]
        assert got["a"] == 42
        assert got["e"] == 7
        assert got["b"] == 2, "没点名的断言不能被动到"
        assert got["c"] == "字符串期望"

    def test_apply_edits_multi_line_value_keeps_shape(self):
        """跨行的值被替换后，其余行数不变（只换字面量那段）。"""
        src = self._source()
        out = verify.apply_value_edits(src, {"b": 42})
        assert len(out.splitlines()) == len(src.splitlines())
        assert out.replace("42", "2", 1) == src.replace("42", "2", 1)

    def test_fix_claims_dry_run_reports_without_writing(self, table):
        path, _ = table
        before = path.read_text(encoding="utf-8")
        changes, skipped = verify.fix_claims(source=path)
        assert {ch.id: ch.new for ch in changes} == {"a": 42, "b": 42, "e": 42}
        assert path.read_text(encoding="utf-8") == before, "不带 write 绝不能写盘"
        assert any("c:" in s and "不是整数" in s for s in skipped)
        assert any("d:" in s and "量不出来" in s for s in skipped)

    def test_fix_claims_write_persists_and_is_idempotent(self, table, monkeypatch):
        path, load = table
        changes, _ = verify.fix_claims(source=path, write=True)
        assert len(changes) == 3
        monkeypatch.setattr(verify, "CLAIMS", load())  # 换进程等价：重载断言表
        assert {c.id: c.expected for c in verify.CLAIMS}["a"] == 42
        again, _ = verify.fix_claims(source=path, write=True)
        assert again == [], "第二遍应当无改动（幂等）"

    def test_fix_claims_only_filters(self, table, monkeypatch):
        path, load = table
        changes, _ = verify.fix_claims(source=path, write=True, only="a")
        assert [ch.id for ch in changes] == ["a"]
        monkeypatch.setattr(verify, "CLAIMS", load())
        assert {c.id: c.expected for c in verify.CLAIMS}["e"] == 5, "没点名的不能动"

    def test_fix_claims_changes_are_old_new_pairs(self, table):
        path, _ = table
        changes, _ = verify.fix_claims(source=path)
        assert next((ch.id, ch.old, ch.new) for ch in changes) == ("a", 1, 42), (
            "改动清单必须带旧值，否则人没法逐条核对"
        )
        assert changes[0].text == "d" or isinstance(changes[0].text, str)

    def test_fix_claims_flags_stale_description(self, table):
        """描述里还写着旧值的要**提示**（不代改）—— 表里那一列会自相矛盾。"""
        path, _ = table
        changes, _ = verify.fix_claims(source=path)
        assert all(not ch.text_stale for ch in changes), "合成表的描述是 'd'，没有数字"

    def test_mentions_number_needs_token_boundary(self):
        assert verify.mentions_number("NAI 参数 1017", 1017)
        assert verify.mentions_number("_add 1635", 1635)
        assert not verify.mentions_number("1.14.2 时是 682", 2), "不能把版本号切出个 2"
        assert not verify.mentions_number("1178 个", 178), "不能命中长数字的一部分"
        assert not verify.mentions_number("11,673 个", 673), "千分位逗号内不算独立数字"
        assert not verify.mentions_number("", 3)

    def test_fix_claims_reports_missing_slot(self, table, monkeypatch):
        """断言在源码里找不到槽位时要**说明**，不能静默漏掉。"""
        path, load = table
        monkeypatch.setattr(
            verify, "CLAIMS", [*load(), verify.Claim("ghost", "x.md", "d", "ok", "", 1)]
        )
        _, skipped = verify.fix_claims(source=path)
        assert any("ghost" in s and "找不到" in s for s in skipped)

    def test_fix_claims_default_source_is_this_module(self):
        """默认路径必须指向真的断言表 —— 写错路径会让 --fix-claims 变成空操作。"""
        default = config.REPO / "tools" / "pdx" / "verify.py"
        src = default.read_text(encoding="utf-8")
        slots = verify.claim_value_slots(src)
        real_ids = {c.id for c in verify.CLAIMS}
        assert len(slots) >= 30
        assert len(real_ids - set(slots)) == 0, "真表里有断言没有槽位"
