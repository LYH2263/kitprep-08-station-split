from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import KitchenOrder
from app.services.bom_engine import SplitMismatch
from app.services.prep_service import PrepNotFound, generate_prep, latest_prep
router = APIRouter(prefix="/prep", tags=["prep"])

@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    try:
        # 两册（热厨册/冷荤册，未标记则一册）与占用在同一事务内同成同败
        return generate_prep(db, order_id)
    except PrepNotFound:
        raise HTTPException(404, "订单不存在")
    except SplitMismatch as exc:
        # 分册失败：两册与占用已全部退回。独立错误码，明确不是“结存不够”
        raise HTTPException(
            status_code=422,
            detail={"code": "split_mismatch", "message": f"分册失败，两册与占用已全部退回：{exc}"},
        )

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest_prep(db, order_id)
    if data is None:
        # 尚未点过“生成备料单”：GET 不替用户落单，返回空壳由前端引导生成
        order = db.get(KitchenOrder, order_id)
        if not order:
            raise HTTPException(404, "订单不存在")
        return {"id": None, "generation": 0, "reused": False,
                "order": {"id": order.id, "code": order.code, "outlet": order.outlet},
                "books": [], "occupancy": [], "prep_lines": [], "shortages": [],
                "stats": {"book_count": 0, "ingredient_count": 0, "shortage_count": 0,
                          "total_shortage_qty": 0, "total_occupancy_qty": 0}}
    return data

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest_prep(db, order_id)
    if data is None:
        return {"order_id": order_id, "shortages": [], "stats": {}}
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}
