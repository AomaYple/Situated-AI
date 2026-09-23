"""CI 基准汇总脚本的测试（`tools/ci/bench_summary.py`）。

这一份被测对象是**给 CI 用的**：它把 pytest-benchmark 的 JSON 变成 job summary 里的一张表。
两条要保住的性质：① 数字**不许改**（它就是给人看的原始口径，不能"顺手美化"）；
② 坏输入（缺文件 / JSON 坏了 / 没有基准）**不许让 job 红** —— 它不是门禁（见模块文档）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "ci" / "bench_summary.py"


def _module() -> ModuleType:
    """按路径加载脚本（`tools/ci/` 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("bench_summary", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _data(*rows: tuple[str, float]) -> dict[str, object]:
    return {
        "benchmarks": [
            {
                "name": name,
                "stats": {
                    "min": value,
                    "mean": value,
                    "median": value,
                    "max": value,
                    "ops": 1 / value,
                },
            }
            for name, value in rows
        ]
    }


class TestTable:
    def test_按名字排序(self) -> None:
        text = _module().table(_data(("b", 0.001), ("a", 0.001)))
        assert text.index("`a`") < text.index("`b`")

    def test_数值原样不美化(self) -> None:
        """0.0135 秒要写成 ``13.50 ms`` —— 换算只换单位，不改有效数字。"""
        text = _module().table(_data(("x", 0.0135)))
        assert "13.50 ms" in text, text

    def test_三个量级各用各的单位(self) -> None:
        table = _module().table
        assert "900.00 ns" in table(_data(("n", 9e-7)))
        assert "50.00 us" in table(_data(("u", 5e-5)))
        assert "2.00 ms" in table(_data(("m", 2e-3)))

    def test_表尾说清它不是门禁(self) -> None:
        text = _module().table(_data(("x", 0.001)))
        assert "不是门禁" in text
        assert "test_cache" in text, "要说清断言落在哪里，否则下一个人会以为基准没人守"

    def test_空数据给一句人话(self) -> None:
        text = _module().table({"benchmarks": []})
        assert "没有基准数据" in text
        assert "|" not in text.splitlines()[0]

    def test_缺stats的条目被跳过而不是崩(self) -> None:
        text = _module().table(
            {"benchmarks": [{"name": "bad"}, {"name": "ok", "stats": {"mean": 1.0}}]}
        )
        assert "`ok`" in text
        assert "`bad`" not in text


class TestMain:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # ⚠️ 子进程的输出编码必须显式钉成 UTF-8：本机 locale 是 GBK 时，脚本里的中文
        # 会按 GBK 打出来，而这边按 UTF-8 解码 ⇒ UnicodeDecodeError（实测踩过，
        # `test_repo_numbers.py` 里也是同一条）。
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )

    def test_正常文件输出表格(self, tmp_path: Path) -> None:
        path = tmp_path / "bench.json"
        path.write_text(json.dumps(_data(("x", 0.001))), encoding="utf-8")
        result = self._run(str(path))
        assert result.returncode == 0
        assert "`x`" in result.stdout

    def test_没有文件也不报错(self, tmp_path: Path) -> None:
        """它不是门禁：汇总失败不该把 job 弄红（见模块文档）。"""
        result = self._run(str(tmp_path / "无.json"))
        assert result.returncode == 0
        assert "找不到" in result.stdout

    def test_坏JSON也不报错(self, tmp_path: Path) -> None:
        path = tmp_path / "bench.json"
        path.write_text("{ 这不是 json", encoding="utf-8")
        result = self._run(str(path))
        assert result.returncode == 0
        assert "读不动" in result.stdout
