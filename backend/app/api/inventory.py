from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient
from app.services.prep_service import effective_occupancy
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    occ = effective_occupancy(db)
    rows = []
    for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all():
        occupied = round(occ.get(r.id, 0.0), 3)
        # 结存永不扣减；占用只来自各订单最新一次备料单；可用可为负，仅作缺料提示。
        rows.append({"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
                     "stock_qty": r.stock_qty, "occupied_qty": occupied,
                     "available_qty": round(float(r.stock_qty) - occupied, 3)})
    return rows
