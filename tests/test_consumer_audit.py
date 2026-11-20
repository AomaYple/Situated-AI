"""F1 静态消费者审计的契约测试。"""

from __future__ import annotations

import json
from typing import cast

import pytest

from pdx import config, consumer_audit, version_contracts

pytestmark = pytest.mark.unit


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    path = tmp_path / "00_default_strategy.txt"
    path.write_text(
        "ai_strategy_default = {\n"
        "    diplomatic_play_neutrality = { value = 0 }\n"
        "    diplomatic_play_support = { value = 0 }\n"
        "    change_law_chance = { value = 0 }\n"
        "    economic_vs_government_spending_balance = { value = 0 }\n"
        "    recklessness = { value = 0 }\n"
        "    subject_value = { value = 0 }\n"
        "    become_subject_value = { value = 0 }\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "REPO", tmp_path)
    return path


def test_静态审计覆盖七模块的全部候选字段(baseline) -> None:
    rows = consumer_audit.audit(baseline=baseline)
    assert len(rows) == 8
    assert {(row.module, row.field) for row in rows} == {
        ("fiscal", "diplomatic_play_neutrality"),
        ("security", "diplomatic_play_support"),
        ("market", "diplomatic_play_support"),
        ("reform", "change_law_chance"),
        ("economy", "economic_vs_government_spending_balance"),
        ("diplomacy", "recklessness"),
        ("subjects", "subject_value"),
        ("subjects", "become_subject_value"),
    }
    assert all(row.status == "static-mapping" for row in rows)
    assert all(row.source_line > 0 for row in rows)
    assert all(row.strategy_cards for row in rows)


def test_静态审计明确行为质量未评估(baseline) -> None:
    data = consumer_audit.report(baseline=baseline)
    assert data["evidence_kind"] == "static-source-and-snapshot"
    assert data["behavior_quality"] == "not_evaluated"
    rows = cast("list[object]", data["rows"])
    limits = cast("list[str]", data["limits"])
    assert len(rows) == 8
    assert "运行期消费者数值" in "".join(limits)


def test_报告渲染和写盘保持_utf8_lf(tmp_path, baseline) -> None:
    data = consumer_audit.report(baseline=baseline)
    text = consumer_audit.render_markdown(data)
    assert "F1 静态字段消费者审计" in text
    assert "behavior_quality=not_evaluated" in text
    json_path, markdown_path = consumer_audit.write(tmp_path, baseline=baseline)
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["schema"] == "sitai-f1-consumer-audit-v1"
    )
    assert "\r" not in markdown_path.read_text(encoding="utf-8")
    assert not markdown_path.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.integration
def test_默认审计使用当前锁定原版和快照() -> None:
    data = consumer_audit.report()
    assert data["baseline"] == version_contracts.DEFAULT_STRATEGY_SOURCE
    rows = cast("list[dict[str, object]]", data["rows"])
    assert len(rows) == 8
    assert all(row["strategy_cards"] for row in rows)
