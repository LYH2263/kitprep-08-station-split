from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

# 工位标记：未标记 / 热厨 / 冷荤
STATION_NONE = "none"
STATION_HOT = "hot"
STATION_COLD = "cold"
STATIONS = (STATION_NONE, STATION_HOT, STATION_COLD)

class Dish(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    portion_unit: Mapped[str] = mapped_column(String(16), default="份")
    station: Mapped[str] = mapped_column(String(16), default=STATION_NONE)

class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="kg")
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)

class BomLine(Base):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty_per_portion: Mapped[float] = mapped_column(Float)

class KitchenOrder(Base):
    __tablename__ = "kitchen_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    outlet: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")

class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    portions: Mapped[int] = mapped_column(Integer)

class PrepRun(Base):
    __tablename__ = "prep_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    # 同一订单第几版两册：标记变化后整体重生，世代 +1；旧版结果永不改写
    generation: Mapped[int] = mapped_column(Integer, default=1)
    # 本版落单时订单内各出品工位标记的签名，同签名重复生成只返回同一套两册
    mark_signature: Mapped[str] = mapped_column(String(512), default="")

class IngredientOccupancy(Base):
    """备料单对库存的占用：按订单+原料唯一，数量为该订单各册需求加总。

    只随最新一代两册在同一事务内整体替换，绝不允许只落一册。
    """
    __tablename__ = "ingredient_occupancies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("prep_runs.id"))
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    __table_args__ = (UniqueConstraint("order_id", "ingredient_id", name="uq_occupancy_order_ingredient"),)
