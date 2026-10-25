"""真实文件覆盖采集稳定性、滚动、缺失值和状态差分。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pdx import cli, config, observe

if TYPE_CHECKING:
    from pathlib import Path


def write_save(path: Path, *, date: str = "1840.1.1", money: int = 42) -> None:
    text = """SAV0100
meta_data={ version="1.14.5" game_date=DATE mods={ "Situated AI" } }
playthrough_id="test-campaign"
date=DATE
speed=4
counters={ wars=100 num_countries=1000 tick=200 }
country_manager={ database={
3={ definition="RUS" government="gov_tsardom" capital=28 market=1
 budget={ money=MONEY principal=10 credit=100 weekly_income={ 20 30 } weekly_expenses={ 10 5 }
 balance_trend={ current=35 } }
 variables={ data={ { flag=sitai_fiscal_risk tick=62 data={ type=value identity=100000 } } } }
 gdp={ channels={ 0={ index=1 values={ 12 99 } } } }
}
29={ definition="NET" government="gov_constitutional_kingdom" market=10 }
4=none
} }
laws={ database={ 1={ country=3 law=law_serfdom active=yes } 2={ country=3 law=law_tenant_farmers } } }
technology={ database={ 2={ country=3 research_technology=railways research_queue={ railways } acquired_technologies={ lathe } } } }
ai={ database={ 2={ country=3 enabled=yes ai_strategy={ type=ai_strategy_agricultural_expansion progress=4 }
 cached_ai_weights={ { type=diplomatic_play_boldness target=29 value=11 date=DATE } }
 potential_building_constructions={ { building=building_tooling_workshop weight=2 } }
 strategic_region_stances={ region_baltic=stance_protect_region } } } }
interest_groups={ database={ 5={ country=3 definition="ig_landowners" clout=0.4 } } }
war_manager={ database={ 0={ name="quoted } = { text" } 1=none } }
""".replace("DATE", date).replace("MONEY", str(money))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_save_contains_scoped_country_state_and_internal_counters(tmp_path: Path) -> None:
    path = tmp_path / "autosave.v3"
    write_save(path)
    result = observe.read_save(path)
    assert result["metadata"]["game_date"] == "1840.1.1"
    assert result["metadata"]["internal_counters"]["wars"] == "100"
    assert result["databases"]["war_manager"] == 1
    country = result["countries"]["3"]
    assert country["definition"] == "RUS"
    assert country["budget"]["money"] == "42"
    assert country["budget"]["balance_trend"]["current"] == "35"
    assert country["active_laws"] == ["law_serfdom"]
    assert country["technology"]["research_technology"] == "railways"
    assert country["ai"]["ai_strategy"][0]["type"] == "ai_strategy_agricultural_expansion"
    assert country["variables"][0]["flag"] == "sitai_fiscal_risk"
    assert country["interest_groups"][0]["clout"] == "0.4"
    assert "budget" not in result["countries"]["29"]


@pytest.mark.parametrize(
    "data", [b"", b"PK\x03\x04compressed", b"SAV0100\na={", b'SAV0100\na="unfinished']
)
def test_reject_incomplete_or_unsupported_saves(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "autosave.v3"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        observe.read_save(path)


def test_archive_deduplicates_rotating_names_and_never_overwrites(tmp_path: Path) -> None:
    save_dir, archive = tmp_path / "input", tmp_path / "archive"
    path = save_dir / "autosave.v3"
    write_save(path)
    collector = observe.SaveCollector(save_dir, archive_dir=archive, stable_seconds=0)
    assert collector.collect() == []
    first = collector.collect()
    assert len(first) == 1
    path.rename(save_dir / "autosave_1.v3")
    assert collector.collect() == []
    assert collector.collect() == []
    write_save(path, date="1840.2.1", money=24)
    assert collector.collect() == []
    assert len(collector.collect()) == 1
    saved = sorted(archive.glob("*.v3"))
    assert len(saved) == 2
    assert len({p.read_bytes() for p in saved}) == 2
    assert collector.collect() == []


def test_same_size_log_replacement_and_split_utf8_preserve_bytes(tmp_path: Path) -> None:
    log = tmp_path / "error.log"
    log.write_bytes(b"old\n")
    collector = observe.LogCollector(tmp_path)
    assert b"".join(e["data"] for e in collector.collect()) == b"old\n"
    log.write_bytes(b"new\n")
    assert b"".join(e["data"] for e in collector.collect()) == b"new\n"
    part = "中文".encode()
    with log.open("ab") as f:
        f.write(part[:2])
    first = list(collector.collect())
    with log.open("ab") as f:
        f.write(part[2:])
    second = list(collector.collect())
    assert b"".join(e["data"] for e in first + second) == part


def test_session_flushes_before_finish_and_reports_chronologically(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    write_save(userdir / "save games/autosave.v3", date="1840.2.1", money=24)
    write_save(userdir / "save games/autosave_1.v3", date="1840.1.1")
    (userdir / "logs").mkdir()
    (userdir / "logs/error.log").write_bytes(
        b"[12:00:00] Script system error!\n  Script location: <unknown>:0\n"
    )
    output = tmp_path / "session"
    session = observe.ObservationSession(userdir, output, stable_seconds=0)
    session.poll()
    session.poll()
    assert len((output / "saves.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert list((output / "logs").rglob("*.log"))
    report = session.finish()
    assert report["campaigns"][0]["first_date"] == "1840.1.1"
    assert report["campaigns"][0]["last_date"] == "1840.2.1"
    assert report["country_changes"][0]["budget.money"] == {"before": "42", "after": "24"}
    assert report["behavior_quality"] == "not_evaluated"
    assert (output / "report.md").exists()


def test_cli_once_collects_saves_without_touching_user_files(tmp_path: Path, monkeypatch) -> None:
    userdir, output = tmp_path / "game", tmp_path / "evidence"
    path = userdir / "save games/autosave.v3"
    write_save(path)
    before = path.read_bytes()
    monkeypatch.setattr(config, "USERDIR", userdir)
    result = CliRunner().invoke(
        cli.app, ["observe", "--once", "--stable-seconds", "0", "--output", str(output)]
    )
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads((output / "report.json").read_text(encoding="utf-8"))["save_count"] == 1
    assert path.read_bytes() == before


def test_session_refuses_existing_output_and_game_directory(tmp_path: Path) -> None:
    userdir = tmp_path / "user"
    userdir.mkdir()
    with pytest.raises(ValueError):
        observe.ObservationSession(userdir, userdir / "logs")
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError):
        observe.ObservationSession(userdir, output)
