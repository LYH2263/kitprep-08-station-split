from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import STATIONS, Dish
router = APIRouter(prefix="/dishes", tags=["dishes"])

@router.get("")
def list_dishes(db: Session = Depends(get_db)):
    return [{"id": r.id, "code": r.code, "name": r.name,
             "portion_unit": r.portion_unit, "station": r.station}
            for r in db.scalars(select(Dish).order_by(Dish.id)).all()]

class StationPatch(BaseModel):
    station: str

@router.patch("/{dish_id}")
def update_station(dish_id: int, patch: StationPatch, db: Session = Depends(get_db)):
    dish = db.get(Dish, dish_id)
    if not dish:
        raise HTTPException(404, "出品不存在")
    if patch.station not in STATIONS:
        raise HTTPException(400, f"工位标记必须是 {', '.join(STATIONS)} 之一")
    dish.station = patch.station
    db.commit()
    db.refresh(dish)
    return {"id": dish.id, "code": dish.code, "name": dish.name,
            "portion_unit": dish.portion_unit, "station": dish.station}
