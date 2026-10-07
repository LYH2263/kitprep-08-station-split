"""备料单事务编排：三册 + 占用同事务落库，输入签名保证幂等。"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepBooking, PrepRun
from app.services.bom_engine import (
    BOOK_KEYS,
    BOOK_NAMES,
    TOL,
    SplitError,
    build_result_with_raw,
)

__all__ = ["SplitError", "compute_input_signature", "generate_prep", "latest_payload",
           "empty_result", "effective_occupancy"]


def compute_input_signature(
    order_id: int,
    order_lines: list[dict],
    stations: dict[int, str | None],
    bom_lines: list[dict],
) -> str:
    """订单行 + 工位标记 + 相关 BOM 用量的 sha256；故意不含库存（库存变化只影响缺料提示）。"""
    dish_ids = {ol["dish_id"] for ol in order_lines}
    payload = {
        "o": order_id,
        "l": sorted([ol["dish_id"], ol["portions"]] for ol in order_lines),
        "s": {str(did): stations.get(did) or "" for did in sorted(dish_ids)},
        "b": sorted(
            [b["dish_id"], b["ingredient_id"], round(float(b["qty_per_portion"]), 6)]
            for b in bom_lines if b["dish_id"] in dish_ids
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def latest_run(db: Session, order_id: int) -> PrepRun | None:
    return db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()


def empty_result(order_id: int) -> dict:
    return {
        "id": None,
        "input_sig": None,
        "generated": False,
        "order_id": order_id,
        "books": {k: {"name": BOOK_NAMES[k], "lines": []} for k in BOOK_KEYS},
        "occupancy": [],
        "prep_lines": [],
        "shortages": [],
        "stats": {"ingredient_count": 0, "shortage_count": 0, "total_shortage_qty": 0.0},
    }


def latest_payload(run: PrepRun) -> dict:
    return {"id": run.id, "input_sig": run.input_sig, "generated": True,
            **json.loads(run.result_json)}


def effective_occupancy(db: Session, order_id: int | None = None) -> dict[int, float]:
    """占用 = 每个订单最新一次 run 的 bookings 按原料加总；旧 run 不计。"""
    stmt = select(func.max(PrepRun.id)).group_by(PrepRun.order_id)
    if order_id is not None:
        stmt = stmt.where(PrepRun.order_id == order_id)
    rows = db.execute(
        select(PrepBooking.ingredient_id, func.sum(PrepBooking.qty))
        .where(PrepBooking.run_id.in_(stmt))
        .group_by(PrepBooking.ingredient_id)
    ).all()
    return {iid: float(qty) for iid, qty in rows}


def _load_inputs(db: Session, order_id: int):
    order = db.get(KitchenOrder, order_id)
    if order is None:
        raise KeyError("订单不存在")
    order_lines = [{"dish_id": l.dish_id, "portions": l.portions}
                   for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    bom_lines = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id,
                  "qty_per_portion": b.qty_per_portion}
                 for b in db.scalars(select(BomLine)).all()]
    ingredients = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
                   for i in db.scalars(select(Ingredient)).all()}
    stations = {d.id: d.station for d in db.scalars(select(Dish)).all()}
    return order, order_lines, bom_lines, ingredients, stations


def generate_prep(db: Session, order_id: int, *, force: bool = False) -> tuple[PrepRun, dict]:
    """生成备料单：三册与占用同一事务同成同败；输入未变返回同一 run（零写入）。"""
    order, order_lines, bom_lines, ingredients, stations = _load_inputs(db, order_id)
    sig = compute_input_signature(order_id, order_lines, stations, bom_lines)

    if not force:
        existing = latest_run(db, order_id)
        if existing is not None and existing.input_sig == sig:
            return existing, latest_payload(existing)

    # 分册与对账在任何写操作之前完成；SplitError 直接抛出，库里什么都不落。
    result, split = build_result_with_raw(
        {"id": order.id, "code": order.code, "outlet": order.outlet},
        order_lines, bom_lines, ingredients, stations,
    )

    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(),
                  result_json=json.dumps(result, ensure_ascii=False), input_sig=sig)
    try:
        db.add(run)
        db.flush()
        raw_books = split["_raw"]["books"]
        raw_occ = split["_raw"]["occ"]
        bookings = []
        for key in BOOK_KEYS:
            for iid, qty in raw_books[key].items():
                bookings.append(PrepBooking(run_id=run.id, book=key, ingredient_id=iid, qty=qty))
        db.add_all(bookings)
        db.flush()
        # 落库后再对一次账：册行合计必须等于全量占用，否则整笔退回。
        summed: dict[int, float] = {}
        for b in bookings:
            summed[b.ingredient_id] = summed.get(b.ingredient_id, 0.0) + b.qty
        if set(summed) != set(raw_occ) or any(
            abs(summed[iid] - raw_occ[iid]) > TOL for iid in summed
        ):
            raise SplitError("分册失败：分册占用合计与总占用不一致，热厨册/冷荤册/未分册已全部退回，结存未变")
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = latest_run(db, order_id)
        if concurrent is not None and concurrent.input_sig == sig:
            return concurrent, latest_payload(concurrent)
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run, latest_payload(run)
