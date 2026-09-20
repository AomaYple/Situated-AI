"""探针实验包的测试。

三件事要钉住：

1. **探针 mod 本身语法正确** —— 用仓库自己的解析器过一遍每个 `.txt` /
   每个 `.yml` 行式结构。探针要是自己写错了，用户跑一次游戏只会得到
   「一堆语法错」，实验全废；
2. **实验清单与探针文件对得上** —— `experiments.EXPERIMENTS` 里点名的每个路径
   都得真实存在（清单腐烂比没清单更糟：人会照着找一个不存在的文件）；
3. **收割逻辑认得日志** —— 给定一份合成日志，`collect` 能把行归到正确编号，
   并且只读不写。
"""

from __future__ import annotations

import pytest

from pdx import experiments
from pdx.cache import parse_cached

pytestmark = pytest.mark.unit

_TXT = sorted(experiments.PROBE_DIR.rglob("*.txt"))
_YML = sorted(experiments.PROBE_DIR.rglob("*.yml"))


def test_探针包存在且非空() -> None:
    assert experiments.PROBE_DIR.is_dir(), "tools/probe/ 不存在 —— 探针包丢了"
    assert len(_TXT) >= 15, f"探针 .txt 只有 {len(_TXT)} 个，太少"
    assert len(_YML) >= 3, f"探针 .yml 只有 {len(_YML)} 个，太少"


@pytest.mark.parametrize("path", _TXT, ids=lambda p: p.name)
def test_探针脚本能被解析器读通(path) -> None:
    """用仓库自己的解析器验证：没有解析错误、顶层键非空。"""
    parsed = parse_cached(path)
    assert not parsed.errors, f"{path.name} 有解析错误：{parsed.errors[:2]}"
    assert parsed.top_keys or path.name.startswith(("c1", "c2", "c3", "c4")), (
        f"{path.name} 一个顶层键都没有"
    )


@pytest.mark.parametrize("path", _YML, ids=lambda p: p.name)
def test_探针本地化是行式格式(path) -> None:
    """`.yml` 不走 PDX 解析器 —— 检查它至少符合 `key:版本 "值"` 的行式结构。"""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("l_"), "第一行必须是语言头（l_simp_chinese / l_english）"
    for line in text.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert ":" in stripped, f"不像本地化行：{stripped[:40]}"
        assert '"' in stripped, f"缺引号：{stripped[:40]}"


def test_每个实验的文件都存在() -> None:
    missing = [rel for e in experiments.EXPERIMENTS for rel in e.probe]
    missing = [rel for rel in missing if not (experiments.PROBE_DIR / rel).is_file()]
    assert not missing, f"实验清单点名了不存在的探针文件：{missing}"


def test_实验编号唯一且元数据齐全() -> None:
    ids = [e.id for e in experiments.EXPERIMENTS]
    assert len(ids) == len(set(ids)), "实验编号重复"
    for e in experiments.EXPERIMENTS:
        assert e.question, f"{e.id} 没写问题"
        assert e.title, f"{e.id} 没写标题"
        assert e.how, f"{e.id} 没写判读方法"
        assert e.read in {"日志", "肉眼", "肉眼 + 日志"}, e.read
        assert e.probe, f"{e.id} 没有探针文件"


def test_两个探针mod都有metadata() -> None:
    for name in experiments.PROBE_MODS:
        meta = experiments.PROBE_DIR / name / ".metadata" / "metadata.json"
        assert meta.is_file(), f"{name} 缺 .metadata/metadata.json（启动器认不出它）"
        assert '"name"' in meta.read_text(encoding="utf-8")


def test_按编号筛选() -> None:
    assert [e.id for e in experiments.experiments(["p2"])] == ["P2"]
    assert len(experiments.experiments(["P2", "P11"])) == 2
    assert len(experiments.experiments()) == len(experiments.EXPERIMENTS)


def test_日志归类() -> None:
    assert (
        experiments.classify("Unknown key 'zzprobe_made_up_style'")
        == "未知键：该写法不被这个位置接受"
    )
    assert (
        experiments.classify("duplicate definition of zzprobe_shared") == "重复：同名键冲突被发现"
    )
    assert experiments.classify("random line") == ""


def test_收割合成日志(tmp_path) -> None:
    log = tmp_path / "debug.log"
    log.write_text(
        "[12:00:00][pdx_parser.cpp:1]: Unknown key 'zzprobe_made_up_style' in zzprobe_bar\n"
        "[12:00:01][pdx_parser.cpp:2]: duplicate definition: zzprobe_shared\n"
        "[12:00:02][game.cpp:3]: unrelated line\n",
        encoding="utf-8",
    )
    report = experiments.collect(tmp_path)
    assert report.files_scanned == 1
    assert len(report.findings) == 2, "无关行不该被收进来"
    grouped = report.by_experiment()
    assert set(grouped) == {"P6", "P11"}
    assert "Unknown key" in grouped["P6"][0].line


def test_收割空目录给提示(tmp_path) -> None:
    report = experiments.collect(tmp_path)
    assert not report.findings
    assert any("zzprobe" in h for h in report.hints), "什么都没收到时应当给排查提示"


def test_日志目录不存在时报出来(tmp_path) -> None:
    report = experiments.collect(tmp_path / "没有这个目录")
    assert report.missing


def test_安装与卸载(tmp_path) -> None:
    installed = experiments.install(tmp_path)
    assert len(installed) == len(experiments.PROBE_MODS)
    for path in installed:
        assert (path / ".metadata" / "metadata.json").is_file()

    # 再装一次：不覆盖（返回原路径，不抛）
    again = experiments.install(tmp_path)
    assert again == installed

    # --force 会覆盖
    (installed[0] / "marker.txt").write_text("x", encoding="utf-8")
    experiments.install(tmp_path, force=True)
    assert not (installed[0] / "marker.txt").exists()

    removed = experiments.uninstall(tmp_path)
    assert len(removed) == len(experiments.PROBE_MODS)
    assert not any(p.exists() for p in removed)


def test_清单里写清了三处肉眼观察() -> None:
    names = " ".join(name for name, _how in experiments.EYEBALL)
    assert "国库" in names
    assert "窗口" in names
    assert "决议" in names
    assert len(experiments.EYEBALL) == 3


def test_plan_文本包含全部实验与收尾命令() -> None:
    text = experiments.plan()
    for e in experiments.EXPERIMENTS:
        assert f"[{e.id}]" in text
    assert "experiment collect" in text
    assert "experiment uninstall" in text


def test_探针mod不计入本机mod统计(tmp_path, monkeypatch) -> None:
    """装探针不该改变「本机有几个 mod」—— 否则黄金回归与 mod 侧断言会随装没装而红。

    实测踩过：装完探针，`test_golden` 的产物指纹与 `refresh --dry-run` 立刻红。
    """
    from pdx import mods

    local = tmp_path / "mod"
    real = local / "some_real_mod"
    real.mkdir(parents=True)
    for name in experiments.PROBE_MODS:
        (local / name).mkdir()
    monkeypatch.setattr(mods.config, "LOCAL_MODS", local)
    monkeypatch.setattr(mods.config, "WORKSHOP", tmp_path / "没有 workshop")

    found = [p.name for p in mods.discover_mods()]
    assert found == ["some_real_mod"]
    assert all(not name.startswith(mods.PROBE_PREFIX) for name in found)
