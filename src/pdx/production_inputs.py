"""从锁定原件解析实际生产方式的隶属及投入产出；不预测利润或切换 PM。"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, TypedDict

from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class GoodsFlow(TypedDict):
    kind: str
    good: str
    quantity: float
    scaling: str
    line: int


class ProductionRecipe(TypedDict):
    building: str
    building_source: str
    group: str
    group_source: str
    method: str
    method_source: str
    goods: list[GoodsFlow]
    status: str
    limits: str


def recipes(
    texts: Mapping[str, str], requests: Iterable[tuple[str, str]]
) -> list[ProductionRecipe]:
    """每项请求必须有真实的建筑→组→PM 链；原件缺失/歧义立即拒绝。"""
    wanted = sorted(set(requests))
    if not wanted:
        return []
    categories: dict[str, dict[str, tuple[str, Block]]] = {
        name: {} for name in ("buildings", "production_method_groups", "production_methods")
    }
    for source, text in sorted(texts.items()):
        category = source.split("/")
        if (
            len(category) != 3
            or category[0] != "common"
            or category[1] not in categories
            or not source.endswith(".txt")
        ):
            continue
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"生产链原件无法解析：{source}")
        entries = categories[category[1]]
        for entry in parsed.top_assignments:
            if entry.is_variable or not isinstance(entry.value, Block):
                continue
            if entry.key in entries:
                raise ValueError(f"生产链定义重复：{entry.key}")
            entries[entry.key] = (source, entry.value)

    def children(block: Block, key: str) -> list[str]:
        matches = block.all(key)
        if len(matches) != 1 or not isinstance(matches[0].value, Block):
            raise ValueError(f"生产链缺少唯一列表：{key}")
        child = matches[0].value
        if any(not isinstance(entry, Scalar) for entry in child.items):
            raise ValueError(f"生产链列表包含未审计表达式：{key}")
        keys = [entry.unquoted for entry in child.scalars()]
        if len(keys) != len(set(keys)):
            raise ValueError(f"生产链列表重复：{key}")
        return keys

    result: list[ProductionRecipe] = []
    for building, method in wanted:
        try:
            building_source, building_block = categories["buildings"][building]
            method_source, method_block = categories["production_methods"][method]
            group_keys = children(building_block, "production_method_groups")
            memberships = []
            for group in group_keys:
                group_source, group_block = categories["production_method_groups"][group]
                if method in children(group_block, "production_methods"):
                    memberships.append((group, group_source))
        except KeyError as exc:
            raise ValueError(f"生产链缺少锁定定义：{building}/{method}/{exc.args[0]}") from exc
        if len(memberships) != 1:
            raise ValueError(f"生产方式不属于建筑的唯一生产组：{building}/{method}")
        goods: list[GoodsFlow] = []
        modifiers = method_block.all("building_modifiers")
        if len(modifiers) > 1 or (modifiers and not isinstance(modifiers[0].value, Block)):
            raise ValueError("生产方式修正块不唯一或无效")
        if modifiers:
            modifier_block = modifiers[0].value
            assert isinstance(modifier_block, Block)
            for scaling in modifier_block.assignments():
                if scaling.key not in {"workforce_scaled", "level_scaled", "unscaled"}:
                    continue
                if not isinstance(scaling.value, Block):
                    raise ValueError("生产方式规模块无效")
                for assignment in scaling.value.assignments():
                    match = re.fullmatch(r"goods_(input|output)_(.+)_add", assignment.key)
                    if match is None:
                        continue
                    if not isinstance(assignment.value, Scalar):
                        raise ValueError("生产方式商品数量不是静态常量")
                    try:
                        quantity = float(assignment.value.unquoted)
                    except ValueError as exc:
                        raise ValueError("生产方式商品数量无法读取") from exc
                    if not math.isfinite(quantity):
                        raise ValueError("生产方式商品数量必须有限")
                    goods.append(
                        {
                            "kind": match[1],
                            "good": match[2],
                            "quantity": quantity,
                            "scaling": scaling.key,
                            "line": assignment.line,
                        }
                    )
        result.append(
            {
                "building": building,
                "building_source": building_source,
                "group": memberships[0][0],
                "group_source": memberships[0][1],
                "method": method,
                "method_source": method_source,
                "goods": goods,
                "status": "static_recipe_and_active_method_reader_pending_f1",
                "limits": "not_profit_prediction; other_groups_wages_employment_and_eligibility_retained_vanilla",
            }
        )
    return result
