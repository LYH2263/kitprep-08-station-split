"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, shortage = need - stock.

分册口径：按菜品工位（hot 热厨 / cold 冷荤 / 未标记 unassigned 未分册）把需求拆进三册；
占用（occupancy）忽略工位全量计算。册合计与占用必须一致，否则 validate_split 抛 SplitError。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

BOOK_KEYS = ("hot", "cold", "unassigned")
BOOK_NAMES = {"hot": "热厨册", "cold": "冷荤册", "unassigned": "未分册"}
TOL = 1e-6


class SplitError(Exception):
    """分册原子性失败：册与占用对不上。绝不表述为结存不够。"""


@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion."""
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines

def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }


def station_book(station: str | None) -> str:
    """工位标记 → 册 key；None 与任何未知值都进未分册。"""
    if station in ("hot", "cold"):
        return station
    return "unassigned"


def split_books(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
    stations: dict[int, str | None],
) -> dict:
    """按工位把需求拆进三册，并独立算出全量占用。

    返回 {"books", "occupancy", "assignments", "_raw"}：
    books/occupancy 的行 qty 保留 3 位小数供展示与快照；
    _raw 保留未取整合计，供 validate_split 对账与 PrepBooking 落库。
    """
    book_raw: dict[str, dict[int, float]] = {k: {} for k in BOOK_KEYS}
    occ_raw: dict[int, float] = {}
    assignments: list[dict] = []
    for ol in order_lines:
        dish_id = ol["dish_id"]
        portions = ol["portions"]
        book = station_book(stations.get(dish_id))
        assignments.append({"dish_id": dish_id, "portions": portions, "book": book})
        for bl in bom_lines:
            if bl["dish_id"] != dish_id:
                continue
            iid = bl["ingredient_id"]
            qty = portions * bl["qty_per_portion"]
            book_raw[book][iid] = book_raw[book].get(iid, 0.0) + qty
            occ_raw[iid] = occ_raw.get(iid, 0.0) + qty

    def _line(iid: int, qty: float) -> dict:
        ing = ingredients[iid]
        return {
            "ingredient_id": iid,
            "ingredient_code": ing["code"],
            "ingredient_name": ing["name"],
            "unit": ing.get("unit", ""),
            "qty": round(qty, 3),
        }

    books = {}
    for key in BOOK_KEYS:
        books[key] = {
            "name": BOOK_NAMES[key],
            "lines": [_line(iid, book_raw[key][iid]) for iid in sorted(book_raw[key])],
        }
    occupancy = [_line(iid, occ_raw[iid]) for iid in sorted(occ_raw)]
    return {"books": books, "occupancy": occupancy, "assignments": assignments,
            "_raw": {"books": book_raw, "occ": occ_raw}}


def validate_split(order_lines: list[dict], split: dict, tol: float = TOL) -> None:
    """落库前对账：每订单行恰好进一册；册合计 == 占用。不符即 SplitError。"""
    assignments = split.get("assignments", [])
    raw = split.get("_raw", {})
    book_raw = raw.get("books", {})
    occ_raw = raw.get("occ", {})

    expected = sorted((ol["dish_id"], ol["portions"]) for ol in order_lines)
    actual = sorted((a["dish_id"], a["portions"]) for a in assignments)
    if expected != actual:
        raise SplitError("分册失败：存在出品未进册或重复进册，热厨册/冷荤册/未分册已全部退回，结存未变")
    for a in assignments:
        if a.get("book") not in BOOK_KEYS:
            raise SplitError("分册失败：存在未知工位册，热厨册/冷荤册/未分册已全部退回，结存未变")

    summed: dict[int, float] = {}
    for key in BOOK_KEYS:
        if key not in book_raw:
            raise SplitError("分册失败：缺少工位册，热厨册/冷荤册/未分册已全部退回，结存未变")
        for iid, qty in book_raw[key].items():
            summed[iid] = summed.get(iid, 0.0) + qty
    if set(summed) != set(occ_raw):
        raise SplitError("分册失败：分册原料与占用原料对不上，热厨册/冷荤册/未分册已全部退回，结存未变")
    for iid, qty in summed.items():
        if abs(qty - occ_raw[iid]) > tol:
            raise SplitError("分册失败：分册占用合计与总占用不一致，热厨册/冷荤册/未分册已全部退回，结存未变")


def build_result_with_raw(
    order: dict,
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
    stations: dict[int, str | None],
) -> tuple[dict, dict]:
    """同 build_result，另返回 split（含未取整 _raw），供落库与再对账。"""
    split = split_books(order_lines, bom_lines, ingredients, stations)
    validate_split(order_lines, split)
    flat = result_to_dict(explode_and_merge(order_lines, bom_lines, ingredients))
    result = {
        "order": {"id": order["id"], "code": order["code"], "outlet": order["outlet"]},
        "books": split["books"],
        "occupancy": split["occupancy"],
        **flat,
    }
    return result, split


def build_result(
    order: dict,
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
    stations: dict[int, str | None],
) -> dict:
    """组装完整备料结果：三册 + 占用 + 扁平 prep_lines/shortages/stats。"""
    return build_result_with_raw(order, order_lines, bom_lines, ingredients, stations)[0]
