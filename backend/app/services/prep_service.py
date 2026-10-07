"""备料单原子落单服务。

核心约束：
- 热厨册 / 冷荤册（及未分册）与占用列在【同一事务】内整体落下：
  要么两册与占用一起成功，要么全部回滚，绝不允许只落一册。
- 库存结存（stock_qty）只读，永远不因生成备料单而改变。
- 同标记重复生成（订单页一次、备料台一次）返回同一 run、同一套两册。
- 标记变更后整套两册按新标记重生（新世代），更早世代的结果 JSON 不被改写。
"""
from __future__ import annotations
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    BomLine, Dish, Ingredient, IngredientOccupancy, KitchenOrder, OrderLine, PrepRun,
)
from app.services.bom_engine import (
    SplitMismatch, build_occupancy, cross_check, explode_by_book, split_to_dict,
)


class PrepNotFound(Exception):
    """订单不存在。"""


def _mark_signature(rows: list, stations: dict[int, str]) -> str:
    # 签名含工位标记与份数：任一变化都会触发新一代两册整体重生
    parts = sorted(f"{r.dish_id}:{stations.get(r.dish_id, 'none') or 'none'}:{r.portions}" for r in rows)
    return "|".join(parts)


def _assemble(order: KitchenOrder, rows: list, stations: dict[int, str], db: Session) -> dict:
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    order_lines = [{"dish_id": r.dish_id, "portions": r.portions,
                    "station": stations.get(r.dish_id, "none") or "none"} for r in rows]
    books = explode_by_book(order_lines, bom, ings)
    occupancy = build_occupancy(books, ings)
    # 分册对账：对不上直接抛 SplitMismatch，调用方必须整体回滚、且不得报成结存不够
    cross_check(books, occupancy)
    result = split_to_dict(books, occupancy, ings)
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def generate_prep(db: Session, order_id: int) -> dict:
    # 锁住订单行串行化同订单的并发生成，避免两笔提交各落一册
    order = db.get(KitchenOrder, order_id, with_for_update=True)
    if not order:
        raise PrepNotFound(f"订单 {order_id} 不存在")
    rows = list(db.scalars(
        select(OrderLine).where(OrderLine.order_id == order_id)
    ).all())
    # 每道出品当前的工位标记
    dish_ids = {r.dish_id for r in rows}
    dishes = {d.id: d for d in db.scalars(select(Dish).where(Dish.id.in_(dish_ids))).all()} if dish_ids else {}
    stations = {did: (d.station or "none") for did, d in dishes.items()}

    latest = db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()
    signature = _mark_signature(rows, stations)

    # 标记（与份数）未变：两处入口只许拿到同一套两册，直接返回已落的那一代
    if latest is not None and latest.mark_signature == signature:
        data = json.loads(latest.result_json)
        return {"id": latest.id, "generation": latest.generation, "reused": True, **data}

    try:
        result = _assemble(order, rows, stations, db)
        generation = (latest.generation + 1) if latest else 1
        result["generation"] = generation
        run = PrepRun(
            order_id=order_id,
            generation=generation,
            mark_signature=signature,
            result_json=json.dumps(result, ensure_ascii=False),
        )
        db.add(run)
        db.flush()  # 取 run.id；此刻占用尚未写入，任何异常都会整体回滚

        # 占用列整体替换：先删后插，与两册在同一事务内同成同败
        old = db.scalars(select(IngredientOccupancy).where(IngredientOccupancy.order_id == order_id)).all()
        for o in old:
            db.delete(o)
        db.flush()
        for row in result["occupancy"]:
            db.add(IngredientOccupancy(
                order_id=order_id,
                ingredient_id=row["ingredient_id"],
                run_id=run.id,
                qty=row["qty"],
            ))
        db.commit()
    except SplitMismatch:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(run)
    return {"id": run.id, "generation": generation, "reused": False, **result}


def latest_prep(db: Session, order_id: int) -> dict | None:
    run = db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()
    if run is None:
        return None
    data = json.loads(run.result_json)
    return {"id": run.id, "generation": run.generation, "reused": True, **data}
