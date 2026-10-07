from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import KitchenOrder
from app.services.bom_engine import SplitError
from app.services.prep_service import empty_result, generate_prep, latest_run, latest_payload

router = APIRouter(prefix="/prep", tags=["prep"])

@router.post("/run")
def run_prep(order_id: int = 1, force: bool = False, db: Session = Depends(get_db)):
    try:
        _run, payload = generate_prep(db, order_id, force=force)
    except KeyError:
        raise HTTPException(404, "订单不存在")
    except SplitError as exc:
        # 分册原子性失败：三册与占用已全部退回，结存未变。不得写成结存不够。
        raise HTTPException(409, str(exc) or "分册失败：热厨册/冷荤册/未分册已全部退回，结存未变")
    return payload

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    if db.get(KitchenOrder, order_id) is None:
        raise HTTPException(404, "订单不存在")
    run = latest_run(db, order_id)
    if run is None:
        return empty_result(order_id)
    return latest_payload(run)

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}
