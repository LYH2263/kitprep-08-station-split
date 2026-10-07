from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Dish)) or 0) > 0:
        return
    # code, name, station（hot 热厨 / cold 冷荤）
    dishes = [
        ("D-HS", "红烧肉套餐", "hot"),
        ("D-YC", "鱼香茄子", "hot"),
        ("D-JT", "鸡汤面", "hot"),
        ("D-LB", "凉拌木耳", "cold"),
    ]
    dish_ids = {}
    for code, name, station in dishes:
        d = Dish(code=code, name=name, portion_unit="份", station=station)
        db.add(d); db.flush(); dish_ids[code] = d.id
    ings = [
        ("I-PR", "五花肉", "kg", 8.0),
        ("I-EG", "茄子", "kg", 3.0),
        ("I-CK", "鸡肉", "kg", 5.0),
        ("I-RC", "大米", "kg", 20.0),
        ("I-ND", "面条", "kg", 4.0),
        ("I-SC", "生抽", "L", 2.0),
        ("I-OL", "食用油", "L", 1.5),
        ("I-BF", "木耳", "kg", 2.0),
    ]
    ing_ids = {}
    for code, name, unit, stock in ings:
        i = Ingredient(code=code, name=name, unit=unit, stock_qty=stock)
        db.add(i); db.flush(); ing_ids[code] = i.id
    bom = [
        ("D-HS", "I-PR", 0.25), ("D-HS", "I-RC", 0.15), ("D-HS", "I-SC", 0.02), ("D-HS", "I-OL", 0.03),
        ("D-YC", "I-EG", 0.3), ("D-YC", "I-RC", 0.15), ("D-YC", "I-SC", 0.015), ("D-YC", "I-OL", 0.025),
        ("D-JT", "I-CK", 0.12), ("D-JT", "I-ND", 0.2), ("D-JT", "I-SC", 0.01),
        ("D-LB", "I-BF", 0.08), ("D-LB", "I-SC", 0.008), ("D-LB", "I-OL", 0.012),
    ]
    for dcode, icode, qty in bom:
        db.add(BomLine(dish_id=dish_ids[dcode], ingredient_id=ing_ids[icode], qty_per_portion=qty))
    order = KitchenOrder(code="KO-0901", outlet="城西门店", status="open")
    db.add(order); db.flush()
    for dcode, portions in [("D-HS", 40), ("D-YC", 30), ("D-JT", 50), ("D-LB", 20)]:
        db.add(OrderLine(order_id=order.id, dish_id=dish_ids[dcode], portions=portions))
    db.commit()
