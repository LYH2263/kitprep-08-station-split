from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient, IngredientOccupancy
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    # 占用列 = 各订单热厨册/冷荤册/未分册需求按原料加总；结存(stock_qty)只读、不因备料落单而变
    occupied: dict[int, float] = {}
    for o in db.scalars(select(IngredientOccupancy)).all():
        occupied[o.ingredient_id] = occupied.get(o.ingredient_id, 0.0) + (o.qty or 0.0)
    rows = []
    for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all():
        occ = round(occupied.get(r.id, 0.0), 3)
        rows.append({
            "id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
            "stock_qty": r.stock_qty,
            "occupied_qty": occ,
            "available_qty": round((r.stock_qty or 0.0) - occ, 3),
        })
    return rows
