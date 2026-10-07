from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Dish
from typing import Literal

router = APIRouter(prefix="/dishes", tags=["dishes"])


class DishUpdate(BaseModel):
    station: Literal["hot", "cold"] | None


def _row(r: Dish) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name,
            "portion_unit": r.portion_unit, "station": r.station}

@router.get("")
def list_dishes(db: Session = Depends(get_db)):
    return [_row(r) for r in db.scalars(select(Dish).order_by(Dish.id)).all()]

@router.patch("/{dish_id}")
def update_dish(dish_id: int, body: DishUpdate, db: Session = Depends(get_db)):
    dish = db.get(Dish, dish_id)
    if dish is None:
        raise HTTPException(404, "菜品不存在")
    dish.station = body.station
    db.commit()
    db.refresh(dish)
    return _row(dish)
