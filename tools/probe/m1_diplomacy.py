"""执行 M1 外交策略接口实机实验。

默认流程：备份用户启用配置 → 部署临时探针 → 启动观察者局 → 5 速后台运行 →
按游戏月等待 → 汇总 ``debug.log`` → 杀掉本次游戏 → 恢复用户配置与本地 mod。

脚本只依赖仓库 ``.venv`` 的 Python 模块，不调用 PowerShell、cmd 或外部 GUI
自动化程序。实机输入仍由 ``pdx.game_auto`` 的显式授权入口完成。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pdx import config, game_run, m1_probe

LOG_DIR = config.USERDIR / "logs"
RESULT_DIR = config.OUT / "m1"


def _log_text(directory: Path | None = None) -> str:
    """按轮转编号从旧到新拼接日志，重复文件只算一次。"""
    directory = directory or LOG_DIR
    rotated = sorted(
        (p for p in directory.glob("debug.[0-9]*.log") if p.stem.rsplit(".", 1)[-1].isdigit()),
        key=lambda p: -int(p.stem.rsplit(".", 1)[-1]),
    )
    paths = [*rotated, *(p for p in (directory / "debug.log",) if p.is_file())]
    chunks: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if text not in seen:
            seen.add(text)
            chunks.append(text)
    return "\n".join(chunks)


def analyze(directory: Path | None = None) -> dict[str, object]:
    rows = m1_probe.parse_rows(_log_text(directory))
    summary = m1_probe.summarize(rows)
    summary["row_samples"] = [
        row.__dict__
        if hasattr(row, "__dict__")
        else {"kind": row.kind, "value": row.value, "country": row.country}
        for row in rows[-20:]
    ]
    return summary


def run(months: float, *, fresh_logs: bool = True) -> dict[str, object]:
    del fresh_logs
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=RESULT_DIR) as directory:
        source = Path(directory)
        m1_probe.write(source)
        return game_run.run(
            {m1_probe.PROBE_MOD: source}, months=months, output=RESULT_DIR, analyze=analyze
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=float, default=24.0)
    parser.add_argument("--fresh-logs", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args(argv)
    if args.analyze_only:
        print(json.dumps(analyze(), ensure_ascii=False, indent=2))
        return 0
    report = run(args.months, fresh_logs=args.fresh_logs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("failure") else 0


if __name__ == "__main__":
    raise SystemExit(main())
