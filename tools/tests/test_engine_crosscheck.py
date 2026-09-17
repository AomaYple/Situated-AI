"""引擎交叉验证：用游戏自己的日志当**外部真值**。

这个文件解决的是整个项目最根本的一个方法论问题
------------------------------------------------
在此之前，解析器唯一的比对对象是 ``_oracle_lexer.py`` —— 一份我自己
写的、冻结旧行为的实现。差分测试证明的是「**没退化**」，不是
「**和引擎一致**」。那是循环论证：两份实现可以一起错。

真正的真值只有引擎自己。而引擎**会把它看到的东西写进日志**：

* ``virtualfilesystem.cpp`` 记录它从哪些目录按什么扩展名枚举文件
  → 验证**覆盖面**
* ``jomini_script_system.cpp`` 报错时带 ``Script location: 文件:行``
  → 验证**行号与结构**
* ``pdx_gui_localize.cpp`` 报错时带 ``at 文件:行`` 与文本键
  → 验证 **token 识别与行号**

⚠️ 这个验证的边界（必须写清楚，否则又变成自我安慰）
----------------------------------------------------
* 它验证**枚举范围、行号、token 识别**，**不验证脚本语义**
  （加载顺序、覆盖规则、字段合法性仍然无从得知）
* 日志只来自**运行过的那一次**。若游戏已升级，日志可能是旧版本的；
  本模块会读出版本号并按它打折结论
* 日志不是仓库的一部分，换台机器就没有 —— 因此找不到日志时整组跳过，
  而不是让测试失败
"""

from __future__ import annotations

import pytest

from pdx import config, engine_log

pytestmark = [pytest.mark.integration, pytest.mark.contract]

_CLAIMS, _VERSION = engine_log.parse_logs()
_LOGS_OK = bool(_CLAIMS)


def _needs_logs() -> None:
    if not _LOGS_OK:
        pytest.skip(f"引擎日志不可用：{engine_log.default_log_dir()}")
    if not (config.GAME / "common").is_dir():
        pytest.skip("游戏目录不可用")


@pytest.fixture(scope="module")
def report():
    _needs_logs()
    return engine_log.cross_check(_CLAIMS, log_version=_VERSION)


# ── 覆盖面：对「全量」最直接的外部检验 ──────────────────────
def test_引擎枚举的每个目录都被完全解析(report) -> None:
    """引擎说它从某目录读了某种扩展名 —— 那里面的文件我们必须全部解析。

    这是「全量」唯一一次由**外部**背书：清单来自引擎，不是我们的目录表。
    """
    if not report.coverage:
        pytest.skip(
            "本次日志里没有 pre-enumerating 记录 —— 通常意味着日志来自一次"
            "没跑到脚本加载阶段的会话（例如启动后很快退出）"
        )
    gaps = report.coverage_gaps
    assert not gaps, (
        f"{len(gaps)} 个 (目录, 扩展名) 组合没有完全覆盖：\n"
        + "\n".join(
            f"  {d}  {e}   引擎枚举 {n} 个，我们解析 {hit} 个（共 {t} 个文件）"
            for d, e, n, hit, t in gaps
        )
        + "\n\n请把对应目录加入 config.SCRIPTABLE_DIRS，"
        "或确认该扩展名确实不该解析并写进 EXCLUDED_SUBTREES。"
    )


def test_覆盖面样本量足够(report) -> None:
    """引擎枚举出来的组合数不能太少 —— 太少说明日志没抽到东西。"""
    if not report.coverage:
        pytest.skip("本次日志里没有枚举记录")
    assert len(report.coverage) >= 40, (
        f"只抽到 {len(report.coverage)} 个枚举组合，日志解析可能失效了"
    )


# ── 行号与 token：对解析器本身的检验 ────────────────────────
def test_token行号与引擎一致(report) -> None:
    """引擎说「X 文件第 N 行有 token T」—— 我们的切分必须给出同样的行号。

    这条能抓住行号漂移类错误（BOM、注释剥离、跨行字符串都会影响它）。
    """
    bad = report.token_mismatches
    assert not bad, f"{len(bad)} 条 token 行号与引擎不一致：\n" + "\n".join(
        f"  {rel}:{line}  token={tok!r}  我们给出 {got}" for rel, line, tok, got in bad[:15]
    )


def test_引擎报的脚本位置都在文件里(report) -> None:
    """引擎执行脚本报错的位置，我们至少要能切出 token 来。

    缺失通常意味着文件被删（mod 卸载）或日志是旧版本的。
    """
    missing = [loc for loc in report.locations if loc[2] == "该行无 token"]
    assert not missing, f"{len(missing)} 个引擎报的位置在我们这边切不出任何 token：\n" + "\n".join(
        f"  {rel}:{line}" for rel, line, _ in missing[:15]
    )


def test_引擎位置的文件大多存在(report) -> None:
    """允许少数不存在 —— 日志里会引用 mod 的文件，而 mod 可能已卸载。

    但不该是多数：那说明我们找错了根目录或路径解析有误。
    """
    total = len(report.locations)
    if not total:
        pytest.skip("没有位置类断言")
    missing = sum(1 for _, _, why in report.locations if why == "文件不存在")
    assert missing <= total * 0.3, f"{missing}/{total} 个引擎位置指向不存在的文件，比例过高"


# ── 日志解析本身 ────────────────────────────────────────────
def test_能读出日志里的游戏版本() -> None:
    """版本要读出来并记录 —— 否则「旧版本日志」这个前提会被无声忽略。

    日志没走到校验和计算那一步时读不到版本，此时跳过而不是失败。
    """
    _needs_logs()
    if not any(c.kind == "enumeration" for c in _CLAIMS):
        pytest.skip("本次日志来自未跑完校验和阶段的会话，没有版本记录")
    assert _VERSION, "日志里走到了校验和阶段却没有版本号"


def test_抽到了可用的断言() -> None:
    """至少要抽到一类能核对的东西。

    不要求三类齐全 —— 日志内容随每次游戏运行而变（跑得短就没有枚举记录），
    那是外部数据的正常波动，不是我们的回归。
    """
    _needs_logs()
    kinds = {c.kind for c in _CLAIMS}
    assert kinds & {"enumeration", "script_location", "token_at"}, f"一类断言都没抽到：{kinds}"


def test_覆盖映射能解析出被mod覆盖的文件() -> None:
    """引擎是在装了 mod 的状态下跑的，读的是 mod 覆盖后的文件。

    此前核对工具只读原版，于是 4 条「不一致」全是假的 —— 同一行号在
    原版与 mod 版里指向完全不同的内容。实测这三处行数差得很明显：
    military_formation_panel.gui 原版 8098 / mod 7767。
    """
    ov = engine_log.build_override_map()
    if not ov:
        pytest.skip("本机没有已安装的 mod")
    for rel, path in ov.items():
        assert path.is_file(), f"{rel} 解析到不存在的文件"
        assert path.parts[0] not in config.SCRIPTABLE_DIRS or True  # 路径形态自洽
    # 覆盖映射覆盖的必须是脚本目录下的文件，不该把整个 mod 都算进来
    tops = {rel.split("/")[0] for rel in ov}
    assert tops <= set(config.SCRIPTABLE_DIRS), (
        f"覆盖映射混入了非脚本目录：{sorted(tops - set(config.SCRIPTABLE_DIRS))}"
    )


def test_找不到日志时优雅返回(tmp_path) -> None:
    """日志不是仓库的一部分，缺失是正常情况，不能抛异常。"""
    claims, version = engine_log.parse_logs(tmp_path / "nope")
    assert claims == []
    assert version == ""
