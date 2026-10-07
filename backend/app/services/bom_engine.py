"""中央厨房 BOM 展开与分册。

规则（业务硬约束）：
- 出品可带工位标记：热厨(hot)/冷荤(cold)/未标记(none)。
- 热厨出品进热厨册、冷荤出品进冷荤册；未标记出品一次提交里只进一册（common 册）。
- 占用列 = 各册需求按原料加总；热厨册、冷荤册、占用列必须对得上，否则算分册失败。
- 分册失败（SplitMismatch）是分册一致性错误，绝不能表述成“结存不够/缺料”。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

# 册键
BOOK_HOT = "hot"
BOOK_COLD = "cold"
BOOK_COMMON = "common"
BOOK_LABELS = {BOOK_HOT: "热厨册", BOOK_COLD: "冷荤册", BOOK_COMMON: "未分册"}
# 占用列里每个原料的各册分量字段
_BOOKS = (BOOK_HOT, BOOK_COLD, BOOK_COMMON)


class SplitMismatch(Exception):
    """热厨册 / 冷荤册 / 占用列加总对不上。属于分册失败，不是库存结存不足。"""


@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float


def _round(v: float) -> float:
    return round(v + 0.0, 3)


def _book_lines(need: dict[int, float], ingredients: dict[int, dict], *, with_stock: bool) -> list[NeedLine]:
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        # 分册行只表达需求；是否缺料统一在“两册加总 vs 库存”层面判断，
        # 避免两册各自拿整份库存比而重复扣减。
        shortage = max(0.0, qty - stock) if with_stock else 0.0
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=_round(qty),
            stock_qty=_round(stock),
            shortage=_round(shortage),
        ))
    return lines


def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion."""
    need = explode_need(order_lines, bom_lines)
    return _book_lines(need, ingredients, with_stock=True)


def explode_need(order_lines: list[dict], bom_lines: list[dict]) -> dict[int, float]:
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    return need


def explode_by_book(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> dict[str, list[NeedLine]]:
    """按工位把需求展开到各册。

    order_lines 每项可含 station: none/hot/cold；未标记出品统一进 common 一册。
    只返回有行的册。
    """
    raw: dict[str, dict[int, float]] = {b: {} for b in _BOOKS}
    for ol in order_lines:
        station = (ol.get("station") or "none")
        book = station if station in (BOOK_HOT, BOOK_COLD) else BOOK_COMMON
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            bucket = raw[book]
            bucket[bl["ingredient_id"]] = bucket.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    return {book: _book_lines(raw[book], ingredients, with_stock=False) for book in _BOOKS if raw[book]}


def merge_total(books: dict[str, list[NeedLine]]) -> dict[int, float]:
    """占用口径：各册按原料加总。"""
    total: dict[int, float] = {}
    for lines in books.values():
        for l in lines:
            total[l.ingredient_id] = total.get(l.ingredient_id, 0.0) + l.need_qty
    return total


def build_occupancy(
    books: dict[str, list[NeedLine]],
    ingredients: dict[int, dict],
) -> list[dict]:
    """占用列：每个原料一行，qty = 各册加总，并带各册分量便于对账与展示。"""
    per_book: dict[int, dict[str, float]] = {}
    for book, lines in books.items():
        for l in lines:
            slot = per_book.setdefault(l.ingredient_id, {b: 0.0 for b in _BOOKS})
            slot[book] += l.need_qty
    rows: list[dict] = []
    for iid in sorted(per_book):
        ing = ingredients[iid]
        slot = per_book[iid]
        rows.append({
            "ingredient_id": iid,
            "ingredient_code": ing["code"],
            "ingredient_name": ing["name"],
            "unit": ing.get("unit", ""),
            "qty": _round(sum(slot.values())),
            "hot_qty": _round(slot[BOOK_HOT]),
            "cold_qty": _round(slot[BOOK_COLD]),
            "common_qty": _round(slot[BOOK_COMMON]),
        })
    return rows


def cross_check(books: dict[str, list[NeedLine]], occupancy: list[dict]) -> None:
    """热厨册 + 冷荤册 + 未分册 必须逐原料等于占用列，否则整次分册失败。"""
    totals = merge_total(books)
    occ_map = {r["ingredient_id"]: r for r in occupancy}
    if set(totals) != set(occ_map):
        raise SplitMismatch("分册原料集合与占用列不一致")
    for iid, qty in totals.items():
        row = occ_map[iid]
        parts = row["hot_qty"] + row["cold_qty"] + row["common_qty"]
        if abs(parts - row["qty"]) > 1e-6 or abs(qty - row["qty"]) > 1e-6:
            raise SplitMismatch(f"原料 {row['ingredient_code']} 分册加总与占用列对不上")
        # 反向核对：册里出现的每个原料必须能在占用行的对应册分量里找到
    for book, lines in books.items():
        for l in lines:
            part_qty = occ_map[l.ingredient_id][f"{book}_qty"]
            if abs(part_qty - l.need_qty) > 1e-6:
                raise SplitMismatch(f"原料 {l.ingredient_code} 的{BOOK_LABELS[book]}与占用列对不上")


def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": _round(sum(l.shortage for l in lines)),
        },
    }


def split_to_dict(
    books: dict[str, list[NeedLine]],
    occupancy: list[dict],
    ingredients: dict[int, dict],
) -> dict:
    """组装一次分册提交的完整结果。shortage 只在两册加总层面计算（信息展示，不阻塞落单）。"""
    total_need = merge_total(books)
    total_lines: list[NeedLine] = []
    for iid, qty in sorted(total_need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        total_lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=_round(qty),
            stock_qty=_round(stock),
            shortage=_round(max(0.0, qty - stock)),
        ))
    book_blocks = [
        {"book": book, "label": BOOK_LABELS[book], "lines": [asdict(l) for l in books[book]]}
        for book in _BOOKS if book in books
    ]
    return {
        "books": book_blocks,
        "occupancy": occupancy,
        "prep_lines": [asdict(l) for l in total_lines],
        "shortages": [asdict(l) for l in total_lines if l.shortage > 0],
        "stats": {
            "book_count": len(book_blocks),
            "ingredient_count": len(total_lines),
            "shortage_count": sum(1 for l in total_lines if l.shortage > 0),
            "total_shortage_qty": _round(sum(l.shortage for l in total_lines)),
            "total_occupancy_qty": _round(sum(r["qty"] for r in occupancy)),
        },
    }
