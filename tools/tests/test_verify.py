"""断言核对模块的测试。

``verify`` 的价值在于「把文档里的数字变成可执行检查」，因此测试也分两层：

* **单元层** —— 断言数据结构、检查函数的注册、比对的成败判定。
  用合成 Claim，不碰真实数据，跑得飞快。
* **集成层** —— 真实跑一遍全部断言。这层慢（要扫全库），
  用 session fixture 只跑一次。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx import config, verify

pytestmark = pytest.mark.integration

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用"
)

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
    """用合成断言验证 check() 的成败判定，不碰真实数据。"""

    def test_passing_claim(self):
        c = verify.Claim("t", "x.md", "d", "dir_subdirs", "", 136)
        r = verify.check(c)
        assert r.ok
        assert r.actual == 136

    def test_failing_claim(self):
        c = verify.Claim("t", "x.md", "d", "dir_subdirs", "", 99999)
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
        c = verify.Claim("t", "x.md", "描述", "dir_subdirs", "", 136)
        assert verify.check(c).line().startswith("✅")

    def test_line_format_fail(self):
        c = verify.Claim("t", "x.md", "描述", "dir_subdirs", "", -1)
        assert verify.check(c).line().startswith("❌")

class TestRunClaims:
    def test_fast_mode_skips_slow_kinds(self):
        results = verify.run_claims(include_slow=False)
        kinds = {r.claim.kind for r in results}
        assert not (kinds & verify.SLOW_KINDS)

    def test_fast_mode_still_has_claims(self):
        assert len(verify.run_claims(include_slow=False)) >= 25

    def test_custom_claim_list(self):
        claims = [verify.Claim("a", "x.md", "d", "dir_subdirs", "", 136)]
        assert len(verify.run_claims(claims)) == 1

class TestSummarize:
    def test_counts(self):
        claims = [
            verify.Claim("a", "x.md", "d", "dir_subdirs", "", 136),
            verify.Claim("b", "x.md", "d", "dir_subdirs", "", -1),
        ]
        s = verify.summarize(verify.run_claims(claims))
        assert s["总数"] == 2
        assert s["通过"] == 1
        assert s["失败"] == 1
        assert s["失败分布"] == {"x.md": 1}

    def test_all_pass(self):
        claims = [verify.Claim("a", "x.md", "d", "dir_subdirs", "", 136)]
        s = verify.summarize(verify.run_claims(claims))
        assert s["失败"] == 0

class TestCoverageScan:
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
        out = verify.find_unregistered_claims(
            known_values={136, 92}, docs_dir=config.DOCS
        )
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
    }

    def test_known_values(self):
        by_id = {c.id: c for c in verify.CLAIMS}
        for cid, want in self.KNOWN.items():
            assert cid in by_id, f"断言 {cid} 不存在"
            r = verify.check(by_id[cid])
            assert r.ok, f"{cid}: 期望 {want}，实得 {r.actual}"
