"""Pinned accepted channel classification, never a population or outcome model.

The manifest transports already reviewed named-v4 bytes and the three complete
dictionary sources. No native search or binary decoder is needed at this layer.
Existing production source/EXE verification still applies at generation time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping

MANIFEST_ID = "research/situated/victoria3-1.15.0-religious-channels.json"
MANIFEST = config.REPO / MANIFEST_ID
MANIFEST_SHA256 = "dc536f0b5b48e92d02922289bab7059dcf07ed2a50e199e4d408c92f0aad9288"
NATIVE_CANONICAL_SHA256 = "35c167efab04125c869b61b16a7cf1a5050928b13926b992b697fa1c33e1a9af"
RELIGION = "common/religions/religion.txt"
HERITAGE = "common/discrimination_traits/03_religious_heritages.txt"
GROUP = "common/discrimination_trait_groups/02_religious_heritage_groups.txt"
ORDER = ("state", "heritage", "group", "other")
MODIFIERS = (
    "country_acceptance_state_religion_add",
    "country_acceptance_shared_religious_trait_add",
    "country_acceptance_shared_religious_trait_group_add",
    "country_acceptance_no_shared_religious_trait_add",
)
RELIGIONS = (
    "catholic",
    "protestant",
    "orthodox",
    "oriental_orthodox",
    "sunni",
    "shiite",
    "ibadi",
    "jewish",
    "mahayana",
    "gelugpa",
    "theravada",
    "confucian",
    "hindu",
    "shinto",
    "sikh",
    "animist",
    "atheist",
)
# At most 17 observed religions, each with at most 16 explicit state identities
# plus two same-country aggregate comparisons. These are syntax budgets, not
# native timing or population enumeration limits.
MAX_RELIGIONS = 17
MAX_PREDICATES = 306
MAX_ASSIGNMENTS = 500
MAX_BLOCKS = 110
MAX_BYTES = 45000
MAX_DEPTH = 7


def _definitions(text: str) -> dict[str, Block]:
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("宗教分类字典解析失败")
    result = {}
    for row in parsed.root.assignments():
        if row.key in result or row.op != "=" or not isinstance(row.value, Block):
            raise ValueError("宗教分类定义必须唯一完整")
        result[row.key] = row.value
    if len(result) != len(parsed.root.items):
        raise ValueError("宗教分类字典不允许非定义项")
    return result


def _name(block: Block, key: str) -> str:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Scalar):
        raise ValueError("宗教分类引用必须唯一标量")
    return rows[0].value.unquoted


@dataclass(frozen=True)
class ChannelDictionary:
    rows: tuple[tuple[str, str, str], ...]
    source_hashes: tuple[tuple[str, str], ...]

    def category(self, state: str, observed: str) -> str:
        index = {religion: (heritage, group) for religion, heritage, group in self.rows}
        if state not in index or observed not in index:
            raise ValueError("宗教分类不接受字典外或未解析对象")
        if state == observed:
            return "state"
        if index[state][0] == index[observed][0]:
            return "heritage"
        if index[state][1] == index[observed][1]:
            return "group"
        return "other"


def snapshot() -> tuple[dict[str, Any], ChannelDictionary]:
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("宗教分类正式manifest字节漂移，须重新独立审查")
    data = json.loads(raw)
    native = data["native"]
    canonical_native = json.dumps(
        native, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if hashlib.sha256(canonical_native).hexdigest() != NATIVE_CANONICAL_SHA256:
        raise ValueError("宗教分类named-v4完整证明内容漂移")
    if (
        data["schema"] != "situated-reviewed-religious-channels/1"
        or tuple(data["channel_order"]) != ORDER
        or tuple(data["modifier_keys"]) != MODIFIERS
        or data["modifier_slots"] != ["0x1453d9130", "0x1453d9128", "0x1453d9118", "0x1453d914c"]
        or native["exe_sha256"]
        != "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
        or native["schema"] != "narrow-static-religious-channel-candidate/1"
        or data["upstream"]["candidate_sha256"]
        != "e328660b5d5b02bb2d3101678f4e549252c611f6162c9035fa7dddad549c8501"
    ):
        raise ValueError("宗教分类manifest偏离已接受四互斥通道")
    if set(data["dictionary_sources"]) != {RELIGION, HERITAGE, GROUP}:
        raise ValueError("宗教分类完整来源集合漂移")
    texts, hashes = {}, {}
    for path, encoded in data["dictionary_sources"].items():
        source = bytes.fromhex(encoded)
        expected = native["sources"][path]
        if (
            len(source) != expected["bytes"]
            or hashlib.sha256(source).hexdigest() != expected["sha256"]
        ):
            raise ValueError("宗教分类已审原始字节漂移")
        texts[path] = normalized_text(source.decode("utf-8-sig"))
        hashes[path] = hashlib.sha256(texts[path].encode()).hexdigest()
    religions = _definitions(texts[RELIGION])
    heritages = _definitions(texts[HERITAGE])
    groups = _definitions(texts[GROUP])
    if tuple(religions) != RELIGIONS or len(religions) != MAX_RELIGIONS:
        raise ValueError("宗教分类有限字典分母漂移")
    rows = []
    for religion, definition in religions.items():
        heritage = _name(definition, "heritage")
        if heritage not in heritages:
            raise ValueError("宗教分类heritage引用未解析")
        group = _name(heritages[heritage], "trait_group")
        if group not in groups or _name(groups[group], "type") != "heritage":
            raise ValueError("宗教分类group引用未解析")
        rows.append((religion, heritage, group))
    return data, ChannelDictionary(tuple(rows), tuple(sorted(hashes.items())))


def verify_inputs(inputs: Mapping[str, str]) -> ChannelDictionary:
    _, dictionary = snapshot()
    for source, digest in dictionary.source_hashes:
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError("宗教分类当前完整来源漂移")
    return dictionary


def exposure(channels: tuple[str, ...], *, loss: bool) -> str:
    """Same-country, same-religion observations in exactly selected channels."""
    if channels not in (("heritage", "other"), ("group",), ("group", "other")) or loss != (
        channels == ("group",)
    ):
        raise ValueError("宗教分类只授权固定mixed-need/group-loss/separation-need查询")
    _, dictionary = snapshot()
    rows = []
    predicates = 0
    for observed in RELIGIONS:
        states = tuple(
            state for state in RELIGIONS if dictionary.category(state, observed) in channels
        )
        if not states:
            continue
        predicates += len(states) + 2
        category = (
            "OR = { "
            + " ".join(f"country_has_state_religion = rel:{state}" for state in states)
            + " }"
        )
        rows.append(
            "AND = { "
            + category
            + f" religion_percent_country = {{ target = rel:{observed} value >= 0.1 }}"
            + f" country_average_religious_acceptance = {{ target = rel:{observed}"
            + f" value {'>' if loss else '<'} 0 }} }}"
        )
    expression = "OR = { " + " ".join(rows) + " }"
    # Import locally to avoid the resources->compiler import cycle.
    from .situated.resources import pdx_metrics  # noqa: PLC0415

    metrics = pdx_metrics(expression)
    if (
        predicates > MAX_PREDICATES
        or metrics["assignment_nodes"] > MAX_ASSIGNMENTS
        or metrics["block_nodes"] > MAX_BLOCKS
        or len(expression.encode("utf-8")) > MAX_BYTES
        or metrics["max_depth"] > MAX_DEPTH
        or metrics["object_scan_sites"]
        or metrics["persistent_write_sites"]
    ):
        raise ValueError("宗教分类查询超出固定谓词/AST预算")
    return expression
