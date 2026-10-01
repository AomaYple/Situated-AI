"""闭环的**最后两步**：等官方套件判定 + 读它的产物（`自动化范式.md` §6）。

为什么这两步值得单独一组用例
----------------------------
在这之前它们是**手动**的，而"手动读成绩单"最容易犯的错恰好是**假红**与**假绿**
各一次（`自动化范式.md` §1.2 记着）：

* ``tests.txt`` 末尾那行 ``[ FAIL ] Error log: 85 errors`` 数的是**整份** `error.log`，
  而原版自己就有几十条噪音 ⇒ 照它判**每次假红**；
* 反过来，``failures == 0 and errors == 0`` 在**一个套件都没跑**时也为真
  ⇒ 那是**最危险的假绿**（"什么都没跑"读成"全过"）。

所以这一组的判据是"两种错都不许发生"，而不是"能不能解析 XML"。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pdx import game_auto as ga

pytestmark = pytest.mark.unit

#: 官方成绩单的**实测原文结构**（`自动化范式.md` §1.2 照录）。
_OK_XML = """<?xml version="1.0" ?>
<testsuites name="f30892c2-a29e-4bdf-98b4-35750343fe04_GameTests" \
tests="1" failures="0" errors="0" disabled="0">
\t<testsuite name="tools/scripted_tests/sitai_ab.txt" tests="1" failures="0" errors="0" disabled="0">
\t\t<testcase classname="smoke_harness_runs" name="" />
\t</testsuite>
</testsuites>
"""

#: ``error.log`` 里两类行的真实长相：原版噪音（左）与我们的（右）。
_NOISE = "[23:30:00][jomini_effect_impl.cpp:454]: common/script_values/00_infamy_values.txt:12: bad value"
_OURS = "[23:30:01][jomini_effect_impl.cpp:454]: common/scripted_effects/sitai_ru_defeat_effects.txt:7: unknown"


@pytest.fixture
def 产物(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """把成绩单、`tests.txt`、`error.log` 三处路径都指到临时目录，返回 `(xml, log)`。"""
    xml = tmp_path / "abc_GameTests_testoutput.xml"
    xml.write_text(_OK_XML, encoding="utf-8")
    log = tmp_path / "error.log"
    log.write_text(_NOISE + "\n", encoding="utf-8")
    tests_txt = tmp_path / "tests.txt"
    tests_txt.write_text("Tests:\n[ OK ] smoke_harness_runs ( 1836年2月2日 )\n", encoding="utf-8")
    monkeypatch.setattr(ga, "TESTS_TXT", tests_txt)
    monkeypatch.setattr(ga, "error_log_path", lambda: log)
    return xml, log


# ── 解析官方 XML（**只认官方那一种结构**）────────────────────────────


def test_解析官方成绩单(产物) -> None:
    xml, _log = 产物
    suites, tests, failures, errors = ga.parse_testoutput(xml)
    assert suites == ("tools/scripted_tests/sitai_ab.txt",)
    assert (tests, failures, errors) == (1, 0, 0)


def test_引擎判失败时读得出来(tmp_path: Path) -> None:
    xml = tmp_path / "bad.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<testsuites tests="1" failures="1" errors="0">\n'
        '\t<testsuite name="tools/scripted_tests/sitai_ab.txt" tests="1" failures="1" errors="0">\n'
        '\t\t<testcase classname="smoke_harness_runs" name=""><failure message="x" /></testcase>\n'
        "\t</testsuite>\n</testsuites>\n",
        encoding="utf-8",
    )
    _suites, tests, failures, _errors = ga.parse_testoutput(xml)
    assert (tests, failures) == (1, 1)


def test_属性缺失时数子元素而不是当零(tmp_path: Path) -> None:
    """官方两种来源都在格式里：属性缺了就数 `<testcase>`，**不许当 0**。"""
    xml = tmp_path / "noattr.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<testsuites><testsuite name="tools/scripted_tests/sitai_ab.txt">'
        '<testcase classname="a" name="" /><testcase classname="b" name=""><error /></testcase>'
        "</testsuite></testsuites>\n",
        encoding="utf-8",
    )
    suites, tests, failures, errors = ga.parse_testoutput(xml)
    assert suites == ("tools/scripted_tests/sitai_ab.txt",)
    assert (tests, failures, errors) == (2, 0, 1)


def test_根元素不是testsuites就报错(tmp_path: Path) -> None:
    xml = tmp_path / "wrong.xml"
    xml.write_text('<?xml version="1.0" ?>\n<testsuite name="x" />\n', encoding="utf-8")
    with pytest.raises(ga.GameAutoError, match="testsuites"):
        ga.parse_testoutput(xml)


def test_属性不是整数就报错(tmp_path: Path) -> None:
    """**不许猜**：读不出来就报错，别悄悄当成 0（那会变成假绿）。"""
    xml = tmp_path / "junk.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n<testsuites><testsuite name="x" tests="很多" />\n</testsuites>\n',
        encoding="utf-8",
    )
    with pytest.raises(ga.GameAutoError, match="不是整数"):
        ga.parse_testoutput(xml)


def test_不是XML就报错(tmp_path: Path) -> None:
    xml = tmp_path / "half.xml"
    xml.write_text("<testsuites><testsuite", encoding="utf-8")  # 只写了一半
    with pytest.raises(ga.GameAutoError, match="不是合法 XML"):
        ga.parse_testoutput(xml)


# ── "我们的报错"只数我们的（假红那一侧）────────────────────────────


def test_只数我们命名空间里的报错() -> None:
    lines = ga.our_error_lines("\n".join([_NOISE, _OURS, _NOISE]))
    assert lines == (_OURS,)


def test_mod名本身也算我们的() -> None:
    """`sitai_` 覆盖脚本/键名，`SITAI` 覆盖 mod 名 —— 挂载期的报错用的是后者。"""
    line = "[23:30:02][mod_system.cpp:1]: SITAI 处境档案 · 奥地利 · 革命潮 failed to mount"
    assert ga.our_error_lines(line) == (line,)


def test_原版噪音一条都不算(产物) -> None:
    xml, _log = 产物
    verdict = ga.read_verdict(xml)
    assert verdict.our_errors == ()
    assert verdict.ok is True


# ── 已知无害的那一类（B74）与轮转的 error.log（B85 第二次）─────────────

#: 引擎对每个 JE 的 `_goal` 槽都会写这么一句（B74 已定口径：上屏以 `_reason` 为准）。
_BENIGN = "[02:19:19][journal_entry_type.cpp:476]: Journal entry has redundant loc for je_sitai_ru_reform_window_goal"


def test_goal槽那句redundant算已知无害不算失败() -> None:
    """**分类，不是忽略**：它照实报出来（`benign_errors`），但不参与判定（B74 的口径）。"""
    text = "\n".join([_NOISE, _BENIGN, _OURS])
    assert ga.our_error_lines(text) == (_OURS,), "已知无害的那一类不该混进『我们的报错』"
    assert ga.benign_error_lines(text) == (_BENIGN,)

    verdict = ga.SuiteVerdict(
        xml=Path("x.xml"),
        suites=("s",),
        tests=1,
        failures=0,
        errors=0,
        our_errors=(),
        benign_errors=(_BENIGN,),
        error_log_read=True,
        tests_txt="",
    )
    assert verdict.ok is True, "9 条 `_goal` redundant 不该把整局判成不通过"
    assert "已知无害" in verdict.describe()
    assert verdict.as_dict()["suite_benign_errors"] == 1


def test_轮转的error日志也要读(产物, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """实测踩过（B85 第二次）：只读 `error.log` 那一份 ⇒ 被轮转走的行读不到，
    **"没看到"被当成了"没有"** —— 同一局的两种读法给出 0 条与 9 条。"""
    xml, _log = 产物
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.1.log").write_text(_BENIGN + "\n", encoding="utf-8")  # 旧的（轮转走了）
    (logs / "error.log").write_text(_OURS + "\n", encoding="utf-8")  # 当前
    monkeypatch.setattr(ga, "error_log_path", lambda: logs / "error.log")

    assert [p.name for p in ga.error_logs()] == ["error.1.log", "error.log"]
    verdict = ga.read_verdict(xml)
    assert len(verdict.our_errors) == 1, "当前那份里的真报错要读到"
    assert len(verdict.benign_errors) == 1, "轮转走的那份里的已知无害行也要读到"


def test_没有error日志时算读不到(产物, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    xml, _log = 产物
    monkeypatch.setattr(ga, "error_log_path", lambda: tmp_path / "logs" / "error.log")
    assert ga.error_logs() == []
    assert ga.read_verdict(xml).error_log_read is False


# ── 两条假绿都必须被挡住 ──────────────────────────────────────────


def test_我们有报错时不算通过(产物) -> None:
    xml, log = 产物
    log.write_text(_NOISE + "\n" + _OURS + "\n", encoding="utf-8")
    verdict = ga.read_verdict(xml)
    assert verdict.ok is False
    assert len(verdict.our_errors) == 1


def test_读不到errorlog时不算通过(产物) -> None:
    """**读不到 ≠ 没有**（与 `NO_TICK` 同一条纪律）—— 不许静默算通过。"""
    xml, log = 产物
    log.unlink()
    verdict = ga.read_verdict(xml)
    assert verdict.error_log_read is False
    assert verdict.ok is False
    assert "读不到 error.log" in verdict.describe()


def test_一个套件都没跑时不算通过(产物) -> None:
    """最危险的假绿：零失败 + 零套件。"""
    xml, _log = 产物
    xml.write_text(
        '<?xml version="1.0" ?>\n<testsuites tests="0" failures="0" errors="0" />\n',
        encoding="utf-8",
    )
    verdict = ga.read_verdict(xml)
    assert verdict.suites == ()
    assert verdict.ok is False
    assert "一个套件都没跑" in verdict.describe()


def test_判定输出带齐证据(产物) -> None:
    xml, _log = 产物
    verdict = ga.read_verdict(xml)
    text = verdict.describe()
    assert "通过 ✅" in text
    assert "sitai_ab.txt" in text
    flat = verdict.as_dict()
    assert flat["suite_ok"] is True
    assert flat["suite_our_errors"] == 0
    assert flat["suite_count"] == 1


# ── 等落盘：条件等待，不猜时长 ────────────────────────────────────


def test_等到新成绩单才返回(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = tmp_path / "old_GameTests_testoutput.xml"
    new = tmp_path / "new_GameTests_testoutput.xml"
    old.write_text(_OK_XML, encoding="utf-8")
    new.write_text(_OK_XML, encoding="utf-8")
    polls: list[int] = []

    def files() -> list[Path]:
        polls.append(len(polls))
        # 前两次轮询：只有上一局留下的那份（**不能**把它当这一局的）
        return [old] if len(polls) < 3 else [old, new]

    def fake_wait(predicate: object, **_kw: object) -> bool:
        return any(callable(predicate) and predicate() for _ in range(10))

    monkeypatch.setattr(ga, "testoutput_files", files)
    monkeypatch.setattr(ga, "wait_until", fake_wait)
    got = ga.wait_for_testoutput(frozenset({old}), timeout=1.0, poll=0.0)
    assert got == new
    assert len(polls) >= 3, "旧成绩单在时不许多等一次就返回"


def test_等不到新成绩单就报错(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ga, "testoutput_files", list)
    monkeypatch.setattr(ga, "wait_until", lambda *_a, **_kw: False)
    with pytest.raises(ga.GameAutoError, match="没等到新的官方成绩单"):
        ga.wait_for_testoutput(timeout=0.0)


def test_成绩单没写完就报错(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """引擎**先建文件再写内容**：读到半截 XML 会让人以为"格式变了"。"""
    xml = tmp_path / "x.xml"
    xml.write_text("<testsuites>", encoding="utf-8")
    monkeypatch.setattr(ga, "wait_until", lambda *_a, **_kw: False)
    with pytest.raises(ga.GameAutoError, match="没写完"):
        ga._wait_size_stable(xml, timeout=0.0)


def test_wait_for_verdict一步到位(产物, monkeypatch: pytest.MonkeyPatch) -> None:
    xml, _log = 产物
    monkeypatch.setattr(ga, "wait_for_testoutput", lambda *_a, **_kw: xml)
    verdict = ga.wait_for_verdict(timeout=1.0)
    assert verdict.ok is True
    assert verdict.xml == xml


# ── 接进闭环：`run_session` 的接线 ────────────────────────────────


def _stub_session(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    """把 `run_session` 的每一步都换成假的，只留接线本身可观测。"""

    def fake_start(*_a: object, **_kw: object) -> ga.SessionStart:
        calls.append("start")
        return _session()

    def fake_background(_hwnd: int, **kw: object) -> ga.Advance:
        calls.append(f"bg:restore={kw.get('restore')}")
        return _advance()

    def fake_verdict(*_a: object, **_kw: object) -> ga.SuiteVerdict:
        calls.append("verdict")
        return _verdict()

    monkeypatch.setattr(ga, "testoutput_files", list)
    monkeypatch.setattr(ga, "launch_to_foreground", lambda **_kw: (4242, 777))
    monkeypatch.setattr(ga, "wait_for_boot_settle", lambda **_kw: _settle())
    monkeypatch.setattr(ga, "start_session", fake_start)
    monkeypatch.setattr(ga, "background_ok", fake_background)
    monkeypatch.setattr(ga, "wait_for_verdict", fake_verdict)


def _advance() -> ga.Advance:
    return ga.Advance(
        advanced=True, before="1836.1.1", after="1836.2.1", seconds=8.0, source="stub"
    )


def _settle() -> ga.BootSettle:
    return ga.BootSettle(
        settled=True, waited=130.0, log_bytes=4096, quiet_seconds=21.0, processes=1, why="stub"
    )


def _verdict(*, failures: int = 0) -> ga.SuiteVerdict:
    return ga.SuiteVerdict(
        xml=Path("stub.xml"),
        suites=("tools/scripted_tests/sitai_ab.txt",),
        tests=1,
        failures=failures,
        errors=0,
        our_errors=(),
        benign_errors=(),
        error_log_read=True,
        tests_txt="[ OK ] smoke_harness_runs",
    )


def _session() -> ga.SessionStart:
    return ga.SessionStart(
        hwnd=4242,
        previous=777,
        settle=_settle(),
        observe=ga.Match(
            name="btn_observe", x=864, y=1055, score=0.98, scale=1.0, box=(755, 1037, 973, 1073)
        ),
        speed_source="模板匹配 (1851, 52)",
        speed_xy=(1851, 52),
        unpause="已按 space 开始推进",
        pressed=True,
        advance=_advance(),
        rate=3.0,
        rate_ok=True,
        attempts=1,
        handover=ga.ForegroundHandover(
            previous=777, after=777, restored=True, minimized=True, seconds=1.2
        ),
        tick="1836.1.8",
    )


def test_不等判定时不碰后台也不读产物(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_session(monkeypatch, calls)
    result = ga.run_session()
    assert calls == ["start"]
    assert result.background is None
    assert result.verdict is None


def test_等判定时先验后台再读产物(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _stub_session(monkeypatch, calls)
    result = ga.run_session(wait_tests=600.0)
    assert calls == ["start", "bg:restore=False", "verdict"]
    assert result.background is not None
    assert result.background.advanced is True
    assert result.verdict is not None
    assert result.verdict.ok is True
    flat = result.as_dict()
    assert flat["background_advanced"] is True
    assert flat["suite_ok"] is True


def test_不带scripted_tests时不等判定(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 `-scripted_tests` 就没有成绩单 —— 等了必然超时，所以直接不等。"""
    calls: list[str] = []
    _stub_session(monkeypatch, calls)
    ga.run_session(scripted_tests=False, wait_tests=600.0)
    assert calls == ["start"]


# ── CLI：判定不通过 ⇒ 退出码 1（不许只打印一句）──────────────────


def test_CLI判定不通过时退出码为1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ga, "run_session", lambda **_kw: _session_with(_verdict(failures=1)))
    assert ga.main(["run", "--wait-tests", "10"]) == 1


def test_CLI判定通过时退出码为0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ga, "run_session", lambda **_kw: _session_with(_verdict()))
    assert ga.main(["run", "--wait-tests", "10"]) == 0


def test_CLI不等判定时退出码只看点火(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ga, "run_session", lambda **_kw: _session())
    assert ga.main(["run"]) == 0


def _session_with(verdict: ga.SuiteVerdict) -> ga.SessionStart:
    """`SessionStart` 是 frozen 的 —— 后两步的结果只能 `replace` 挂上去。"""
    return dataclasses.replace(_session(), verdict=verdict)
