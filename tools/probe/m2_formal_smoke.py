"""M2 正式 mod 的实机加载冒烟。

脚本只做一次短观察者局：部署仓库 ``mod/`` 的生成产物，启动游戏，使用现有
``game_auto`` 流程进入观察者、5 速、后台推进，随后检查日志并完整恢复用户的
``content_load.json``。它不声称证明外交行为因果，只验证正式生成物能被游戏加载，
且自动化收尾没有留下临时 mod 或用户配置残留。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from pdx import config, decisions, game_run

MOD_NAME = "sitai_formal_m2"
RESULT_DIR = config.OUT / "m2"


def run(months: float) -> dict[str, object]:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=RESULT_DIR) as directory:
        candidate = Path(directory)
        decisions.write(candidate)
        issues = decisions.check(candidate)
        if issues:
            raise ValueError("冒烟候选目录存在未声明产物：" + "、".join(issues))
        return game_run.run({MOD_NAME: candidate}, months=months, output=RESULT_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=float, default=6.0)
    parser.add_argument(
        "--fresh-logs", action="store_true", help="兼容历史命令；现在每局均隔离日志"
    )
    args = parser.parse_args(argv)
    report = run(args.months)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("failure") else 0


if __name__ == "__main__":
    raise SystemExit(main())
