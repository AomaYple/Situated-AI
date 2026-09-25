"""t16 的「和平期 / 危机期占槽率」读数器（口径写死在代码里，可复算）。

它做什么
--------
读 `stage3_rerun.py --archive <id> --fresh-logs` **那一局**的日志（整个日志集合，含轮转副本
`debug.1.log`…；B85：只看 `debug.log` 得到的「没有」从来不是证据），按月度自报行算两个数：

| 数 | 定义 |
|---|---|
| **和平期占槽率** | `SHOCK;no` 的那些观测月里，「当月政治牌 = 本档案 `[probe].reform_card` 声明的那张」的月份占比 |
| **危机期占槽率** | `SHOCK;yes` 的那些观测月里，同一个占比 |
| **自建牌占槽率** | `CARD;<牌名\\|none>` 逐月读数里非 `none` 的月份占比 —— 闸门 ③ 那个「0 张牌 / 0.0%」的**实机对照** |

为什么口径要写死在代码里（P9 单一数据源）：t16 的读数要求「必须带**盘上自报行数**与
**算进读数的行数**」——那正是分析器踩过的那一类坑（B85：轮转日志顺序错一次，1,401 行只报了 402 行，
还报出一个假的「窗口 inactive → active」）。把它写在一处、可复算，比在文档里复述一遍强。

用法
----
```powershell
.venv\\Scripts\\python.exe -X utf8 tools\\probe\\t16_share.py [档案 id，默认 ru_defeat]
```
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

DEFAULT_ARCHIVE = "ru_defeat"


def _load_probe():
    """按路径加载同目录的 `stage3_rerun.py`（它不是包，见 `test_probe_stage3.py` 的说明）。"""
    spec = importlib.util.spec_from_file_location(
        "probe_s3", Path(__file__).with_name("stage3_rerun.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    archive_id = (argv or sys.argv[1:] or [DEFAULT_ARCHIVE])[0]
    probe = _load_probe()

    found_id, target = probe._probe_target([f"…: ZZPROBE AB;TARGET;{archive_id}"])
    if target is None:
        print(f"数据源里找不到 {archive_id!r}（认到的档案 id：{found_id or '—'}）")
        return 2
    declared = target.probe.reform_card if target.probe is not None else ""
    card_short = declared.replace("ai_strategy_", "")

    paths = probe.debug_logs(probe.DEBUG_LOG.parent)
    seen: set[str] = set()
    total = 0
    rows: list[list[str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if text in seen:
            continue
        seen.add(text)
        for line in text.splitlines():
            if "ZZPROBE AB;" in line:
                total += 1
                rows.append(line.split("ZZPROBE AB;", 1)[1].split('"', 1)[0].split(";"))

    print(f"日志文件 {len(paths)} 份（逐字节去重后 {len(seen)} 份）")
    print(f"盘上自报行数 {total}｜算进读数的行数 {len(rows)}（这一局用 --fresh-logs，两者应相等）")
    print(f"本档案声明的目标牌：{declared or '（留空 = 不判）'}（日志里写作 {card_short or '—'}）")

    arm = "（臂未知）"
    cards: dict[str, list[str]] = {}
    je: dict[str, list[str]] = {}
    ours: dict[str, list[str]] = {}
    # ⚠️ 探针的 `STRATEGY` 行写的是**全名**（`ai_strategy_progressive_agenda`，见 `ab_probe.py`），
    # 而历史上有些归档里是短名（`progressive_agenda`）—— 两种都认，免得算出假的 0%（第一次就踩到）。
    accepted = {declared, card_short} - {""}
    for parts in rows:
        kind = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if kind == "SHOCK":
            arm = "危机期" if value == "yes" else "和平期"
            cards.setdefault(arm, [])
            je.setdefault(arm, [])
            ours.setdefault(arm, [])
        elif kind == "STRATEGY":
            cards.setdefault(arm, []).append(value)
        elif kind == "JE":
            je.setdefault(arm, []).append(value)
        elif kind == "CARD":
            ours.setdefault(arm, []).append(value)

    print()
    for name in ("和平期", "危机期"):
        arm_cards = cards.get(name, [])
        arm_je = je.get(name, [])
        arm_ours = ours.get(name, [])
        if not arm_cards:
            print(f"{name}：没有观测月（这一局可能没跑到那一段）")
            continue
        hit = sum(1 for card in arm_cards if card in accepted) if accepted else None
        share = f"{hit / len(arm_cards):.1%}" if hit is not None else "不判（目标牌留空）"
        je_on = sum(1 for value in arm_je if value == "active")
        own_hit = sum(1 for value in arm_ours if value != "none")
        print(
            f"{name}：观测月 {len(arm_cards)}｜目标牌命中 {hit if hit is not None else '—'}"
            f" ⇒ 占槽率 **{share}**｜窗口 active {je_on}/{len(arm_je)}"
            f"｜自建牌逐月读数 {len(arm_ours)} 行、非 none {own_hit}"
        )

    print()
    for kind in ("SHOCK", "INPUT", "JE", "STRATEGY", "CARD", "ENACT", "GOV"):
        seq = [parts[1] for parts in rows if parts[0] == kind]
        if seq:
            counts = Counter(seq)
            top = "、".join(f"{k}×{v}" for k, v in counts.most_common(6))
            print(f"{kind:9s} 去重：{sorted(set(seq))}  计数：{len(seq)}（{top}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
