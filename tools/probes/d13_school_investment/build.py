"""冻结三组 D13 本地诊断载荷。仅从安装读取已锁定的原版依据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from pdx import version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.textio import text_bytes

TEMPLATE = Path(__file__).with_name("school_injection.txt")
STRATEGY = "common/ai_strategies/zz_sitai_d13_school_investment.txt"
ARMS = {"neutral": "0", "diagnostic": "10000", "candidate": "0.25"}


def _unique_block(parent: Block, name: str) -> Block:
    matches = parent.all(name)
    if len(matches) != 1:
        raise ValueError(f"D13 缺失或重复字段 {name}")
    (item,) = matches
    if item.prefix is not None or item.op != "=" or not isinstance(item.value, Block):
        raise ValueError(f"D13 字段块无效 {name}")
    return item.value


def verify_default(source: str) -> None:
    parsed = parse_text(source, path=version_contracts.DEFAULT_STRATEGY_SOURCE)
    parsed.require_complete()
    strategy = _unique_block(parsed.root, "ai_strategy_default")
    scores = _unique_block(strategy, "institution_scores")
    schools = _unique_block(scores, "institution_schools")
    if len(schools.items) != 1:
        raise ValueError("D13 原版学校评分体变化")
    (value,) = schools.items
    if (
        not isinstance(value, Assignment)
        or value.key != "value"
        or value.prefix is not None
        or value.op != "="
        or not isinstance(value.value, Scalar)
        or value.value.text != "10"
    ):
        raise ValueError("D13 原版学校初始分变化")


def arm_payloads(arm: str) -> dict[str, bytes]:
    marker = "\t\t\t\t\tadd = 0.25\n"
    script = TEMPLATE.read_text(encoding="utf-8")
    if script.count(marker) != 1:
        raise ValueError("D13 诊断分值位置不唯一")
    script = script.replace(marker, f"\t\t\t\t\tadd = {ARMS[arm]}\n")
    metadata = {
        "name": f"Situated AI D13 Schools ({arm})",
        "id": f"sitai-d13-schools-{arm}",
        "version": "0.0.1",
        "supported_game_version": version_contracts.CURRENT_VERSION,
        "short_description": "Local D13 institution score diagnostic",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return {
        ".metadata/metadata.json": text_bytes(json.dumps(metadata, indent=2) + "\n"),
        STRATEGY: text_bytes(script, game=True),
    }


def write_arm(archive_path: Path, arm: str) -> dict[str, object]:
    payloads = arm_payloads(arm)
    with zipfile.ZipFile(archive_path, "x") as archive:
        for name, raw in sorted(payloads.items()):
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            archive.writestr(member, raw)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.namelist() != sorted(payloads) or archive.testzip() is not None:
            raise ValueError("D13 试片 ZIP 的成员集或 CRC 无效")
        actual = {name: archive.read(name) for name in archive.namelist()}
    if actual != payloads:
        raise ValueError("D13 试片 ZIP 与原始载荷不一致")
    return {
        "archive": archive_path.name,
        "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in actual.items()},
    }


def build(installation: Path, output_dir: Path) -> None:
    identity = version_contracts.verify_installation_identity(installation)
    verify_default(version_contracts.read_default_strategy(identity.root / "game"))
    output_dir = output_dir.resolve()
    if output_dir.exists() or output_dir.is_relative_to(identity.root):
        raise ValueError("D13 试片要求独立的新输出目录")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir.parent) as temporary:
        staged = Path(temporary) / "artifacts"
        staged.mkdir()
        arms = {arm: write_arm(staged / f"sitai-d13-schools-{arm}.zip", arm) for arm in ARMS}
        if version_contracts.verify_installation_identity(installation) != identity:
            raise ValueError("D13 原版安装身份在生成期间变化")
        version_contracts.read_default_strategy(identity.root / "game")
        receipt = {
            "evidence_type": "static_check",
            "game_version": version_contracts.CURRENT_VERSION,
            "default_strategy_sha256": version_contracts.contract().default_strategy_sha256,
            "arms": arms,
        }
        (staged / "manifest.json").write_bytes(text_bytes(json.dumps(receipt, indent=2) + "\n"))
        staged.rename(output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    build(args.installation, args.output_dir)


if __name__ == "__main__":
    main()
